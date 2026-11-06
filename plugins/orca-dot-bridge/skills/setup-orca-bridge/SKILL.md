---
name: setup-orca-bridge
description: Choose, change, or inspect the Orca Dot Bridge coordinator session mode for GitHub Projects intake. Use for first-time session setup or when switching between on-demand and persistent sessions.
---

# Set up the Orca Dot Bridge session

Use the existing bridge CLI to save the session choice in the user's local GitHub intake configuration.

1. Find the bridge CLI and the intended `github-intake.json` (or another user-selected intake configuration). The plugin package includes `bin/orca-dot-bridge`. Use a known bridge checkout or an installed executable if the client only imported the skill. If the target configuration is ambiguous, ask for its path. For a fresh setup, copy the packaged `github-intake.example.json` to the user-selected local configuration path only if the destination is absent. Keep it outside the plugin's installation directory if that directory is managed by the client.
2. If the user already chose a mode, use it. Otherwise present these choices in the user's language:
   - **On demand** (`on-demand`, default for a new setup). Keep the same session while issues are queued. Close it when the queue is empty and GitHub sync has finished. The next session uses the same Worktree and Run.
   - **Keep the same session** (`persistent`). Leave the coordinator session open when the queue is empty so its conversation context stays available.
   For an existing configuration, offer to keep the saved choice. A request to inspect the mode needs only the `coordinator_auto_close` value and leaves the file as it is.
3. Save the explicit choice using the CLI with the resolved paths. Replace the placeholders with the actual paths and selected mode.

   ```sh
   python3 -B "/path/to/bin/orca-dot-bridge" --config "/path/to/github-intake.json" github-intake-setup --session-mode on-demand
   ```

   Use `persistent` for the second choice. If using the installed `orca-dot-bridge` entry point, call the executable directly instead of through Python. Use the CLI result to confirm the saved mode. It applies on the next intake invocation.

Limit this workflow to session configuration. GitHub intake, Orca session changes, and enabling scheduled or batch execution are separate operations. Report only the mode and any setup fields the user still needs to fill. For initial GitHub and Orca connection settings, use [the intake setup guide](../../docs/github-intake.md) from the bridge package.
