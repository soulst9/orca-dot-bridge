import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from . import __version__
from .core import (BridgeError, DISABLED, Journal, Orca, REQ, Slack, encode, load_config,
                   new_request, tick, timestamp)
from .compat import automation_plan, check
from . import intake


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parser():
    p = argparse.ArgumentParser(description="One-shot Dot ↔ Slack ↔ Orca analysis bridge")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("validate-config")
    store = sub.add_parser("auth-store", help="Interactive Keychain prompt; no token argument")
    store.add_argument("--role", choices=("writer", "reader"), required=True)
    sub.add_parser("auth-test", help="Read-only Slack identity checks; never prints tokens")
    doctor = sub.add_parser("doctor", help="Local install and Orca help checks")
    doctor.add_argument("--online", action="store_true", help="Also verify Slack auth/read and manager binding")
    doctor.add_argument("--thread-ts", help="Existing canary thread to test complete replies access")
    sub.add_parser("automation-plan", help="Print a disabled Orca Automation command, do not create it")
    request = sub.add_parser("request", help="Post one new analysis-only request")
    request.add_argument("--question-file", required=True)
    request.add_argument("--task-id", required=True)
    request.add_argument("--gate-id", required=True)
    request.add_argument("--risk", choices=("low", "medium", "high", "critical"), default="low")
    post = sub.add_parser("post", help="Send plain text to the configured channel only")
    post.add_argument("--text-file", required=True)
    post.add_argument("--thread-ts")
    read = sub.add_parser("read", help="Original Slack metadata; output contains message content")
    read.add_argument("--thread-ts")
    pump = sub.add_parser("tick", help="Process once and exit; never changes Gates or Tasks")
    pump.add_argument("--dry-run", action="store_true", help="Reads only, no sends or state writes")
    intake.configure(sub.add_parser("github-intake", help="Intake an issue from an existing GitHub Project"))
    setup = sub.add_parser("github-intake-setup", help="Choose how the GitHub intake coordinator session runs")
    setup.add_argument("--session-mode", choices=intake.SESSION_MODES,
                       help="Set the session mode without an interactive prompt")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    os.umask(0o077)
    try:
        if args.command == "github-intake-setup":
            output(intake.setup_session_mode(args.config or "github-intake.json", args.session_mode))
            return 0
        if args.command == "github-intake":
            output(intake.execute(args, args.config or "github-intake.json"))
            return 0
        config_path = args.config or "config.yaml"
        c = load_config(config_path)
        if args.command == "validate-config":
            output({"ok": True, "enabled": c["enabled"], "unsupported_features_disabled": list(DISABLED)})
        elif args.command == "auth-store":
            if sys.platform != "darwin" or not sys.stdin.isatty():
                raise BridgeError("interactive_macos_terminal_required")
            s = c["slack"]
            # -w is deliberately LAST. security prompts for the password; no token in argv/history.
            p = subprocess.run(["/usr/bin/security", "add-generic-password", "-U", "-a", s["keychain_account"],
                                "-s", s[args.role + "_service"], "-w"], check=False)
            if p.returncode:
                raise BridgeError("keychain_store_failed")
            output({"ok": True, "stored_role": args.role})
        elif args.command == "auth-test":
            slack = Slack(c)
            output({"ok": True, "writer": slack.identity(writer=True), "reader": slack.identity()})
        elif args.command == "doctor":
            report = check(c)
            report.update(python_version=sys.version.split()[0], keychain_available=sys.platform == "darwin",
                          config_valid=True, enabled=c["enabled"], online_checks="not_run")
            Journal(c["state_file"])
            if args.online:
                slack = Slack(c)
                slack.identity(writer=True)
                slack.identity()
                slack.messages()
                if args.thread_ts:
                    timestamp(args.thread_ts)
                    slack.messages(thread=args.thread_ts)
                Orca(c).manager()
                report["online_checks"] = "auth_history_manager_passed"
                report["thread_read_verified"] = bool(args.thread_ts)
            output(report)
            return 0 if report["compatible"] and report["keychain_available"] else 2
        elif args.command == "automation-plan":
            output(automation_plan(c, config_path, Path(__file__).resolve().parents[1], check(c)))
        elif args.command == "post":
            slack = Slack(c)
            slack.identity(writer=True)
            output({"ok": True, "ts": slack.post(Path(args.text_file).read_text(), args.thread_ts)})
        elif args.command == "request":
            slack = Slack(c)
            slack.identity(writer=True)
            q = new_request(c, Path(args.question_file).read_text().strip(), args.task_id, args.gate_id, args.risk)
            # Validate local fields using a synthetic timestamp before an external write.
            from .core import request_from_message
            now = dt.datetime.now(dt.timezone.utc).timestamp()
            fake = {"type": "message", "user": c["slack"]["bridge_user_id"],
                    "bot_id": c["slack"]["bridge_bot_id"], "ts": "%.6f" % now, "text": encode(REQ, q)}
            request_from_message(fake, c, now + 0.001)
            ts = slack.post(encode(REQ, q))
            output({"ok": True, "thread_ts": ts, "request": q})
        elif args.command == "read":
            slack = Slack(c)
            slack.identity()
            output({"ok": True, "messages": slack.messages(thread=args.thread_ts)})
        elif args.command == "tick":
            # Probe exact installed command capabilities every run before possible input delivery.
            if not check(c)["compatible"]:
                raise BridgeError("orca_cli_incompatible")
            output({"ok": True, "results": tick(c, dry_run=args.dry_run)})
        return 0
    except BridgeError as e:
        output({"ok": False, "error": str(e)})
        return 2
    except (OSError, KeyError, TypeError, ValueError):
        # Do not leak token-bearing stack traces or subprocess diagnostics.
        output({"ok": False, "error": "invalid_local_file_or_unsupported_response_shape"})
        return 2


if __name__ == "__main__":
    sys.exit(main())
