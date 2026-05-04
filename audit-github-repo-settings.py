#!/usr/bin/env python3
from github import Github, Auth
import argparse
import logging
import os
import pathlib
import requests
import time


green = "✅ \033[92m"
red = "❌ \033[91m"
yellow = "⚠️  \033[93m"

# Repos where default branch is allowed to NOT be "develop".
DEFAULT_BRANCH_EXEMPT = [
    "usdot-fhwa-stol/usdot-asn1c",
    "usdot-fhwa-stol/autoware.ai",
    "usdot-fhwa-stol/navigation2",
    "usdot-fhwa-stol/rosbridge_suite",
    "usdot-fhwa-stol/tracetools_analysis",
    "usdot-fhwa-stol/docs.nav2.org",
    "usdot-fhwa-stol/rosbag2",
    "usdot-fhwa-stol/cda-mmitss",
    "usdot-fhwa-stol/intersection-safety-challenge",
    "usdot-fhwa-stol/To-21-426-multivariate-piecewise-linear-ACC-car-following-model",
    "usdot-fhwa-stol/5G-MEC-testing",
    "usdot-fhwa-stol/To-21-426-modeling-HV-interactions-with-inconspicuous-ACC-equipped-vehicles",
    "usdot-fhwa-stol/robot_localization",
    "usdot-fhwa-stol/asn-code-gen",
    "usdot-fhwa-stol/DOT-V2X-Fieldtest-Data",
    "usdot-fhwa-stol/carma_ament_lint",
    "usdot-fhwa-stol/ros2_tracing",
    "usdot-fhwa-stol/novatel_oem7_driver",
    "usdot-fhwa-stol/voices-cda-use-case-scenario-database",
    "usdot-fhwa-stol/sumo",
    "usdot-fhwa-stol/mosaic",
    "usdot-fhwa-stol/cda-simulation-twg",
    "usdot-fhwa-stol/CARMAConcept",
    "usdot-fhwa-stol/CARMAConceptOld",
    "usdot-fhwa-stol/glidepath-ead",
    "usdot-fhwa-ops/v2xhub-angular-ui-prototype",
    "usdot-fhwa-ops/libwebsockets",
    "usdot-jpo-ode/j2735-ffm-java",
    "usdot-jpo-ode/actions",
    "usdot-jpo-ode/scms-asn1",
    "usdot-jpo-ode/TDx",
    "usdot-jpo-ode/jpo-cvportal",
    "usdot-jpo-ode/usdot-jpo-ode.github.io",
    "usdot-jpo-ode/jpo-record-parser",
    "usdot-jpo-ode/jpo-security",
    "usdot-jpo-ode/jpo-ode-scms-asn",
    "usdot-jpo-ode/Pikalert-Vehicle-Data-Translator-",
]


def get_github_json(url, token):
    headers = {
        "Authorization": "token " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=180)
    except requests.RequestException as e:
        logging.error(red + "request failed: " + url + f" ({e})")
        exit(1)

    if not resp.ok:
        logging.error(
            red + f"GitHub API returned {resp.status_code} for {url}. Body: {resp.text[:250]}"
        )
        exit(1)

    try:
        return resp.json()
    except ValueError:
        logging.error(red + f"Invalid JSON response for {url}. Body: {resp.text[:250]}")
        exit(1)


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

