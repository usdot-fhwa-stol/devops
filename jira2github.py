#!/usr/bin/env python3

from generate_release_notes import get_issues_from_pr
from github import Github
from jira import JIRA
from jira_utils import *
from requests.auth import HTTPBasicAuth
import argparse
import logging
import re
import sys

# GitHub repos to search for pre-existing issues already linked to Jira keys
# Duplicate Jira keys are allowed in this list
github_repo_jira_project_children = {
    "usdot-fhwa-OPS/V2X-Hub": "VH",
    "usdot-fhwa-stol/.github": "DEV",
    "usdot-fhwa-stol/actions": "DEV",
    "usdot-fhwa-stol/arena_camera_ros": "",
    "usdot-fhwa-stol/autoware.ai": "",
    "usdot-fhwa-stol/autoware.auto": "",
    "usdot-fhwa-stol/avt_vimba_camera": "",
    "usdot-fhwa-stol/c1t-tools": "",
    "usdot-fhwa-stol/c1t2x-emulator": "",
    "usdot-fhwa-stol/c1t_razor_imu_m0_driver": "",
    "usdot-fhwa-stol/c1t_rplidar_driver": "",
    "usdot-fhwa-stol/c1t_vesc_driver": "",
    "usdot-fhwa-stol/c1t_zed_driver": "",
    "usdot-fhwa-stol/c2c-ri": "",
    "usdot-fhwa-stol/carma-analytics-fotda": "",
    "usdot-fhwa-stol/carma-base": "",
    "usdot-fhwa-stol/carma-builds": "DEV",
    "usdot-fhwa-stol/carma-carla-integration": "",
    "usdot-fhwa-stol/carma-cloud": "CRMCLD",
    "usdot-fhwa-stol/carma-cohda-dsrc-driver": "",
    "usdot-fhwa-stol/carma-config": "",
    "usdot-fhwa-stol/carma-delphi-esr-driver": "",
    "usdot-fhwa-stol/carma-delphi-srr2-driver": "",
    "usdot-fhwa-stol/carma-garmin-lidar-lite-v3-driver-wrapper": "",
    "usdot-fhwa-stol/carma-j2735": "",
    "usdot-fhwa-stol/carma-lightbar-driver": "",
    "usdot-fhwa-stol/carma-message-filters": "",
    "usdot-fhwa-stol/carma-messenger": "",
    "usdot-fhwa-stol/carma-msgs": "",
    "usdot-fhwa-stol/carma-novatel-oem7-driver-wrapper": "",
    "usdot-fhwa-stol/carma-ns3-adapter": "",
    "usdot-fhwa-stol/carma-platform": "CAR",
    "usdot-fhwa-stol/carma-ssc-interface-wrapper": "",
    "usdot-fhwa-stol/carma-streets": "",
    "usdot-fhwa-stol/carma-time-lib": "",
    "usdot-fhwa-stol/carma-torc-pinpoint-driver": "",
    "usdot-fhwa-stol/carma-utils": "",
    "usdot-fhwa-stol/carma-vehicle-model-framework": "",
    "usdot-fhwa-stol/carma-velodyne-lidar-driver": "",
    "usdot-fhwa-stol/carma-web-ui": "",
    "usdot-fhwa-stol/cav-education": "",
    "usdot-fhwa-stol/cavams": "",
    "usdot-fhwa-stol/cda-telematics": "WFD",
    "usdot-fhwa-stol/cdasim": "",
    "usdot-fhwa-stol/cooperative-perception-core": "",
    "usdot-fhwa-stol/devops": "DEV",
    "usdot-fhwa-stol/documentation": "DEV",
    "usdot-fhwa-stol/dwm1001_ros2": "",
    "usdot-fhwa-stol/github_metrics": "DEV",
    "usdot-fhwa-stol/novatel_gps_driver": "",
    "usdot-fhwa-stol/opendrive2lanelet": "",
    "usdot-fhwa-stol/ros1_bridge": "",
    "usdot-fhwa-stol/rosbridge_suite": "",
    "usdot-fhwa-stol/snmp-client": "VH",
    "usdot-fhwa-stol/tim-bc": "",
    "usdot-fhwa-stol/voices-cda-use-case-scenario-database": "",
    "usdot-fhwa-stol/voices-common-interface": "",
    "usdot-fhwa-stol/voices-poc": "",
}

