# Jira To Confluence Automation

This repository contains a Jira-to-Confluence automation workflow.

## What is included

- `jira/bin/run_weekly_jira_to_confluence.py`
  - end-to-end runner that reads Jira issues from two Jira sites and updates a Confluence page
- `jira/bin/check_jira_issue_keys.py`
  - read-only Jira access checker for exact issue keys
- `jira/bin/check_confluence_page_access.py`
  - Confluence read/write capability checker
- `jira/bin/weekly_jira_to_confluence_dry_run.py`
  - local dry-run table renderer
- `.github/workflows/weekly-jira-to-confluence.yml`
  - GitHub Actions workflow that runs on a daily schedule and can be triggered manually

## Local secrets

For local runs, create:

- `.automation.env`

with:

```bash
JIRA_EMAIL=your-email@cisco.com
JIRA_API_TOKEN=your-atlassian-api-token
```

Do not commit `.automation.env`.

## GitHub Actions secrets

Set these repository secrets in GitHub:

- `JIRA_EMAIL`
- `JIRA_API_TOKEN`

## Manual local run

Preview:

```bash
python3 jira/bin/run_weekly_jira_to_confluence.py
```

Apply:

```bash
python3 jira/bin/run_weekly_jira_to_confluence.py --apply --force-version
```

## Scheduled run

The GitHub Actions workflow is scheduled for `23:00 UTC`, which is `4:00 PM PDT`.
