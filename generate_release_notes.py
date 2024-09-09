#!/usr/bin/env python3
from github import Github
import argparse
import logging
import pathlib
import re
import sys
import requests


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


def get_parent_epic(jira_issue, jira_url, jira_email, jira_token):
    # Check if the Jira issue has a parent epic by checking the "parent" field
    parent_field = jira_issue['fields'].get('parent')
    
    if parent_field:
        epic_key = parent_field['key']  # Get the parent epic's key
        epic = get_jira_issue(epic_key, jira_url, jira_email, jira_token)

        if epic:
            epic_title = epic['fields'].get('summary', 'No title')
            epic_description = epic['fields'].get('description', 'No description provided')

            # Clean the description (optional, based on need)
            if isinstance(epic_description, dict) and 'content' in epic_description:
                content_blocks = epic_description.get('content', [])
                cleaned_description = []
                for block in content_blocks:
                    if block['type'] == 'paragraph':
                        paragraph_text = " ".join([item.get('text', '') for item in block.get('content', []) if item.get('type') == 'text'])
                        cleaned_description.append(paragraph_text)
                epic_description = "\n".join(cleaned_description) if cleaned_description else 'No description available'

            return epic_key, epic_title, epic_description
    return None, None, None


def get_issues_from_pr(github_repo, pr_number):
    github_pull_request = github_repo.get_pull(pr_number)

    # Remove <!-- comments --> from issue body
    try:
        issue_body = re.sub('<!--.*-->', '', github_pull_request.body)
    except:
        issue_body = ""
        pass

    result = []
    jira_keys = []
    if issue_body:
        # Handle both Related GitHub Issue and Related Jira Key
        result = re.findall(r'## Related GitHub Issue(?:.*?)([A-Za-z0-9-#]+)', issue_body, re.DOTALL)

        if not result:
            result = re.findall(r'## Related Issue(?:.*?)([A-Za-z0-9-#]+)', issue_body, re.DOTALL)

        # Extract Jira keys from the "Related Jira Key" section in the PR body
        jira_keys = re.findall(r'## Related Jira Key(?:.*?)([A-Z]+-\d+)', issue_body, re.DOTALL)

    if result:
        # Split the extracted string into list items based on newlines 
        issues = re.split(r'\s*,\s*|\s*\n\s*', "\n".join(result))
    else:
        issues = []

    # Clean up issues, remove any unwanted characters
    issues = [issue.strip() for issue in issues if issue.strip() and issue.strip().lower() not in ["na", "todo"]]

    # Only keep issues with numeric identifiers
    issues = [issue for issue in issues if re.search(r'\d+', issue)]

    if issues:
        logging.info(f"PR #{pr_number}: found GitHub Issues: {', '.join(sorted(issues))}")

    if jira_keys:
        logging.info(f"PR #{pr_number}: found Jira Keys: {', '.join(sorted(jira_keys))}")

    return issues, jira_keys

def get_issue_titles(github_repo, issues):
    issue_titles_bugs = []
    issue_titles_enhancements = []
    issue_titles_other = []

    for issue in issues:
        github_issue = github_repo.get_issue(number=int(issue))

        # Get issue's label names
        issue_labels_names = set()
        for label in github_issue.labels:
            issue_labels_names.add(label.name)

        if "enhancement" in issue_labels_names:
            issue_titles_enhancements = issue_titles_enhancements + [github_issue.title.strip()]
        elif "anomaly" or "bug" in issue_labels_names:
            issue_titles_bugs = issue_titles_bugs + [github_issue.title.strip()]
        else:
            issue_titles_other = issue_titles_other + [github_issue.title.strip()]

    return issue_titles_bugs, issue_titles_enhancements, issue_titles_other

def get_repo_list(github_org, github):
    repo_list = []

    for repo in github.get_organization(github_org).get_repos():
        repo_list = repo_list + [repo.full_name]

    repo_list = sorted(repo_list)

    return repo_list


def get_repo(repo_name, github):
    try:
        return github.get_repo(repo_name)
    except Exception as e:
        logging.error(f"{repo_name}: repo does not exist or bad token. Error: {e}")
        sys.exit(1)

