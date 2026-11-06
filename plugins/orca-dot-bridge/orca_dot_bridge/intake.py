"""GitHub Projects intake, isolated from the legacy Slack/manager binding."""
import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from .core import BridgeError, orca_executable, run, strict_json

SESSION_MODES = {"on-demand": True, "persistent": False}


def configure(parser):
    parser.add_argument("--issue", type=positive, action="append",
                        help="Process this existing board issue. Repeat to select a queue.")
    parser.add_argument("--apply", action="store_true", help="Allow coordinator and GitHub writes")
    parser.add_argument("--workers", action="store_true", help="Also run or reconcile approved worker tasks")
    parser.add_argument("--doctor", action="store_true", help="Check GitHub and Orca read access")


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("expected a positive issue number")
    return number


def load(path):
    c = strict_json(Path(path).read_text())
    required = {
        "repository": r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+",
        "project_id": r"PVT_[A-Za-z0-9_-]+",
        "orca_repo_id": r"[A-Za-z0-9-]+",
        "github_login": r"[A-Za-z0-9-]+",
        "base_ref": r"origin/[A-Za-z0-9._/-]+",
    }
    if c["schema_version"] != 1 or not all(re.fullmatch(p, c[k]) for k, p in required.items()):
        raise BridgeError("invalid_intake_config")
    if not Path(c["state_file"]).is_absolute():
        raise BridgeError("intake_state_path_must_be_absolute")
    if c["orca"]["executable"] != "auto" and not Path(c["orca"]["executable"]).is_absolute():
        raise BridgeError("intake_orca_executable_must_be_auto_or_absolute")
    if c["coordinator_agent"] not in ("codex", "claude"):
        raise BridgeError("unsupported_coordinator_agent")
    for key in ("ready_status", "received_status", "intake_label"):
        if not isinstance(c[key], str) or not c[key].strip():
            raise BridgeError("invalid_intake_config:" + key)
    if c["ready_status"] == c["received_status"]:
        raise BridgeError("intake_statuses_must_differ")
    if type(c["batch_enabled"]) is not bool:
        raise BridgeError("batch_enabled_must_be_boolean")
    allowed = c["issue_allowlist"]
    if not isinstance(allowed, list) or any(type(n) is not int or n < 1 for n in allowed):
        raise BridgeError("invalid_issue_allowlist")
    if c.get("worker_mode", "off") not in ("off", "read_only"):
        raise BridgeError("unsupported_worker_mode")
    canaries = c.get("worker_canaries", [])
    if not isinstance(canaries, list) or any(type(n) is not int or n not in allowed for n in canaries):
        raise BridgeError("worker_canaries_must_be_in_issue_allowlist")
    if type(c.get("draft_pr_enabled", False)) is not bool:
        raise BridgeError("draft_pr_enabled_must_be_boolean")
    if type(c.get("coordinator_auto_close", False)) is not bool:
        raise BridgeError("coordinator_auto_close_must_be_boolean")
    return c


