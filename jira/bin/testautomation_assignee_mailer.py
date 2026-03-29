#!/usr/bin/env python3
"""Summarize open TestAutomation Jira issues per assignee and optionally email them."""

from __future__ import annotations

import argparse
import base64
import json
import os
import smtplib
import ssl
import sys
from collections import defaultdict
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib import error, parse, request


DEFAULT_LABEL = "TestAutomation"


@dataclass
class JiraConfig:
    base_url: str
    email: str
    api_token: str
    project: str
    label: str


def env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def build_config(args: argparse.Namespace) -> JiraConfig:
    return JiraConfig(
        base_url=(args.base_url or os.environ.get("JIRA_BASE_URL", "")).rstrip("/"),
        email=args.user or os.environ.get("JIRA_EMAIL", ""),
        api_token=os.environ.get("JIRA_API_TOKEN", ""),
        project=args.project or os.environ.get("JIRA_PROJECT", ""),
        label=args.label or os.environ.get("JIRA_LABEL", DEFAULT_LABEL),
    )


class JiraClient:
    def __init__(self, config: JiraConfig):
        self.config = config
        auth = f"{config.email}:{config.api_token}".encode("utf-8")
        self.auth_header = base64.b64encode(auth).decode("ascii")

    def _request_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.config.base_url}{path}"
        if params:
            query = parse.urlencode(params, doseq=True)
            url = f"{url}?{query}"
        data = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Basic {self.auth_header}",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(
            url,
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with request.urlopen(req) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SystemExit(f"Jira API request failed ({exc.code}) for {path}: {detail}") from exc
        except error.URLError as exc:
            raise SystemExit(f"Unable to reach Jira at {self.config.base_url}: {exc}") from exc

    def search(self, jql: str) -> list[dict[str, Any]]:
        next_page_token: str | None = None
        issues: list[dict[str, Any]] = []
        fields = ["summary", "status", "assignee", "labels"]
        while True:
            body: dict[str, Any] = {
                "jql": jql,
                "maxResults": 100,
                "fields": fields,
            }
            if next_page_token:
                body["nextPageToken"] = next_page_token
            payload = self._request_json(
                "/rest/api/3/search/jql",
                method="POST",
                body=body,
            )
            batch = payload.get("issues", [])
            issues.extend(batch)
            next_page_token = payload.get("nextPageToken")
            if not next_page_token or not batch:
                return issues

    def lookup_email(self, account_id: str) -> str | None:
        payload = self._request_json("/rest/api/3/user/email", {"accountId": account_id})
        email_address = payload.get("email")
        if email_address:
            return str(email_address)
        return None


def build_jql(project: str, label: str) -> str:
    escaped_project = project.replace('"', '\\"')
    escaped_label = label.replace('"', '\\"')
    return (
        f'project = "{escaped_project}" '
        f'AND statusCategory != Done '
        f'AND labels = "{escaped_label}" '
        f"ORDER BY assignee, priority DESC, updated DESC"
    )


