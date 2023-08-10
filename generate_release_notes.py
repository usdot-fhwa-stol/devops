#!/usr/bin/env python3
from github import Github
import argparse
import logging
import pathlib
import re
import sys


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
        # Get text in Related Issue section
        result = re.findall('## Related GitHub Issue(.*)## Related Jira Key', issue_body, re.DOTALL)

        if not result:
            result = re.findall('## Related Issue(.*)## Related Jira Key', issue_body, re.DOTALL)

    if result:
        # Single string list to multi-string list
        issues = "\n".join(result).split("\n")
    else:
        issues = []

    try:
        # Remove \r from list entries
        issues = [s.replace('\r', '') for s in issues]
    except:
        issues = []

    # Remove empty list entries
    issues = list(filter(None, issues))

    if issues:
        # Remove NA and TODO from list
        issues = [s for s in issues if s != "NA" and s != "TODO"]

        # Remove entries with no numbers
        issues = [s for s in issues if any(c.isdigit() for c in s)]

        issues = [s.replace(' (mostly)', '') for s in issues]

        issues = [s.strip() for s in issues]

        if issues:
            logging.info("PR #" + str(pr_number) + ": found " + ", ".join(sorted(issues)))
            try:
                issues = [re.findall('\d+$',s.strip())[0] for s in issues]
            except:
                pass

    return issues


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
    msg_failure = repo_name + ": repo does not exist or bad token"

    try:
        repo = github.get_repo(repo_name)
    except Exception as e:
        logging.error(e)
        logging.error(msg_failure)
        sys.exit(1)

    return repo

def generate_release_notes(repo_name, version, issue_titles_bugs, issue_titles_enhancements, issue_titles_other, commit_only, pull_requests_missing_issues):
    release_notes = f"""
## {repo_name}
### {version}

"""

    if issue_titles_bugs:
        release_notes += "#### Bugs & Anomalies\n"
        release_notes += "\n".join(f"* {title}" for title in sorted(set(issue_titles_bugs))) + "\n\n"

    if issue_titles_enhancements:
        release_notes += "#### Enhancements\n"
        release_notes += "\n".join(f"* {title}" for title in sorted(set(issue_titles_enhancements))) + "\n\n"

    if issue_titles_other:
        release_notes += "#### Issues Missing Labels\n"
        release_notes += "\n".join(f"* {title}" for title in sorted(set(issue_titles_other))) + "\n\n"

    if commit_only:
        release_notes += "#### Commits Missing Issues\n"
        release_notes += "\n".join(f"* {commit}" for commit in sorted(commit_only)) + "\n\n"

    if pull_requests_missing_issues:
        release_notes += "#### Pull Requests Missing Issues\n"
        release_notes += "\n".join(f"* {pr}" for pr in sorted(pull_requests_missing_issues)) + "\n\n"

    return release_notes


def release_notes():
    try:
        github = Github(args.github_token)
    except Exception as e:
        logging.error(e)
        sys.exit(1)

    try:
        release_notes_content = "# Releases\n\n"

        for org in args.organizations:
            for github_repo in get_repo_list(org, github):
                logging.info(f"Processing {github_repo}")
                repo = get_repo(github_repo, github)
                # Skip archived repos
                if repo.archived:
                    logging.warning(
                        github_repo + ": archived repository, skipping it"
                    )
                    continue

                # New branch versus old branch
                compare_branches = [args.release_branch, args.stable_branch]

                # Skip blacklisted repos
                if is_blacklisted_repo(github_repo):
                    continue
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
                        logging.info('PR number ' +  str(pr.number) )
                        try:
                            issues = get_issues_from_pr(repo, pr.number)

                            if issues:
                                issue_titles_bugs, issue_titles_enhancements, issue_titles_other = get_issue_titles(repo, issues)
                            else:
                                pull_requests_missing_issues.add(pr.title.strip() + " (Pull Request [#" + str(pr.number) + "](" + pr.html_url + "))")
                        except:
                            logging.warning("Cannot get issue information for pull request "  +  str(pr.number) )
                else:
                    logging.warning(github_repo + ": no pull requests found")

                # Generate release notes for repo
                release_notes_content += generate_release_notes(repo.name, args.version, issue_titles_bugs, issue_titles_enhancements, issue_titles_other, commit_only, pull_requests_missing_issues)
                logging.info(f'Generated release notes for repository: {github_repo}')

        # Write release notes to file
        with open(args.output_file, "w") as f:
            f.write(release_notes_content)

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
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler()],
    )

    release_notes()
