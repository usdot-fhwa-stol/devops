#!/usr/bin/env python3

from github import Github
from jira import JIRA
from requests.auth import HTTPBasicAuth
import argparse
import logging
import json
import requests


def get_jira(jira_email, jira_server, jira_token):
    try:
        jira = JIRA(
            basic_auth=(jira_email, jira_token),
            server=jira_server,
        )
    except Exception as e:
        logging.error(e)
        exit()

    return jira


def get_github(github_token):
    try:
        github = Github(github_token)
    except Exception as e:
        logging.error(e)
        exit()

    return github


def get_jira_board_api_url(jira, jira_board_name):

    boards = jira.boards()

    # Get the board id
    board_url = ""
    for board in boards:
        if board.name == jira_board_name:
            board_url = board.self

    if not board_url:
        logging.error("Could not determine " + jira_board_name + " API URL")
        exit()

    return board_url


def get_jira_json(jira_email, jira_token, url):
    auth = HTTPBasicAuth(jira_email, jira_token)

    headers = {"Accept": "application/json"}

    try:
        r = requests.request("GET", url, headers=headers, auth=auth)
    except Exception as e:
        logging.error("Could not request " + url, e)

    jira_json = json.loads(r.text)

    return jira_json


def get_jira_issue_remote_links(jira_email, jira_token, jira_issue_key, jira_server):

    # <BASE_URL>/rest/api/2/issue/<ISSUE_KEY>/remotelink
    url = jira_server + "/rest/api/2/issue/" + jira_issue_key + "/remotelink"

    jira_json = get_jira_json(jira_email, jira_token, url)

    urls = []
    for dict in jira_json:
        urls = urls + [dict["object"]["url"]]

    return urls


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-repo", required=True)
    parser.add_argument("--github-token", required=True)
    parser.add_argument("--jira-board", required=True)
    parser.add_argument("--jira-email", required=True)
    parser.add_argument("--jira-server", required=True)
    parser.add_argument("--jira-token", required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--github-issue-number", type=int)
    group.add_argument("--pull-request-number", type=int)
    args = parser.parse_args()

    jira = get_jira(args.jira_email, args.jira_server, args.jira_token)

    github = get_github(args.github_token)

    github_repo = github.get_repo(args.github_repo)

    # Default jira_component
    jira_component = "Infrastructure"

    # Create Jira issue for dependabot GitHub Pull Request
    if args.pull_request_number:
        pull = github_repo.get_pull(args.pull_request_number)

        if pull.user.login == "dependabot[bot]":
            github_url = pull.html_url
            github_title = pull.title
        else:
            logging.info("Not a dependabot PR, doing nothing")
            exit()

    # Create Jira issue for new GitHub issue
    if args.github_issue_number:
        github_issue = github_repo.get_issue(number=args.github_issue_number)
        github_title = github_issue.title
        github_url = github_issue.html_url
        # Determine the Component from GitHub template required field
        github_issue_component_header = "\n".join(github_issue.body.splitlines()[0:1])
        if github_issue_component_header == "### Component":
            github_issue_component = "\n".join(github_issue.body.splitlines()[2:3])
            if github_issue_component != "Other":
                jira_component = github_issue_component
            else:
                logging.warning(
                    "GitHub Issue Component is Other, defaulting to Infrastructure"
                )
        else:
            logging.warning(
                "Failed to determine Component of GitHub issue, template related problem?"
            )

    jira_board_api_url = get_jira_board_api_url(jira, args.jira_board)

    jira_board_json = get_jira_json(
        args.jira_email, args.jira_token, jira_board_api_url
    )

    jira_board_key = jira_board_json["location"]["projectKey"]

    jira_board_issues = jira.search_issues("project=" + jira_board_key, maxResults=9999)

    jira_remote_links = []
    for jira_issue in jira_board_issues:
        jira_remote_links = jira_remote_links + get_jira_issue_remote_links(
            args.jira_email, args.jira_token, jira_issue.key, args.jira_server
        )

    if github_url in jira_remote_links:
        logging.info("GitHub URL already associated with a Jira issue, doing nothing")
        exit()

    # FIXME: also set Status
    jira_issue_json = {
        "project": {"key": jira_board_key},
        "summary": github_title,
        "description": "See linked GitHub URL",
        "issuetype": {"name": "Task"},
        "components": [{"name": jira_component}],
    }

    try:
        jira_issue = jira.create_issue(fields=jira_issue_json)
        logging.info("Created Jira issue " + jira_issue.key)
    except Exception as e:
        logging.error(e)
        exit()

    jira_link_json = {
        "url": github_url,
        "title": github_title,
    }

    try:
        jira.add_simple_link(jira_issue, jira_link_json)
        logging.info(jira_issue.key + ": added " + github_url)
    except Exception as e:
        logging.error(e)
        exit()
