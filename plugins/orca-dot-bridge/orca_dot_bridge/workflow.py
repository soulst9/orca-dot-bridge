"""Opt-in worker orchestration and draft PR reconciliation for received issues."""
import re
from urllib.parse import quote

from .core import BridgeError
from .intake import begin, status_of


def task_spec(issue):
    return (
        f"Read-only smoke test for GitHub issue {issue['url']}. "
        "Run git rev-parse --is-inside-work-tree in your assigned workspace. "
        "Report whether it returned true using Orca's worker_done protocol. "
        "Do not fetch issue text, change files, push, deploy, delete data, or modify a Gate."
    )


def exact_task(orca, run_id, handle, title):
    result = orca.command("orchestration", "task-list", "--run", run_id, "--from", handle)
    if result.get("runId") != run_id:
        raise BridgeError("worker_task_run_unverified")
    matches = [task for task in result["tasks"] if task["title"] == title]
    if len(matches) > 1:
        raise BridgeError("ambiguous_github_issue_task")
    return next(iter(matches), None)


def dispatch_for(orca, task_id, handle):
    result = orca.command("orchestration", "dispatch-show", "--task", task_id, "--from", handle, "--full")
    return result.get("dispatch") or None


def synced_comment(gh, state, work, key, issue, message):
    marker = f"<!-- orca-dot-bridge:{key}:{work['task']} -->"
    if not work.get(key + "_url"):
        url = gh.find_comment(issue["number"], marker)
        if not url:
            begin(state, work, key + "_comment")
            url = gh.comment(issue["number"], marker + "\n" + message)
        work[key + "_url"] = url
        state.save()
    return work[key + "_url"]


def draft_pr(c, gh, orca, state, issue, work):
    if not c.get("draft_pr_enabled"):
        return None
    workspace = orca.workspace(work["workspace_name"])
    if (not workspace or workspace["id"] != work["worktree"]
            or workspace.get("isMain") or workspace.get("isPrimary")):
        raise BridgeError("worker_workspace_missing_or_primary")
    branch = workspace["branch"].removeprefix("refs/heads/")
    base = c["base_ref"].removeprefix("origin/")
    if (base != gh.default_branch or branch == base
            or not re.fullmatch(r"[A-Za-z0-9._/-]+", branch)
            or not branch.endswith("/" + work["workspace_name"]) and branch != work["workspace_name"]):
        raise BridgeError("worker_pr_branch_not_verified")
    endpoint = "repos/" + c["repository"]
    owner = c["repository"].split("/")[0]
    pulls = gh.api(["--method", "GET", endpoint + "/pulls", "-f", "state=all",
                    "-f", "head=" + owner + ":" + branch, "-f", "base=" + base])
    candidates = [pr for pr in pulls
                  if (pr["head"].get("repo") or {}).get("full_name", "").casefold() == c["repository"].casefold()
                  and pr["head"]["ref"] == branch and pr["base"]["ref"] == base]
    if len(candidates) > 1:
        raise BridgeError("ambiguous_worker_pull_request")
    if candidates:
        pr = candidates[0]
    else:
        # An operator pushes the reviewed branch. This bridge never pushes,
        # and an approval bound to the remote commit is required to open a PR.
        line = "orca-approve-draft-pr " + branch
        approval_lines = [row["body"].strip() for row in gh.comments(issue["number"])
                          if row["user"]["login"].casefold() == c["github_login"].casefold()
                          and row["body"].strip().startswith(line + " ")]
        if not approval_lines:
            return None
        ref = gh.api([endpoint + "/git/ref/heads/" + quote(branch, safe="/")])
        sha = ref["object"]["sha"]
        if not re.fullmatch(r"[a-f0-9]{40}", sha) or line + " " + sha not in approval_lines:
            return None
        begin(state, work, "draft_pr")
        pr = gh.api(["--method", "POST", endpoint + "/pulls",
                     "-f", "title=Orca implementation for #" + str(issue["number"]),
                     "-f", "head=" + branch, "-f", "base=" + base, "-F", "draft=true",
                     "-f", "body=Refs #" + str(issue["number"])])
        if pr["head"]["sha"] != sha or pr["draft"] is not True:
            raise BridgeError("draft_pull_request_head_or_state_changed")
    if work.get("pr") and work["pr"] != pr["html_url"]:
        raise BridgeError("worker_pull_request_binding_changed")
    work["pr"] = pr["html_url"]
    state.save()
    synced_comment(gh, state, work, "pull-request", issue, "Orca 작업 PR · " + work["pr"])
    return work["pr"]