def _enabled(obj):
    """
    allow_* fields can be:
      - {"enabled": true/false}
      - missing
    """
    if isinstance(obj, dict):
        return obj.get("enabled")
    if isinstance(obj, bool):
        return obj
    return None

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

        # Default branch enforcement ONLY if develop branch exists
        if is_branch("develop", repo):
            # Skip default-branch enforcement for exempt repos
            if repo.full_name in DEFAULT_BRANCH_EXEMPT:
                logging.info(yellow + repo.full_name + ": default-branch exempt; skipping default-branch check")
            else:
                if test_repo_default_branch(repo):
                    logging.info(green + repo.name + ': "Default branch" is "develop"')
                else:
                    message_fail = '"Default branch" is not "develop"!'
                    branch_errors = branch_errors + [message_fail]
                    logging.error(red + repo.full_name + ": " + message_fail)
        else:
            logging.info(green + repo.full_name + ": develop branch not present; skipping default-branch check")
    else:
        logging.warning(yellow + msg + "branch does not exist, skipping it")
        return

    # Test .github/workflows existence
    if branch.name == "develop" and test_branch_contains(repo, branch.name, ".github/workflows"):
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
        if branch.name == "develop" and test_branch_contains(repo, branch.name, template):
            message_fail = "Branch contains " + template + " instead of YAML-based template"
            # FIXME: change to fatal error in the future
            # branch_errors = branch_errors + [message_fail]
            logging.warning(yellow + msg + message_fail)
        else:
            logging.info(green + msg + "Branch does not contain " + template)

    # "Branch protection rules"
    if branch.protected:
        logging.info(green + msg + '"Branch protection rules" enabled')

        if org == "usdot-fhwa-stol":
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
        if branch.get_required_pull_request_reviews().required_approving_review_count >= 1:
            logging.info(green + msg + '"Required number of approvals before merging" >= 1')
        else:
            message_fail = '"Required number of approvals before merging" < 1!'
            branch_errors = branch_errors + [message_fail]
            logging.error(red + msg + message_fail)

        # "Dismiss stale pull request approvals when new commits are pushed"
        if branch.get_required_pull_request_reviews().dismiss_stale_reviews:
            logging.info(green + msg + '"Dismiss stale pull request approvals when new commits are pushed" enabled')
        else:
            message_fail = '"Dismiss stale pull request approvals when new commits are pushed" disabled'
            branch_errors = branch_errors + [message_fail]
            logging.error(red + msg + message_fail)

        # "Do not allow bypassing the above settings"
        if test_branch_admin_enforcement(branch, msg):
            logging.info(green + msg + '"Do not allow bypassing the above settings" enabled')
        else:
            message_fail = '"Do not allow bypassing the above settings" disabled!'
            branch_errors = branch_errors + [message_fail]
            logging.error(red + msg + message_fail)

        # "Restrict who can push to matching branches"
        if org == "usdot-fhwa-stol":
            admin_teams = ["Administration"]
            dev_teams = ["Administration", "Leidos Developers"]
        elif org == "usdot-jpo-ode":
            admin_teams = ["administrators"]
            dev_teams = ["administrators", "leidos_team"]
        elif org == "usdot-fhwa-ops":
            admin_teams = ["V2X-Hub Admins"]
            dev_teams = ["V2X-Hub Team"]

        if test_branch_push_restrictions(repo, admin_teams, branch, dev_teams, org):
            if repo.private:
                logging.info(green + msg + '"Restrict who can push to matching branches" enabled (private repo: team names not enforced)')
            else:
                if branch.name in ["main", "master"]:
                    logging.info(green + msg + '"Restrict who can push to matching branches" set to ' + ", ".join(admin_teams))
                else:
                    logging.info(green + msg + '"Restrict who can push to matching branches" set to ' + ", ".join(dev_teams))
        else:
            if repo.private:
                message_fail = '"Restrict who can push to matching branches" is not enabled (no team restriction set)'
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
    if branch.get_admin_enforcement():
        return True
    else:
        return False

# "Allow deletions"
def test_branch_allow_deletions(branch, token):
    protection_json = get_github_json(branch.get_protection().url, token)
    if not protection_json:
        return True  # skip/assume pass if we can't read protection

    enabled = _enabled(protection_json.get("allow_deletions"))
    if enabled is None:
        return True  # field missing -> skip/assume pass

    return not enabled


# "Allow force pushes"
def test_branch_allow_force_pushes(branch, token):
    protection_json = get_github_json(branch.get_protection().url, token)

    if protection_json["allow_force_pushes"]["enabled"]:
        return False
    else:
        return True

