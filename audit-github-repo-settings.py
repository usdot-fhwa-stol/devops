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
    except Exception as e:
        logging.error(red + "Request failed: " + url + " | Error: " + str(e))
        exit(1)

    try:
        request_json = json.loads(request.text)
    except json.JSONDecodeError:
        logging.error(red + f"Non-JSON response from {url}")
        exit(1)

    return request_json


def get_repo_list(github_org, github):
    repo_list = []

    try:
        for repo in github.get_organization(github_org).get_repos():
            repo_list = repo_list + [repo.name]
    except Exception as e:
        logging.error(red + f"Error fetching repositories for organization {github_org}: {str(e)}")
        exit(1)

    repo_list = sorted(repo_list)

    return repo_list


def is_branch(branch, repo):
    # Test branch existence
    branch_exists = False
    try:
        for ref in repo.get_git_refs():
            if "refs/heads/" + branch == ref.ref:
                branch_exists = True
                break 
    except Exception as e:
        logging.error(red + f"Error checking branch existence for {branch} in {repo.name}: {str(e)}")
    return branch_exists


def tests(github_branch, repo_full_name, token):
    repo = github.get_repo(repo_full_name)
    msg = repo.name + ": " + github_branch + ": "

    branch_errors = []

    repo_dict = {}
    repo_dict[repo.name] = {}

    # Test branch existence
    if is_branch(github_branch, repo):
        try:
            branch = repo.get_branch(github_branch)
        except Exception as e:
            logging.error(red + f"{repo.name}: Error fetching branch {github_branch}: {str(e)}")
            return {}  
        repo_dict[repo.name][branch.name] = {}
        repo_dict[repo.name][branch.name]["branch-errors"] = branch_errors

        if test_repo_default_branch(repo):
            logging.info(green + repo.name + ': "Default branch" is "develop"')
        else:
            message_fail = '"Default branch" is not "develop"!'
            branch_errors.append(message_fail)
            logging.error(red + repo.name + ": " + message_fail)
    else:
        logging.warning(yellow + msg + "branch does not exist, skipping it")
        return {} 

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

        if repo.organization.login == "usdot-fhwa-stol":
            # "Allow specified actors to bypass required pull requests"
            if test_branch_require_pull_requests(branch, token):
                logging.info(
                    green
                    + msg
                    + '"Allow specified actors to bypass required pull requests" includes Kyle and Mike'
                )
            else:
                message_fail = '"Allow specified actors to bypass required pull requests" excludes Kyle'
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
        try:
            required_approvals = branch.get_required_pull_request_reviews().required_approving_review_count
            if required_approvals >= 1:
                logging.info(
                    green + msg + '"Required number of approvals before merging" >= 1'
                )
            else:
                message_fail = '"Required number of approvals before merging" < 1!'
                branch_errors = branch_errors + [message_fail]
                logging.error(red + msg + message_fail)
        except Exception as e:
            logging.error(red + f"{msg} Error fetching required approvals: {str(e)}")
            branch_errors = branch_errors + ["Error fetching required approvals"]

        # "Dismiss stale pull request approvals when new commits are pushed"
        try:
            dismiss_stale = branch.get_required_pull_request_reviews().dismiss_stale_reviews
            if dismiss_stale:
                logging.info(
                    green
                    + msg
                    + '"Dismiss stale pull request approvals when new commits are pushed" enabled'
                )
            else:
                message_fail = '"Dismiss stale pull request approvals when new commits are pushed" disabled'
                branch_errors = branch_errors + [message_fail]
                logging.error(red + msg + message_fail)
        except Exception as e:
            logging.error(red + f"{msg} Error fetching dismiss stale reviews setting: {str(e)}")
            branch_errors = branch_errors + ["Error fetching dismiss stale reviews setting"]

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
                branch_errors = branch_errors + [message_fail]
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
        if repo.organization.login == "usdot-fhwa-stol":
            admin_teams = ["Administration"]
            dev_teams = ["Administration", "Leidos Developers"]
        elif repo.organization.login == "usdot-jpo-ode":
            admin_teams = ["administration"]
            dev_teams = ["admins", "bah_team", "leidos_team"]
        elif repo.organization.login == "usdot-fhwa-ops":
            admin_teams = ["V2X Hub Admins"]
            dev_teams = ["V2X Hub Team", "PCS Team"]
        else:
            message_fail = f"Organization '{repo.organization.login}' is not recognized. Skipping checks."
            logging.error(red + message_fail)
            branch_errors = branch_errors + [message_fail]
            repo_dict[repo.name][branch.name]["branch-errors"] = branch_errors
            return repo_dict 

        if test_branch_push_restrictions(admin_teams, branch, dev_teams, repo.organization.login):
            if branch.name in ["main", "master"]:
                message_pass = (
                    green
                    + msg
                    + '"Restrict who can push to matching branches" set to ' + ", ".join(admin_teams)
                )
            else:
                message_pass = (
                    green
                    + msg
                    + '"Restrict who can push to matching branches" set to ' + ", ".join(dev_teams)
                )
            logging.info(message_pass)
        else:
            if branch.name in ["main", "master"]:
                message_fail = '"Restrict who can push to matching branches" not set to ' + ", ".join(admin_teams)
            else:
                message_fail = '"Restrict who can push to matching branches" not set to ' + ", ".join(dev_teams)
            branch_errors = branch_errors + [message_fail]
            logging.error(red + msg + message_fail)
    else:
        message_fail = '"Branch protection rules" disabled!'
        branch_errors = branch_errors + [message_fail]
        logging.error(red + msg + message_fail)

    repo_dict[repo.name][branch.name]["branch-errors"] = branch_errors

    return repo_dict


