#!/usr/bin/env python3
from github import Github
import argparse
import json
import logging
import os
import pathlib
import requests
import time


green = "✅ \033[92m"
red = "❌ \033[91m"
yellow = "⚠️  \033[93m"


def get_github_json(url, token):
    headers = {
        "Authorization": "token " + token,
        "Accept": "application/vnd.github+json",
    }
    try:
        request = requests.get(
            url,
            headers=headers,
        )
    except:
        logging.error(red + "request failed: " + url)
        exit()

    request_json = json.loads(request.text)

    return request_json


def get_repo_list(github_org, github):
    repo_list = []

    for repo in github.get_organization(github_org).get_repos():
        repo_list = repo_list + [repo.name]

    repo_list = sorted(repo_list)

    return repo_list


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


def tests(github_branch, repo, token):
    repo = github.get_repo(repo)
    msg = repo.name + ": " + github_branch + ": "

    branch_errors = []

    repo_dict = {}
    repo_dict[repo.name] = {}

    # Test branch existence
    if is_branch(github_branch, repo):
        branch = repo.get_branch(github_branch)
        repo_dict[repo.name][branch.name] = {}
        repo_dict[repo.name][branch.name]["branch-errors"] = {}

        if test_repo_default_branch(repo):
            logging.info(green + repo.name + ': "Default branch" is "develop"')
        else:
            message_fail = '"Default branch" is not "develop"!'
            branch_errors = [message_fail]
            logging.error(red + repo.name + ": " + message_fail)
    else:
        logging.warning(yellow + msg + "branch does not exist, skipping it")
        return

    # Test .github/workflows existence
    if branch.name == "develop" and test_branch_contains(
        repo, branch.name, ".github/workflows"
    ):
        # Test dependabot.yml existence
        if test_branch_contains(repo, branch.name, ".github/dependabot.yml"):
            logging.info(green + msg + "Branch contains .github/dependabot.yml")
        else:
            message_fail = "Branch does not contain .github/dependabot.yml"
            # FIXME: change to fatal error in the future
            # branch_errors = branch_errors + [message_fail]
            logging.warning(yellow + msg + message_fail)

    # Test Markdown template existence
    templates = ["docs/ISSUE_TEMPLATE.md", "docs/PULL_REQUEST_TEMPLATE.md"]
    for template in templates:
        if branch.name == "develop" and test_branch_contains(
            repo, branch.name, template
        ):
            message_fail = (
                "Branch contains " + template + " instead of YAML-based template"
            )
            # FIXME: change to fatal error in the future
            # branch_errors = branch_errors + [message_fail]
            logging.warning(yellow + msg + message_fail)
        else:
            logging.info(green + msg + "Branch does not contain " + template)

    # "Branch protection rules"
    if branch.protected:
        logging.info(green + msg + '"Branch protection rules" enabled')

        # "Allow specified actors to bypass required pull requests"
        if test_branch_require_pull_requests(branch, token):
            logging.info(
                green
                + msg
                + '"Allow specified actors to bypass required pull requests" includes Kyle and Mike'
            )
        else:
            message_fail = '"Allow specified actors to bypass required pull requests" excludes Kyle and Mike'
            # FIXME: change to fatal once GitHub API returns to normal(?), protection json stopped showing consistent output
            # branch_errors = branch_errors + [message_fail]
            logging.warning(yellow + msg + message_fail)

        # "Allow deletions"
        if test_branch_allow_deletions(branch, token):
            logging.info(green + msg + '"Allow deletions" disabled')
        else:
            message_fail = '"Allow deletions" enabled!'
            branch_errors = branch_errors + [message_fail]
            logging.error(red + msg + message_fail)

        # "Allow force pushes"
        if test_branch_allow_force_pushes(branch, token):
            logging.info(green + msg + '"Allow force pushes" disabled')
        else:
            message_fail = '"Allow force pushes" enabled!'
            branch_errors = branch_errors + [message_fail]
            logging.error(red + msg + message_fail)

        # "Required number of approvals before merging"
        if (
            branch.get_required_pull_request_reviews().required_approving_review_count
            >= 1
        ):
            logging.info(
                green + msg + '"Required number of approvals before merging" >= 1'
            )
        else:
            message_fail = '"Required number of approvals before merging" < 1!'
            branch_errors = branch_errors + [message_fail]
            logging.error(red + msg + message_fail)

        # "Dismiss stale pull request approvals when new commits are pushed"
        if branch.get_required_pull_request_reviews().dismiss_stale_reviews:
            logging.info(
                green
                + msg
                + '"Dismiss stale pull request approvals when new commits are pushed" enabled'
            )
        else:
            message_fail = '"Dismiss stale pull request approvals when new commits are pushed" disabled'
            branch_errors = branch_errors + [message_fail]
            logging.error(red + msg + message_fail)

        # "Require status checks before merging"
        if test_branch_require_status_checks(branch, token):
            logging.info(green + msg + '"Require status checks before merging" enabled')

            # "Status checks that are required"
            ci_name = "ci/circleci: build"
            if test_branch_status_checks_ci(branch, token, ci_name):
                message_pass = (
                    '"Require status checks before merging" included "' + ci_name + '"'
                )
                logging.info(green + msg + message_pass)
            else:
                message_fail = (
                    '"Require status checks before merging" excluded "' + ci_name + '"!'
                )
                logging.warning(yellow + msg + message_fail)
        else:
            message_fail = '"Require status checks before merging" disabled!'
            branch_errors = branch_errors + [message_fail]
            logging.error(red + msg + message_fail)

        # "Do not allow bypassing the above settings"
        if test_branch_admin_enforcement(branch, msg):
            logging.info(
                green + msg + '"Do not allow bypassing the above settings" enabled'
            )
        else:
            message_fail = '"Do not allow bypassing the above settings" disabled!'
            branch_errors = branch_errors + [message_fail]
            logging.error(red + msg + message_fail)

        # "Restrict who can push to matching branches"
        if test_branch_push_restrictions(branch):
            if branch.name in ["main", "master"]:
                message_pass = (
                    green
                    + msg
                    + '"Restrict who can push to matching branches" set to Administration'
                )
            else:
                message_pass = (
                    green
                    + msg
                    + '"Restrict who can push to matching branches" set to Administration and Leidos Developers'
                )
            logging.info(message_pass)
        else:
            if branch.name in ["main", "master"]:
                message_fail = '"Restrict who can push to matching branches" not set to Administration!'
            else:
                message_fail = '"Restrict who can push to matching branches" not set to Administration and Leidos Developers!'
            branch_errors = branch_errors + [message_fail]
            logging.error(red + msg + message_fail)
    else:
        message_fail = '"Branch protection rules" disabled!'
        branch_errors = branch_errors + [message_fail]
        logging.error(red + msg + message_fail)

    repo_dict[repo.name][branch.name]["branch-errors"] = branch_errors

    # print(str(repo_dict))

    return repo_dict


