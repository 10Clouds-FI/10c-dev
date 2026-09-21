"""Offline tests for site resolution and the credential tiers in _auth.py.

What is asserted is the contract SKILL.md documents: the site comes from
--site, then JIRA_SITE, then jira.site in .claude/task-flow.json, then whatever
setup.py stored, and only then is it an error; a credential in the environment
wins over any file, half a pair is ignored rather than mixed with a file, and
with nothing set the answer is the JIRA_CREDS_MISSING sentinel. No network, no
real token.

    python3 -m pytest skills/jira/scripts -q
    python3 skills/jira/scripts/test_auth.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _auth  # noqa: E402

CRED_KEYS = ("JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_SITE", "JIRA_PLUGIN_DATA", "CLAUDE_PLUGIN_DATA")

SITE_A = "https://acme.atlassian.net"
SITE_B = "https://other.atlassian.net"


class AuthTestCase(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in CRED_KEYS}
        self._tmp = tempfile.TemporaryDirectory()
        # Point every file tier at an empty directory, so the developer's own
        # ~/.claude never leaks into the run.
        os.environ["JIRA_PLUGIN_DATA"] = self._tmp.name
        os.environ["CLAUDE_PLUGIN_DATA"] = self._tmp.name
        self._saved_default = _auth._DEFAULT_DATA_DIR
        _auth._DEFAULT_DATA_DIR = Path(self._tmp.name) / "default"
        # And keep task-flow.json lookups away from the real working directory.
        self._cwd = Path(self._tmp.name) / "repo"
        self._cwd.mkdir()
        self._saved_cwd = os.getcwd()
        os.chdir(self._cwd)

    def tearDown(self):
        os.chdir(self._saved_cwd)
        _auth._DEFAULT_DATA_DIR = self._saved_default
        self._tmp.cleanup()
        for k in CRED_KEYS:
            os.environ.pop(k, None)
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def _write_file(self, email="file@example.com", token="file-token", site=SITE_A):
        p = Path(self._tmp.name) / "jira" / "credentials.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "default": site,
            "profiles": {site: {"email": email, "token": token, "account_id": "acc-1",
                                "host": site}},
        }))
        return p

    def _write_task_flow(self, payload):
        p = self._cwd / ".claude" / "task-flow.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload))
        return p


class SiteResolution(AuthTestCase):
    def test_normalize_accepts_url_host_and_slug(self):
        self.assertEqual(_auth.normalize_site("https://acme.atlassian.net/"), SITE_A)
        self.assertEqual(_auth.normalize_site("acme.atlassian.net"), SITE_A)
        self.assertEqual(_auth.normalize_site("acme"), SITE_A)
        self.assertEqual(_auth.normalize_site("https://jira.acme.example"),
                         "https://jira.acme.example")
        self.assertIsNone(_auth.normalize_site(""))
        self.assertIsNone(_auth.normalize_site(None))

    def test_explicit_site_wins_over_everything(self):
        os.environ["JIRA_SITE"] = SITE_B
        self._write_task_flow({"jira": {"site": SITE_B}})
        self._write_file(site=SITE_B)
        self.assertEqual(_auth.resolve_site("acme"), SITE_A)

    def test_env_beats_task_flow_and_stored(self):
        os.environ["JIRA_SITE"] = SITE_A
        self._write_task_flow({"jira": {"site": SITE_B}})
        self._write_file(site=SITE_B)
        self.assertEqual(_auth.resolve_site(), SITE_A)

    def test_task_flow_site_is_found_by_walking_up(self):
        self._write_task_flow({"jira": {"site": "acme.atlassian.net", "projectKey": "ABC"}})
        nested = self._cwd / "packages" / "web" / "src"
        nested.mkdir(parents=True)
        os.chdir(nested)
        self.assertEqual(_auth.resolve_site(), SITE_A)

    def test_task_flow_beats_the_stored_default(self):
        self._write_task_flow({"jira": {"site": SITE_A}})
        self._write_file(site=SITE_B)
        self.assertEqual(_auth.resolve_site(), SITE_A)

    def test_stored_default_is_the_last_resort(self):
        self._write_file(site=SITE_B)
        self.assertEqual(_auth.resolve_site(), SITE_B)

    def test_a_malformed_task_flow_is_treated_as_absent(self):
        p = self._cwd / ".claude" / "task-flow.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json")
        self._write_file(site=SITE_B)
        self.assertEqual(_auth.resolve_site(), SITE_B)

    def test_nothing_configured_reports_the_site_sentinel(self):
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            _auth.resolve_site()
        self.assertEqual(cm.exception.code, 2)
        self.assertIn(_auth.SENTINEL_NO_SITE, err.getvalue())
        self.assertIn("setup.py", err.getvalue())

    def test_required_false_returns_none_instead_of_exiting(self):
        self.assertIsNone(_auth.resolve_site(required=False))

    def test_use_site_pins_the_site_for_the_process(self):
        _auth.use_site("acme")
        self.assertEqual(os.environ["JIRA_SITE"], SITE_A)
        self.assertEqual(_auth.resolve_site(), SITE_A)


class CredentialTiers(AuthTestCase):
    def test_environment_wins_over_the_file(self):
        self._write_file()
        os.environ["JIRA_EMAIL"] = "env@example.com"
        os.environ["JIRA_API_TOKEN"] = "env-token"
        creds = _auth.load_creds()
        self.assertEqual(creds["email"], "env@example.com")
        self.assertEqual(creds["token"], "env-token")
        self.assertEqual(creds["host"], SITE_A)

    def test_site_flag_still_picks_the_host_for_an_environment_credential(self):
        os.environ["JIRA_EMAIL"] = "env@example.com"
        os.environ["JIRA_API_TOKEN"] = "env-token"
        self.assertEqual(_auth.load_creds(site="other")["host"], SITE_B)

    def test_half_a_pair_falls_through_to_the_file(self):
        self._write_file()
        os.environ["JIRA_API_TOKEN"] = "env-token"
        creds = _auth.load_creds()
        self.assertEqual(creds["email"], "file@example.com")
        self.assertEqual(creds["token"], "file-token")

    def test_file_profile_is_selected_by_the_resolved_site(self):
        self._write_file(site=SITE_A)
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            _auth.load_creds(site=SITE_B)
        self.assertEqual(cm.exception.code, 2)
        self.assertIn(_auth.SENTINEL_MISSING, err.getvalue())

    def test_nothing_set_reports_the_missing_sentinel(self):
        os.environ["JIRA_SITE"] = SITE_A
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            _auth.load_creds()
        self.assertEqual(cm.exception.code, 2)
        self.assertIn(_auth.SENTINEL_MISSING, err.getvalue())
        self.assertIn("JIRA_API_TOKEN", err.getvalue())

    def test_environment_credential_carries_no_account_id(self):
        # resolve_user("me") must look it up rather than KeyError; only the
        # absence is asserted here, the lookup needs the network.
        os.environ["JIRA_SITE"] = SITE_A
        os.environ["JIRA_EMAIL"] = "env@example.com"
        os.environ["JIRA_API_TOKEN"] = "env-token"
        self.assertNotIn("account_id", _auth.load_creds())

    def test_jira_plugin_data_overrides_claude_plugin_data(self):
        other = Path(self._tmp.name) / "elsewhere"
        (other / "jira").mkdir(parents=True)
        (other / "jira" / "credentials.json").write_text(json.dumps({
            "default": SITE_A,
            "profiles": {SITE_A: {"email": "override@example.com", "token": "t", "host": SITE_A}},
        }))
        self._write_file()  # under CLAUDE_PLUGIN_DATA
        os.environ["JIRA_PLUGIN_DATA"] = str(other)
        self.assertEqual(_auth.load_creds()["email"], "override@example.com")


class TaskFlowHelpers(AuthTestCase):
    def test_jira_section_defaults_to_empty(self):
        self.assertEqual(_auth.task_flow_jira(), {})
        self._write_task_flow({"slack": {"workspace": "acme.slack.com"}})
        self.assertEqual(_auth.task_flow_jira(), {})

    def test_jira_section_is_returned_whole(self):
        self._write_task_flow({"jira": {"site": SITE_A, "projectKey": "ABC"},
                                "statusMap": {"in_progress": "Doing"}})
        section = _auth.task_flow_jira()
        self.assertEqual(section["projectKey"], "ABC")
        self.assertNotIn("statusMap", section)


if __name__ == "__main__":
    unittest.main()
