import copy
import io
import json
import os
import stat
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
from orca_dot_bridge import core as b
from orca_dot_bridge.compat import REQUIRED, SLACK_COMMANDS, automation_plan, check
from orca_dot_bridge.cli import main


def config(directory):
    # Synthetic identities generated here; no deployment account or project handles.
    ident = lambda prefix, n: prefix + str(n) * 8
    return {
        "schema_version": 1, "enabled": True,
        "features": {flag: False for flag in b.DISABLED},
        "state_file": str(Path(directory) / "state.json"), "orca": {"executable": "auto"},
        "slack": {"team_id": ident("T", 1), "channel_id": ident("C", 2),
                  "bridge_user_id": ident("U", 3), "bridge_bot_id": ident("B", 3),
                  "dot_user_id": ident("U", 4), "dot_bot_id": ident("B", 4),
                  "approver_ids": [ident("U", 5)], "keychain_account": "TEST_ACCOUNT",
                  "writer_service": "TEST_WRITER", "reader_service": "TEST_READER"},
        "manager": {"provider": "codex", "run_id": "run_TEST_ONLY", "terminal_handle": "term_TEST_ONLY",
                    "worktree_path": str(Path(directory))},
        "automation": {"name": "TEST_ONLY", "trigger": "*/10 * * * *"},
        "limits": {"page_limit": 15, "max_pages": 3, "lookback_seconds": 86400, "request_ttl_seconds": 3600}}


NOW = 1000000100.0
PARENT = "1000000000.000001"


def fixture(c, decision="approve", risk="low"):
    q = b.new_request(c, "Synthetic question; do not execute", "task_TEST_ONLY", "gate_TEST_ONLY", risk,
                      now=1000000000.0)
    root = {"type": "message", "user": c["slack"]["bridge_user_id"],
            "bot_id": c["slack"]["bridge_bot_id"], "ts": PARENT, "text": b.encode(b.REQ, q)}
    d = {k: q[k] for k in b.BIND}
    d.update(decision=decision, execute=False, reason="Synthetic assessment")
    reply = {"type": "message", "user": c["slack"]["dot_user_id"], "bot_id": c["slack"]["dot_bot_id"],
             "ts": "1000000010.000001", "thread_ts": PARENT, "text": b.encode(b.DOT, d)}
    return q, root, d, reply


class FakeSlack:
    def __init__(self, c, root, messages):
        self.c, self.root, self.thread = c, root, list(messages)
        self.posts = []
    def identity(self, writer=False):
        return {}
    def messages(self, thread=None, oldest=None):
        return self.thread if thread else [self.root]
    def post(self, text, thread=None):
        ts = "1000000020.%06d" % (len(self.posts) + 1)
        self.posts.append((text, thread))
        self.thread.append({"type": "message", "user": self.c["slack"]["bridge_user_id"],
                            "bot_id": self.c["slack"]["bridge_bot_id"], "ts": ts,
                            "thread_ts": thread, "text": text})
        return ts