# "Do not allow bypassing the above settings"
def test_branch_admin_enforcement(branch, msg):
    if branch.get_admin_enforcement():
        return True

    else:
        return False


# "Require status checks before merging"
def test_branch_require_status_checks(branch, token):
    try:
        get_github_json(branch.get_required_status_checks().url, token)
        return True
    except:
        return False


# "Status checks that are required"
def test_branch_status_checks_ci(branch, token, ci_name):
    status_checks_json = get_github_json(branch.get_required_status_checks().url, token)

    ci_list = status_checks_json["contexts"]
    if ci_name in ci_list:
        return True
    else:
        return False


# "Allow deletions"
def test_branch_allow_deletions(branch, token):
    protection_json = get_github_json(branch.get_protection().url, token)

    if protection_json["allow_deletions"]["enabled"]:
        return False
    else:
        return True


# "Allow force pushes"
def test_branch_allow_force_pushes(branch, token):
    protection_json = get_github_json(branch.get_protection().url, token)

    if protection_json["allow_force_pushes"]["enabled"]:
        return False
    else:
        return True


# "Restrict who can push to matching branches"
def test_branch_push_restrictions(branch):
    if branch.name in ["main", "master"]:
        team_names = ["Administration"]
    else:
        team_names = ["Administration", "Leidos Developers"]

    try:
        if len(list(branch.get_team_push_restrictions())) >= 1:
            github_team_names = []
            for team in branch.get_team_push_restrictions():
                github_team_names = github_team_names + [team.name]

            for team in team_names:
                if team not in github_team_names:
                    return False

            return True
    except:
        return False


