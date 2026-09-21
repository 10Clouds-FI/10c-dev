#!/usr/bin/env python3
"""Interactive first-run setup: site + email + API token, validated, then stored.

    python3 setup.py                                      # asks for the site
    python3 setup.py --site https://acme.atlassian.net    # site given up front
    python3 setup.py --site acme                          # same, Atlassian Cloud slug

Run it once per Jira site. Each site becomes a named profile in one
credentials.json (chmod 600), so a second site is just another run. The first
site set up becomes the default used when nothing else names one.

The token is read with getpass and is never printed back.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from _auth import (
    creds_path,
    normalize_site,
    request,
    resolve_site,
    save_creds,
    task_flow_jira,
)

TOKEN_URL = "https://id.atlassian.com/manage-profile/security/api-tokens"


def _pick_site(explicit: str | None) -> str | None:
    """--site, else anything already configured, else ask."""
    site = normalize_site(explicit)
    if site:
        return site
    site = resolve_site(None, required=False)
    if site:
        answer = input(f"Jira site [{site}]: ").strip()
        return normalize_site(answer) or site
    hint = task_flow_jira().get("site")
    prompt = "Jira site URL (e.g. https://acme.atlassian.net): "
    if hint:
        prompt = f"Jira site URL [{hint}]: "
    answer = input(prompt).strip()
    return normalize_site(answer) or normalize_site(hint)


def main() -> int:
    p = argparse.ArgumentParser(description="Interactive Jira credential setup, per site.")
    p.add_argument(
        "--site",
        help="Jira base URL or host, e.g. https://acme.atlassian.net (asked for if omitted).",
    )
    args = p.parse_args()

    host = _pick_site(args.site)
    if not host:
        print("No site given — nothing to set up.", file=sys.stderr)
        return 1

    print("=" * 60)
    print(f"Jira skill setup — {host}")
    print("=" * 60)
    print()
    print(f"1. Open {TOKEN_URL}")
    print("2. Click 'Create API token'.")
    print("3. Label it something you will recognise later, e.g. 'Claude Code'.")
    print("4. Copy the token (it is shown only once).")
    print()
    print(f"NOTE: the token must belong to an account on {host}.")
    print()

    # Normally typed in; either value may instead arrive in the environment, for
    # terminals that will not paste into a hidden getpass prompt.
    email = (os.environ.get("JIRA_EMAIL") or "").strip()
    if email:
        print(f"Atlassian email (from JIRA_EMAIL): {email}")
    else:
        email = input("Atlassian email: ").strip()
    if not email or "@" not in email:
        print("Invalid email.", file=sys.stderr)
        return 1

    token = (os.environ.get("JIRA_API_TOKEN") or "").strip()
    if token:
        print("API token: taken from JIRA_API_TOKEN env var.")
    else:
        token = getpass.getpass("API token (hidden): ").strip()
    if not token:
        print("Empty token.", file=sys.stderr)
        return 1

    print()
    print(f"Validating against {host}/rest/api/3/myself ...")
    probe = {"email": email, "token": token, "host": host}
    me = request("GET", "/rest/api/3/myself", creds=probe)
    if not isinstance(me, dict) or not me.get("accountId"):
        print("Validation failed — unexpected response shape.", file=sys.stderr)
        return 1

    path = save_creds(
        email=email,
        token=token,
        account_id=me["accountId"],
        display_name=me.get("displayName", ""),
        host=host,
    )
    print()
    print(f"OK. Logged in as: {me.get('displayName')} <{me.get('emailAddress')}>")
    print(f"AccountId: {me['accountId']}")
    print(f"Credentials for {host} stored at: {path}")
    print()
    print("Scripts pick the site from --site, then JIRA_SITE, then jira.site in")
    print(".claude/task-flow.json, then this stored default.")
    print("To add another site, re-run with --site <url>. To rotate a token, re-run.")
    if path != creds_path():  # pragma: no cover - defensive, paths agree in practice
        print(f"(read path differs: {creds_path()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
