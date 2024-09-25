#!/usr/bin/env python3
"""
This script generates release notes by comparing branches in GitHub repositories
and fetching associated Jira issue details. It retrieves commits, PRs, Jira epics,
and generates a markdown release note.
"""

import argparse
import logging
import pathlib
import re
import sys
import requests
from github import Github, GithubException

# Lists to track skipped repositories and PRs
skipped_repos = []
skipped_prs = []

def get_jira_issue(issue_key, jira_url, jira_email, jira_token):
    """
    Function to get Jira issue details based on the Jira key.

    Args:
        issue_key (str): The Jira issue key (example, C1T-1234).
        jira_url (str): Jira base URL.
        jira_email (str): Jira email for authentication.
        jira_token (str): Jira token for authentication.

    Returns:
        dict: JSON response with issue details if successful, None otherwise.
    """
    url = f"{jira_url}/rest/api/3/issue/{issue_key}"
    auth = (jira_email, jira_token)
    headers = {"Accept": "application/json"}

    try:
        response = requests.get(url, auth=auth, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.Timeout:
        logging.error("Request timed out for Jira issue %s", issue_key)
        return None
    except requests.RequestException as error:
        logging.error("Failed to fetch Jira issue %s: %s", issue_key, error)
        return None

    return response.json()

def get_epic_details(jira_issue):
    """
    Extract the Jira epic's title and description.

    Args:
        jira_issue (dict): The JSON response for a Jira issue.

    Returns:
        tuple: A tuple containing the epic key, title, and description.
    """
    epic_key = jira_issue['key']
    epic_title = jira_issue['fields'].get('summary', 'No title')
    epic_description = jira_issue['fields'].get('description', 'No description provided')

    if isinstance(epic_description, dict) and 'content' in epic_description:
        content_blocks = epic_description.get('content', [])
        cleaned_description = []
        for block in content_blocks:
            if block['type'] == 'paragraph':
                paragraph_text = " ".join(
                    [item.get('text', '') for item in block.get('content', [])
                     if item.get('type') == 'text']
                )
                cleaned_description.append(paragraph_text)
        epic_description = (
            "\n".join(cleaned_description)
            if cleaned_description
            else 'No description available'
        )

    return epic_key, epic_title, epic_description

def get_parent_epic(jira_issue, jira_url, jira_email, jira_token):
    """
    Get the parent epic of a Jira story or task.

    Args:
        jira_issue (dict): The JSON response for a Jira issue.
        jira_url (str): Jira base URL.
        jira_email (str): Jira email for authentication.
        jira_token (str): Jira token for authentication.

    Returns:
        tuple: The epic key, title, and description, or None if no parent is found.
    """
    parent_key = jira_issue['fields'].get('parent', {}).get('key')
    if parent_key:
        parent_epic = get_jira_issue(parent_key, jira_url, jira_email, jira_token)
        return get_epic_details(parent_epic)
    return None, None, None

def get_issues_from_pr(github_repo, pr_number):
    """
    Get Jira keys and GitHub issues from the pull request body.

    Args:
        github_repo (Repository): The GitHub repository object.
        pr_number (int): The number of the pull request.

    Returns:
        tuple: Lists of Jira keys and GitHub issues.
    """
    github_pull_request = github_repo.get_pull(pr_number)
    try:
        issue_body = re.sub(r'<!--.*-->', '', github_pull_request.body)
    except TypeError:
        issue_body = ""

    jira_keys = []
    github_issues = []

    if issue_body:
        jira_key_match = re.findall(r'Related Jira Key.*?(\[[^\]]*\])?\(?([A-Z]+-\d+)\)?', issue_body, re.DOTALL)
        if jira_key_match:
            jira_keys = [match[1].strip() for match in jira_key_match if match[1].strip()]

        if not jira_keys:
            github_issue_match = re.findall(r'Related GitHub Issue.*?(\[[^\]]*\])?\(?#(\d+)\)?', issue_body, re.DOTALL)
            if github_issue_match:
                github_issues = [f"#{match[1].strip()}" for match in github_issue_match if match[1].strip()]

        if not jira_keys and not github_issues:
            jira_keys = [f"PR Title: {github_pull_request.title.strip()}"]
            github_issues = [f"PR Description: {github_pull_request.body.strip()[:100]}"]

    return jira_keys, github_issues

def get_repo_list(github_org, github):
    """
    Get the list of repositories for the given GitHub organization from input.
    Args:
        github_org (str): The GitHub organization name.
        github (Github): The authenticated GitHub instance.
    Returns:
        list: A sorted list of full repository names for the organization.
    """
    repo_list = []
    for repo in github.get_organization(github_org).get_repos():
        repo_list.append(repo.full_name)
    return sorted(repo_list)

def get_repo(repo_name, github):
    """
    Fetch a repository by name from GitHub.

    Args:
        repo_name (str): The full name of the repository.
        github (Github): The authenticated GitHub instance.

    Returns:
        Repository: A GitHub repository object.
    """
    msg_failure = f"{repo_name}: repo does not exist or bad token"
    try:
        repo = github.get_repo(repo_name)
    except GithubException as error:
        logging.error("%s", error)
        logging.error("%s", msg_failure)
        sys.exit(1)
    return repo

def get_release_notes(name, version, issue_titles_epics,
                      issue_titles_other, commit_only, pull_requests_missing_epics, pr_mapping):
    """
    Format release notes for the given repository.

    Args:
        name (str): The repository name.
        version (str): The release version.
        issue_titles_epics (set): Titles of unique Jira epics.
        issue_titles_other (list): Titles of other issues.
        commit_only (list): Commits missing issues.
        pull_requests_missing_epics (list): PRs missing epics and GitHub issues.
        pr_mapping (dict): Mapping of Jira epics to GitHub PR numbers.

    Returns:
        str: Formatted release notes in markdown.
    """
    notes_content = f"\n\n## {name} - {version}\n"

    # List of Jira Epics
    if issue_titles_epics:
        notes_content += "\n### List of Jira Epics\n"
        for epic in sorted(issue_titles_epics):
            epic_parts = epic.split(' - ')
            epic_key = epic_parts[0]
            epic_title = epic_parts[1] if len(epic_parts) > 1 else ""
            epic_description = epic_parts[2] if len(epic_parts) > 2 else ""
            pr_number = pr_mapping.get(epic_key, "N/A")
            if epic_description:
                notes_content += f"Epic ### {epic_key}: {epic_title}: {epic_description} (GitHub PR #{pr_number})\n"
            else:
                notes_content += f"Epic ### {epic_key}: {epic_title} (GitHub PR #{pr_number})\n"
    else:
        notes_content += "\n### No Jira Epics Found\n"

    if issue_titles_other:
        notes_content += "\n### List of Other Jira Items (Bugs, Tasks, Anomalies)\n"
        for item in issue_titles_other:
            notes_content += f"Jira Item ###: {item}\n"
    else:
        notes_content += "\n### No Other Jira Items Found\n"

    if pull_requests_missing_epics:
        notes_content += "\n### List of GitHub PRs Missing Epics and Issues\n"
        for pr in pull_requests_missing_epics:
            if ':' in pr:
                parts = pr.split(': ', 1)
                pr_title = parts[0]
                pr_description = parts[1] if len(parts) > 1 else "No description"
            else:
                pr_title = pr
                pr_description = "No description"
            notes_content += f"PR ###: {pr_title}: {pr_description} (Commit ###)\n"
    else:
        notes_content += "\n### No PRs Missing Epics or GitHub Issues Found\n"

    if commit_only:
        notes_content += "\n### List of Orphaned Commits\n"
        for commit in commit_only:
            commit_title = commit.split(': ', 1)[0]
            notes_content += f"Commit ###: {commit_title}\n"
    else:
        notes_content += "\n### No Orphaned Commits Found\n"

    return notes_content

def is_blacklisted_repo(repo_name):
    """
    Check if a repository is blacklisted and should be skipped.

    Args:
        repo_name (str): The full name of the repository.

    Returns:
        bool: True if the repo is blacklisted, otherwise False.
    """
    blacklist = [
        "usdot-fhwa-stol/documentation",
        "usdot-fhwa-stol/github_metrics",
        "usdot-fhwa-stol/voices-cda-use-case-scenario-database",
    ]
    if repo_name in blacklist:
        logging.warning("%s: blacklisted repository, skipping it", repo_name)
        skipped_repos.append(repo_name)
        return True
    return False

def is_branch(branch, repo):
    """
    Check if a given branch exists in the repository.

    Args:
        branch (str): Branch name.
        repo (Repository): GitHub repository object.

    Returns:
        bool: True if the branch exists, otherwise False.
    """
    try:
        return any(f"refs/heads/{branch}" == ref.ref for ref in repo.get_git_refs())
    except GithubException:
        return False

def release_notes(parsed_args):
    """
    Main function to generate release notes by comparing branches.
    """
    try:
        github = Github(parsed_args.github_token)
    except GithubException as error:
        logging.error("%s", error)
        sys.exit(1)

    try:
        notes = "# Releases"
        for org in parsed_args.organizations:
            for github_repo in get_repo_list(org, github):
                logging.info("Processing %s", github_repo)
                repo = get_repo(github_repo, github)

                if repo.archived or is_blacklisted_repo(github_repo):
                    continue

                compare_branches = [parsed_args.release_branch, parsed_args.stable_branch]
                skip = False
                for branch in compare_branches:
                    if not is_branch(branch, repo):
                        logging.warning('%s: "%s" branch does not exist, skipping repo', github_repo, branch)
                        skipped_repos.append(f"{github_repo}: missing branch {branch}")
                        skip = True
                        break

                if skip:
                    continue

                found_commits = repo.compare(compare_branches[1], compare_branches[0]).commits
                commit_only = set()
                prr_list = set()
                pr_mapping = {}

                for found_commit in found_commits:
                    try:
                        pr_list = found_commit.get_pulls()
                        if pr_list:
                            prr_list.update(list(pr_list))
                    except GithubException as error:
                        logging.warning(
                            "Failed to retrieve pull requests for commit %s: %s",
                            found_commit.sha, error)
                        skipped_prs.append(f"Commit {found_commit.sha} in repo {github_repo} could not retrieve PRs")
                    else:
                        commit_title = "{} (Commit [{}])".format(
                            found_commit.commit.message.strip().split('\n', 1)[0], found_commit.commit.sha[:6]
                        )
                        commit_only.add(commit_title)

                issue_titles_epics, issue_titles_other = set(), []
                pull_requests_missing_epics = set()

                if prr_list:
                    for pr in prr_list:
                        try:
                            jira_keys, github_issues = get_issues_from_pr(repo, pr.number)
                            if jira_keys:
                                for jira_key in jira_keys:
                                    jira_issue = get_jira_issue(jira_key, parsed_args.jira_url, parsed_args.jira_email, parsed_args.jira_token)
                                    if jira_issue:
                                        epic_key, epic_title, epic_description = get_parent_epic(
                                            jira_issue, parsed_args.jira_url, parsed_args.jira_email, parsed_args.jira_token)
                                        if epic_title:
                                            issue_titles_epics.add(f"{epic_key} - {epic_title}: {epic_description}")
                                            pr_mapping[epic_key] = pr.number
                                        else:
                                            pull_requests_missing_epics.add(
                                                f"{pr.title.strip()} (Pull Request [#{pr.number}]({pr.html_url})) - Epic missing"
                                            )

                            elif github_issues:
                                issue_titles_other.extend(github_issues)

                            else:
                                pull_requests_missing_epics.add(f"{pr.title.strip()} (Pull Request [#{pr.number}]({pr.html_url}))")
                        except GithubException as error:
                            logging.error("Error processing PR #%d for repo %s: %s", pr.number, repo.name, error)
                            skipped_prs.append(f"PR #{pr.number} in repo {repo.name} failed to process")

                notes += get_release_notes(
                    repo.name, parsed_args.version, issue_titles_epics,
                    issue_titles_other, commit_only, pull_requests_missing_epics, pr_mapping
                )
                logging.info("Generated release note for repo: %s", github_repo)

        if skipped_repos:
            notes += "\n\n### Skipped Repositories\n" + "\n".join(skipped_repos)

        if skipped_prs:
            notes += "\n\n### Skipped Pull Requests\n" + "\n".join(skipped_prs)

        pathlib.Path(parsed_args.output_file).unlink(missing_ok=True)
        with open(parsed_args.output_file, "w", encoding="utf-8") as file:
            file.write(notes)

    except GithubException as error:
        logging.error("%s", error)
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-token", required=True)
    parser.add_argument("--release-branch", required=True)
    parser.add_argument("--stable-branch", required=True)
    parser.add_argument("--organizations", nargs="+", required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--jira-url", required=True)
    parser.add_argument("--jira-email", required=True)
    parser.add_argument("--jira-token", required=True)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler()],
    )
    release_notes(args)