# "Allow specified actors to bypass required pull requests"
def test_branch_require_pull_requests(branch, token):
    bypass_users = ["kjrush"]

    protection_json = get_github_json(branch.get_protection().url, token)

    try:
        github_bypass_json = protection_json["required_pull_request_reviews"][
            "bypass_pull_request_allowances"
        ]["users"]
    except:
        return False

    # Get users from github
    github_bypass_users = []
    for user in github_bypass_json:
        github_bypass_users = github_bypass_users + [user["login"]]

    for user in bypass_users:
        if user not in github_bypass_users:
            return False

    return True


def test_branch_dismiss_stale_reviews(branch):
    branch.get_required_pull_request_reviews().dismiss_stale_reviews


def get_repo(github_repo, github):
    msg_failure = red + github_repo + ": repo does not exist or bad token"

    try:
        repo = github.get_repo(github_repo)
    except Exception as e:
        logging.error(e)
        logging.error(msg_failure)
        exit()

    return repo


def test_repo_default_branch(repo):
    if repo.default_branch != "develop":
        return False
    else:
        return True


def test_branch_contains(repo, branch, contents):
    try:
        repo.get_contents(contents, ref=branch)
        return True
    except:
        return False


def is_blacklisted_repo(github_repo):
    blacklist = [
        "usdot-fhwa-stol/documentation",
        "usdot-fhwa-stol/github_metrics",
        "usdot-fhwa-stol/voices-cda-use-case-scenario-database",
    ]

    if github_repo in blacklist:
        logging.warning(yellow + github_repo + ": blacklisted repository, skipping it")
        return True
    else:
        return False


def open_github_issue(errors_dict, github_token, org):
    issue_repo = os.environ["GITHUB_REPOSITORY"]
    github = Github(github_token)
    repo = github.get_repo(issue_repo)

    def github_issue_exists(title):
        open_issues = repo.get_issues(state="open")
        for issue in open_issues:
            if issue.title == title:
                return True
        return False

    for github_repo in errors_dict:
        for branch in errors_dict[github_repo]:
            if errors_dict[github_repo][branch]["branch-errors"]:
                issue_title = (
                    "GitHub repository settings misconfigured: %s/%s %s branch"
                    % (org, github_repo, branch)
                )
                if not github_issue_exists(issue_title):
                    settings_url = (
                        "https://github.com/" + org + "/" + github_repo + "/settings"
                    )
                    issue_body = "### Component\n\nInfrastructure\n\n### Specifics\n\n- [ ] CircleCI\n- [ ] Docker or Docker Hub\n- [ ] Doxygen\n- [ ] GitHub Actions\n- [X] GitHub branch or repo\n- [ ] Sonar\n\n### What happened?\n\n"
                    issue_body = issue_body + (
                        "The following ["
                        + org
                        + "/"
                        + github_repo
                        + " settings]("
                        + settings_url
                        + ") are misconfigured:"
                        + "\n- [ ] "
                        + "\n- [ ] ".join(
                            errors_dict[github_repo][branch]["branch-errors"]
                        )
                    )
                    try:
                        issue = repo.create_issue(title=issue_title, body=issue_body)
                        print(
                            "GitHub repository settings misconfigured: %s/%s %s branch - Created issue %d"
                            % (
                                org,
                                github_repo,
                                branch,
                                issue.number,
                            )
                        )
                        # Try to avoid API rate limit
                        time.sleep(15)
                    except Exception as e:
                        logging.error("Failed to create GitHub issue\n" + e)
                        exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--branches", nargs="+", required=True)
    parser.add_argument("--open-github-issues", action="store_true")
    parser.add_argument("--organizations", nargs="+", required=True)
    parser.add_argument("--github-token", required=True)
    args = parser.parse_args()

    log = pathlib.Path("github-settings-scanner.log")
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

    try:
        for org in args.organizations:
            for github_repo in get_repo_list(org, github):
                if not is_blacklisted_repo(org + "/" + github_repo):
                    repo = get_repo(org + "/" + github_repo, github)
                    if repo.archived:
                        logging.warning(
                            yellow + github_repo + ": archived repository, skipping it"
                        )
                    else:
                        for branch in args.branches:
                            errors_dict = tests(
                                branch, org + "/" + github_repo, args.github_token
                            )
                            if args.open_github_issues and errors_dict:
                                open_github_issue(errors_dict, args.github_token, org)
    except KeyboardInterrupt:
        exit()
