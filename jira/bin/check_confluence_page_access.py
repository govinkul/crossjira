#!/usr/bin/env python3
"""Safely test Confluence page read access and optional write permission."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from urllib import error, parse, request


DEFAULT_BASE_URL = "https://miggbo.atlassian.net"
DEFAULT_PAGE_ID = "1951531028"


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


class ConfluenceClient:
    def __init__(self, base_url: str, email: str, api_token: str):
        raw = f"{email}:{api_token}".encode("utf-8")
        self.base_url = base_url.rstrip("/")
        self.auth_header = base64.b64encode(raw).decode("ascii")

    def _request_json(
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
            "Authorization": f"Basic {self.auth_header}",
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
            raise SystemExit(f"Confluence API request failed ({exc.code}) for {path}: {detail}") from exc
        except error.URLError as exc:
            raise SystemExit(f"Unable to reach Confluence at {self.base_url}: {exc}") from exc

    def _request_no_content(self, path: str, *, method: str = "DELETE") -> None:
        url = f"{self.base_url}{path}"
        req = request.Request(
            url,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {self.auth_header}",
            },
        )
        try:
            with request.urlopen(req):
                return
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SystemExit(f"Confluence API request failed ({exc.code}) for {path}: {detail}") from exc
        except error.URLError as exc:
            raise SystemExit(f"Unable to reach Confluence at {self.base_url}: {exc}") from exc

    def get_page(self, page_id: str) -> dict:
        return self._request_json(
            f"/wiki/api/v2/pages/{page_id}",
            params={"body-format": "storage", "include-version": "true"},
        )

    def create_page_property(self, page_id: str, key: str, value: dict[str, object]) -> dict:
        return self._request_json(
            f"/wiki/api/v2/pages/{page_id}/properties",
            method="POST",
            body={"key": key, "value": value},
        )

    def delete_page_property(self, page_id: str, property_id: str) -> None:
        self._request_no_content(f"/wiki/api/v2/pages/{page_id}/properties/{property_id}")


def storage_value(page: dict) -> str:
    body = page.get("body") or {}
    storage = body.get("storage") or {}
    return str(storage.get("value") or "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Confluence page access and optional write permission.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Confluence base URL")
    parser.add_argument("--page-id", default=DEFAULT_PAGE_ID, help="Confluence page id")
    parser.add_argument(
        "--check-write",
        action="store_true",
        help="Create and then delete a temporary hidden page property to verify write permission.",
    )
    args = parser.parse_args()

    email = env_required("CONFLUENCE_EMAIL", "JIRA_EMAIL")
    api_token = env_required("CONFLUENCE_API_TOKEN", "JIRA_API_TOKEN")
    client = ConfluenceClient(args.base_url, email, api_token)

    page = client.get_page(args.page_id)
    version = page.get("version") or {}
    content = storage_value(page)

    print(f"Base URL: {args.base_url}")
    print(f"Page ID: {args.page_id}")
    print(f"Title: {page.get('title', '')}")
    print(f"Status: {page.get('status', '')}")
    print(f"Version: {version.get('number', '')}")
    print(f"Body Length: {len(content)}")
    print(f"Body Preview: {content[:200].replace(chr(10), ' ')}")

    if args.check_write:
        key = f"codex-write-check-{int(time.time())}"
        created = client.create_page_property(
            args.page_id,
            key,
            {"createdBy": "codex", "timestamp": int(time.time())},
        )
        property_id = str(created.get("id") or "")
        if not property_id:
            raise SystemExit("Write check failed: Confluence did not return a property id.")
        client.delete_page_property(args.page_id, property_id)
        print("")
        print("Write Check: OK")
        print(f"Temporary Property Key: {key}")
        print("Cleanup: OK")

    return 0


if __name__ == "__main__":
    sys.exit(main())
