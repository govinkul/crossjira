#!/usr/bin/env python3
"""Read-only Jira checker for exact issue keys across one site."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from urllib import error, request


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUTOMATION_ENV_PATH = PROJECT_ROOT / ".automation.env"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith(("\"", "'")) and value.endswith(("\"", "'")) and len(value) >= 2:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str):
        auth = f"{email}:{api_token}".encode("utf-8")
        self.base_url = base_url.rstrip("/")
        self.auth_header = base64.b64encode(auth).decode("ascii")

    def get_issue(self, key: str) -> dict:
        url = f"{self.base_url}/rest/api/3/issue/{key}?fields=summary,description,assignee,duedate,status"
        req = request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {self.auth_header}",
            },
        )
        try:
            with request.urlopen(req) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SystemExit(f"Jira API request failed ({exc.code}) for {key}: {detail}") from exc
        except error.URLError as exc:
            raise SystemExit(f"Unable to reach Jira at {self.base_url}: {exc}") from exc


def summarize_description(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=True)[:120]


def main() -> int:
    parser = argparse.ArgumentParser(description="Read exact Jira issue keys from one Jira site.")
    parser.add_argument("--base-url", help="Jira base URL, for example https://example.atlassian.net")
    parser.add_argument("keys", nargs="+", help="One or more Jira issue keys to fetch")
    args = parser.parse_args()

    load_dotenv(AUTOMATION_ENV_PATH)

    base_url = (args.base_url or os.environ.get("JIRA_BASE_URL", "")).strip() or env_required("JIRA_BASE_URL")
    email = env_required("JIRA_EMAIL")
    api_token = env_required("JIRA_API_TOKEN")

    client = JiraClient(base_url, email, api_token)

    print(f"Base URL: {base_url}")
    for key in args.keys:
        issue = client.get_issue(key)
        fields = issue.get("fields") or {}
        assignee = (fields.get("assignee") or {}).get("displayName", "Unassigned")
        due_date = fields.get("duedate") or ""
        status = (fields.get("status") or {}).get("name", "")
        summary = fields.get("summary") or ""
        description = summarize_description(fields.get("description"))
        print("")
        print(f"Key: {issue.get('key', key)}")
        print(f"Summary: {summary}")
        print(f"Assignee: {assignee}")
        print(f"Due Date: {due_date}")
        print(f"Status: {status}")
        print(f"Description Preview: {description}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