# "Restrict who can push to matching branches"
def test_branch_push_restrictions(repo, admin_teams, branch, dev_teams, org):
    # For private repos, allow repo-specific teams: just require that some restriction exists.
    enforce_exact_teams = not repo.private

    if branch.name in ["main", "master"]:
        team_names = admin_teams
    else:
        team_names = dev_teams

    try:
        teams = list(branch.get_team_push_restrictions())
        if len(teams) < 1:
            return False

        if not enforce_exact_teams:
            return True

        github_team_names = [t.name for t in teams]

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
    if not protection_json:
        return False

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
        "usdot-jpo-ode/usdot-jpo-ode.github.io",
        "usdot-fhwa-stol/carma_ament_lint",
        "usdot-fhwa-stol/cav-education",
        "usdot-fhwa-stol/CARMASensitive",
        "usdot-fhwa-stol/opendrive2lanelet",
        "usdot-fhwa-stol/actions",
        "usdot-fhwa-stol/devops",
        "usdot-fhwa-stol/carma-builds",
        "usdot-fhwa-stol/spectrum-testing",
        "usdot-fhwa-stol/.github",
        "usdot-fhwa-stol/To-21-426-multivariate-piecewise-linear-ACC-car-following-model",
        "usdot-fhwa-stol/To-21-426-modeling-HV-interactions-with-inconspicuous-ACC-equipped-vehicles",
        "usdot-fhwa-stol/tracetools_analysis",
        "usdot-fhwa-stol/robot_localization",
        "usdot-fhwa-stol/Stol-scratchpad",
        "usdot-fhwa-stol/asn-code-gen",
        "usdot-fhwa-stol/voices-protocol-io-library",
        "usdot-fhwa-stol/dwm1001_ros2",
        "usdot-fhwa-stol/c1t_zed_driver",
        "usdot-fhwa-stol/c1t_razor_imu_m0_driver",
        "usdot-fhwa-stol/c1t_rplidar_driver",
        "usdot-fhwa-stol/temp_test_repo",
        "usdot-jpo-ode/jpo-security",
        "usdot-jpo-ode/jpo-tim-builder",
        "usdot-jpo-ode/wzdx",
        "usdot-jpo-ode/wzdc-tool",
        "usdot-jpo-ode/TDx",
        "usdot-jpo-ode/jpo-mec-deposit",
        "usdot-jpo-ode/jpo-cvportal",
        "usdot-jpo-ode/scms-asn1",
        "usdot-jpo-ode/jpo-haas-asn1-bridge",
        "usdot-jpo-ode/jpo-rtk-asn1-bridge",
        "usdot-jpo-ode/github-access-review",
        "usdot-jpo-ode/Pikalert-Vehicle-Data-Translator-",
        "usdot-fhwa-ops/sample_angular_saml_app",
        "usdot-fhwa-ops/.github",
        "usdot-fhwa-ops/libwebsockets",
        "usdot-fhwa-OPS/v2xhub-network-test",
        "usdot-fhwa-ops/v2xhub-integration-tests"
        "usdot-fhwa-ops/github-access-review",
    ]

    if github_repo in blacklist:
        logging.warning(yellow + github_repo + ": blacklisted repository, skipping it")
        return True
    else:
        return False

def open_github_issue(errors_dict, github_token, org):
    issue_repo = os.environ["GITHUB_REPOSITORY"]
    github = Github(auth=Auth.Token(github_token))
    repo = github.get_repo(issue_repo)

    # Prevent duplicates even if issues are closed: find in state="all", reopen + update.
    def find_issue_by_title(title):
        issues = repo.get_issues(state="all")
        for issue in issues:
            if issue.title == title:
                return issue
        return None

    for github_repo in errors_dict:
        for branch in errors_dict[github_repo]:
            if errors_dict[github_repo][branch]["branch-errors"]:
                issue_title = (
                    "GitHub repository settings misconfigured: %s/%s %s branch"
                    % (org, github_repo, branch)
                )

                settings_url = "https://github.com/" + org + "/" + github_repo + "/settings"

                issue_body = ( "### Component\n\nInfrastructure\n\n### Specifics\n\n"
                    "- [ ] Docker or Docker Hub\n"
                    "- [ ] Doxygen\n"
                    "- [ ] GitHub Actions\n"
                    "- [X] GitHub branch or repo\n"
                    "- [ ] Sonar\n\n"
                    "### What happened?\n\n"
                )
                issue_body = issue_body + (
                    "The following ["
                    + org
                    + "/"
                    + github_repo
                    + " settings]("
                    + settings_url
                    + ") are misconfigured:"
                    + "\n- [ ] "
                    + "\n- [ ] ".join(errors_dict[github_repo][branch]["branch-errors"])
                )

                existing = find_issue_by_title(issue_title)
                try:
                    if existing:
                        if existing.state == "closed":
                            existing.edit(state="open")
                        existing.edit(body=issue_body)
                        print(
                            "GitHub repository settings misconfigured: %s/%s %s branch - Updated issue %d"
                            % (org, github_repo, branch, existing.number)
                        )
                        time.sleep(2)
                    else:
                        issue = repo.create_issue(title=issue_title, body=issue_body)
                        print(
                            "GitHub repository settings misconfigured: %s/%s %s branch - Created issue %d"
                            % (org, github_repo, branch, issue.number)
                        )
                        time.sleep(15)
                except Exception as e:
                    logging.error("Failed to create/update GitHub issue\n" + str(e))
                    exit(1)