# "Do not allow bypassing the above settings"
def test_branch_admin_enforcement(branch, msg):
    try:
        if branch.get_admin_enforcement():
            return True
    except Exception as e:
        logging.error(red + f"{msg} Error checking admin enforcement: {str(e)}")
    return False


# "Require status checks before merging"
def test_branch_require_status_checks(branch, token):
    try:
        protection = branch.get_protection()
        return protection.required_status_checks is not None
    except Exception as e:
        logging.error(red + f"Error checking status checks for branch {branch.name}: {str(e)}")
        return False


# "Status checks that are required"
def test_branch_status_checks_ci(branch, token, ci_name):
    try:
        protection = branch.get_protection()
        status_checks = protection.required_status_checks.contexts
        return ci_name in status_checks
    except Exception as e:
        logging.error(red + f"Error checking CI status checks for branch {branch.name}: {str(e)}")
        return False


# "Allow deletions"
def test_branch_allow_deletions(branch, token):
    try:
        protection = branch.get_protection()
        return not protection.allow_deletions
    except Exception as e:
        logging.error(red + f"Error checking allow deletions for branch {branch.name}: {str(e)}")
        return False


# "Allow force pushes"
def test_branch_allow_force_pushes(branch, token):
    try:
        protection = branch.get_protection()
        return not protection.allow_force_pushes
    except Exception as e:
        logging.error(red + f"Error checking allow force pushes for branch {branch.name}: {str(e)}")
        return False


# "Restrict who can push to matching branches"
def test_branch_push_restrictions(admin_teams, branch, dev_teams, org):

    if branch.name in ["main", "master"]:
        team_names = admin_teams
    else:
        team_names = dev_teams

    try:
        if len(list(branch.get_team_push_restrictions())) >= 1:
            github_team_names = []
            for team in branch.get_team_push_restrictions():
                github_team_names = github_team_names + [team.name]

            for team in team_names:
                if team not in github_team_names:
                    return False

            return True
    except Exception as e:
        logging.error(red + f"Error checking push restrictions for branch {branch.name}: {str(e)}")
    return False


# "Allow specified actors to bypass required pull requests"
def test_branch_require_pull_requests(branch, token):
    bypass_users = ["kjrush", "maefromm", "JonSmet"]

    try:
        protection_json = get_github_json(branch.get_protection().url, token)
        github_bypass_json = protection_json["required_pull_request_reviews"][
            "bypass_pull_request_allowances"
        ]["users"]
    except Exception as e:
        logging.error(red + f"Error accessing bypass users: {str(e)}")
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
        exit(1)

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
        "usdot-jpo-ode/usdot-jpo-ode.github.io",
    ]

    if github_repo in blacklist:
        logging.warning(yellow + github_repo + ": blacklisted repository, skipping it")
        return True
    else:
        return False


