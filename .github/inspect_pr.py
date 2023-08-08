import os
import requests

GITHUB_API_URL = "https://api.github.com"
GITHUB_ACCESS_TOKEN = os.environ.get("GITHUB_ACCESS_TOKEN")  # Set your GitHub access token as an environment variable

def check_issue_reference(repo_full_name, pr_number):
    url = f"{GITHUB_API_URL}/repos/{repo_full_name}/pulls/{pr_number}/commits"
    headers = {"Authorization": f"token {GITHUB_ACCESS_TOKEN}"}
    response = requests.get(url, headers=headers)
    commits = response.json()

    for commit in commits:
        if "message" in commit["commit"] and "issue #" in commit["commit"]["message"].lower():
            return True

    return False

def add_comment_to_pr(repo_full_name, pr_number):
    url = f"{GITHUB_API_URL}/repos/{repo_full_name}/issues/{pr_number}/comments"
    headers = {"Authorization": f"token {GITHUB_ACCESS_TOKEN}"}
    data = {
        "body": "This pull request does not reference a GitHub issue. Please link to an issue in the PR description."
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 201:
        print("Comment added successfully!")
    else:
        print(f"Failed to add comment. Status code: {response.status_code}")

if __name__ == "__main__":
    repo_full_name = os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("PR_NUMBER")

    has_issue_reference = check_issue_reference(repo_full_name, pr_number)

    if not has_issue_reference:
        add_comment_to_pr(repo_full_name, pr_number)
