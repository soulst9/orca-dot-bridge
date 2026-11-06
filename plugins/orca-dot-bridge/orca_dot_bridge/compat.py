"""Capability detection from the selected CLI, never a guessed version range."""
import re
import shlex
import shutil
import sys
from pathlib import Path
from .core import BridgeError, Orca, orca_executable, run


REQUIRED = {
    "automations create": ("--name", "--trigger", "--prompt", "--provider", "--workspace", "--disabled", "--json"),
    "automations edit": ("--id", "--disabled", "--enabled", "--json"),
    "automations run": ("--id", "--json"),
    "automations runs": ("--id", "--limit", "--json"),
    "terminal show": ("--terminal", "--json"),
    "terminal read": ("--terminal", "--cursor", "--limit", "--screen", "--json"),
    "terminal send": ("--terminal", "--text", "--enter", "--json"),
    "orchestration gate-list": ("--task", "--from", "--json"),
    "orchestration task-list": ("--run", "--json"),
    "orchestration worker-list": ("--run", "--json"),
    "orchestration dispatch-show": ("--task", "--from", "--json"),
    "orchestration gate-resolve": ("--id", "--resolution", "--from", "--json"),
    "orchestration task-update": ("--id", "--status", "--result", "--run", "--from", "--json"),
}


def check(c, runner=run):
    exe = orca_executable(c)
    version = runner([exe, "--version"]).strip()
    # A non-Orca executable must not accidentally pass general --help discovery.
    root = runner([exe, "--help"])
    if not all(word in root.lower() for word in ("orca", "automations", "orchestration")):
        raise BridgeError("selected_executable_is_not_supported_orca")
    guides = {}
    for skill in ("orca-cli", "orchestration"):
        try:
            output = runner([exe, "skills", "get", skill, "--json"])
            guides[skill] = '"markdown"' in output
        except BridgeError:
            guides[skill] = False
    results = {}
    for command, flags in REQUIRED.items():
        try:
            help_text = runner([exe, *command.split(), "--help"])
            # Require actual option lines, not an incidental mention in examples or errors.
            options = set(re.findall(r"^\s+(--[a-z][a-z-]*)\b", help_text, re.M))
            missing = [flag for flag in flags if flag not in options]
            results[command] = {"supported": not missing, "missing_flags": missing}
        except BridgeError:
            results[command] = {"supported": False, "missing_flags": list(flags)}
    return {"executable": exe, "version": version, "guides_available": guides,
            "commands": results, "compatible": all(r["supported"] for r in results.values()),
            "live_semantics_verified": False}


def automation_plan(c, config_path, package_root, report):
    if not report["compatible"]:
        raise BridgeError("orca_cli_incompatible:no_automation_plan")
    exe = orca_executable(c)
    template = Path(__file__).with_name("automation_prompt.txt").read_text()
    launcher = Path(package_root) / "bin" / "orca-dot-bridge"
    if not launcher.exists():
        invoked = Path(sys.argv[0]).resolve()
        installed = str(invoked) if invoked.name == "orca-dot-bridge" and invoked.is_file() else shutil.which("orca-dot-bridge")
        if not installed:
            raise BridgeError("bridge_launcher_not_found")
        launcher = Path(installed)
    command = shlex.join([str(launcher),
                          "--config", str(Path(config_path).resolve()), "tick"])
    prompt = template.replace("{{TICK_COMMAND}}", command)
    argv = [exe, "automations", "create", "--name", c["automation"]["name"],
            "--trigger", c["automation"]["trigger"], "--provider", c["manager"]["provider"],
            "--workspace", "path:" + c["manager"]["worktree_path"],
            "--prompt", prompt, "--disabled", "--json"]
    return {"status": "PLAN_ONLY", "enabled_on_create": False, "argv": argv,
            "shell_command": shlex.join(argv), "schedule_timezone": "Orca host setting; verify in UI"}