def open_github_issue(errors_dict, github_token, org):
    issue_repo = os.environ.get("GITHUB_REPOSITORY")
    if not issue_repo:
        logging.error("Environment variable GITHUB_REPOSITORY is not set.")
        return  

    github = Github(github_token)
    try:
        repo = github.get_repo(issue_repo)
    except Exception as e:
        logging.error(red + f"Error accessing issue repository {issue_repo}: {str(e)}")
        return 

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
                    issue_body += (
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
                        logging.error("Failed to create GitHub issue\n" + str(e))
                        exit(1)

def check_branch_protection_graphql(owner, repo, token):
    """
    Uses GitHub's GraphQL API to check for branch protection rules matching 'hotfix/*' and 'release/*'.
    Returns a list of existing patterns.
    """
    url = "https://api.github.com/graphql"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    query = """
    query($owner: String!, $repo: String!) {
      repository(owner: $owner, name: $repo) {
        branchProtectionRules(first: 100) {
          nodes {
            pattern
          }
        }
      }
    }
    """
    variables = {
        "owner": owner,
        "repo": repo
    }
    try:
        response = requests.post(url, json={'query': query, 'variables': variables}, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"GraphQL query failed for {owner}/{repo}: {str(e)}")
        return None

    try:
        result = response.json()
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON response for {owner}/{repo}: {str(e)}")
        return None

    if ('data' not in result or
        'repository' not in result['data'] or
        result['data']['repository'] is None or
        'branchProtectionRules' not in result['data']['repository'] or
        result['data']['repository']['branchProtectionRules'] is None):
        logging.error(f"Failed to fetch branch protection rules for {owner}/{repo}. No data returned.")
        return None

    patterns = [rule['pattern'] for rule in result['data']['repository']['branchProtectionRules']['nodes']]
    return patterns


def check_hotfix_release_rules(repo_full_name, token):
    """
    Checks if 'hotfix/*' and 'release/*' branch protection rules exist using GraphQL.
    Returns a dict with branch-errors if rules are missing.
    """
    parts = repo_full_name.split('/', 1)
    if len(parts) != 2:
        logging.error(f"Invalid repository name format: {repo_full_name}")
        return {"branch-errors": [f"Invalid repository name format: {repo_full_name}"]}

    owner, repo = parts
    patterns = check_branch_protection_graphql(owner, repo, token)
    
    if patterns is None:
        return {}
    
    errors_dict = {"branch-errors": []}
    
    if "hotfix/*" not in patterns:
        errors_dict["branch-errors"].append('No branch protection rule for "hotfix/*"')
    
    if "release/*" not in patterns:
        errors_dict["branch-errors"].append('No branch protection rule for "release/*"')
    
    return errors_dict if errors_dict["branch-errors"] else {}

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
        logging.error(red + "Error initializing GitHub client: " + str(e))
        exit(1)

    try:
        for org in args.organizations:
            for github_repo in get_repo_list(org, github):
                full_repo_name = f"{org}/{github_repo}"
                if not is_blacklisted_repo(full_repo_name):
                    try:
                        repo = get_repo(full_repo_name, github)
                    except Exception as e:
                        logging.error(red + f"{full_repo_name}: Error fetching repository: {str(e)}")
                        continue

                    # Skip archived repos
                    if repo.archived:
                        logging.warning(
                            yellow + github_repo + ": archived repository, skipping it"
                        )
                        continue

                    # For each named branch (e.g. develop, main, master), perform existing checks
                    for branch in args.branches:
                        errors_dict = tests(
                            branch, full_repo_name, args.github_token
                        )
                        if not isinstance(errors_dict, dict):
                            errors_dict = {} 

                        hotfix_release_errors = check_hotfix_release_rules(full_repo_name, args.github_token)
                        if hotfix_release_errors:
                            if full_repo_name not in errors_dict:
                                errors_dict[full_repo_name] = {}
                            
                            errors_dict[full_repo_name]["hotfix_release_rules"] = {
                                "branch-errors": hotfix_release_errors["branch-errors"]
                            }
                        if args.open_github_issues and errors_dict:
                            open_github_issue(errors_dict, args.github_token, org)
    except KeyboardInterrupt:
        logging.info("Script interrupted by user. Exiting.")
        exit(0)
    except Exception as e:
        logging.error(red + f"Unexpected error: {str(e)}")
        exit(1)