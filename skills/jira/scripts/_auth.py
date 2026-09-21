"""Shared HTTP + credential layer for the jira skill.

Two independent questions are answered here, and they are answered separately:

* **Which Jira site?** `--site` flag -> `JIRA_SITE` env -> `jira.site` in the
  consuming repo's `.claude/task-flow.json` -> the site stored by `setup.py`
  -> error.
* **Which credential?** `JIRA_EMAIL` + `JIRA_API_TOKEN` in the environment ->
  the stored `credentials.json` (`JIRA_PLUGIN_DATA`, else `CLAUDE_PLUGIN_DATA`,
  else `~/.claude/10c-dev/jira/credentials.json`).

Nothing about any particular company is baked in: a fresh install has no site
at all until someone runs `setup.py` or configures one.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

CRED_FILENAME = "credentials.json"
TASK_FLOW_RELPATH = Path(".claude") / "task-flow.json"

SENTINEL_MISSING = "JIRA_CREDS_MISSING"
SENTINEL_NO_SITE = "JIRA_SITE_MISSING"
SENTINEL_AUTH_EXPIRED = "JIRA_AUTH_EXPIRED"
SENTINEL_RATE_LIMITED = "JIRA_RATE_LIMITED"
SENTINEL_NOT_FOUND = "JIRA_NOT_FOUND"
SENTINEL_BAD_REQUEST = "JIRA_BAD_REQUEST"

# Where credentials live when neither env var names a plugin data directory.
_DEFAULT_DATA_DIR = Path.home() / ".claude" / "10c-dev"

SETUP_HINT = (
    "Run: python3 \"${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/setup.py\" "
    "--site https://<your-company>.atlassian.net"
)


# --------------------------------------------------------------------- site


def normalize_site(value: str | None) -> str | None:
    """Accept a full URL, a bare host, or an Atlassian Cloud slug; return a base URL.

        https://acme.atlassian.net/  ->  https://acme.atlassian.net
        acme.atlassian.net           ->  https://acme.atlassian.net
        jira.acme.example            ->  https://jira.acme.example
        acme                         ->  https://acme.atlassian.net
    """
    if not value:
        return None
    raw = value.strip().rstrip("/")
    if not raw:
        return None
    if "://" in raw:
        parsed = urllib.parse.urlparse(raw)
        if not parsed.hostname:
            return None
        scheme = parsed.scheme or "https"
        netloc = parsed.netloc
        return f"{scheme}://{netloc}".rstrip("/")
    if "." not in raw:
        raw = f"{raw}.atlassian.net"
    return f"https://{raw}"


def use_site(site: str | None) -> None:
    """Record the site chosen on the command line for the rest of this process,
    so every later load_creds()/request() resolves the same host. No-op if None."""
    normalized = normalize_site(site)
    if normalized:
        os.environ["JIRA_SITE"] = normalized


def _walk_up_for_task_flow(start: Path) -> Path | None:
    for directory in [start, *start.parents]:
        candidate = directory / TASK_FLOW_RELPATH
        if candidate.is_file():
            return candidate
    return None


def task_flow_config(start: Path | None = None) -> dict[str, Any]:
    """`.claude/task-flow.json` of the repo the session is working in, or {}.

    Found by walking up from the working directory; a malformed or unreadable
    file is treated as absent rather than as a crash, because it is optional
    config in somebody else's repo.
    """
    start = (start or Path.cwd()).resolve()
    path = _walk_up_for_task_flow(start)
    if path is None:
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def task_flow_jira(start: Path | None = None) -> dict[str, Any]:
    section = task_flow_config(start).get("jira")
    return section if isinstance(section, dict) else {}


def _profiles(data: dict) -> dict:
    """Profiles keyed by normalized site. A flat single-site file
    ({"email", "token", "host", ...}, the pre-profiles layout) counts as one profile."""
    profiles = data.get("profiles")
    if isinstance(profiles, dict) and profiles:
        return {normalize_site(k): v for k, v in profiles.items()}
    if data.get("email") and data.get("token") and data.get("host"):
        return {normalize_site(data["host"]): data}
    return {}


def _stored_site() -> str | None:
    path = creds_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    site = data.get("default")
    if site:
        return normalize_site(site)
    profiles = _profiles(data)
    if len(profiles) == 1:
        return next(iter(profiles))
    return None


def resolve_site(site: str | None = None, required: bool = True) -> str | None:
    """The site to talk to, in the documented order. Exits 2 when nothing says."""
    for candidate in (
        site,
        os.environ.get("JIRA_SITE"),
        task_flow_jira().get("site"),
        _stored_site(),
    ):
        normalized = normalize_site(candidate)
        if normalized:
            return normalized
    if not required:
        return None
    print(SENTINEL_NO_SITE, file=sys.stderr)
    print(
        "No Jira site configured. Pass --site https://<your-company>.atlassian.net, "
        "set JIRA_SITE, add {\"jira\": {\"site\": \"...\"}} to .claude/task-flow.json, "
        "or store one with setup.py.",
        file=sys.stderr,
    )
    print(SETUP_HINT, file=sys.stderr)
    sys.exit(2)


# -------------------------------------------------------------- credentials


def _creds_candidates() -> list[Path]:
    """Every place a credentials file may live, most specific first.

    `JIRA_PLUGIN_DATA` is the explicit override (a caller that knows where this
    skill's data lives), `CLAUDE_PLUGIN_DATA` is the host's per-plugin
    persistent directory, and the home-directory default is what `setup.py`
    falls back to when neither is set.
    """
    out: list[Path] = []
    for env in ("JIRA_PLUGIN_DATA", "CLAUDE_PLUGIN_DATA"):
        base = os.environ.get(env)
        if base:
            out.append(Path(base).expanduser() / "jira" / CRED_FILENAME)
    out.append(_DEFAULT_DATA_DIR / "jira" / CRED_FILENAME)
    seen: set[Path] = set()
    uniq: list[Path] = []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def creds_path() -> Path:
    """The credentials file to read: the first candidate that exists. When none
    does, the most preferred candidate — that is where setup.py writes, and what
    the JIRA_CREDS_MISSING message points at."""
    candidates = _creds_candidates()
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]


def _env_creds(site: str | None) -> dict[str, Any] | None:
    """The credential from the environment, when the whole of it is there.

    A value in the environment wins over any file, because that is the one
    channel every host has — a shell `export` locally, an injected secret in a
    container. Half a pair is ignored rather than mixed with a file: a token
    from one account and an email from another is a 401 with no explanation.
    """
    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    if not (email and token):
        return None
    host = resolve_site(site)
    return {"email": email, "token": token, "host": host, "site": host}


def load_creds(site: str | None = None) -> dict[str, Any]:
    from_env = _env_creds(site)
    if from_env is not None:
        return from_env

    path = creds_path()
    if not path.exists():
        print(SENTINEL_MISSING, file=sys.stderr)
        print(
            f"No Jira credentials at {path}. Run setup.py first, or set JIRA_EMAIL and "
            "JIRA_API_TOKEN in the environment.",
            file=sys.stderr,
        )
        print(SETUP_HINT, file=sys.stderr)
        sys.exit(2)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(SENTINEL_MISSING, file=sys.stderr)
        print(f"Cannot read {path}: {exc}. Re-run setup.py.", file=sys.stderr)
        sys.exit(2)

    profiles = _profiles(data)
    if not profiles:
        print(SENTINEL_MISSING, file=sys.stderr)
        print(f"No profiles in {path}. Re-run setup.py.", file=sys.stderr)
        sys.exit(2)

    host = resolve_site(site)
    profile = profiles.get(host)
    if profile is None:
        print(SENTINEL_MISSING, file=sys.stderr)
        print(
            f"No Jira credentials for {host}. Configured: {sorted(profiles)}. "
            f"Run setup.py --site {host}.",
            file=sys.stderr,
        )
        sys.exit(2)

    prof = dict(profile)
    prof["host"] = host
    prof["site"] = host
    return prof


def save_creds(
    email: str,
    token: str,
    account_id: str,
    display_name: str,
    host: str,
) -> Path:
    host = normalize_site(host) or host
    path = creds_path()

    data: dict[str, Any] = {"profiles": {}, "default": None}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            existing = {}
        if isinstance(existing, dict) and isinstance(existing.get("profiles"), dict):
            data = existing

    data["profiles"][host] = {
        "email": email,
        "token": token,
        "host": host,
        "account_id": account_id,
        "display_name": display_name,
    }
    if not data.get("default"):
        data["default"] = host

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(path, 0o600)
    return path


# --------------------------------------------------------------------- HTTP


def _auth_header(email: str, token: str) -> str:
    raw = f"{email}:{token}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    creds: dict[str, Any] | None = None,
    retries: int = 1,
) -> dict[str, Any] | list[Any] | None:
    if creds is None:
        creds = load_creds()
    base = (creds.get("host") or resolve_site(None)).rstrip("/")
    url = base + path
    if query:
        filtered = {k: v for k, v in query.items() if v is not None}
        if filtered:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(filtered, doseq=True)

    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", _auth_header(creds["email"], creds["token"]))
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")

    attempt = 0
    while True:
        attempt += 1
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode()
                if not raw:
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            body_text = e.read().decode(errors="replace")
            if e.code == 401:
                print(SENTINEL_AUTH_EXPIRED, file=sys.stderr)
                print("Token rejected (401). Re-run setup.py.", file=sys.stderr)
                sys.exit(3)
            if e.code == 429 and attempt <= retries:
                retry_after = int(e.headers.get("Retry-After", "5"))
                print(f"Rate limited, sleeping {retry_after}s...", file=sys.stderr)
                time.sleep(retry_after)
                continue
            if e.code == 429:
                print(SENTINEL_RATE_LIMITED, file=sys.stderr)
                print(body_text, file=sys.stderr)
                sys.exit(4)
            if e.code == 404:
                print(SENTINEL_NOT_FOUND, file=sys.stderr)
                print(
                    f"404 on {method} {path} — issue/board missing OR you lack permission.",
                    file=sys.stderr,
                )
                print(body_text, file=sys.stderr)
                sys.exit(5)
            if e.code == 400:
                print(SENTINEL_BAD_REQUEST, file=sys.stderr)
                print(f"400 on {method} {path}:", file=sys.stderr)
                print(body_text, file=sys.stderr)
                sys.exit(6)
            if e.code == 410:
                print(f"HTTP 410 (Gone) on {method} {path}. Endpoint removed:", file=sys.stderr)
                print(body_text, file=sys.stderr)
                sys.exit(7)
            print(f"HTTP {e.code} on {method} {path}:", file=sys.stderr)
            print(body_text, file=sys.stderr)
            sys.exit(1)
        except urllib.error.URLError as e:
            print(f"Network error on {method} {path}: {e}", file=sys.stderr)
            sys.exit(8)


def get(path: str, **kw) -> Any:
    return request("GET", path, **kw)


def post(path: str, body: dict[str, Any], **kw) -> Any:
    return request("POST", path, body=body, **kw)


def put(path: str, body: dict[str, Any], **kw) -> Any:
    return request("PUT", path, body=body, **kw)


def delete(path: str, **kw) -> Any:
    return request("DELETE", path, **kw)


def resolve_user(query: str, creds: dict[str, Any] | None = None) -> str | None:
    """Resolve 'me', an email, or an accountId into an accountId. None means unassign."""
    if creds is None:
        creds = load_creds()
    if query in ("me", "self", "currentUser"):
        # setup.py records the account id beside the token; a credential from the
        # environment carries none, so ask Jira who the token belongs to.
        if not creds.get("account_id"):
            creds["account_id"] = get("/rest/api/3/myself", creds=creds)["accountId"]
        return creds["account_id"]
    if query in ("-1", "none", "unassign"):
        return None
    if ":" in query and "-" in query:
        return query
    users = get("/rest/api/3/user/search", query={"query": query}, creds=creds)
    if not users:
        print(f"No user found matching {query!r}", file=sys.stderr)
        sys.exit(9)
    if len(users) > 1:
        print(f"Ambiguous user query {query!r}, matches:", file=sys.stderr)
        for u in users[:5]:
            print(
                f"  {u.get('accountId')} — {u.get('displayName')} "
                f"<{u.get('emailAddress', '?')}>",
                file=sys.stderr,
            )
        sys.exit(10)
    return users[0]["accountId"]
