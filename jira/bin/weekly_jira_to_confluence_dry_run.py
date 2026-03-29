#!/usr/bin/env python3
"""Dry-run renderer for the Weekly Jira To Confluence automation."""

from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass
from urllib import error, request


MIGGBO_BASE_URL = "https://miggbo.atlassian.net"
SEDONA_BASE_URL = "https://sedona.atlassian.net"

MIGGBO_KEYS = ["DCC3-54", "DCC3-55", "DCC3-56", "DCC3-57", "DCC3-58", "DCC3-59"]
SEDONA_KEYS = ["TORT-16840", "TORT-16841", "TORT-16842", "TORT-16843", "TORT-16844", "TORT-16846"]


def env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


@dataclass
class JiraAuth:
    email: str
    api_token: str

    @property
    def auth_header(self) -> str:
        raw = f"{self.email}:{self.api_token}".encode("utf-8")
        return base64.b64encode(raw).decode("ascii")


class JiraClient:
    def __init__(self, base_url: str, auth: JiraAuth):
        self.base_url = base_url.rstrip("/")
        self.auth = auth

    def get_issue(self, key: str) -> dict:
        url = (
            f"{self.base_url}/rest/api/3/issue/{key}"
            "?fields=summary,description,assignee,duedate,status"
        )
        req = request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {self.auth.auth_header}",
            },
        )
        try:
            with request.urlopen(req) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SystemExit(
                f"Jira API request failed ({exc.code}) for {self.base_url} {key}: {detail}"
            ) from exc
        except error.URLError as exc:
            raise SystemExit(f"Unable to reach Jira at {self.base_url}: {exc}") from exc


def text_from_adf(node: object) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(text_from_adf(child) for child in node)
    if not isinstance(node, dict):
        return ""
    text = node.get("text")
    if isinstance(text, str):
        return text
    content = node.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for child in content:
            child_text = text_from_adf(child)
            if child_text:
                parts.append(child_text)
        separator = "\n" if node.get("type") in {"paragraph", "bulletList", "orderedList", "listItem"} else ""
        return separator.join(parts) if separator else "".join(parts)
    return ""


def normalize_cell(value: str) -> str:
    return " ".join(value.split()).strip()


def issue_row(issue: dict) -> list[str]:
    fields = issue.get("fields") or {}
    summary = normalize_cell(str(fields.get("summary") or ""))
    description = normalize_cell(text_from_adf(fields.get("description")))
    assignee = normalize_cell((fields.get("assignee") or {}).get("displayName") or "Unassigned")
    due_date = normalize_cell(str(fields.get("duedate") or ""))
    status = normalize_cell((fields.get("status") or {}).get("name") or "")
    key = normalize_cell(str(issue.get("key") or ""))
    return [key, summary, description, assignee, due_date, status]


def markdown_table(rows: list[list[str]]) -> str:
    headers = ["Jira Key", "Summary", "Description", "Assignee", "Due Date", "Status"]
    all_rows = [headers, ["---"] * len(headers), *rows]
    return "\n".join("| " + " | ".join(cell or "" for cell in row) + " |" for row in all_rows)


def main() -> int:
    auth = JiraAuth(
        email=env_required("JIRA_EMAIL"),
        api_token=env_required("JIRA_API_TOKEN"),
    )

    miggbo = JiraClient(MIGGBO_BASE_URL, auth)
    sedona = JiraClient(SEDONA_BASE_URL, auth)

    rows: list[list[str]] = []
    for key in MIGGBO_KEYS:
        rows.append(issue_row(miggbo.get_issue(key)))
    for key in SEDONA_KEYS:
        rows.append(issue_row(sedona.get_issue(key)))

    print("Dry run only. No Confluence update performed.")
    print("")
    print(markdown_table(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