def check_branch_protection_graphql(owner, repo_name, token):
    """
    Uses GitHub's GraphQL API to fetch existing branch protection patterns (e.g. main, develop, hotfix/*).
    Returns a list of patterns, or None on error.
    """
    url = "https://api.github.com/graphql"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
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
    variables = {"owner": owner, "repo": repo_name}
    try:
        response = requests.post(url, json={"query": query, "variables": variables}, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"GraphQL query failed for {owner}/{repo_name}: {str(e)}")
        return None

    try:
        data = response.json()
    except:
        logging.error(f"Invalid JSON response for {owner}/{repo_name}")
        return None

    if (
        ("data" not in data)
        or ("repository" not in data["data"])
        or (data["data"]["repository"] is None)
        or ("branchProtectionRules" not in data["data"]["repository"])
        or (data["data"]["repository"]["branchProtectionRules"] is None)
    ):
        logging.error(f"Failed to fetch branch protection rules for {owner}/{repo_name}. No data returned.")
        return None

    patterns = []
    for rule_node in data['data']['repository']['branchProtectionRules']['nodes']:
        patterns = patterns + [rule_node['pattern']]

    return patterns


def check_hotfix_release_rules(full_repo_name, token):
    """
    Checks if "hotfix/*" and "release/*" branch protection rules exist for the given repo.
    If missing, returns a dict with 'branch-errors'.
    Otherwise returns an empty dict.
    """
    parts = full_repo_name.split("/", 1)
    if len(parts) != 2:
        logging.error(f"Invalid repo name format: {full_repo_name}")
        return {"branch-errors": [f"Invalid repo name format: {full_repo_name}"]}

    owner, repo_name = parts
    patterns = check_branch_protection_graphql(owner, repo_name, token)
    if patterns is None:
        return {}  # if we can't fetch the patterns, just skip gracefully

    missing_rules = []
    if "hotfix/*" not in patterns:
        missing_rules = missing_rules + ['No branch protection rule for "hotfix/*"']
    if "release/*" not in patterns:
        missing_rules = missing_rules + ['No branch protection rule for "release/*"']

    if missing_rules:
        return {"branch-errors": missing_rules}

    return {}

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
        github = Github(auth=Auth.Token(args.github_token))
    except Exception as e:
        logging.error(e)
        exit()

    try:
        for org in args.organizations:
            for github_repo_name in get_repo_list(org, github):
                if not is_blacklisted_repo(org + "/" + github_repo_name):
                    repo = get_repo(org + "/" + github_repo_name, github)
                    if repo.archived:
                        logging.warning(yellow + github_repo_name + ": archived repository, skipping it")
                    else:
                        for branch in args.branches:
                            errors_dict = tests(branch, org + "/" + github_repo_name, args.github_token)

                            # If no errors dict returned, skip
                            if not errors_dict:
                                errors_dict = {}

                            # Check for hotfix/*, release/* rules
                            hotfix_release_errors = check_hotfix_release_rules(org + "/" + github_repo_name, args.github_token)
                            if hotfix_release_errors:
                                # Keep same key style as tests() also which fix double-org links in Issue body
                                if github_repo_name not in errors_dict:
                                    errors_dict[github_repo_name] = {}
                                errors_dict[github_repo_name]["hotfix_release_rules"] = {
                                    "branch-errors": hotfix_release_errors["branch-errors"]
                                }

                            # If user wants to open issues and we have errors, do it
                            if args.open_github_issues and errors_dict:
                                open_github_issue(errors_dict, args.github_token, org)
    except KeyboardInterrupt:
        exit()
