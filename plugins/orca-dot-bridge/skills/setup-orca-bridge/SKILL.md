---
name: setup-orca-bridge
description: Choose, change, or inspect the Orca Dot Bridge coordinator session mode for GitHub Projects intake. Use for first-time session setup or when switching between on-demand and persistent sessions.
---

# Set up the Orca Dot Bridge session

Use the existing bridge CLI to save the session choice in the user's local GitHub intake configuration.

1. Resolve the bundled files from the installed skill.
   - In Claude Code, the launcher is `${CLAUDE_PLUGIN_ROOT}/bin/orca-dot-bridge` and the example is `${CLAUDE_PLUGIN_ROOT}/github-intake.example.json`.
   - In Codex, resolve `../../bin/orca-dot-bridge` and `../../github-intake.example.json` from the directory containing this `SKILL.md`. Use the resulting absolute paths.
   - For a standalone copy of this skill, use an already installed `orca-dot-bridge` executable or a bridge checkout supplied by the user.
   Resolve the user's intake configuration separately. Ask for its path if ambiguous. For a fresh setup, copy the packaged example to the chosen local path if it is absent. Keep the configuration outside the client-managed plugin directory.
2. If the user already chose a mode, use it. Otherwise present these choices in the user's language:
   - **On demand** (`on-demand`, default for a new setup). Keep the same session while issues are queued. Close it when the queue is empty and GitHub sync has finished. The next session uses the same Worktree and Run.
   - **Keep the same session** (`persistent`). Leave the coordinator session open when the queue is empty so its conversation context stays available.
   For an existing configuration, offer to keep the saved choice. A legacy configuration without `coordinator_auto_close` runs in persistent mode. For an inspection, read that field and report the effective mode without editing the file.
3. Set `bridge_cli` and `intake_config` to the resolved absolute paths and run the command with the chosen mode.

   ```sh
   python3 -B "$bridge_cli" --config "$intake_config" github-intake-setup --session-mode on-demand
   ```

   Use `persistent` for the second choice. If using the installed `orca-dot-bridge` entry point, call the executable directly instead of through Python. Use the CLI result to confirm the saved mode. It applies on the next intake invocation.

Limit this workflow to session configuration. GitHub intake, Orca session changes, and enabling scheduled or batch execution are separate operations. Report only the mode and any setup fields the user still needs to fill. For initial GitHub and Orca connection settings, use [the intake setup guide](../../docs/github-intake.md) from the bridge package.
