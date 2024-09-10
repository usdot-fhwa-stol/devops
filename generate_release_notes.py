#!/usr/bin/env python3
from github import Github
import argparse
import logging
import pathlib
import re
import sys
import requests

# Lists to track skipped repositories and PRs
skipped_repos = []
skipped_prs = []
# Function to get Jira issue details based on the Jira key
def get_jira_issue(issue_key, jira_url, jira_email, jira_token):
    url = f"{jira_url}/rest/api/3/issue/{issue_key}"
    auth = (jira_email, jira_token)
    headers = {"Accept": "application/json"}
    response = requests.get(url, auth=auth, headers=headers)
    if response.status_code == 200:
        return response.json()  # Return the full Jira issue JSON response
    else:
        logging.error(f"Failed to fetch Jira issue {issue_key}: {response.status_code} - {response.text}")
        return None
# Function to extract the Jira issue title and description
def get_epic_details(jira_issue):
    epic_title = jira_issue['fields']['summary']  # The title of the Jira issue (epic)
    epic_description = jira_issue['fields'].get('description', 'No description provided')  # The description of the epic
    return epic_title, epic_description
# Extract Jira keys from Pull Requests
def get_issues_from_pr(github_repo, pr_number):
    github_pull_request = github_repo.get_pull(pr_number)
    # Remove <!-- comments --> from issue body
    try:
        issue_body = re.sub('<!--.*-->', '', github_pull_request.body)
    except:
        issue_body = ""
        pass
    result = []
    if issue_body:
        # Get Jira keys from the PR description (Look for the "Related Jira Key" section)
        result = re.findall('## Related Jira Key(.*)## End', issue_body, re.DOTALL)
    if result:
        # Convert the single string list to a multi-string list, grab Jira key (CF-123, Arc-123)
        issues = "\n".join(result).split("\n")
    else:
        issues = []
    # Clean up the Jira keys
    issues = [s.strip() for s in issues if s]
    return issues
# Get repository list from GitHub
def get_repo_list(github_org, github):
    repo_list = []

    for repo in github.get_organization(github_org).get_repos():
        repo_list.append(repo.full_name)
    return sorted(repo_list)

def get_repo(repo_name, github):
    msg_failure = repo_name + ": repo does not exist or bad token"
    try:
        repo = github.get_repo(repo_name)
    except Exception as e:
        logging.error(e)
        logging.error(msg_failure)
        sys.exit(1)
    return repo

def get_release_notes(name, version, issue_titles_bugs, issue_titles_enhancements, issue_titles_other, commit_only, pull_requests_missing_issues):
    release_notes = f"\n\n## {name} - {version}\n"
    if issue_titles_bugs:
        release_notes += "\n\n#### Bugs & Anomalies\n"
        release_notes += "* " + "\n* ".join(sorted(set(issue_titles_bugs)))

    if issue_titles_enhancements:
        release_notes += "\n\n#### Enhancements\n"
        release_notes += "* " + "\n* ".join(sorted(set(issue_titles_enhancements)))

    if issue_titles_other:
        release_notes += "\n\n#### Other Issues\n"
        release_notes += "* " + "\n* ".join(sorted(set(issue_titles_other)))

    if commit_only:
        release_notes += "\n\n#### Commits Missing Issues\n"
        release_notes += "* " + "\n* ".join(sorted(commit_only))

    if pull_requests_missing_issues:
        release_notes += "\n\n#### PRs Missing Issues\n"
        release_notes += "* " + "\n* ".join(sorted(pull_requests_missing_issues))
    return release_notes
# TODO add blacklisted repo's here before merging this changes to main brnach
def is_blacklisted_repo(repo_name):
    blacklist = [
        "usdot-fhwa-stol/documentation",
        "usdot-fhwa-stol/github_metrics",
        "usdot-fhwa-stol/voices-cda-use-case-scenario-database",
    ]

    if repo_name in blacklist:
        logging.warning(repo_name + ": blacklisted repository, skipping it")
        skipped_repos.append(repo_name)
        return True
    return False
