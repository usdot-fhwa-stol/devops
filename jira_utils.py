#!/usr/bin/env python3

from jira import JIRA
from requests.auth import HTTPBasicAuth
import json
import logging
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


def get_jira_issue_remote_links(jira_email, jira_token, jira_issue_key, jira_server):

    url = jira_server + "/rest/api/2/issue/" + jira_issue_key + "/remotelink"

    jira_json = get_jira_json(jira_email, jira_token, url)

    urls = []
    for dict in jira_json:
        urls = urls + [dict["object"]["url"]]

    return urls


def get_jira_json(jira_email, jira_token, url):
    auth = HTTPBasicAuth(jira_email, jira_token)

    headers = {"Accept": "application/json"}

    try:
        r = requests.request("GET", url, headers=headers, auth=auth)
    except Exception as e:
        logging.error("Could not request " + url, e)

    jira_json = json.loads(r.text)

    return jira_json