class FakeOrca:
    def __init__(self):
        self.deliveries, self.ack = [], True
    def prepare_delivery(self, q, d):
        return q, d
    def deliver(self, q, d):
        self.deliveries.append((q, d))
        return {"cursor": 1, "runtime_id": "TEST_RUNTIME"}
    def confirm(self, q, receipt):
        return self.ack


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.c = config(self.temp.name)
        self.q, self.root, self.d, self.reply = fixture(self.c)
        self.slack = FakeSlack(self.c, self.root, [self.root, self.reply])
        self.orca = FakeOrca()

    def pump(self, dry=False):
        return b.tick(self.c, self.slack, self.orca, NOW, dry)[0]["status"]

    def test_preflight_draft_can_clear_without_poisoning_the_journal(self):
        with patch.object(self.orca, "prepare_delivery",
                          side_effect=b.BridgeError("manager_has_draft:no_input_sent")):
            with self.assertRaisesRegex(b.BridgeError, "manager_has_draft"):
                self.pump()
        self.assertFalse(Path(self.c["state_file"]).exists())
        self.assertFalse(self.orca.deliveries)
        self.assertEqual(self.pump(), "RECEIVED_CONFIRMED")
        self.assertEqual(len(self.orca.deliveries), 1)

    def test_incomplete_ack_stops_tick_without_repeating_the_send(self):
        with patch.object(self.orca, "confirm", side_effect=b.BridgeError(
                "ack_output_incomplete:manual_reconciliation_required")):
            with self.assertRaisesRegex(b.BridgeError, "ack_output_incomplete"):
                self.pump()
        with patch.object(self.orca, "prepare_delivery", side_effect=AssertionError("preflight replayed")):
            self.assertEqual(self.pump(), "RECEIVED_CONFIRMED")
        self.assertEqual(len(self.orca.deliveries), 1)

    def test_unrelated_dot_thread_message_is_not_a_decision(self):
        self.slack.thread += [dict(self.reply, text="Reviewing the issue"),
                              dict(self.reply, text='{"progress":"read"}')]
        self.assertEqual(self.pump(), "RECEIVED_CONFIRMED")

    def test_empty_environment_value_is_only_allowed_for_optional_dot_bot(self):
        with patch.dict(os.environ, {"TEST_EMPTY": ""}):
            self.assertEqual(b.expand({"slack": {"dot_bot_id": "${TEST_EMPTY}"}}),
                             {"slack": {"dot_bot_id": ""}})
            with self.assertRaisesRegex(b.BridgeError, "missing_environment_variable"):
                b.expand({"slack": {"dot_user_id": "${TEST_EMPTY}"}})

    def human(self, decision="reject", execute=False):
        value = {k: self.q[k] for k in b.BIND}
        value.update(decision=decision, execute=execute, reason="Synthetic human decision")
        return {"type": "message", "user": self.c["slack"]["approver_ids"][0],
                "ts": "1000000030.000001", "thread_ts": PARENT, "text": b.encode(b.HUMAN, value)}

    def test_roundtrip_and_sequential_duplicate(self):
        self.assertEqual(self.pump(), "RECEIVED_CONFIRMED")
        self.assertEqual(self.pump(), "DUPLICATE_SKIPPED")
        self.assertEqual(len(self.orca.deliveries), 1)
        self.assertEqual(len(self.slack.posts), 1)
        report = b.decode(self.slack.posts[0][0], b.REPORT)
        self.assertFalse(report["execute"])
        self.assertFalse(report["gate_mutated"])
        self.assertFalse(report["task_mutated"])

    def test_no_dot_means_no_side_effects(self):
        self.slack.thread = [self.root]
        self.assertEqual(self.pump(), "NO_DOT_DECISION")
        self.assertFalse(self.slack.posts or self.orca.deliveries)

    def test_slack_text_fallback_flattened_header_newline(self):
        self.reply['text'] = self.reply['text'].replace(b.DOT + '\n', b.DOT + ' ', 1)
        self.assertEqual(self.pump(), 'RECEIVED_CONFIRMED')
        self.assertEqual(len(self.orca.deliveries), 1)
        self.assertEqual(self.pump(), 'DUPLICATE_SKIPPED')

    def test_header_normalization_does_not_accept_prose_or_prefix_spoof(self):
        with self.assertRaises(b.BridgeError):
            b.decode(b.DOT + ' explanation ' + json.dumps(self.d), b.DOT)
        self.assertFalse(b.has_marker(b.DOT + '_OTHER ' + json.dumps(self.d), b.DOT))
        with self.assertRaises(b.BridgeError):
            b.decode(b.DOT + ' ' + json.dumps(dict(self.d, execute='false')), b.HUMAN)

    def test_transport_receipt_is_not_ack_and_does_not_resend(self):
        self.orca.ack = False
        self.assertEqual(self.pump(), "AWAITING_MANAGER_ACK_NO_RESEND")
        self.assertEqual(self.pump(), "AWAITING_MANAGER_ACK_NO_RESEND")
        self.assertEqual(len(self.orca.deliveries), 1)
        self.assertFalse(self.slack.posts)
        self.orca.ack = True
        self.assertEqual(self.pump(), "RECEIVED_CONFIRMED")

    def test_human_request_then_identification_only(self):
        self.q, self.root, self.d, self.reply = fixture(self.c, "human_required")
        self.slack = FakeSlack(self.c, self.root, [self.root, self.reply])
        self.assertEqual(self.pump(), "HUMAN_APPROVAL_REQUESTED")
        self.assertEqual(self.pump(), "WAITING_FOR_HUMAN")
        self.assertEqual(len(self.slack.posts), 1)
        self.slack.thread.append(self.human())
        self.assertEqual(self.pump(), "RECEIVED_CONFIRMED")
        report = b.decode(self.slack.posts[-1][0], b.REPORT)
        self.assertTrue(report["human_decision_identified"])
        self.assertFalse(report["execute"])
        self.assertEqual(self.orca.deliveries[0][1]["decision"], "reject")

    def test_high_risk_requires_human_even_if_dot_approves(self):
        self.q, self.root, self.d, self.reply = fixture(self.c, risk="critical")
        self.slack = FakeSlack(self.c, self.root, [self.root, self.reply])
        self.assertEqual(self.pump(), "HUMAN_APPROVAL_REQUESTED")
        self.assertFalse(self.orca.deliveries)

    def test_human_execute_true_never_creates_execution(self):
        self.q, self.root, self.d, self.reply = fixture(self.c, "human_required")
        self.slack = FakeSlack(self.c, self.root, [self.root, self.reply])
        self.pump()
        self.slack.thread.append(self.human("approve", True))
        self.assertEqual(self.pump(), "RECEIVED_CONFIRMED")
        self.assertFalse(b.decode(self.slack.posts[-1][0], b.REPORT)["execute"])

    def test_human_metadata_rejections(self):
        for change in ({"bot_id": None}, {"app_id": "SYNTHETIC"}, {"subtype": "bot_message"},
                       {"edited": {}}, {"user": self.c["slack"]["dot_user_id"]},
                       {"thread_ts": "1000000001.000001"}):
            with self.subTest(change=change):
                msg = self.human()
                msg.update(change)
                with self.assertRaises(b.BridgeError):
                    b.validate_decision(msg, self.q, PARENT, self.c, True, "1000000020.000001", NOW)

    def test_cross_request_or_nonce_replay_rejected(self):
        for key in b.BIND:
            with self.subTest(key=key):
                msg, value = self.human(), copy.deepcopy(self.d)
                value[key] = "OTHER_BINDING"
                msg["text"] = b.encode(b.HUMAN, value)
                with self.assertRaisesRegex(b.BridgeError, "binding_mismatch"):
                    b.validate_decision(msg, self.q, PARENT, self.c, True, "1000000020.000001", NOW)

    def test_boolean_strings_and_integers_rejected(self):
        for bad in ("false", "true", 0, 1, None):
            value = dict(self.d, execute=bad)
            msg = dict(self.reply, text=b.encode(b.DOT, value))
            with self.subTest(bad=bad), self.assertRaisesRegex(b.BridgeError, "json_boolean"):
                b.validate_decision(msg, self.q, PARENT, self.c, now=NOW)

    def test_dot_execute_true_blocked(self):
        msg = dict(self.reply, text=b.encode(b.DOT, dict(self.d, execute=True)))
        with self.assertRaisesRegex(b.BridgeError, "execution_request_blocked"):
            b.validate_decision(msg, self.q, PARENT, self.c, now=NOW)

    def test_old_human_decision_rejected(self):
        with self.assertRaisesRegex(b.BridgeError, "precedes_approval"):
            b.validate_decision(self.human(), self.q, PARENT, self.c, True, "1000000040.000001", NOW)

    def test_expired_and_wrong_route_requests_rejected(self):
        with self.assertRaisesRegex(b.BridgeError, "expired"):
            b.request_from_message(self.root, self.c, NOW + 10000)
        self.c["manager"]["run_id"] = "run_OTHER"
        with self.assertRaisesRegex(b.BridgeError, "route"):
            b.request_from_message(self.root, self.c, NOW)

    def test_ambiguous_decisions_fail_closed(self):
        self.slack.thread.append(dict(self.reply, ts="1000000011.000001"))
        self.assertEqual(self.pump(), "VERIFICATION_FAILED")
        self.assertFalse(self.orca.deliveries or self.slack.posts)

    def test_forged_report_cannot_suppress_forwarding(self):
        self.slack.thread.append({"type": "message", "user": self.c["slack"]["approver_ids"][0],
                                  "ts": "1000000012.000001", "thread_ts": PARENT,
                                  "text": b.encode(b.REPORT, self.d)})
        self.assertEqual(self.pump(), "RECEIVED_CONFIRMED")

    def test_dry_run_has_no_state_or_external_writes(self):
        self.assertEqual(self.pump(True), "WOULD_FORWARD_ANALYSIS_ONLY")
        self.assertFalse(Path(self.c["state_file"]).exists())
        self.assertFalse(self.orca.deliveries or self.slack.posts)

    def test_disabled_features_cannot_be_enabled(self):
        for flag in b.DISABLED:
            c = copy.deepcopy(self.c)
            c["features"][flag] = True
            with self.subTest(flag=flag), self.assertRaisesRegex(b.BridgeError, "unsupported_feature"):
                b.validate_config(c)

    def test_uncertain_send_never_retried(self):
        calls = []
        def ambiguous():
            calls.append(1)
            raise b.BridgeError("synthetic_timeout")
        journal = b.Journal(self.c["state_file"])
        with self.assertRaises(b.BridgeError):
            journal.effect("SYNTHETIC", ambiguous)
        reloaded = b.Journal(self.c["state_file"])
        with self.assertRaisesRegex(b.BridgeError, "manual_reconciliation"):
            reloaded.effect("SYNTHETIC", ambiguous)
        self.assertEqual(calls, [1])
        self.assertEqual(stat.S_IMODE(Path(self.c["state_file"]).stat().st_mode), 0o600)

    def test_corrupt_or_public_state_fails_closed(self):
        path = Path(self.c["state_file"])
        path.write_text("corrupt")
        path.chmod(0o600)
        with self.assertRaises(b.BridgeError):
            b.Journal(path)
        path.write_text('{"schema_version":1,"effects":{}}')
        path.chmod(0o644)
        with self.assertRaisesRegex(b.BridgeError, "permissions"):
            b.Journal(path)

    def test_duplicate_json_keys_are_not_silently_accepted(self):
        with self.assertRaisesRegex(b.BridgeError, "duplicate_json_key"):
            b.strict_json('{"execute":false,"execute":true}')

    def test_missing_environment_fails_before_any_network(self):
        file = Path(self.temp.name) / "cfg.yaml"
        file.write_text('{"x":"${BRIDGE_TEST_MISSING_ENV}"}')
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(b.BridgeError, "missing_environment"):
            b.load_config(file)

    def test_duplicate_request_ids_block_both_before_forwarding(self):
        root2 = dict(self.root, ts="1000000001.000001")
        original = self.slack.messages
        self.slack.messages = lambda thread=None, oldest=None: original(thread, oldest) if thread else [self.root, root2]
        results = b.tick(self.c, self.slack, self.orca, NOW)
        self.assertEqual([r["status"] for r in results], ["VERIFICATION_FAILED"] * 2)
        self.assertFalse(self.orca.deliveries or self.slack.posts)

    def test_root_edit_rejected_before_forwarding(self):
        self.root["edited"] = {"ts": "1000000002.000001"}
        self.assertEqual(self.pump(), "VERIFICATION_FAILED")
        self.assertFalse(self.orca.deliveries or self.slack.posts)

    def test_untrusted_original_author_rejected(self):
        self.root["user"] = self.c["slack"]["approver_ids"][0]
        self.assertEqual(self.pump(), "VERIFICATION_FAILED")
        self.assertFalse(self.orca.deliveries or self.slack.posts)

    def test_disabled_bridge_does_not_read_network(self):
        self.c["enabled"] = False
        with self.assertRaisesRegex(b.BridgeError, "bridge_disabled"):
            b.tick(self.c, self.slack, self.orca, NOW)
        self.assertFalse(self.orca.deliveries or self.slack.posts)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.c = config(self.temp.name)
        self.calls = []
    def client(self, responses):
        owner = self
        class Opener:
            def open(self, req, timeout):
                owner.calls.append(req)
                response = responses.pop(0)
                if isinstance(response, Exception):
                    raise response
                return io.BytesIO(json.dumps(response).encode())
        return b.Slack(self.c, lambda c, role: "SYNTHETIC_SECRET_NEVER_LOG", Opener())

    def test_auth_identity_and_bot_writer_checked(self):
        s = self.c["slack"]
        client = self.client([{"ok": True, "team_id": s["team_id"], "user_id": s["bridge_user_id"],
                               "bot_id": s["bridge_bot_id"]}])
        self.assertEqual(client.identity(True)["bot_id"], s["bridge_bot_id"])
        client = self.client([{"ok": True, "team_id": "WRONG"}])
        with self.assertRaisesRegex(b.BridgeError, "workspace_mismatch"):
            client.identity()

    def test_paginated_thread_preserves_original_metadata(self):
        client = self.client([
            {"ok": True, "messages": [{"ts": "1.000001", "bot_id": None}], "has_more": True,
             "response_metadata": {"next_cursor": "NEXT_SYNTHETIC"}},
            {"ok": True, "messages": [{"ts": "2.000001", "type": "message"}]}])
        messages = client.messages(thread=PARENT)
        self.assertIn("bot_id", messages[0])
        self.assertNotIn("bot_id", messages[1])
        self.assertIn("cursor=NEXT_SYNTHETIC", self.calls[1].full_url)
        self.assertTrue(all(r.method == "GET" for r in self.calls))

    def test_incomplete_pagination_is_never_processed(self):
        client = self.client([{"ok": True, "messages": [], "has_more": True}])
        with self.assertRaisesRegex(b.BridgeError, "pagination_incomplete"):
            client.messages()

    def test_repeated_cursor_and_budget_exhaustion_fail_closed(self):
        page = {"ok": True, "messages": [], "response_metadata": {"next_cursor": "SAME"}}
        client = self.client([page, page])
        with self.assertRaisesRegex(b.BridgeError, "pagination_loop"):
            client.messages()
        self.c["limits"]["max_pages"] = 1
        client = self.client([page])
        with self.assertRaisesRegex(b.BridgeError, "page_budget_exhausted"):
            client.messages()

    def test_auth_test_writer_must_be_expected_bot(self):
        client = self.client([{"ok": True, "team_id": self.c["slack"]["team_id"], "user_id": "OTHER"}])
        with self.assertRaisesRegex(b.BridgeError, "writer_identity_mismatch"):
            client.identity(True)

    def test_rate_limit_no_retry_no_secret_in_error(self):
        error = urllib.error.HTTPError("https://slack.com", 429, "SECRET", {"Retry-After": "60"}, None)
        client = self.client([error])
        with self.assertRaisesRegex(b.BridgeError, "retry_after_seconds=60") as caught:
            client.messages()
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("SECRET", str(caught.exception))

    def test_post_uses_header_allowlist_and_no_unfurls(self):
        client = self.client([{"ok": True, "channel": self.c["slack"]["channel_id"], "ts": PARENT}])
        client.post("plain text", PARENT)
        req = self.calls[0]
        payload = json.loads(req.data)
        self.assertFalse(payload["mrkdwn"])
        self.assertFalse(payload["unfurl_links"])
        self.assertNotIn("SYNTHETIC_SECRET", req.full_url + req.data.decode())
        self.assertTrue(req.get_header("Authorization").startswith("Bearer "))
        with self.assertRaisesRegex(b.BridgeError, "not_allowed"):
            client.call("chat.postMessage", {"channel": "WRONG"}, True)

    def test_slack_ok_false_is_failure_even_with_http_200(self):
        client = self.client([{"ok": False, "error": "missing_scope"}])
        with self.assertRaisesRegex(b.BridgeError, "missing_scope"):
            client.messages()

    def test_redirects_are_refused(self):
        self.assertIsNone(b.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid"))


class CompatAndOrcaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.c = config(self.temp.name)

    def help_runner(self, args):
        if args[-1] == "--version":
            return "SYNTHETIC_VERSION"
        if args[-1] == "--help" and len(args) == 2:
            return "orca automations orchestration"
        if "skills" in args:
            return '{"markdown":"synthetic guide"}'
        return "\n".join("  " + flag + " <value>" for flag in REQUIRED[" ".join(args[1:-1])])

    def test_current_help_capabilities_and_disabled_plan(self):
        report = check(self.c, self.help_runner)
        self.assertTrue(report["compatible"])
        plan = automation_plan(self.c, "/tmp/config.yaml", Path(__file__).resolve().parents[1], report)
        self.assertIn("--disabled", plan["argv"])
        self.assertNotIn("--enabled", plan["argv"])
        self.assertFalse(plan["enabled_on_create"])

    def test_old_or_unknown_flag_does_not_get_guessed(self):
        def old(args):
            value = self.help_runner(args)
            return value.replace("--cursor", "--old-flag") if args[1:3] == ["terminal", "read"] else value
        report = check(self.c, old)
        self.assertFalse(report["compatible"])
        with self.assertRaisesRegex(b.BridgeError, "incompatible"):
            automation_plan(self.c, "cfg", ".", report)

    def test_incidental_flag_mention_is_not_capability(self):
        def fake(args):
            value = self.help_runner(args)
            return value.replace("  --cursor <value>", "Example: unsupported --cursor")
        self.assertFalse(check(self.c, fake)["compatible"])

    def test_slack_probe_never_probes_automation_or_gate_mutations(self):
        seen = []
        def runner(args):
            if args[-1] == "--help" and len(args) > 2:
                seen.append(" ".join(args[1:-1]))
            return self.help_runner(args)
        self.assertTrue(check(self.c, runner, commands=SLACK_COMMANDS, include_guides=False)["compatible"])
        self.assertEqual(set(seen), {"terminal read", "terminal send", "terminal show"})

    def test_executable_selection_does_not_shell_split_or_fallback(self):
        with patch.dict(os.environ, {"ORCA_CLI_COMMAND": "/tmp/one executable"}, clear=True):
            self.assertEqual(b.orca_executable(self.c), "/tmp/one executable")
        with patch.dict(os.environ, {}, clear=True), patch.object(b.sys, "platform", "linux"):
            self.assertEqual(b.orca_executable(self.c), "orca-ide")

    def test_manager_data_delivery_and_ack_from_terminal_only(self):
        q, _, d, _ = fixture(self.c)
        calls = []
        ack = {k: q[k] for k in b.BIND}
        ack.update(status="RECEIVED_CONFIRMED", execute=False)
        def runner(args):
            calls.append(args)
            if args[1:3] == ["terminal", "show"]:
                result = {"terminal": {"handle": self.c["manager"]["terminal_handle"], "connected": True,
                                       "agentIdentity": "codex", "worktreePath": self.c["manager"]["worktree_path"]}}
            elif args[1:3] == ["terminal", "read"]:
                result = {"terminal": {"latestCursor": 5, "source": "screen", "tail": [b.ACK + " " + json.dumps(ack)]}}
            else:
                result = {"accepted": True}
            return json.dumps({"ok": True, "result": result, "_meta": {"runtimeId": "SYNTHETIC_RUNTIME"}})
        orca = b.Orca(self.c, runner)
        receipt = orca.deliver(*orca.prepare_delivery(q, d))
        self.assertTrue(orca.confirm(q, receipt))
        self.assertTrue(all(args[1] == "terminal" for args in calls))
        self.assertNotIn("gate-resolve", str(calls))
        self.assertNotIn("task-update", str(calls))
        prompt = next(args[args.index("--text") + 1] for args in calls if "--text" in args)
        self.assertNotIn(b.ACK + " {", prompt)  # prompt echo alone cannot match the ACK line

    def test_manager_draft_is_preserved_without_sending(self):
        q, _, d, _ = fixture(self.c)
        calls = []
        def runner(args):
            calls.append(args)
            if args[1:3] == ["terminal", "show"]:
                result = {"terminal": {"handle": self.c["manager"]["terminal_handle"], "connected": True,
                                       "agentIdentity": "codex", "worktreePath": self.c["manager"]["worktree_path"]}}
            else:
                result = {"terminal": {"source": "screen", "draft": "unsent user input"}}
            return json.dumps({"ok": True, "result": result, "_meta": {"runtimeId": "SYNTHETIC_RUNTIME"}})
        with self.assertRaisesRegex(b.BridgeError, "manager_has_draft"):
            b.Orca(self.c, runner).prepare_delivery(q, d)
        self.assertFalse(any(args[1:3] == ["terminal", "send"] for args in calls))

    def test_ack_split_between_cursor_pages_is_detected(self):
        root, _, _, _ = fixture(self.c)
        ack = {k: root[k] for k in b.BIND}
        ack.update(status="RECEIVED_CONFIRMED", execute=False)
        prefix = b.ACK + " " + json.dumps(ack)
        orca = b.Orca(self.c)
        pages = [
            {"tail": ["noise"] * 999 + [prefix[:70]], "limited": True,
             "nextCursor": 1001, "latestCursor": 1002},
            {"tail": [prefix[70:]], "limited": False, "nextCursor": 1002},
        ]
        with patch.object(orca, "manager", return_value="runtime"), \
                patch.object(orca, "read", side_effect=pages) as read:
            self.assertTrue(orca.confirm(root, {"cursor": 1, "runtime_id": "runtime"}))
        self.assertEqual([call.args[0] for call in read.call_args_list], [1, 1001])

    def test_nonadvancing_ack_cursor_fails_instead_of_repeating_page(self):
        root, _, _, _ = fixture(self.c)
        orca = b.Orca(self.c)
        with patch.object(orca, "manager", return_value="runtime"), \
                patch.object(orca, "read", return_value={"tail": [], "limited": True, "nextCursor": 1}) as read, \
                patch.object(orca, "command", return_value={"result": {"terminal": {"source": "screen"}}}):
            with self.assertRaisesRegex(b.BridgeError, "ack_output_incomplete"):
                orca.confirm(root, {"cursor": 1, "runtime_id": "runtime"})
        read.assert_called_once_with(1)

    def test_bulleted_hard_wrapped_ack_preserves_exact_binding(self):
        q, _, _, _ = fixture(self.c)
        value = {k: q[k] for k in b.BIND}
        value.update(status="RECEIVED_CONFIRMED", execute=False)
        body = json.dumps(value, separators=(",", ":"))
        lines = ["• " + b.ACK + " " + body[:53], "  " + body[53:128], "  " + body[128:]]
        self.assertTrue(b.ack_in_tail(lines, q))
        altered = dict(q, nonce="DIFFERENT_NONCE")
        self.assertFalse(b.ack_in_tail(lines, altered))

    def test_ack_prompt_echo_and_execute_true_do_not_confirm(self):
        q, _, _, _ = fixture(self.c)
        value = {k: q[k] for k in b.BIND}
        value.update(status="RECEIVED_CONFIRMED", execute=False)
        self.assertFalse(b.ack_in_tail(["DATA_JSON " + json.dumps(value)], q))
        self.assertFalse(b.ack_in_tail([b.ACK + " 뒤 공백과 JSON 객체를 작성하세요"], q))
        value['execute'] = True
        self.assertFalse(b.ack_in_tail([b.ACK + " " + json.dumps(value)], q))

    def test_cli_error_does_not_leak_subprocess_diagnostics(self):
        with patch("orca_dot_bridge.cli.load_config", side_effect=b.BridgeError("safe_error")), patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(main(["validate-config"]), 2)
        self.assertEqual(json.loads(stdout.getvalue())["error"], "safe_error")

    def test_cli_returns_json_for_non_object_slack_state(self):
        state_path = Path(self.c["state_file"])
        state_path.write_text("[]")
        state_path.chmod(0o600)
        config_path = state_path.with_name("config.yaml")
        config_path.write_text(json.dumps(self.c))
        with patch("orca_dot_bridge.cli.check", return_value={"compatible": True}), \
                patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(main(["--config", str(config_path), "doctor"]), 2)
        self.assertEqual(json.loads(stdout.getvalue()), {
            "ok": False, "error": "state_invalid:manual_reconciliation_required"})
        self.assertEqual(state_path.read_text(), "[]")

    def test_keychain_password_is_not_a_command_argument(self):
        with patch("orca_dot_bridge.cli.load_config", return_value=self.c), \
             patch("orca_dot_bridge.cli.sys.platform", "darwin"), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("orca_dot_bridge.cli.subprocess.run") as runner, \
             patch("sys.stdout", new_callable=io.StringIO):
            runner.return_value.returncode = 0
            self.assertEqual(main(["auth-store", "--role", "writer"]), 0)
            args = runner.call_args[0][0]
            self.assertEqual(args[-1], "-w")
            self.assertNotIn("-A", args)

    def test_runner_uses_argv_without_shell_and_suppresses_errors(self):
        with patch("orca_dot_bridge.core.subprocess.run") as runner:
            runner.return_value.returncode = 1
            runner.return_value.stdout = "SYNTHETIC_SECRET"
            with self.assertRaises(b.BridgeError) as caught:
                b.run(["synthetic", "$(untrusted); arbitrary"])
            self.assertNotIn("SECRET", str(caught.exception))
            self.assertNotIn("shell", runner.call_args[1])


if __name__ == "__main__":
    unittest.main()