# Check if a branch exists in the repo
def is_branch(branch, repo):
    branch_exists = False
    try:
        for ref in repo.get_git_refs():
            if "refs/heads/" + branch == ref.ref:
                branch_exists = True
    except:
        return branch_exists

    return branch_exists

def release_notes():
    try:
        github = Github(args.github_token)
    except Exception as e:
        logging.error(e)
        sys.exit(1)

    try:
        release_notes = "# Releases"

        for org in args.organizations:
            for github_repo in get_repo_list(org, github):
                logging.info("Processing " + github_repo)
                repo = get_repo(github_repo, github)
                # Skip archived and blacklisted repos
                if repo.archived or is_blacklisted_repo(github_repo):
                    continue
                # Compare branches (release or any branches vs. stable )
                compare_branches = [args.release_branch, args.stable_branch]
                skip = False
                for branch in compare_branches:
                    if not is_branch(branch, repo):
                        logging.warning(github_repo + f": \"{branch}\" branch does not exist, skipping repo")
                        skipped_repos.append(f"{github_repo}: missing branch {branch}")
                        skip = True
                        break

                # Skip repo if branch does not exist
                if skip:
                    continue

                # Get commits
                found_commits = repo.compare(compare_branches[1], compare_branches[0]).commits
                commit_only = set()
                prr_list = set()
                # Fetch Pull Requests from commits
                for found_commit in found_commits:
                    try:
                        pr_list = found_commit.get_pulls()
                        if pr_list:
                            prr_list.update(list(pr_list))
                    except Exception as e:
                        logging.warning(f"Failed to retrieve pull requests for commit {found_commit.sha}: {e}")
                        skipped_prs.append(f"Commit {found_commit.sha} in repo {github_repo} could not retrieve PRs")
                    else:
                        commit_url = found_commit.commit.html_url[:-34]
                        commit_title = "{} (Commit [{}])".format(found_commit.commit.message.strip().split('\n', 1)[0], found_commit.commit.sha[:6])
                        commit_only.add(commit_title)
                issue_titles_bugs, issue_titles_enhancements, issue_titles_other = [], [], []
                pull_requests_missing_issues = set()
                # Check Jira keys in PRs and fetch Epic details
                if prr_list:
                    for pr in prr_list:
                        try:
                            jira_keys = get_issues_from_pr(repo, pr.number)
                            if jira_keys:
                                for jira_key in jira_keys:
                                    jira_issue = get_jira_issue(jira_key, args.jira_url, args.jira_email, args.jira_token)
                                    if jira_issue:
                                        epic_title, epic_description = get_epic_details(jira_issue)
                                        issue_titles_enhancements.append(f"{epic_title}: {epic_description}")
                                    else:
                                        pull_requests_missing_issues.add(pr.title.strip() + f" (Pull Request [#{pr.number}]({pr.html_url}))")
                            else:
                                pull_requests_missing_issues.add(pr.title.strip() + f" (Pull Request [#{pr.number}]({pr.html_url}))")
                        except Exception as e:
                            logging.error(f"Error processing PR #{pr.number} for repo {repo.name}: {e}")
                            skipped_prs.append(f"PR #{pr.number} in repo {repo.name} failed to process")
                else:
                    logging.warning(f"No pull requests found for repo {repo.name}")
                # Generate release notes for repo
                release_notes += get_release_notes(repo.name, args.version, issue_titles_bugs, issue_titles_enhancements, issue_titles_other, commit_only, pull_requests_missing_issues)
                logging.info('Generated release note for repo: ' + github_repo)
        # write skipped repositories and PRs to the release notes
        if skipped_repos:
            release_notes += "\n\n### Skipped Repositories\n"
            release_notes += "\n".join(skipped_repos)
        if skipped_prs:
            release_notes += "\n\n### Skipped Pull Requests\n"
            release_notes += "\n".join(skipped_prs)
        # Write release notes to file
        pathlib.Path(args.output_file).unlink(missing_ok=True)
        with open(args.output_file, "w") as f:
            f.write(release_notes)

    except Exception as e:
        logging.error(e)
        sys.exit(1)
    except KeyboardInterrupt:
        logging.error("Keyboard interrupt")
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
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler()])
    release_notes()