def load_email_overrides(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {str(key): str(value) for key, value in data.items()}


def group_issues_by_assignee(
    issues: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, str]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    profiles: dict[str, dict[str, str]] = {}
    for issue in issues:
        assignee = (issue.get("fields") or {}).get("assignee")
        if not assignee:
            grouped["unassigned"].append(issue)
            profiles.setdefault(
                "unassigned",
                {"displayName": "Unassigned", "accountId": "unassigned", "emailAddress": ""},
            )
            continue
        account_id = assignee.get("accountId") or assignee.get("displayName") or "unknown"
        grouped[account_id].append(issue)
        profiles.setdefault(
            account_id,
            {
                "displayName": assignee.get("displayName") or account_id,
                "accountId": assignee.get("accountId") or account_id,
                "emailAddress": assignee.get("emailAddress") or "",
            },
        )
    return grouped, profiles


def build_email_body(
    display_name: str,
    issues: list[dict[str, Any]],
    base_url: str,
    label: str,
) -> str:
    lines = [
        f"Hi {display_name},",
        "",
        f"Here is your current list of Jira issues labeled {label} that are not in Done:",
        "",
    ]
    for issue in issues:
        fields = issue.get("fields") or {}
        status = (fields.get("status") or {}).get("name", "Unknown")
        summary = fields.get("summary", "(no summary)")
        key = issue.get("key", "(unknown key)")
        lines.append(f"- {key} [{status}]: {summary}")
        lines.append(f"  {base_url}/browse/{key}")
    lines.extend(
        [
            "",
            "Please review these items and update them as needed.",
            "",
            "Thanks,",
        ]
    )
    return "\n".join(lines)


def render_report(
    grouped: dict[str, list[dict[str, Any]]],
    profiles: dict[str, dict[str, str]],
    base_url: str,
    label: str,
) -> str:
    sections = []
    for account_id, issues in sorted(grouped.items(), key=lambda item: profiles[item[0]]["displayName"].lower()):
        profile = profiles[account_id]
        sections.append(
            "\n".join(
                [
                    f"Assignee: {profile['displayName']}",
                    f"Account ID: {profile['accountId']}",
                    f"Issue Count: {len(issues)}",
                    build_email_body(profile["displayName"], issues, base_url, label),
                ]
            )
        )
    return "\n\n" + ("\n\n" + ("-" * 72) + "\n\n").join(sections) if sections else "No matching issues found."


def maybe_fill_emails(
    client: JiraClient,
    profiles: dict[str, dict[str, str]],
    overrides: dict[str, str],
) -> None:
    for account_id, profile in profiles.items():
        if account_id in overrides:
            profile["emailAddress"] = overrides[account_id]
            continue
        if profile.get("emailAddress") or account_id == "unassigned":
            continue
        lookup_id = profile.get("accountId", "")
        if not lookup_id or lookup_id == "unassigned":
            continue
        try:
            email_address = client.lookup_email(lookup_id)
        except SystemExit:
            email_address = None
        if email_address:
            profile["emailAddress"] = email_address


def smtp_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required SMTP environment variable: {name}")
    return value


def send_emails(
    grouped: dict[str, list[dict[str, Any]]],
    profiles: dict[str, dict[str, str]],
    config: JiraConfig,
    subject_prefix: str,
) -> list[str]:
    host = smtp_required("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = smtp_required("SMTP_USERNAME")
    password = smtp_required("SMTP_PASSWORD")
    from_addr = smtp_required("SMTP_FROM")
    use_ssl = os.environ.get("SMTP_SSL", "").lower() in {"1", "true", "yes"}
    sent_to: list[str] = []

    if use_ssl:
        server: smtplib.SMTP | smtplib.SMTP_SSL = smtplib.SMTP_SSL(host, port, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(host, port)
        server.starttls(context=ssl.create_default_context())

    with server:
        server.login(username, password)
        for account_id, issues in grouped.items():
            recipient = profiles[account_id].get("emailAddress", "").strip()
            if not recipient:
                continue
            message = EmailMessage()
            message["From"] = from_addr
            message["To"] = recipient
            message["Subject"] = f"{subject_prefix} {config.project} {config.label} open issues"
            message.set_content(
                build_email_body(
                    profiles[account_id]["displayName"],
                    issues,
                    config.base_url,
                    config.label,
                )
            )
            server.send_message(message)
            sent_to.append(recipient)

    return sent_to


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize Jira issues with statusCategory != Done and a target label, grouped by assignee."
    )
    parser.add_argument("--base-url", help="Jira base URL, for example https://example.atlassian.net")
    parser.add_argument("--user", help="Jira login email")
    parser.add_argument("--project", help="Jira project key")
    parser.add_argument("--label", default=DEFAULT_LABEL, help="Label to filter by")
    parser.add_argument(
        "--email-overrides",
        help="Path to JSON object mapping Jira account IDs to email addresses",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send emails using SMTP_* environment variables. Without this flag, the script prints a dry-run report.",
    )
    parser.add_argument(
        "--subject-prefix",
        default="[Jira Follow-up]",
        help="Email subject prefix when --send is used",
    )
    parser.add_argument(
        "--report-file",
        help="Optional path to write the rendered report",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = build_config(args)
    config.base_url = config.base_url or env_required("JIRA_BASE_URL")
    config.email = config.email or env_required("JIRA_EMAIL")
    config.api_token = config.api_token or env_required("JIRA_API_TOKEN")
    config.project = config.project or env_required("JIRA_PROJECT")

    client = JiraClient(config)
    jql = build_jql(config.project, config.label)
    issues = client.search(jql)
    grouped, profiles = group_issues_by_assignee(issues)
    maybe_fill_emails(client, profiles, load_email_overrides(args.email_overrides))

    report = f"JQL: {jql}\nTotal Issues: {len(issues)}\n" + render_report(
        grouped,
        profiles,
        config.base_url,
        config.label,
    )

    if args.report_file:
        Path(args.report_file).write_text(report + "\n", encoding="utf-8")

    if args.send:
        sent_to = send_emails(grouped, profiles, config, args.subject_prefix)
        print(report)
        print("")
        print(f"Emails sent: {len(sent_to)}")
        for recipient in sent_to:
            print(f"- {recipient}")
    else:
        print(report)

    missing_emails = [
        profile["displayName"]
        for profile in profiles.values()
        if profile["accountId"] != "unassigned" and not profile.get("emailAddress")
    ]
    if missing_emails:
        print("")
        print("Assignees without an email address:")
        for name in missing_emails:
            print(f"- {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
