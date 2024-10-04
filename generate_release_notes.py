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
    # Query parameter to restrict fields returned for issues. Without this parameter all fields are returned.
    fields="summary,issuetype,status,description,key,epic,parent"
    url = f"{jira_url}/rest/api/3/issue/{issue_key}?fields={fields}"
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
    Extract the Jira epic's title, description, and status.

    Args:
        jira_issue (dict): The JSON response for a Jira issue.

    Returns:
        tuple: A tuple containing the epic key, title, description, and status.
    """
    epic_key = jira_issue['key']
    epic_title = jira_issue['fields'].get('summary', 'No title')
    epic_description = jira_issue['fields'].get('description', 'No description provided')
    epic_status = jira_issue['fields'].get('status', {}).get('name', None)

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

    return epic_key, epic_title, epic_description, epic_status

def get_parent_epic(jira_issue, jira_url, jira_email, jira_token):
    """
    Get the parent epic of a Jira story or task.

    Args:
        jira_issue (dict): The JSON response for a Jira issue.
        jira_url (str): Jira base URL.
        jira_email (str): Jira email for authentication.
        jira_token (str): Jira token for authentication.

    Returns:
        tuple: The epic key, title, description, and status, or None if no parent is found.
    """
    parent_key = jira_issue['fields'].get('parent', {}).get('key')
    if parent_key:
        parent_epic = get_jira_issue(parent_key, jira_url, jira_email, jira_token)
        return get_epic_details(parent_epic)
    return None, None, None, None

def get_issues_from_pr(github_repo, pr_number):
    """
    Get Jira keys and GitHub issues from the pull request body.

    Args:
        github_repo (Repository): The GitHub repository object.
        pr_number (int): The number of the pull request.
        jira_key (str): The Jira issue key (example, 'C1T-1234').

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
        # If no github issue or jira issue is found, PR is orphan
        if not jira_keys and not github_issues:
            return None, None

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
        logging.error("Error: %s. Message failure: %s", error, msg_failure)
        sys.exit(1)
    return repo

