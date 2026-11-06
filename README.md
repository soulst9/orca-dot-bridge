# Orca Dot Bridge

Orca Dot Bridge connects a GitHub Projects intake queue and Slack approval workflows to a local Orca installation. It can open a coordinator when work arrives, reuse the session while issues are queued, and close the session when the queue is empty and GitHub sync has finished. The same Worktree and Run are used for the next session. A persistent session is also available.

## Requirements

Run the bridge on a Mac with Python 3.9 or newer and a running Orca installation. GitHub intake also requires the GitHub CLI with access to the chosen repository and Projects board. The plugin setup skill saves local configuration. GitHub batch intake, scheduling, and draft pull requests require separate setup.

## Install from GitHub

Replace `OWNER/REPO` with the GitHub path of this marketplace repository.

**Codex**

```sh
codex plugin marketplace add OWNER/REPO
codex plugin add orca-dot-bridge@orca-dot-bridge
```

Open the installed plugin's setup flow or select the `setup-orca-bridge` skill. [Codex plugin documentation](https://developers.openai.com/plugins/build/plugins)

**Claude Code**

```sh
claude plugin marketplace add OWNER/REPO
claude plugin install orca-dot-bridge@orca-dot-bridge
```

Run `/orca-dot-bridge:setup-orca-bridge` in Claude Code. [Claude Code marketplace documentation](https://code.claude.com/docs/en/plugin-marketplaces)

## Configure the bridge

The setup skill offers **On demand** and **Keep the same session**. The default for a new configuration is on demand. Store each project's intake configuration and state locally outside the plugin cache.

See the [GitHub intake guide](plugins/orca-dot-bridge/docs/github-intake.md) for connection settings and the terminal setup command. The [bridge README](plugins/orca-dot-bridge/README.md) includes the Slack configuration and the CLI reference.

## License

[MIT](LICENSE)