# GitHub repos to create new issues for previously unlinked Jira keys
# Duplicate Jira keys are NOT allowed in this list
github_repo_jira_project_parents = {
    "CAR": "usdot-fhwa-stol/carma-platform",
    "CRMCLD": "usdot-fhwa-stol/carma-cloud",
    "DEV": "usdot-fhwa-stol/devops",
    "VH": "usdot-fhwa-OPS/V2X-Hub",
    "WFD": "usdot-fhwa-stol/cda-telematics",
}

def reject_pull_request(github_pull_request):
    comment = "This PR is being rejected because it does not reference a Jira Key or GitHub Issue.\n\nPlease reference one in the appropriate section of the PR body and re-submit."
    github_pull_request.create_issue_comment(comment)
    github_pull_request.edit(state="closed")

def comment_on_github_pr(github_pull_request, github_issue_number):
    comment = "Closes #" + str(github_issue_number)
    github_pull_request.create_issue_comment(comment)

def get_pr_jira_key(github_pull_request):
    jira_key = ""

    # Remove <!-- comments --> from PR body
    try:
        pr_body = re.sub('<!--.*-->', '', github_pull_request.body)
    except:
        pr_body = ""
        pass

    result = []
    if pr_body:
        # Get text in Related Issue section
        result = re.findall('## Related Jira Key(.*)## Motivation and Context', pr_body, re.DOTALL)

    if result:
        # Single string list to multi-string list
        jira_keys = "\n".join(result).split("\n")
    else:
        jira_keys = []

    try:
        # Remove \r from list entries
        jira_keys = [s.replace('\r', '') for s in jira_keys]
    except:
        jira_keys = []

    # Remove empty list entries
    jira_keys = list(filter(None, jira_keys))

    if jira_keys:
        jira_key = jira_keys[0]

        logging.info("Found keys: " + str(jira_keys))
        #FIXME: support multiple keys instead of discarding them
        logging.info("Discarding any additional keys, ONLY using first key: " + jira_key)
    else:
        logging.info("No keys found")

    return jira_key

def get_issue_number_from_github_url(github_repo, github_issue_url):
    github_issue_number = None

    for github_issue in github_repo.get_issues():
        if github_issue.html_url == github_issue_url:
            return github_issue.number

    return github_issue_number

def close_jira_issue(jira_issue):
    if jira_issue.fields.resolution.name == "Done":
        logging.info("Jira issue is already closed, doing nothing")
        return
    else:
        logging.info("Closing Jira issue")
        jira_issue.update(fields={"resolution": {"name": "Done"}})