def get_release_notes(name, version, issue_titles_epics,
                      issue_titles_other, github_issues, pr_missing_jira_issues, commit_only, pr_mapping):
    """
    Generate formatted release notes for the given repository.

    Args:
        name (str): The repository name.
        version (str): The release version.
        issue_titles_epics (set): Titles of unique Jira epics.
        issue_titles_other (list): Titles of other Jira issues (e.g., Story, Bug, Anomaly).
        github_issues (list): GitHub issues.
        pr_missing_jira_issues (list): PRs missing Jira items or GitHub issues.
        commit_only (list): Commits missing issues.
        pr_mapping (dict): Mapping of Jira epics to lists of GitHub PR numbers.

    Returns:
        str: Formatted release notes in markdown.
    """
    notes_content = f"\n\n## {name} - {version}\n"

    # List of Jira Epics
    notes_content += "\n**List of Jira Epics**\n"
    if issue_titles_epics:
        for epic_fields in sorted(issue_titles_epics):
            epic_key = epic_fields[0]
            epic_title = epic_fields[1]
            epic_description = epic_fields[2] if len(epic_fields) >2 and epic_fields[2] else "No description provided"
            epic_status = epic_fields[3] if len(epic_fields) > 3 and epic_fields[3] else "No status provided" 
            pr_numbers = pr_mapping.get(epic_key, [])
            pr_list = ', '.join([f"#{pr}" for pr in pr_numbers]) if pr_numbers else "N/A"
            notes_content += f"* {epic_key}: {epic_title} (Status: {epic_status}): "
            notes_content += f"{epic_description}. (GitHub PRs {pr_list})\n"

    else:
        notes_content += "No Jira epics found\n"

    # List of other Jira Items
    notes_content += "\n**List of other Jira Items (e.g. Story/Bug/Anomaly/Task)**\n"
    if issue_titles_other:
        for item in issue_titles_other:
            notes_content += f"* {item}\n"
    else:
        notes_content += "No other Jira items found\n"

    # List of GitHub Issues
    notes_content += "\n**List of GitHub Issues**\n"
    if github_issues:
        for issue in github_issues:
            notes_content += f"* {issue}\n"
    else:
        notes_content += "No GitHub issues found\n"

    # List of GitHub PRs (no Jira Item or GitHub Issue)
    notes_content += "\n**List of GitHub PRs (no Jira Item or GitHub Issue)**\n"
    if pr_missing_jira_issues:
        for pr in pr_missing_jira_issues:
            notes_content += f"* {pr}\n"
    else:
        notes_content += "No GitHub PRs found\n"

    # List of Orphaned Commits
    notes_content += "\n**List of Orphaned Commits**\n"
    if commit_only:
        for commit in commit_only:
            commit_title = commit.split(': ', 1)[0]
            notes_content += f"* Commit: {commit_title}\n"
    else:
        notes_content += "No Orphaned Commits found\n"

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

                issue_titles_epics, issue_titles_other, pull_requests_missing_epics, github_issues = [], [], [], []

                if prr_list:
                    for pr in prr_list:
                        try:
                            jira_keys, pr_github_issues = get_issues_from_pr(repo, pr.number)
                            if jira_keys:
                                for jira_key in jira_keys:
                                    jira_issue = get_jira_issue(jira_key, parsed_args.jira_url, parsed_args.jira_email, parsed_args.jira_token)
                                    if jira_issue:
                                        epic_key, epic_title, epic_description, epic_status = get_parent_epic(
                                            jira_issue, parsed_args.jira_url, parsed_args.jira_email, parsed_args.jira_token)
                                        if epic_title:
                                            # Create a list of epic fields for each epic including key, title, status and description
                                            issue_titles_epics.append([epic_key,epic_title, epic_description, epic_status,])
                                            pr_mapping.setdefault(epic_key, []).append(pr.number)
                                        else:
                                            issue_titles_other.append(
                                                f"{jira_issue['fields']['summary'].strip()} (Jira {jira_issue['fields']['issuetype']['name']} : {jira_issue['key']}) - Epic missing"
                                            )

                            elif pr_github_issues:
                                github_issues.append(pr_github_issues)

                            else:
                                pull_requests_missing_epics.append(f"{pr.title.strip()} (Pull Request [#{pr.number}]({pr.html_url}))")
                        except GithubException as error:
                            logging.error("Error processing PR #%d for repo %s: %s", pr.number, repo.name, error)
                            skipped_prs.append(f"PR #{pr.number} in repo {repo.name} failed to process")

                notes += get_release_notes(
                    repo.name, parsed_args.version, issue_titles_epics,
                    issue_titles_other, github_issues, pull_requests_missing_epics, commit_only, pr_mapping
                )
                logging.info("Generated release note for repo: %s", github_repo)

        if skipped_repos:
            notes += "\n\n**Skipped Repositories**\n"
            notes += "\n".join([f"* {repo}" for repo in skipped_repos])

        if skipped_prs:
            notes += "\n\n**Skipped Pull Requests**\n"
            notes += "\n".join([f"* {pr}" for pr in skipped_prs])

        pathlib.Path(parsed_args.output_file).unlink(missing_ok=True)
        with open(parsed_args.output_file, "w", encoding="utf-8") as file:
            file.write(notes)

    except GithubException as error:
        logging.error("%s", error)
        sys.exit(1)

if __name__ == "__main__":

    # This is Main execution block for generating release notes
    # by comparing branches in each GitHub repo
    # and fetching associated Jira Issue details.
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-token", required=True, help="GitHub personal access token for authenticating API requests.")
    parser.add_argument("--release-branch", required=True, help="The release branch to compare changes from (e.g., 'release/omega').")
    parser.add_argument("--stable-branch", default="master", help="The stable branch to compare against. Defaults to 'master'.")
    parser.add_argument("--organizations", default="usdot-fhwa-stol", nargs="+", required=True, help="List of GitHub organizations to process default can be either one of these three usdot-fhwa-stol, usdot-fhwa-ops,usdot-jpo-ode.")
    parser.add_argument("--output-file", required=True, help="Path to the output file where the release notes will be saved.")
    parser.add_argument("--version", required=True , help="Version number")
    parser.add_argument("--jira-url", default="https://usdot-carma.atlassian.net/", help="The Jira base URL (default is 'https://usdot-carma.atlassian.net/')")
    parser.add_argument("--jira-email", required=True, help=" Jira Email for authenticating Jira API requests.")
    parser.add_argument("--jira-token", required=True, help="Jira API token for authenticating requests.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler()],
    )
    release_notes(args)
