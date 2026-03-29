#!/usr/bin/env python3
"""Manual end-to-end runner for the Weekly Jira To Confluence workflow."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import error, parse, request
from xml.sax.saxutils import escape


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output" / "weekly_jira_to_confluence"
AUTOMATION_ENV_PATH = PROJECT_ROOT / ".automation.env"

MIGGBO_BASE_URL = os.environ.get("MIGGBO_BASE_URL", "https://miggbo.atlassian.net")
SEDONA_BASE_URL = os.environ.get("SEDONA_BASE_URL", "https://sedona.atlassian.net")
CONFLUENCE_BASE_URL = os.environ.get("CONFLUENCE_BASE_URL", "https://miggbo.atlassian.net")
CONFLUENCE_PAGE_ID = os.environ.get("CONFLUENCE_PAGE_ID", "1951531028")

MIGGBO_KEYS = ["DCC3-54", "DCC3-55", "DCC3-56", "DCC3-57", "DCC3-58", "DCC3-59"]
SEDONA_KEYS = ["TORT-16840", "TORT-16841", "TORT-16842", "TORT-16843", "TORT-16844", "TORT-16846"]

TABLE_PATTERN = re.compile(r"<table\b.*?</table>", re.DOTALL | re.IGNORECASE)


def env_first(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def env_required(*names: str) -> str:
    value = env_first(*names)
    if not value:
        raise SystemExit(f"Missing required environment variable. Tried: {', '.join(names)}")
    return value


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


def append_run_log(message: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = OUTPUT_DIR / "automation-run.log"
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")
    return log_path


@dataclass
class AtlassianAuth:
    email: str
    api_token: str

    @property
    def auth_header(self) -> str:
        raw = f"{self.email}:{self.api_token}".encode("utf-8")
        return base64.b64encode(raw).decode("ascii")


class JsonClient:
    def __init__(self, base_url: str, auth: AtlassianAuth):
        self.base_url = base_url.rstrip("/")
        self.auth = auth

    def request_json(
        self,
        path: str,
        *,
        params: dict[str, object] | None = None,
        method: str = "GET",
        body: dict[str, object] | None = None,
    ) -> dict:
        url = f"{self.base_url}{path}"
        if params:
            query = parse.urlencode(params, doseq=True)
            url = f"{url}?{query}"
        data = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Basic {self.auth.auth_header}",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(url, data=data, method=method, headers=headers)
        try:
            with request.urlopen(req) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload) if payload else {}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SystemExit(f"API request failed ({exc.code}) for {url}: {detail}") from exc
        except error.URLError as exc:
            raise SystemExit(f"Unable to reach {self.base_url}: {exc}") from exc


class JiraClient(JsonClient):
    def get_issue(self, key: str) -> dict:
        return self.request_json(
            f"/rest/api/3/issue/{key}",
            params={"fields": "summary,description,assignee,duedate,status"},
        )


class ConfluenceClient(JsonClient):
    def get_page(self, page_id: str) -> dict:
        return self.request_json(
            f"/wiki/api/v2/pages/{page_id}",
            params={"body-format": "storage", "include-version": "true"},
        )

    def update_page(self, page_id: str, payload: dict[str, object]) -> dict:
        return self.request_json(f"/wiki/api/v2/pages/{page_id}", method="PUT", body=payload)


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


def issue_row(issue: dict, base_url: str) -> list[str]:
    fields = issue.get("fields") or {}
    key = normalize_cell(str(issue.get("key") or ""))
    summary = normalize_cell(str(fields.get("summary") or ""))
    description = normalize_cell(text_from_adf(fields.get("description")))
    assignee = normalize_cell((fields.get("assignee") or {}).get("displayName") or "Unassigned")
    due_date = normalize_cell(str(fields.get("duedate") or ""))
    status = normalize_cell((fields.get("status") or {}).get("name") or "")
    return [key, f"{base_url}/browse/{key}", summary, description, assignee, due_date, status]


def build_storage_table(rows: list[list[str]]) -> str:
    header_cells = [
        "<th><p>Jira Key</p></th>",
        "<th><p>Summary</p></th>",
        "<th><p>Description</p></th>",
        "<th><p>Assignee</p></th>",
        "<th><p>Due Date</p></th>",
        "<th><p>Status</p></th>",
    ]
    body_rows: list[str] = []
    for key, url, summary, description, assignee, due_date, status in rows:
        body_rows.append(
            "".join(
                [
                    "<tr>",
                    '<td><p><a href="', escape(url), '">', escape(key), "</a></p></td>",
                    "<td><p>", escape(summary), "</p></td>",
                    "<td><p>", escape(description), "</p></td>",
                    "<td><p>", escape(assignee), "</p></td>",
                    "<td><p>", escape(due_date), "</p></td>",
                    "<td><p>", escape(status), "</p></td>",
                    "</tr>",
                ]
            )
        )
    return (
        '<table data-layout="default" ac:local-id="codex-jira-data-table"><tbody>'
        + "<tr>"
        + "".join(header_cells)
        + "</tr>"
        + "".join(body_rows)
        + "</tbody></table>"
    )


def storage_value(page: dict) -> str:
    return str(((page.get("body") or {}).get("storage") or {}).get("value") or "")


def replace_table(body: str, replacement: str, table_index: int) -> tuple[str, int]:
    matches = list(TABLE_PATTERN.finditer(body))
    if not matches:
        raise SystemExit("No <table> element found in the Confluence page body.")
    if table_index < 0 or table_index >= len(matches):
        raise SystemExit(f"Requested table index {table_index} is out of range. Found {len(matches)} table(s).")
    match = matches[table_index]
    new_body = body[: match.start()] + replacement + body[match.end() :]
    return new_body, len(matches)


def maybe_append_footer_stamp(body: str, enabled: bool) -> str:
    if not enabled:
        return body
    stamp = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    footer = f"<p><sub>Last automated refresh test: {escape(stamp)}</sub></p>"
    return body + footer


def write_preview_files(page_body: str, new_body: str) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    current_path = OUTPUT_DIR / f"current-page-body-{stamp}.html"
    updated_path = OUTPUT_DIR / f"updated-page-body-{stamp}.html"
    current_path.write_text(page_body, encoding="utf-8")
    updated_path.write_text(new_body, encoding="utf-8")
    return current_path, updated_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or apply the Weekly Jira To Confluence update.")
    parser.add_argument("--apply", action="store_true", help="Actually update the Confluence page.")
    parser.add_argument("--table-index", type=int, default=0, help="Zero-based table index to replace. Default: 0")
    parser.add_argument("--page-id", default=CONFLUENCE_PAGE_ID, help="Confluence page id")
    parser.add_argument(
        "--force-version",
        action="store_true",
        help="Append a small timestamp footer so Confluence definitely gets changed and creates a new page version.",
    )
    args = parser.parse_args()

    load_dotenv(AUTOMATION_ENV_PATH)
    log_path = append_run_log(
        "START preview={} apply={} force_version={} jira_email_present={} jira_token_present={}".format(
            "no" if args.apply else "yes",
            "yes" if args.apply else "no",
            "yes" if args.force_version else "no",
            "yes" if bool(env_first("JIRA_EMAIL", "CONFLUENCE_EMAIL")) else "no",
            "yes" if bool(env_first("JIRA_API_TOKEN", "CONFLUENCE_API_TOKEN")) else "no",
        )
    )

    auth = AtlassianAuth(
        email=env_required("JIRA_EMAIL", "CONFLUENCE_EMAIL"),
        api_token=env_required("JIRA_API_TOKEN", "CONFLUENCE_API_TOKEN"),
    )

    miggbo = JiraClient(MIGGBO_BASE_URL, auth)
    sedona = JiraClient(SEDONA_BASE_URL, auth)
    confluence = ConfluenceClient(CONFLUENCE_BASE_URL, auth)

    rows: list[list[str]] = []
    for key in MIGGBO_KEYS:
        rows.append(issue_row(miggbo.get_issue(key), MIGGBO_BASE_URL))
    for key in SEDONA_KEYS:
        rows.append(issue_row(sedona.get_issue(key), SEDONA_BASE_URL))

    page = confluence.get_page(args.page_id)
    page_body = storage_value(page)
    replacement = build_storage_table(rows)
    new_body, table_count = replace_table(page_body, replacement, args.table_index)
    new_body = maybe_append_footer_stamp(new_body, args.force_version)
    current_path, updated_path = write_preview_files(page_body, new_body)
    current_hash = hashlib.sha256(page_body.encode("utf-8")).hexdigest()
    updated_hash = hashlib.sha256(new_body.encode("utf-8")).hexdigest()
    body_changed = page_body != new_body

    print(f"Page Title: {page.get('title', '')}")
    print(f"Page ID: {args.page_id}")
    print(f"Current Version: {(page.get('version') or {}).get('number', '')}")
    print(f"Tables Found: {table_count}")
    print(f"Replacing Table Index: {args.table_index}")
    print(f"Body Changed: {'yes' if body_changed else 'no'}")
    print(f"Current Body SHA256: {current_hash}")
    print(f"Updated Body SHA256: {updated_hash}")
    print(f"Current Body Snapshot: {current_path}")
    print(f"Updated Body Preview: {updated_path}")
    print(f"Run Log: {log_path}")

    if not args.apply:
        append_run_log(
            f"PREVIEW_ONLY page_id={args.page_id} body_changed={'yes' if body_changed else 'no'} table_index={args.table_index}"
        )
        print("")
        print("Preview only. No Confluence update performed.")
        return 0

    version = page.get("version") or {}
    payload: dict[str, object] = {
        "id": str(page.get("id") or args.page_id),
        "status": str(page.get("status") or "current"),
        "title": str(page.get("title") or ""),
        "body": {
            "representation": "storage",
            "value": new_body,
        },
        "version": {
            "number": int(version.get("number") or 0) + 1,
            "message": "Update Jira Data table from miggbo and sedona issue keys",
        },
    }
    if page.get("spaceId") is not None:
        payload["spaceId"] = str(page.get("spaceId"))
    if page.get("parentId") is not None:
        payload["parentId"] = str(page.get("parentId"))

    updated = confluence.update_page(args.page_id, payload)
    append_run_log(
        "APPLY_OK page_id={} old_version={} new_version={} body_changed={} force_version={}".format(
            args.page_id,
            (page.get("version") or {}).get("number", ""),
            (updated.get("version") or {}).get("number", ""),
            "yes" if body_changed else "no",
            "yes" if args.force_version else "no",
        )
    )
    print("")
    print("Confluence update completed.")
    print(f"New Version: {(updated.get('version') or {}).get('number', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