def create_github_issue(github_repo, jira_issue):
    github_issue_title = jira_issue.fields.summary
    github_issue_body = jira_issue.fields.description
    github_issue_body += "\n\n" + "### Jira Issue" + "\n" + jira_issue.permalink()
    github_issue = github_repo.create_issue(title=github_issue_title, body=github_issue_body)
    return github_issue

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-pr-number", required=True, type=int)
    parser.add_argument("--github-repo", required=True)
    parser.add_argument("--github-token", required=True)
    parser.add_argument("--jira-email", required=True)
    parser.add_argument("--jira-server", required=True)
    parser.add_argument("--jira-token", required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    # Get Jira project key from GitHub repo
    if args.github_repo in github_repo_jira_project_children:
        # Match GitHub repo to Jira project key
        jira_board_key = github_repo_jira_project_children[args.github_repo]
    else:
        logging.error("Unknown GitHub repo, add to github_repo_jira_project_children in this script then try again")
        sys.exit(1)

    # Log in to GitHub
    try:
        github = Github(args.github_token)
    except Exception as e:
        logging.error(e)
        sys.exit(1)

    # Get GitHub repo from GitHub repo name
    github_repo = github.get_repo(args.github_repo)

    # Get GitHub pull request from PR number
    github_pull_request = github_repo.get_pull(args.github_pr_number)

    # Log in to Jira
    jira = get_jira(args.jira_email, args.jira_server, args.jira_token)

    # Get Jira issue key from PR body
    pr_jira_key = get_pr_jira_key(github_pull_request)

    if not pr_jira_key:
        # Reject opened PR if no Jira key or GitHub issue found
        if github_pull_request.state == "open":
            pr_issues = get_issues_from_pr(github_repo, args.github_pr_number)
            if not pr_issues:
                logging.info("No GitHub issue found in PR body")
                reject_pull_request(github_pull_request)
                sys.exit(1)
        # Do nothing when PR is closed and no Jira issue key found
        elif github_pull_request.state == "closed":
            logging.info("PR is closed, doing nothing")
            sys.exit(0)

    # Get Jira issue from Jira issue key
    jira_issue = jira.issue(pr_jira_key)

    # Close Jira issue when PR is closed and Jira issue key found
    if pr_jira_key and github_pull_request.state == "closed":
        close_jira_issue(jira_issue)
        sys.exit(0)

    # Get Jira project for Jira issue
    jira_project = jira.project(jira_issue.fields.project)

    # Find parent GitHub repo for Jira project where new GitHub issues could potentially be created
    for parent_jira_project in github_repo_jira_project_parents:
        if parent_jira_project == jira_project.key:
            parent_github_repo = github.get_repo(github_repo_jira_project_parents[parent_jira_project])
            logging.info("Found parent GitHub repo " + parent_github_repo.full_name + " for Jira project " + jira_project.key)
            break

    # Find existing GitHub issue for Jira issue
    github_issue_url = ""
    github_issue_url_startswith = "https://github.com/" + args.github_repo + "/issues/"
    jira_issue_remote_links = jira.remote_links(jira_issue)
    if jira_issue_remote_links:
        for jira_issue_remote_link in jira_issue_remote_links:
            if jira_issue_remote_link.raw["object"]["url"].startswith(github_issue_url_startswith):
                logging.info("Found existing GitHub issue for Jira issue " + jira_issue_remote_link.raw["object"]["url"])
                github_issue_url = jira_issue_remote_link.raw["object"]["url"]
                break

    # Comment on GitHub PR with Jira issue's GitHub issue
    if github_issue_url:
        logging.info("GitHub issue already exists for Jira issue " + github_issue_url)

        # Determine repo(s) to search for existing GitHub issue
        sibling_github_repos = set()
        sibling_github_repos.add(args.github_repo)
        for sibling_repo in github_repo_jira_project_children:
            if github_repo_jira_project_children[sibling_repo] == jira_project.key:
                sibling_github_repos.add(sibling_repo)
        logging.info("Found sibling GitHub repos " + str(sibling_github_repos) + " for Jira project " + jira_project.key)

        # Search repo(s) for existing GitHub issue
        for potential_repo in sibling_github_repos:
            potential_github_repo = github.get_repo(potential_repo)
            github_issue_number = get_issue_number_from_github_url(potential_github_repo, github_issue_url)

            # Comment on GitHub PR with Jira issue's GitHub issue
            if github_issue_number:
                logging.info("Found GitHub issue " + str(github_issue_number) + " for Jira issue " + github_issue_url)

                github_issue = potential_github_repo.get_issue(github_issue_number)
                comment_on_github_pr(github_pull_request, github_issue.number)
                break
            
    # Create GitHub issue for Jira issue
    else:
        logging.info("Creating GitHub issue at " + parent_github_repo.html_url + " for Jira issue " + jira_issue.permalink())

        # Create GitHub issue
        github_issue = create_github_issue(parent_github_repo, jira_issue)
        logging.info("Created " + github_issue.html_url)

        # Comment magic words on GitHub PR to associate it with the new GitHub issue
        comment_on_github_pr(github_pull_request, github_issue.number)
