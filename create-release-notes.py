#!/usr/bin/env python3
from github import Github
import argparse
import logging
import pathlib
import re


green = "✅ \033[92m"
red = "❌ \033[91m"
yellow = "⚠️  \033[93m"

def get_issues_from_pr(github_repo, pr_number):
    github_issue = github_repo.get_pull(pr_number)

    # Remove <!-- comments --> from issue body
    try:
        issue_body = re.sub('<!--.*-->', '', github_issue.body)
    except:
        pass

    # Get text in Related Issue section
    result = re.findall('## Related Issue(.*)## Motivation and Context', issue_body, re.DOTALL)

    # Single string list to multi-string list
    issues = "\n".join(result).split("\n")

    # Remove "\r"
    issues = [s.replace('\r', '') for s in issues]

    # Remove empty list entries
    issues = list(filter(None, issues))

    # Remove entries with no numbers
    issues = [s for s in issues if any(c.isdigit() for c in s)]

    issues = [s.replace(' (mostly)', '') for s in issues]

    issues = [s.strip() for s in issues]

    if issues:
        print("PR #" + str(pr_number) + ": found " + ", ".join(sorted(issues)))
        issues = [re.findall('\d+$',s.strip())[0] for s in issues]

    return issues

def get_issue_titles(github_repo, issues):
    issue_titles = []

    for issue in issues:
        github_issue = github_repo.get_issue(number=int(issue))

        # Get issue's label names
        issue_labels_names = set()
        for label in github_issue.labels:
            issue_labels_names.add(label.name)

        # Format issue labels into string [label1, label2]
        labels = ""
        if issue_labels_names:
            labels = " [" + ", ".join(issue_labels_names) + "]"

        # Combine issue number with issue title
        issue_title = "Issue #" + str(issue) + ": " + github_issue.title.strip()

        # Combine issue title with issue label(s) if they exist
        if labels:
            issue_title = issue_title + labels

        issue_titles = issue_titles + [issue_title]

    return issue_titles

def get_repo_list(github_org, github):
    repo_list = []

    for repo in github.get_organization(github_org).get_repos():
        repo_list = repo_list + [repo.full_name]

    repo_list = sorted(repo_list)

    return repo_list


def get_repo(repo_name, github):
    msg_failure = red + repo_name + ": repo does not exist or bad token"

    try:
        repo = github.get_repo(repo_name)
    except Exception as e:
        logging.error(e)
        logging.error(msg_failure)
        exit()

    return repo


def is_blacklisted_repo(repo_name):
    blacklist = [
        "usdot-fhwa-stol/carma-cloud",
        "usdot-fhwa-stol/documentation",
        "usdot-fhwa-stol/github_metrics",
        "usdot-fhwa-stol/voices-cda-use-case-scenario-database",
    ]

    if repo_name in blacklist:
        logging.warning(yellow + repo_name +
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-token", required=True)
    parser.add_argument("--organizations", nargs="+", required=True)
    args = parser.parse_args()

    log = pathlib.Path("github-create.log")
    log.unlink(missing_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[logging.FileHandler(log), logging.StreamHandler()],
    )

    try:
        github = Github(args.github_token)
    except Exception as e:
        logging.error(e)
        exit()

    spreadsheet = set()
    commit_only = set()

    try:
        for org in args.organizations:
            #for github_repo in get_repo_list(org, github):
            for github_repo in ["usdot-fhwa-stol/carma-platform"]:
                repo = get_repo(github_repo, github)

                if repo.archived:
                    logging.warning(
                        yellow + github_repo + ": archived repository, skipping it"
                    )
                    continue

                if is_blacklisted_repo(github_repo):
                    continue

                compare_branches = ["develop", "master"]

                skip = False
                for branch in compare_branches:
                    if not is_branch(branch, repo):
                        logging.warning(
                            yellow + github_repo + ": \"" + branch +
                            "\" branch does not exist, skipping repo"
                        )
                        skip = True
                        break

                if skip:
                    continue

                found_commits = repo.compare(
                    compare_branches[1], compare_branches[0]).commits

                pull_requests = []
                prr_list = set()

                for found_commit in found_commits:
                    # Pull request
                    if len(list(found_commit.get_pulls())) >= 1:
                        pull_requests = pull_requests + \
                            [found_commit.get_pulls()]
                        for pr in pull_requests:
                            for prr in pr:
                                prr_list.add(prr)
                                continue
                    # Commit
                    else:
                        commit_url = found_commit.commit.html_url[:-34]
                        commit_title = "Commit: " + found_commit.commit.message.strip().split('\n', 1)[0]  + " (" + commit_url + ")"
                        commit_only.add(commit_title)
                        continue

    except KeyboardInterrupt:
        exit()

final_issues = []
for pr in prr_list:
    issues = get_issues_from_pr(repo, pr.number)

    if issues:
        final_issues = final_issues + get_issue_titles(repo, issues)

if final_issues:
    print("\nIssues:")
    print("• " + "\n• ".join(sorted(set(final_issues))))
    print("\n")

if commit_only:
    print("Commits with no detected issues:")
    print("• " + "\n• ".join(sorted(commit_only)))
