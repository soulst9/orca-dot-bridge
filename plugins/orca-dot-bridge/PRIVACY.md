# Privacy and data handling

Orca Dot Bridge runs on the user's Mac. The bridge has no maintainer-operated service, usage analytics, or crash-reporting endpoint. These notes describe the bridge and its setup skill. GitHub, Slack, Orca, Codex, and Claude Code handle their own data under their respective policies and settings.

## Local configuration and records

The setup skill invokes the bundled Python CLI to store the chosen coordinator session mode in a local configuration file. Installing from GitHub retrieves the public plugin files. Changing the session mode is a local operation. Subsequent runs use local state files for project and issue identifiers, operation receipts, status, and URLs. The files have no automatic expiration and remain on the user's machine until the user removes them. Orca controls its own session and worktree history. The bridge has no copy of these records on a maintainer-operated service.

## GitHub Projects intake

The bridge invokes the GitHub CLI against GitHub using the user's authenticated account. It checks repository and Projects access, reads project items and relevant issue data, and reads comments when reconciling previously posted receipts or explicit approval. This can include account names, issue author and commenter identifiers, timestamps, labels, and issue or comment text supplied by participants. These are used to scope intake, check approvals, and prevent duplicate effects. A read-only coordinator or worker request includes the verified issue URL. The intake request also includes a one-time acknowledgment token. The bridge saves intake comments and updates the configured Projects status when the operator runs an apply command.

Batch intake, worker canaries, and draft PR publishing have separate settings. Batch intake and draft PR publishing are off in the example configuration. The optional draft PR path checks an approval tied to a specific branch and commit. The bridge does not push commits or merge PRs.

## Optional Slack relay

The Slack relay uses macOS Keychain entries configured by the user. It authenticates to the Slack API at `slack.com`, reads messages, replies, and sender identifiers in the configured channel, and posts bridge requests or reports to configured threads. The relay uses sender and thread metadata to check whether a reply came from an authorized source. It validates sender and thread information before forwarding an analysis-only decision to the configured local Orca manager. Slack tokens go to the Slack API. The bridge does not include them in its local configuration, logs, or distribution files.

## Controls and retention

The user chooses the GitHub repository and Projects board, the Slack channel if enabled, and when to run or schedule intake. To stop processing, disable the relevant automation and stop running the CLI for that configuration. After processing is stopped, the user can remove local configuration and state files or manage retained sessions in Orca. GitHub comments and project status and Slack messages remain subject to those services and workspace retention settings. Removing local records does not remove records from those services.

Set up service credentials through the GitHub CLI or the macOS Keychain prompt. Keep credentials, regulated records, and other sensitive material out of bridge prompts and issues used for testing.

## Support

Use [GitHub Issues](https://github.com/soulst9/orca-dot-bridge/issues) for support. Remove credentials, private issue content, Slack messages, and identifiers before posting in the public issue tracker.
