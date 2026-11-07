# Orca Dot Bridge

Orca Dot Bridge connects a GitHub Projects intake queue and Slack approval workflows to a local Orca installation. It can open a coordinator when work arrives, reuse the session while issues are queued, and close the session when the queue is empty and GitHub sync has finished. The same Worktree and Run are used for the next session. A persistent session is also available.

## Requirements

Run the bridge on a Mac with Python 3.9 or newer and a running Orca installation. GitHub intake also requires the GitHub CLI with access to the chosen repository and Projects board. The plugin setup skill saves local configuration. GitHub batch intake, scheduling, and draft pull requests require separate setup.

## Install from GitHub

Install directly from this repository's marketplace. Add the source once, then install the plugin by name.

**Codex**

```sh
codex plugin marketplace add https://github.com/soulst9/orca-dot-bridge.git
codex plugin add orca-dot-bridge@orca-dot-bridge
```

Select `setup-orca-bridge` from your installed skills to choose the coordinator session mode. [Codex plugin documentation](https://developers.openai.com/plugins/build/plugins)

**Claude Code**

```sh
claude plugin marketplace add https://github.com/soulst9/orca-dot-bridge.git
claude plugin install orca-dot-bridge@orca-dot-bridge
```

Run `/orca-dot-bridge:setup-orca-bridge` in Claude Code. [Claude Code marketplace documentation](https://code.claude.com/docs/en/plugin-marketplaces)

The Claude package targets local Claude Code on macOS and includes its CLI in `bin/`.

**Standalone CLI**

Clone the public repository and run the bundled CLI.

```sh
git clone https://github.com/soulst9/orca-dot-bridge.git
cd orca-dot-bridge/plugins/orca-dot-bridge
./bin/orca-dot-bridge --version
```

## Configure the bridge

The setup skill offers **On demand** and **Keep the same session**. The default for a new configuration is on demand. Store each project's intake configuration and state locally outside the plugin cache.

See the [GitHub intake guide](plugins/orca-dot-bridge/docs/github-intake.md) for connection settings and the terminal setup command. The [bridge README](plugins/orca-dot-bridge/README.md) includes the Slack configuration and the CLI reference.

## Local execution and data

Orca Dot Bridge is a community integration for macOS. The setup skill invokes the bundled Python CLI to save the selected session mode. In a separately configured intake run, the CLI uses `gh` to query GitHub and `orca` to manage the configured project. It writes intake comments and project status only when the operator runs an apply command. The optional Slack relay uses Keychain credentials to call Slack and deliver a configured analysis request to a local Orca manager.

GitHub batch intake and draft PR publishing are disabled in the example configuration. A worker canary is read-only. The bridge stores its configuration and processing state on the user's machine. See [privacy and data handling](plugins/orca-dot-bridge/PRIVACY.md).

## Deploying this for a team

Need help setting up the bridge for your team, or a variant that fits your workflow? Open an [issue](https://github.com/soulst9/orca-dot-bridge/issues). Feedback on what you would want next is welcome.

## License

[MIT](LICENSE)