def work_issue(c, gh, orca, state, item, entry):
    issue = item["content"]
    current = gh.current(item["id"], issue["id"])
    if current["content"]["state"] != "OPEN" or status_of(current) != c["received_status"]:
        return {"status": "worker_project_status_changed"}
    if issue["number"] not in c.get("worker_canaries", []):
        return {"status": "worker_not_approved"}
    work = entry.get("worker")
    if not work:
        coordinator_key = state.data["coordinator"]["name"].split("-")[-1]
        name = f"bridge-issue-{issue['number']}-{coordinator_key}"
        work = entry["worker"] = {"workspace_name": name}
        state.save()
    # Durable terminal outcomes can be re-read without waking the coordinator
    # or depending on a test workspace that the user has since removed.
    if work.get("completed_url"):
        had_pr = bool(work.get("pull-request_url"))
        pr = draft_pr(c, gh, orca, state, issue, work)
        if pr:
            return {"status": "draft_pr_linked" if had_pr else "draft_pr_synced", "pr": pr}
        return {"status": "worker_completed", "task": work["task"],
                "dispatch": work["dispatch"], "worker_status": "completed"}
    if work.get("failed_url"):
        return {"status": "worker_failed", "task": work["task"],
                "dispatch": work["dispatch"], "worker_status": "failed"}
    handle, run_id = orca.ensure(state)
    title = work["workspace_name"]
    task = exact_task(orca, run_id, handle, title)
    if not task:
        if work.get("task"):
            raise BridgeError("recorded_worker_task_missing")
        spec = task_spec(issue)
        begin(state, work, "task_create")
        orca.command("orchestration", "task-create", "--run", run_id, "--from", handle,
                     "--task-title", title, "--spec", spec)
        task = exact_task(orca, run_id, handle, title)
        if not task:
            raise BridgeError("worker_task_create_unverified")
    if not work.get("task_create") or work.get("task", task["id"]) != task["id"]:
        raise BridgeError("worker_task_binding_changed")
    work["task"] = task["id"]
    state.save()
    if not work.get("worker_start"):
        tree = orca.provision_workspace(state, work, title, reference=issue["url"])
        terminal = orca.provision_terminal(
            state, work, tree,
            "You are a dedicated read-only smoke-test Worker. Wait for your Orca Task and make no changes.",
        )
        if not orca.ready(terminal):
            return {"status": "awaiting_worker_terminal", "task": task["id"]}
        screen = orca.read(terminal, "--screen")
        if screen.get("source") != "screen" or screen.get("draft"):
            raise BridgeError("worker_screen_unavailable_or_has_draft")
        begin(state, work, "worker_start")
        orca.command("orchestration", "worker-start", "--task", task["id"], "--run", run_id,
                     "--from", handle, "--worktree", "id:" + tree, "--terminal", terminal,
                     "--timeout-ms", "30000", timeout=90)
        return {"status": "worker_started", "task": task["id"]}
    dispatch = dispatch_for(orca, task["id"], handle)
    if not dispatch:
        raise BridgeError("worker_start_outcome_unknown:inspect_orca_before_retry")
    dispatch_id = dispatch["id"]
    if dispatch["run_id"] != run_id or dispatch["task_id"] != task["id"]:
        raise BridgeError("worker_dispatch_binding_changed")
    if work.get("dispatch", dispatch_id) != dispatch_id:
        raise BridgeError("worker_dispatch_changed")
    work["dispatch"] = dispatch_id
    receipt = orca.command("orchestration", "worker-show", "--dispatch", dispatch_id, "--full")["worker"]
    workspace = orca.workspace(title)
    if (not workspace or receipt["worktreeId"] != workspace["id"]
            or work.get("worktree", workspace["id"]) != workspace["id"]):
        raise BridgeError("worker_worktree_binding_changed")
    work["worktree"] = workspace["id"]
    state.save()
    if task["status"] not in ("completed", "failed", "blocked"):
        return {"status": "worker_running", "task": task["id"], "dispatch": dispatch_id}
    had_comment = bool(work.get(task["status"] + "_url"))
    message = {"completed": "완료", "failed": "실패", "blocked": "보류"}[task["status"]]
    synced_comment(gh, state, work, task["status"], issue, f"Orca Worker 작업 {message} · `{task['id']}`")
    if task["status"] == "completed":
        had_pr = bool(work.get("pull-request_url"))
        pr = draft_pr(c, gh, orca, state, issue, work)
        if pr:
            return {"status": "draft_pr_linked" if had_pr else "draft_pr_synced", "pr": pr}
    return {"status": "worker_" + task["status"] if had_comment else "worker_synced",
            "task": task["id"], "dispatch": dispatch_id, "worker_status": task["status"]}