def get_release_notes(name, version, issue_titles_bugs, issue_titles_enhancements, issue_titles_other, commit_only, pull_requests_missing_issues):
    release_notes = "\n\n## " + name + "\n"
    release_notes += "### " + version

    if issue_titles_bugs:
        release_notes += "\n\n#### Bugs & Anomalies\n"
        release_notes += "* " + "\n* ".join(sorted(set(issue_titles_bugs)))

    if issue_titles_enhancements:
        release_notes += "\n\n#### Enhancements\n"
        release_notes += "* " + "\n* ".join(sorted(set(issue_titles_enhancements)))

    if issue_titles_other:
        release_notes += "\n\n#### Issues Missing Labels\n"
        release_notes += "* " + "\n* ".join(sorted(set(issue_titles_other)))

    if commit_only:
        release_notes += "\n\n#### Commits Missing Issues\n"
        release_notes += "* " + "\n* ".join(sorted(commit_only))

    if pull_requests_missing_issues:
        release_notes += "\n\n#### Pull Requests Missing Issues\n"
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
        logging.warning(repo_name +
                        ": blacklisted repository, skipping it")
        return True
    else:
        return False


def is_branch(branch, repo):
    # Test branch existence
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

                # Skip archived repos
                if repo.archived:
                    logging.warning(
                        github_repo + ": archived repository, skipping it"
                    )
                    continue

                # Skip blacklisted repos
                if is_blacklisted_repo(github_repo):
                    continue

                # New branch versus old branch
                compare_branches = [args.release_branch, args.stable_branch]


                # Test branch existence
                skip = False
                for branch in compare_branches:
                    if not is_branch(branch, repo):
                        logging.warning(
                            github_repo + ": \"" + branch +
                            "\" branch does not exist, skipping repo"
                        )
                        skip = True
                        break

                # Skip repo if branch does not exist
                if skip:
                    continue

                # Get commits
                found_commits = repo.compare(
                    compare_branches[1], compare_branches[0]).commits

                # Parse commits
                commit_only = set()
                prr_list = set()
                pull_requests_from_commit = set()
                for found_commit in found_commits:
                    # Get pull requests from commits
                    if len(list(found_commit.get_pulls())) >= 1:
                        pull_requests_from_commit.add(found_commit.get_pulls())

                        for pr in pull_requests_from_commit:
                            for prr in pr:
                                prr_list.add(prr)
                                continue

                    # Save commits with no pull requests
                    else:
                        commit_url = found_commit.commit.html_url[:-34]
                        commit_title = found_commit.commit.message.strip().split('\n', 1)[0] + " (Commit [" + found_commit.commit.sha[0:6]  + "](" + commit_url + "))"
                        commit_only.add(commit_title)
                        continue

                # Get issues from pull requests
                logging.info('Get issue info from pull request (PR)...')
                issue_titles_bugs, issue_titles_enhancements, issue_titles_other = [], [], []
                pull_requests_missing_issues = set()
                if prr_list:
                    for pr in prr_list:
                        try:
                            jira_keys, github_issues = get_issues_from_pr(repo, pr.number)
                            
                            # Handle Jira Epics
                            if jira_keys:
                                for jira_key in jira_keys:
                                    jira_issue = get_jira_issue(jira_key, args.jira_url, args.jira_email, args.jira_token)
                                    if jira_issue:
                                        epic_key, epic_title, epic_description = get_parent_epic(jira_issue, args.jira_url, args.jira_email, args.jira_token)
                                        if epic_title:
                                            issue_titles_enhancements.append(f"{epic_key} - {epic_title}: {epic_description}")
                                        else:
                                            pull_requests_missing_issues.add(pr.title.strip() + f" (Pull Request [#{pr.number}]({pr.html_url}))")

                            # Fallback to GitHub Issues
                            elif github_issues:
                                issue_titles_bugs.extend(github_issues)

                            # Fallback to PR description and title
                            else:
                                pull_requests_missing_issues.add(pr.title.strip() + " (Pull Request [#" + str(pr.number) + "](" + pr.html_url + "))")
                        except:
                            logging.warning("Cannot get issue information for pull request "  +  str(pr.number) )
                else:
                    logging.warning(github_repo + ": no pull requests found")

                # Generate release notes for repo
                release_notes += get_release_notes(repo.name, args.version, issue_titles_bugs, issue_titles_enhancements, issue_titles_other, commit_only, pull_requests_missing_issues)
                logging.info('Generating release note for repos: ' + github_repo)
                logging.info(release_notes)

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

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler()],
    )

    release_notes()