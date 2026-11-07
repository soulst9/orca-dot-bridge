import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from orca_dot_bridge.cli import main
from orca_dot_bridge.core import BridgeError
from orca_dot_bridge.intake import (Coordinator, eligible, execute, has_queued_work, locked_state,
                                    setup_session_mode, sync_intake)
from orca_dot_bridge.workflow import draft_pr, task_spec, work_issue


def item(status="할 것", number=25):
    return {"id": "board-item", "status": {"name": status},
            "content": {"id": "issue-id", "state": "OPEN", "number": number,
                        "url": f"https://github.com/acme/repo/issues/{number}",
                        "labels": {"nodes": [], "pageInfo": {"hasNextPage": False}}}}


class SessionSetupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "github-intake.json"
        sample = Path(__file__).resolve().parents[1] / "github-intake.example.json"
        self.config = json.loads(sample.read_text())

    def write(self):
        self.path.write_text(json.dumps(self.config))

    def test_enter_defaults_to_on_demand_for_new_setting(self):
        self.write()
        with patch("orca_dot_bridge.intake.sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=""):
            result = setup_session_mode(self.path)
        self.assertEqual(result["session_mode"], "on-demand")
        self.assertTrue(json.loads(self.path.read_text())["coordinator_auto_close"])

    def test_legacy_missing_auto_close_preserves_persistent_runtime(self):
        self.config.pop("coordinator_auto_close")
        self.write()
        with patch("orca_dot_bridge.intake.sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=""):
            result = setup_session_mode(self.path)
        self.assertEqual(result["session_mode"], "persistent")
        self.assertFalse(json.loads(self.path.read_text())["coordinator_auto_close"])

    def test_persistent_updates_only_session_setting(self):
        self.write()
        result = setup_session_mode(self.path, "persistent")
        self.assertTrue(result["changed"])
        self.config["coordinator_auto_close"] = False
        self.assertEqual(json.loads(self.path.read_text()), self.config)
        self.assertEqual(self.path.stat().st_mode & 0o077, 0)

    def test_enter_keeps_an_existing_persistent_choice(self):
        self.config["coordinator_auto_close"] = False
        self.write()
        with patch("orca_dot_bridge.intake.sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=""):
            result = setup_session_mode(self.path)
        self.assertEqual(result["session_mode"], "persistent")
        self.assertFalse(result["changed"])

    def test_noninteractive_setup_does_not_change_config_without_option(self):
        self.write()
        before = self.path.read_bytes()
        with patch("orca_dot_bridge.intake.sys.stdin.isatty", return_value=False):
            with self.assertRaisesRegex(BridgeError, "session_mode_selection_requires_a_terminal"):
                setup_session_mode(self.path)
        self.assertEqual(self.path.read_bytes(), before)


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.config = {"project_id": "project", "ready_status": "할 것", "received_status": "하는 중",
                       "intake_label": "orca-intake", "issue_allowlist": [25], "batch_enabled": False}
        self.github = Mock()

    def test_incompatible_worker_cli_fails_before_constructing_clients(self):
        args = Mock(doctor=False, apply=True, issue=[25], workers=True)
        config = dict(self.config, worker_mode="read_only", coordinator_auto_close=True)
        with patch("orca_dot_bridge.intake.load", return_value=config), \
                patch("orca_dot_bridge.intake.check", return_value={
                    "compatible": False, "commands": {"orchestration worker-start": {"supported": False}}}) as probe, \
                patch("orca_dot_bridge.intake.GitHub") as github, \
                patch("orca_dot_bridge.intake.Coordinator") as orca:
            with self.assertRaisesRegex(BridgeError, "orca_cli_incompatible:github_intake:orchestration worker-start"):
                execute(args, "config.json")
        commands = probe.call_args.kwargs["commands"]
        self.assertIn("--wait-submit", commands["terminal send"])
        self.assertIn("terminal close", commands)
        self.assertIn("orchestration worker-show", commands)
        self.assertNotIn("orchestration gate-resolve", commands)
        self.assertNotIn("orchestration task-update", commands)
        github.assert_not_called()
        orca.assert_not_called()

    def test_cli_returns_json_for_non_object_orca_response(self):
        config = dict(self.config, orca={"executable": "/usr/local/bin/orca"}, orca_repo_id="test-repo")
        for response in ([], {"ok": True, "result": []}):
            with self.subTest(response=response):
                coordinator = Coordinator(config, runner=Mock(return_value=json.dumps(response)))
                with patch("orca_dot_bridge.intake.load", return_value=config), \
                        patch("orca_dot_bridge.intake.check", return_value={"compatible": True}), \
                        patch("orca_dot_bridge.intake.GitHub"), \
                        patch("orca_dot_bridge.intake.Coordinator", return_value=coordinator), \
                        patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    self.assertEqual(main(["github-intake", "--doctor"]), 2)
                self.assertEqual(json.loads(stdout.getvalue()), {
                    "ok": False, "error": "orca_intake_response_invalid:repo/list"})

    def test_intake_rejects_invalid_state_containers_without_rewriting(self):
        identity = ["test-project"]
        invalid = ([], {"version": 1, "identity": identity, "coordinator": [], "issues": {}})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            for payload in invalid:
                with self.subTest(payload=payload):
                    content = json.dumps(payload)
                    path.write_text(content)
                    path.chmod(0o600)
                    with self.assertRaisesRegex(BridgeError, "intake_state_invalid"):
                        with locked_state(path, identity):
                            self.fail("invalid state was accepted")
                    self.assertEqual(path.read_text(), content)

    def test_canary_is_explicit_and_batch_needs_label(self):
        self.assertTrue(eligible(self.config, self.github, item(), True))
        self.assertFalse(eligible(self.config, self.github, item(), False))
        other = item(number=26)
        other["content"]["labels"]["nodes"] = [{"name": "orca-intake"}]
        self.assertFalse(eligible(self.config, self.github, other, False))
        self.config["batch_enabled"] = True
        self.assertTrue(eligible(self.config, self.github, other, False))
        other["content"]["state"] = "CLOSED"
        self.assertFalse(eligible(self.config, self.github, other, False))
        self.github.issue.assert_not_called()

    def test_private_state_survives_restart_and_excludes_concurrent_tick(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with locked_state(path, ["project"]) as state:
                state.data["issues"]["issue-id"] = {"ack": True}
                state.save()
                with self.assertRaisesRegex(BridgeError, "intake_already_running"):
                    with locked_state(path, ["project"]):
                        self.fail("second lock was granted")
            with locked_state(path, ["project"]) as state:
                self.assertTrue(state.data["issues"]["issue-id"]["ack"])
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            with self.assertRaisesRegex(BridgeError, "intake_state_binding_changed"):
                with locked_state(path, ["other-project"]):
                    self.fail("changed project was accepted")

    def test_ambiguous_comment_is_reconciled_by_existing_marker(self):
        entry = {"comment": True}
        self.github.current.side_effect = [item(), item(), item("하는 중")]
        self.github.find_comment.return_value = "https://github.com/acme/repo/issues/25#issuecomment-1"
        status = sync_intake(self.config, self.github, Mock(), item(), entry)
        self.assertEqual(status, "received")
        self.assertTrue(entry["received"])
        self.github.comment.assert_not_called()
        self.github.move.assert_called_once_with("board-item", "하는 중")

    def test_unknown_comment_without_remote_evidence_does_not_retry(self):
        self.github.current.return_value = item()
        self.github.find_comment.return_value = None
        with self.assertRaisesRegex(BridgeError, "comment_outcome_unknown"):
            sync_intake(self.config, self.github, Mock(), item(), {"comment": True})
        self.github.comment.assert_not_called()
        self.github.move.assert_not_called()

    def test_human_project_status_change_is_preserved(self):
        self.github.current.return_value = item("완료")
        self.github.find_comment.return_value = None
        status = sync_intake(self.config, self.github, Mock(), item(), {})
        self.assertEqual(status, "project_status_changed")
        self.github.comment.assert_not_called()
        self.github.move.assert_not_called()

    def test_ack_is_exact_and_no_input_is_replayed(self):
        coordinator = Coordinator({"orca": {"executable": "/usr/local/bin/orca"}, "orca_repo_id": "repo"})
        coordinator.command = Mock()
        coordinator.read = Mock(side_effect=[
            {"tail": ["› ORCA_INTAKE_ACK followed by a space and the token"]},
            {"tail": ["• ORCA_INTAKE_ACK different"]},
            {"source": "screen", "tail": ["• ORCA_INTAKE_ACK nonce"]},
        ])
        entry = {"send": True, "cursor": 11, "token": "nonce", "send_handle": "old"}
        state = Mock()
        state.data = {"coordinator": {}}
        self.assertFalse(coordinator.intake(state, entry, item()["content"], "restored"))
        self.assertTrue(coordinator.intake(state, entry, item()["content"], "restored"))
        state.save.assert_called_once()
        coordinator.command.assert_not_called()
        self.assertNotIn("--cursor", coordinator.read.call_args_list[1].args)

    def test_queue_checks_latest_board_and_ignores_received_canaries(self):
        state = Mock()
        first, second = item(), item(number=26)
        second["content"]["id"] = "second-issue"
        self.config["issue_allowlist"].append(26)
        state.data = {"issues": {"issue-id": {"received": True}}}
        self.github.items.side_effect = [[first, second], [first, item("하는 중", 26)]]
        self.assertTrue(has_queued_work(self.config, self.github, state, {25, 26}, False))
        self.assertFalse(has_queued_work(self.config, self.github, state, {25, 26}, False))

    def test_queue_checks_batch_candidates_on_targeted_runs(self):
        state = Mock()
        state.data = {"issues": {}}
        production = item(number=27)
        production["content"]["labels"]["nodes"] = [{"name": "orca-intake"}]
        self.github.items.side_effect = [[production], [production]]
        self.assertFalse(has_queued_work(self.config, self.github, state, {25}, False))
        self.config["batch_enabled"] = True
        self.assertTrue(has_queued_work(self.config, self.github, state, {25}, False))

    def test_idle_coordinator_waits_for_queue_then_closes_only_its_terminal(self):
        coordinator = Coordinator({"orca": {"executable": "/usr/local/bin/orca"}, "orca_repo_id": "repo"})
        record = {"launch": True, "run": "run-1", "run_owner": "term-1",
                  "handle": "term-1", "pane": ["tab", "leaf"], "session_epoch": "epoch",
                  "name": "bridge-coordinator", "worktree": "repo::/coordinator", "objective": "bridge"}
        state = Mock()
        state.data = {"coordinator": record, "issues": {"issue-id": {"send": True, "received": True}}}
        coordinator.workspace = Mock(return_value={"id": record["worktree"]})
        coordinator.own_terminal = Mock(return_value={"handle": "term-1"})
        coordinator.ready = Mock(return_value=True)
        coordinator.read = Mock(return_value={"source": "screen"})
        coordinator.terminal_gone = Mock(return_value=True)
        def command(*args):
            if args[1] == "run-show":
                return {"run": {"id": "run-1", "objective": "bridge", "coordinator_handle": "term-1"}}
            if args[1] == "task-list":
                return {"runId": "run-1", "tasks": [{"status": "completed"}]}
            if args == ("terminal", "close", "--terminal", "term-1"):
                return {}
            self.fail("unexpected Orca command")
        coordinator.command = Mock(side_effect=command)
        state.data["issues"]["issue-id"]["worker"] = {"task": "task-1"}
        self.assertEqual(coordinator.close_if_idle(state, Mock()), "pending")
        coordinator.command.assert_not_called()
        state.data["issues"]["issue-id"]["worker"]["completed_url"] = "github-result"
        self.assertEqual(coordinator.close_if_idle(state, lambda: True), "queued")
        self.assertEqual(record["handle"], "term-1")
        self.assertEqual(coordinator.command.call_count, 2)
        self.assertEqual(coordinator.close_if_idle(state, lambda: False), "closed")
        coordinator.command.assert_called_with("terminal", "close", "--terminal", "term-1")
        self.assertEqual(record["run"], "run-1")
        self.assertEqual(record["worktree"], "repo::/coordinator")
        self.assertNotIn("handle", record)


class WorkflowTests(unittest.TestCase):
    def test_worker_prompt_contains_only_the_validated_reference_and_fixed_spec(self):
        issue = dict(item()["content"], body="arbitrary issue command")
        spec = task_spec(issue)
        self.assertIn(issue["url"], spec)
        self.assertNotIn(issue["body"], spec)

    def test_draft_pr_is_opt_in_and_requires_reviewed_remote_sha(self):
        gh, orca, state = Mock(), Mock(), Mock()
        work = {"workspace_name": "bridge-issue-25-token", "task": "task-1"}
        config = {"repository": "acme/repo", "base_ref": "origin/main", "github_login": "reviewer"}
        issue = item()["content"]
        self.assertIsNone(draft_pr(config, gh, orca, state, issue, work))
        gh.api.assert_not_called()
        config["draft_pr_enabled"] = True
        gh.default_branch = "main"
        gh.comments.return_value = [{"body": "orca-approve-draft-pr bridge-issue-25-token oldsha",
                                     "user": {"login": "reviewer"}}]
        orca.workspace.return_value = {"id": "repo::/work", "branch": "bridge-issue-25-token"}
        work["worktree"] = "repo::/work"
        gh.api.side_effect = [[], {"object": {"sha": "different"}}]
        self.assertIsNone(draft_pr(config, gh, orca, state, issue, work))
        self.assertEqual(gh.api.call_count, 2)
        self.assertNotIn("draft_pr", work)

    def test_worker_uses_a_prepared_terminal_in_the_exact_worktree(self):
        gh, orca, state = Mock(), Mock(), Mock()
        state.data = {"coordinator": {"name": "bridge-coordinator-token"}}
        gh.current.return_value = item("하는 중")
        orca.ensure.return_value = ("term-coordinator", "run-1")
        orca.provision_workspace.return_value = "repo::/work"
        orca.provision_terminal.return_value = "term-worker"
        orca.ready.return_value = True
        orca.read.return_value = {"source": "screen", "draft": None}
        orca.repo = "id:repo"
        title = "bridge-issue-25-token"
        def command(*args, **options):
            if args[1] == "task-list":
                return {"runId": "run-1", "tasks": [{"title": title, "id": "task-1", "status": "ready"}]}
            if args[1] == "worker-start":
                return {"dispatchId": "dispatch-1"}
            self.fail("unexpected Orca command")
        orca.command.side_effect = command
        config = {"received_status": "하는 중", "worker_canaries": [25]}
        entry = {"worker": {"workspace_name": title, "task_create": True}}
        self.assertEqual(work_issue(config, gh, orca, state, item(), entry)["status"], "worker_started")
        orca.command.assert_called_with("orchestration", "worker-start", "--task", "task-1", "--run", "run-1",
                                        "--from", "term-coordinator", "--worktree", "id:repo::/work",
                                        "--terminal", "term-worker", "--timeout-ms", "30000", timeout=90)
        self.assertTrue(entry["worker"]["worker_start"])

    def test_reconciles_already_created_draft_pr_instead_of_creating_another(self):
        gh, orca, state = Mock(), Mock(), Mock()
        work = {"workspace_name": "bridge-issue-25-token", "task": "task-1",
                "worktree": "repo::/work", "draft_pr": True}
        config = {"repository": "acme/repo", "base_ref": "origin/main",
                  "github_login": "reviewer", "draft_pr_enabled": True}
        branch = "reviewer/bridge-issue-25-token"
        url = "https://github.com/acme/repo/pull/4"
        gh.default_branch = "main"
        gh.api.return_value = [{"html_url": url, "head": {"ref": branch, "repo": {"full_name": "acme/repo"}},
                                "base": {"ref": "main"}}]
        gh.find_comment.return_value = "https://github.com/acme/repo/issues/25#issuecomment-1"
        orca.workspace.return_value = {"id": "repo::/work", "branch": "refs/heads/" + branch}
        self.assertEqual(draft_pr(config, gh, orca, state, item()["content"], work), url)
        gh.api.assert_called_once()
        gh.comment.assert_not_called()


if __name__ == "__main__":
    unittest.main()
