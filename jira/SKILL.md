---
name: jira
description: Work with Jira issues for search, triage, creation, updates, comments, and workflow transitions. Use when Codex needs to interact with Jira or Atlassian issue data to find tickets, summarize status, draft or create issues, update fields, add comments, move issues through workflow states, or prepare concise project and backlog updates.
---

# Jira

## Overview

Use this skill for day-to-day Jira issue workflows. Prefer precise issue keys, project keys, assignee names, and field names over guesses, and keep the user informed about exactly which issues were inspected or changed.

This skill also includes a helper for the recurring follow-up flow:

- find all issues in a project where `statusCategory != Done`
- filter to a target label such as `TestAutomation`
- group those issues by distinct assignee
- draft or send one email per assignee with their open items

## Quick Start

Start by confirming what Jira access is actually available in the current environment.

- Check for a Jira MCP tool, connector, CLI, or repository-specific helper before assuming one exists.
- Check whether authentication is already configured through environment variables, local config, or the active tool session.
- Never paste API tokens into code, committed files, shell history, or user-facing output.
- Prefer environment-based auth such as `JIRA_API_TOKEN`, `ATLASSIAN_API_TOKEN`, `JIRA_BASE_URL`, and `JIRA_EMAIL` when a tool requires them.

For the built-in follow-up helper in this skill, use:

- `JIRA_BASE_URL`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `JIRA_PROJECT`
- optional `JIRA_LABEL` if you do not want the default `TestAutomation`

If email sending is required, also configure:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- optional `SMTP_SSL=true` for implicit TLS

If no Jira-capable tool is available, still help by drafting JQL, issue text, rollout notes, or structured updates for the user to paste into Jira manually.

## Core Workflow

### 1. Build Context

- Identify the goal first: lookup, search, create, update, comment, transition, or reporting.
- Gather the minimum missing identifiers before acting: project key, issue key, board name, sprint name, assignee, or status.
- When the request is ambiguous, search first and present the likely matches instead of guessing.

### 2. Inspect Before Changing

- Read the current issue summary, description, status, assignee, priority, labels, and recent comments before modifying it.
- Check required fields and available transitions before attempting updates.
- For bulk or multi-issue work, summarize the planned changes before executing them.

### 3. Execute Safely

- Prefer exact issue keys like `ABC-123` whenever available.
- Use explicit field names and explicit transition names.
- When creating issues, include a concise summary, clear description, expected behavior, actual behavior, impact, and reproduction details when relevant.
- When adding comments or status updates, keep them short, concrete, and teammate-friendly.

### 4. Report Back Clearly

- List the exact issue keys you inspected or changed.
- Summarize what changed: fields updated, comment added, transition performed, or issue created.
- Call out any blockers such as missing permissions, invalid field names, unavailable transitions, or ambiguous search matches.

## Common Tasks

### Search And Triage

- Use focused JQL when possible.
- Narrow results by project, issue type, assignee, status, label, sprint, or updated date.
- If the user asks for a summary, group results by status, owner, or priority and highlight the next obvious action.

Example requests:

- "Find my open bugs in project PAY and summarize next steps."
- "Show recently updated checkout incidents."
- "List blocked tickets for the mobile team."

### Email Assignees For Open Labeled Issues

Use the helper script at [jira/bin/testautomation_assignee_mailer.py](/Users/govinkul/Documents/New project/jira/bin/testautomation_assignee_mailer.py) when the workflow is:

- search one project for issues where `statusCategory != Done`
- filter by a label such as `TestAutomation`
- group the matches by assignee
- prepare or send one email per assignee

Default behavior is a dry run that prints the grouped report and email bodies. Use `--send` only after SMTP settings are configured.

Example:

```bash
export JIRA_BASE_URL="https://your-site.atlassian.net"
export JIRA_EMAIL="you@example.com"
export JIRA_API_TOKEN="..."
export JIRA_PROJECT="AUTOMGMT"
python3 jira/bin/testautomation_assignee_mailer.py
```

With SMTP configured:

```bash
python3 jira/bin/testautomation_assignee_mailer.py --send
```

Notes:

- Jira Cloud often omits assignee email addresses from standard issue payloads.
- The helper attempts `/rest/api/3/user/email` when needed, but that endpoint may require elevated Jira permissions.
- If Jira does not expose assignee emails, pass `--email-overrides path/to/assignee_emails.json` with a JSON object keyed by Jira account ID.

### Create Issues

When drafting or creating an issue, prefer this structure:

- Summary: one sentence, specific and searchable
- Description: context, problem, expected behavior, actual behavior
- Impact: who is affected and how severe it is
- Reproduction: numbered steps when applicable
- Attachments or links: PRs, logs, dashboards, docs

If important fields are unknown, say what is missing instead of fabricating details.

### Update Issues

Safe updates include:

- Rewriting a summary or description for clarity
- Setting or correcting labels, priority, assignee, or due date
- Adding implementation notes or QA notes
- Linking related issues or documenting rollout status

Preserve important existing context unless the user asked for a rewrite.

### Comment On Issues

Comments should usually:

- Start with the current state or decision
- Include the most important technical or project detail
- End with the next step, owner, or blocker

Avoid long narrative comments when a short operational update is enough.

### Transition Issues

- Read available transitions first because transition names differ across projects.
- Confirm the target state when similar transitions exist, such as `In Progress` vs `Doing`.
- Mention the final status explicitly in the response.

## Failure Handling

- Missing auth: explain what credential or tool is missing and switch to draft-only help if possible.
- Missing permission: report the denied action and suggest a manual fallback.
- Unknown transition: list available transitions if the tool exposes them.
- Ambiguous search results: present the candidates and ask for the issue key only if necessary.
- Required field errors: name the missing field and propose a sensible value if the user provided enough context.

## Output Style

- Keep updates concise and operational.
- Prefer bullets when summarizing several issues.
- Include JQL used when it helps the user repeat the query.
- Do not expose secrets, tokens, cookies, or raw auth headers in output.
