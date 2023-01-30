#!/usr/bin/env python3
from github import Github
import argparse
import logging
import pathlib
import re


green = "✅ \033[92m"
red = "❌ \033[91m"
yellow = "⚠️  \033[93m"


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

    try:
        for org in args.organizations:
            # for org in ["usdot-fhwa-stol"]:
            for github_repo in get_repo_list(org, github):
                # for github_repo in [".github", "devops", "carma-messenger"]:
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

                for found_commit in found_commits:
                    # Pull request
                    if len(list(found_commit.get_pulls())) >= 1:
                        pull_requests = pull_requests + \
                            [found_commit.get_pulls()]
                        for pr in pull_requests:
                            for prr in pr:
                                # Remove leading and trailing space and replace commas with spaces
                                pr_title = prr.title.strip().replace(",", " ")
                                # Remove multiple spaces
                                pr_title = re.sub(" +", " ", pr_title)
                                # Add PR number to title
                                pr_title = pr_title + \
                                    " (PR #" + str(prr.number) + ")"

                                row = github_repo + "," + pr_title + "," + str(prr.closed_at) + "," + prr.html_url

                                spreadsheet.add(row)
                    # Commit
                    else:
                        commit_title = found_commit.commit.message.strip().split('\n', 1)[0]  + " (Commit " + found_commit.sha[0:6] + ")"
                        commit_url = found_commit.commit.html_url[:-34]
                        row = github_repo + "," + commit_title + "," + str(found_commit.commit.committer.date) + "," + commit_url
                        spreadsheet.add(row)

    except KeyboardInterrupt:
        exit()

# Create .csv
with open(r'prs.csv', 'w') as f:
    f.write("Repo,Title,Date,URL\n")
    for item in sorted(spreadsheet):
        f.write("%s\n" % item)