def write_private_json(path, data):
    fd, temp = tempfile.mkstemp(prefix=".intake-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def setup_session_mode(config_path, mode=None):
    path = Path(config_path)
    if not path.is_file():
        raise BridgeError("github_intake_config_missing:copy_github-intake.example.json_first")
    path = path.resolve(strict=True)
    config = load(path)
    if mode is None:
        if not sys.stdin.isatty():
            raise BridgeError("session_mode_selection_requires_a_terminal_or_--session-mode")
        default = "1" if config.get("coordinator_auto_close", True) else "2"
        prompt = (
            "관리자 세션 방식\n"
            "  1. 필요할 때 열기 — 대기열이 비고 GitHub 반영이 끝나면 닫기\n"
            "  2. 같은 세션 유지 — 대기열이 비어도 현재 세션을 계속 열어두기\n"
            f"선택 [기본값 {default}] "
        )
        try:
            while True:
                choice = input(prompt).strip() or default
                if choice in ("1", "2"):
                    break
                print("1 또는 2를 입력하세요.", file=sys.stderr)
        except (EOFError, KeyboardInterrupt):
            raise BridgeError("session_mode_selection_cancelled") from None
        mode = "on-demand" if choice == "1" else "persistent"
        # Preserve any other settings changed while the prompt was open.
        config = load(path)
    auto_close = SESSION_MODES[mode]
    changed = config.get("coordinator_auto_close") is not auto_close
    if changed:
        config["coordinator_auto_close"] = auto_close
        write_private_json(path, config)
    return {"ok": True, "session_mode": mode, "coordinator_auto_close": auto_close, "changed": changed}


class State:
    def __init__(self, path, identity):
        self.path = path
        if path.is_symlink():
            raise BridgeError("intake_state_must_not_be_a_symlink")
        if path.exists():
            if not path.is_file() or path.stat().st_mode & 0o077:
                raise BridgeError("intake_state_permissions_must_be_private")
            self.data = strict_json(path.read_text())
            if self.data["version"] != 1 or self.data["identity"] != identity:
                raise BridgeError("intake_state_binding_changed")
        else:
            self.data = {"version": 1, "identity": identity, "coordinator": {}, "issues": {}}

    def save(self):
        write_private_json(self.path, self.data)


@contextmanager
def locked_state(path, identity):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BridgeError("intake_already_running") from None
        yield State(path, identity)


ISSUE_FIELDS = """
  __typename
  ... on Issue {
    id number url state repository { nameWithOwner }
    labels(first: 50) { nodes { name } pageInfo { hasNextPage } }
  }
"""
ITEM_FIELDS = """
  id isArchived
  project { id }
  status: fieldValueByName(name: "Status") {
    ... on ProjectV2ItemFieldSingleSelectValue { name }
  }
  content { %s }
""" % ISSUE_FIELDS


class GitHub:
    def __init__(self, c, runner=run):
        self.c, self.runner = c, runner

    def api(self, args):
        return strict_json(self.runner(["gh", "api", "--hostname", "github.com", *args], timeout=60))

    def graph(self, query, **variables):
        args = ["graphql", "-f", "query=" + query]
        for key, value in variables.items():
            args.extend(["-f", f"{key}={value}"])
        return self.api(args)["data"]

    def identity(self):
        login = self.api(["user"])["login"]
        if login.casefold() != self.c["github_login"].casefold():
            raise BridgeError("github_login_does_not_match_intake_config")
        repo = self.api(["repos/" + self.c["repository"]])
        if repo["full_name"].casefold() != self.c["repository"].casefold():
            raise BridgeError("github_repository_does_not_match_intake_config")
        if not repo["has_issues"]:
            raise BridgeError("github_issues_disabled")
        self.default_branch = repo["default_branch"]
        return login

    def board(self):
        board = self.graph("""
          query($id: ID!) { node(id: $id) { ... on ProjectV2 {
            id url closed viewerCanUpdate
            field(name: "Status") { ... on ProjectV2SingleSelectField { id options { id name } } }
          } } }
        """, id=self.c["project_id"])["node"]
        if not board or board.get("id") != self.c["project_id"] or board["closed"]:
            raise BridgeError("github_project_inaccessible_or_closed")
        options = {o["name"]: o["id"] for o in board["field"]["options"]}
        for key in ("ready_status", "received_status"):
            if self.c[key] not in options:
                raise BridgeError("github_project_status_missing:" + key)
        self.board_data, self.options = board, options
        return board

    def items(self):
        query = """
          query($id: ID!, $endCursor: String) { node(id: $id) { ... on ProjectV2 {
            items(first: 100, after: $endCursor) {
              nodes { %s }
              pageInfo { hasNextPage endCursor }
            }
          } } }
        """ % ITEM_FIELDS
        args = ["graphql", "--paginate", "--slurp", "-f", "query=" + query,
                "-f", "id=" + self.c["project_id"]]
        for page in self.api(args):
            for item in page["data"]["node"]["items"]["nodes"]:
                issue = item["content"]
                if (not item["isArchived"] and issue and issue["__typename"] == "Issue"
                        and issue["repository"]["nameWithOwner"].casefold()
                        == self.c["repository"].casefold()):
                    expected = f"https://github.com/{self.c['repository']}/issues/{issue['number']}"
                    if issue["url"].casefold() != expected.casefold():
                        raise BridgeError("unexpected_github_issue_url")
                    yield item

    def current(self, item_id, issue_id):
        item = self.graph("query($id: ID!) { node(id: $id) { ... on ProjectV2Item {"
                          + ITEM_FIELDS + "} } }", id=item_id)["node"]
        if (not item or item["isArchived"] or item["project"]["id"] != self.c["project_id"]
                or not item["content"] or item["content"]["id"] != issue_id):
            raise BridgeError("github_issue_removed_from_configured_project")
        return item

    def issue(self, number):
        return self.api([self.issue_endpoint(number)])

    def issue_endpoint(self, number):
        return f"repos/{self.c['repository']}/issues/{number}"

    def find_comment(self, number, marker):
        matches = [row["html_url"] for row in self.comments(number)
                   if row["user"]["login"].casefold() == self.c["github_login"].casefold()
                   and marker in row["body"].splitlines()]
        if len(matches) > 1:
            raise BridgeError("duplicate_github_comment_marker")
        return next(iter(matches), None)

    def comments(self, number):
        pages = self.api(["--paginate", "--slurp", self.issue_endpoint(number) + "/comments"])
        return (row for page in pages for row in page)

    def comment(self, number, body):
        return self.api(["--method", "POST", self.issue_endpoint(number) + "/comments",
                         "-f", "body=" + body])["html_url"]

    def move(self, item_id, status):
        query = """
          mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
            updateProjectV2ItemFieldValue(input: {projectId: $project, itemId: $item,
              fieldId: $field, value: {singleSelectOptionId: $option}}) {
              projectV2Item { id }
            }
          }
        """
        result = self.graph(query, project=self.c["project_id"], item=item_id,
                            field=self.board_data["field"]["id"], option=self.options[status])
        if result["updateProjectV2ItemFieldValue"]["projectV2Item"]["id"] != item_id:
            raise BridgeError("github_project_update_unverified")


def status_of(item):
    return (item["status"] or {}).get("name")


def begin(state, row, operation):
    if row.get(operation):
        raise BridgeError(operation + "_outcome_unknown:reconcile_before_retry")
    row[operation] = True
    state.save()


class Coordinator:
    def __init__(self, c, runner=run):
        self.c, self.runner = c, runner
        self.exe = orca_executable(c)
        self.repo = "id:" + c["orca_repo_id"]

    def command(self, *args, timeout=45):
        try:
            response = strict_json(self.runner([self.exe, *args, "--json"], timeout=timeout))
        except BridgeError as error:
            raise BridgeError("orca_intake_command_failed:" + "/".join(args[:2]) + ":" + str(error)) from None
        if response.get("ok") is not True:
            raise BridgeError("orca_intake_command_failed:" + "/".join(args[:2]))
        return response["result"]

    def verify_repo(self):
        rows = self.command("repo", "list")["repos"]
        match = [r for r in rows if r["id"] == self.c["orca_repo_id"]]
        expected = "github.com/" + self.c["repository"].casefold()
        if (len(match) != 1 or match[0]["kind"] != "git"
                or (match[0].get("gitRemoteIdentity") or {}).get("canonicalKey", "").casefold() != expected):
            raise BridgeError("orca_repo_does_not_match_github_repository")

    def workspace(self, name):
        result = self.command("worktree", "list", "--repo", self.repo, "--limit", "10000")
        if result.get("truncated"):
            raise BridgeError("orca_worktree_list_truncated")
        matches = [w for w in result["worktrees"] if w["displayName"] == name
                   and w["id"].startswith(self.c["orca_repo_id"] + "::")]
        if len(matches) > 1:
            raise BridgeError("ambiguous_coordinator_worktree")
        return next(iter(matches), None)

    def terminal_inventory(self, worktree):
        return self.command("terminal", "list", "--worktree", "id:" + worktree)

    def terminals(self, worktree):
        return self.terminal_inventory(worktree)["terminals"]

    def show(self, handle):
        return self.command("terminal", "show", "--terminal", handle)["terminal"]

    def own_terminal(self, worktree, record):
        rows = self.terminals(worktree)
        candidates = []
        for row in rows:
            if row["handle"] in record.get("terminals_before_launch", []):
                continue
            if record.get("handle") and row["handle"] != record["handle"] and not record.get("pane"):
                continue
            t = self.show(row["handle"])
            if record.get("pane") and [t.get("tabId"), t.get("leafId")] != record["pane"]:
                continue
            if (t.get("connected") is True and t.get("agentIdentity") == self.c["coordinator_agent"]
                    and t.get("worktreePath") == worktree.split("::", 1)[1]):
                candidates.append(t)
        if len(candidates) > 1:
            raise BridgeError("ambiguous_coordinator_terminal")
        return next(iter(candidates), None)

    def provision_workspace(self, state, record, name, reference=None):
        existing = self.workspace(name)
        if record.get("worktree"):
            if not existing or existing["id"] != record["worktree"]:
                raise BridgeError("recorded_bridge_worktree_missing")
            return record["worktree"]
        if not existing:
            begin(state, record, "worktree_create")
            extra = ["--reference", reference] if reference else []
            self.command("worktree", "create", "--repo", self.repo, "--name", name, "--no-parent",
                         "--base-branch", self.c["base_ref"], "--setup", "skip", *extra, timeout=90)
            existing = self.workspace(name)
        if not record.get("worktree_create") or not existing:
            raise BridgeError("bridge_worktree_unverified")
        record["worktree"] = existing["id"]
        state.save()
        return record["worktree"]

    def terminal_gone(self, worktree, record):
        if not record.get("handle") or not record.get("pane"):
            return False
        inventory = self.terminal_inventory(worktree)
        scope = inventory.get("hostScope") or {}
        if inventory.get("truncated") is not False or record.get("host", "local") not in scope.get("hostIds", []):
            return False
        for row in inventory["terminals"]:
            if row["handle"] == record["handle"] or [row.get("tabId"), row.get("leafId")] == record["pane"]:
                return False
            # A reconnected agent may have a new runtime handle or placeholder
            # pane fields in list; show provides its actual pane identity.
            if row["handle"] not in record.get("terminals_before_launch", []):
                terminal = self.show(row["handle"])
                if ([terminal.get("tabId"), terminal.get("leafId")] == record["pane"]
                        or terminal.get("agentIdentity") == self.c["coordinator_agent"]):
                    return False
        return True

    @staticmethod
    def clear_terminal(state, record):
        for key in ("launch", "handle", "pane", "host", "terminals_before_launch", "session_epoch"):
            record.pop(key, None)
        state.save()

    def provision_terminal(self, state, record, worktree, prompt, reopen=False):
        terminal = self.own_terminal(worktree, record) if record.get("launch") else None
        if reopen and record.get("launch") and not terminal and self.terminal_gone(worktree, record):
            self.clear_terminal(state, record)
        if not record.get("launch"):
            record["terminals_before_launch"] = [t["handle"] for t in self.terminals(worktree)]
            record["session_epoch"] = uuid.uuid4().hex
            begin(state, record, "launch")
            launched = self.command("agent", "launch", "--agent", self.c["coordinator_agent"],
                                    "--worktree", "id:" + worktree, "--surface", "terminal",
                                    "--prompt", prompt, timeout=60)
            outcome = (launched.get("launch") or launched).get("outcome") or {}
            if outcome.get("handle"):
                record["handle"] = outcome["handle"]
                state.save()
            terminal = self.own_terminal(worktree, record)
        if not terminal:
            raise BridgeError("bridge_terminal_unavailable:restore_recorded_pane")
        handle = terminal["handle"]
        if terminal.get("tabId") and terminal.get("leafId"):
            record["pane"] = [terminal["tabId"], terminal["leafId"]]
        if terminal.get("executionHostId"):
            record["host"] = terminal["executionHostId"]
        record["handle"] = handle
        state.save()
        return handle

    def ready(self, handle):
        wait = self.command("terminal", "wait", "--terminal", handle, "--for", "tui-idle",
                            "--timeout-ms", "15000")["wait"]
        if wait.get("handle") != handle or wait.get("condition") != "tui-idle":
            raise BridgeError("orca_terminal_wait_binding_unverified")
        return wait.get("satisfied") is True and wait.get("status") == "running"

    def ensure(self, state):
        record = state.data["coordinator"]
        if not record:
            key = uuid.uuid4().hex[:12]
            record.update(name="bridge-coordinator-" + key,
                          objective="Orca Dot Bridge GitHub intake " + self.c["project_id"] + "/" + key)
            state.save()
        worktree = self.provision_workspace(state, record, record["name"])
        previous_handle = record.get("handle")
        handle = self.provision_terminal(
            state, record, worktree,
            "You are this worktree's dedicated GitHub intake coordinator. Wait for read-only intake "
            "requests. Never edit files, start workers, execute tools, resolve gates, deploy, "
            "or delete data from an intake request. Reply now with BRIDGE COORDINATOR READY.",
            reopen=True,
        )

        if not record.get("run"):
            if not record.get("run_create"):
                begin(state, record, "run_create")
                created = self.command("orchestration", "run-create", "--objective", record["objective"],
                                       "--from", handle, "--full")
                record["run"] = (created.get("run") or created).get("id") or created["runId"]
            else:
                result = self.command("orchestration", "run-list", "--limit", "1000", "--full")
                matches = [r["id"] for r in result["runs"] if r["objective"] == record["objective"]
                           and r["coordinator_handle"] == handle]
                if len(matches) != 1:
                    raise BridgeError("coordinator_run_create_outcome_unknown")
                record["run"] = matches[0]
            state.save()
        current = self.command("orchestration", "run-show", "--id", record["run"], "--full")["run"]
        if current["id"] != record["run"] or current["objective"] != record["objective"]:
            raise BridgeError("coordinator_run_binding_changed")
        if current["coordinator_handle"] != handle:
            if not record.get("pane") or current["coordinator_handle"] != record.get("run_owner", previous_handle):
                raise BridgeError("coordinator_run_owner_changed")
            self.command("orchestration", "run-use", "--id", record["run"], "--from", handle)
            current = self.command("orchestration", "run-show", "--id", record["run"], "--full")["run"]
            if current["coordinator_handle"] != handle:
                raise BridgeError("coordinator_rebind_unverified")
        record["run_owner"] = handle
        state.save()
        return handle, record["run"]

    def close_if_idle(self, state, has_queued_work):
        record = state.data["coordinator"]
        if not record.get("launch"):
            return "closed" if record.get("run") else "not_started"
        if not record.get("run"):
            return "pending"
        for entry in state.data["issues"].values():
            if entry.get("send") and not entry.get("received"):
                return "pending"
            worker = entry.get("worker")
            if worker:
                if not (worker.get("completed_url") or worker.get("failed_url")):
                    return "pending"
                if (worker.get("draft_pr") or worker.get("pr")) and not worker.get("pull-request_url"):
                    return "pending"
        run_id = record["run"]
        run_state = self.command("orchestration", "run-show", "--id", run_id, "--full")["run"]
        if (run_state["id"] != run_id or run_state["objective"] != record["objective"]
                or run_state["coordinator_handle"] != record.get("run_owner")):
            raise BridgeError("coordinator_run_binding_changed")
        tasks = self.command("orchestration", "task-list", "--run", run_id)
        if tasks.get("runId") != run_id or tasks.get("nextCursor") or tasks.get("truncated"):
            raise BridgeError("coordinator_run_tasks_unverified")
        if any(t["status"] not in ("completed", "failed") for t in tasks["tasks"]):
            return "pending"
        tree = record["worktree"]
        existing = self.workspace(record["name"])
        if not existing or existing["id"] != tree:
            raise BridgeError("recorded_bridge_worktree_missing")
        terminal = self.own_terminal(tree, record)
        if terminal:
            handle = terminal["handle"]
            if handle != run_state["coordinator_handle"] or not self.ready(handle):
                return "pending"
            screen = self.read(handle, "--screen")
            if screen.get("source") != "screen" or screen.get("draft"):
                return "pending"
            if has_queued_work():
                return "queued"
            self.command("terminal", "close", "--terminal", handle)
        if not self.terminal_gone(tree, record):
            return "pending"
        self.clear_terminal(state, record)
        return "closed"

    def read(self, handle, *args):
        return self.command("terminal", "read", "--terminal", handle, *args)["terminal"]

    def intake(self, state, entry, issue, handle):
        if entry.get("ack"):
            return True
        epoch = state.data["coordinator"].get("session_epoch")
        if entry.get("send") and entry.get("send_epoch") != epoch:
            # The prior pane was proven gone. Only this read-only prompt can
            # be reissued; GitHub and task receipts remain unchanged.
            entry.pop("send")
            state.save()
        if not entry.get("send"):
            if not self.ready(handle):
                return False
            screen = self.read(handle, "--screen")
            if screen.get("source") != "screen" or screen.get("draft"):
                raise BridgeError("coordinator_screen_unavailable_or_has_draft")
            tail = self.read(handle, "--limit", "1000")
            cursor = tail.get("latestCursor", tail.get("nextCursor"))
            if cursor is None:
                raise BridgeError("coordinator_output_cursor_missing")
            entry["cursor"] = cursor
            entry["send_handle"] = handle
            entry["send_epoch"] = epoch
            entry["token"] = uuid.uuid4().hex
            begin(state, entry, "send")
            prompt = (
                "Read-only GitHub intake. Acknowledge this issue reference without running tools. "
                "Do not edit files, start a task or worker, deploy, delete data or resolve a gate. "
                "Reply with one line consisting of ORCA_INTAKE_ACK followed by a space and the token.\n"
                f"Issue URL: {issue['url']}\nToken: {entry['token']}"
            )
            self.command("terminal", "send", "--terminal", handle, "--text", prompt,
                         "--enter", "--wait-submit", "10")
        expected = "ORCA_INTAKE_ACK " + entry["token"]
        screen = self.read(handle, "--screen")
        lines = screen["tail"] if screen.get("source") == "screen" else []
        if not has_ack(lines, expected):
            cursor = ["--cursor", str(entry["cursor"])] if entry.get("send_handle", handle) == handle else []
            tail = self.read(handle, *cursor, "--limit", "1000")
            if not has_ack(tail["tail"], expected):
                return False
        entry["ack"] = True
        state.save()
        return True


def has_ack(lines, expected):
    return any(line.strip().lstrip("•●›> ").strip("` ") == expected for line in lines)


def eligible(c, gh, item, explicit):
    issue = item["content"]
    if issue["state"] != "OPEN" or status_of(item) != c["ready_status"]:
        return False
    if issue["number"] in c["issue_allowlist"]:
        return explicit
    if not c["batch_enabled"]:
        return False
    labels = issue["labels"]
    if c["intake_label"] in {label["name"] for label in labels["nodes"]}:
        return True
    if labels["pageInfo"]["hasNextPage"]:
        return c["intake_label"] in {label["name"] for label in gh.issue(issue["number"])["labels"]}
    return False


def has_queued_work(c, gh, state, requested, workers):
    # Query the board again after the current tick's writes and just before
    # closing. Check the production queue even on a targeted CLI run.
    records = state.data["issues"]
    for item in gh.items():
        issue = item["content"]
        number = issue["number"]
        entry = records.get(issue["id"], {})
        if not entry.get("received"):
            if eligible(c, gh, item, number in requested):
                return True
        elif (workers and number in c.get("worker_canaries", [])
              and (not requested or number in requested) and not entry.get("worker")
              and issue["state"] == "OPEN" and status_of(item) == c["received_status"]):
            return True
    return False


def sync_intake(c, gh, state, item, entry):
    issue = item["content"]
    current = gh.current(item["id"], issue["id"])
    if current["content"]["state"] != "OPEN":
        return "issue_closed"
    if not entry.get("comment_url"):
        digest = hashlib.sha256((c["project_id"] + ":" + issue["id"]).encode()).hexdigest()[:24]
        marker = f"<!-- orca-dot-bridge:intake:{digest} -->"
        comment_url = gh.find_comment(issue["number"], marker)
        if not comment_url:
            if status_of(current) != c["ready_status"]:
                return "project_status_changed"
            begin(state, entry, "comment")
            comment_url = gh.comment(issue["number"], marker + "\n"
                                     "Orca Coordinator가 이 이슈를 읽기 전용으로 접수했습니다. "
                                     "구현 작업은 별도 승인 절차를 따릅니다.")
        entry["comment_url"] = comment_url
        state.save()
    current = gh.current(item["id"], issue["id"])
    if current["content"]["state"] != "OPEN":
        return "issue_closed"
    current_status = status_of(current)
    if current_status == c["ready_status"]:
        begin(state, entry, "move")
        gh.move(item["id"], c["received_status"])
        current = gh.current(item["id"], issue["id"])
        current_status = status_of(current)
    if current_status != c["received_status"]:
        return "project_status_changed"
    entry["received"] = True
    state.save()
    return "received"


def execute(args, config_path):
    c = load(config_path)
    if args.doctor and (args.apply or args.issue or args.workers):
        raise BridgeError("intake_doctor_is_read_only")
    if args.workers and c.get("worker_mode", "off") == "off":
        raise BridgeError("intake_workers_disabled")
    if args.apply and not args.issue and not c["batch_enabled"]:
        raise BridgeError("intake_batch_disabled")
    gh, orca = GitHub(c), Coordinator(c)
    login = gh.identity()
    board = gh.board()
    orca.verify_repo()
    if args.doctor:
        return {"ok": True, "github_login": login, "project": board["url"],
                "project_can_update": board["viewerCanUpdate"], "orca_repo": orca.repo}
    if args.apply and not board["viewerCanUpdate"]:
        raise BridgeError("github_project_write_access_required")
    requested = {number: index for index, number in enumerate(args.issue or [])}
    items = [item for item in gh.items() if not requested or item["content"]["number"] in requested]
    if requested and (len(items) != len(requested)
                      or {i["content"]["number"] for i in items} != set(requested)):
        raise BridgeError("issue_not_found_or_ambiguous_on_configured_board")
    if not args.apply:
        report = {"ok": True, "dry_run": True, "candidates": [i["content"]["url"] for i in items
                  if eligible(c, gh, i, i["content"]["number"] in requested)]}
        return report
    identity = [c[k] for k in ("project_id", "repository", "orca_repo_id", "coordinator_agent",
                              "base_ref", "github_login")]
    with locked_state(c["state_file"], identity) as state:
        report = apply_intake(args, c, gh, orca, state, items, requested)
        if c.get("coordinator_auto_close"):
            report["coordinator_session"] = orca.close_if_idle(
                state, lambda: has_queued_work(c, gh, state, requested, args.workers))
        return report


def apply_intake(args, c, gh, orca, state, items, requested):
    records = state.data["issues"]
    # Reconcile existing work first, retaining the caller's issue order.
    items.sort(key=lambda i: (i["content"]["id"] not in records, requested.get(i["content"]["number"], 0)))
    existing_report = None
    for item in items:
        issue = item["content"]
        explicit = issue["number"] in requested
        entry = records.get(issue["id"])
        if entry and entry["item"] != item["id"]:
            raise BridgeError("github_project_item_binding_changed")
        if not entry:
            if not eligible(c, gh, item, explicit):
                continue
            entry = records[issue["id"]] = {"item": item["id"], "issue": issue["number"]}
            state.save()
        if entry.get("received"):
            report = {"ok": True, "status": "already_received", "issue": issue["url"],
                      "comment": entry["comment_url"], "run": state.data["coordinator"]["run"]}
            if args.workers:
                from .workflow import work_issue
                report.update(work_issue(c, gh, orca, state, item, entry))
                if report["status"] in ("awaiting_worker_terminal", "worker_started",
                                         "worker_synced", "draft_pr_synced"):
                    return report
            if len(requested) == 1:
                return report
            if explicit and existing_report is None:
                existing_report = report
            continue
        current = gh.current(item["id"], issue["id"])
        if current["content"]["state"] != "OPEN":
            continue
        if not entry.get("ack"):
            if status_of(current) != c["ready_status"]:
                continue
            if not entry.get("send") and not eligible(c, gh, current, explicit):
                continue
            handle, run_id = orca.ensure(state)
            if not orca.intake(state, entry, issue, handle):
                return {"ok": True, "status": "awaiting_coordinator_ack",
                        "issue": issue["url"], "run": run_id}
        result = sync_intake(c, gh, state, item, entry)
        report = {"ok": True, "status": result, "issue": issue["url"],
                  "comment": entry.get("comment_url"), "run": state.data["coordinator"]["run"]}
        if result == "received" and args.workers and issue["number"] in c.get("worker_canaries", []):
            from .workflow import work_issue
            report.update(work_issue(c, gh, orca, state, item, entry))
            report["intake_status"] = result
        return report
    return existing_report or {"ok": True, "status": "no_eligible_issue"}
