#!/usr/bin/env python3
from github import Github
import argparse
import logging
import pathlib
import re
import sys

def get_issues_from_pr(github_repo, pr_number):
    # ... (rest of the function remains unchanged)

def get_issue_titles(github_repo, issues):
    # ... (rest of the function remains unchanged)

def get_repo_list(github_org, github):
    # ... (rest of the function remains unchanged)

def get_repo(repo_name, github):
    # ... (rest of the function remains unchanged)

def get_release_notes(name, version, issue_titles_bugs, issue_titles_enhancements, issue_titles_other, commit_only, pull_requests_missing_issues):
    release_notes = f"""
## {name}

### {version}

"""

    if issue_titles_bugs:
        release_notes += f"""
#### Bugs & Anomalies

* {("\n* ".join(sorted(set(issue_titles_bugs))))}
"""

    if issue_titles_enhancements:
        release_notes += f"""
#### Enhancements

* {("\n* ".join(sorted(set(issue_titles_enhancements))))}
"""

    if issue_titles_other:
        release_notes += f"""
#### Issues Missing Labels

* {("\n* ".join(sorted(set(issue_titles_other))))}
"""

    if commit_only:
        release_notes += f"""
#### Commits Missing Issues

* {("\n* ".join(sorted(commit_only)))}
"""

    if pull_requests_missing_issues:
        release_notes += f"""
#### Pull Requests Missing Issues

* {("\n* ".join(sorted(pull_requests_missing_issues)))}
"""

    return release_notes

# ... (rest of the functions remains unchanged)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # ... (rest of the argument parsing remains unchanged)

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler()],
    )

    release_notes()
