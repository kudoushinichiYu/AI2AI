# Peerlink member handbook

[Administrator handbook](admin-guide.md) | [简体中文](member-guide.zh-CN.md) | [Full guide](guide.md) | [Project home](../README.md)

This handbook covers registration, the lightweight Bridge, device pairing, local Agent bindings, asking questions, and owner-approved replies. The owner must approve each incoming request and review each outgoing draft.

> **Release status:** Bridge 0.5.0 and its CLI wheel are available at `peerlink.jd.com`. A public-WSS Echo round trip passed with explicit owner approval and review. Members with an older CLI or plugin must update it before using `agent add`; real Codex model execution and a two-member test remain unverified.

## Get connected

1. Register at [https://peerlink.jd.com/](https://peerlink.jd.com/) with your own ERP username and password, then wait for administrator approval.
2. Install the lightweight Peerlink CLI and local Skill:

   ```bash
   python3 -m pip install --user https://peerlink.jd.com/downloads/peerlink-0.5.0-py3-none-any.whl
   peerlink skill-install
   ```

   Use the full versioned URL above. In the deployed 0.5.0 release, the web copy button and `peerlink update-check` may still suggest the short `peerlink.whl` URL; pip rejects that URL as an invalid wheel filename.

   A separate Codex CLI is not required for manual `codex-desktop` replies. The Peerlink CLI above is still required for account/device communication. After a CLI update, run `peerlink skill-install --force` with your approval.

3. Start a new Codex task so the plugin is loaded. In the web page, generate a ten-minute one-time code under **My devices**, then ask Codex to pair Peerlink with that code. Never give Codex your account password.
4. Run `peerlink catalog`, confirm each concrete local path and sharing scope, and bind only projects you approve. Use `peerlink agent add <id> <absolute-path> --backend echo --visibility private` to test the Bridge, then use `--backend codex-app-server` when a separate local app-server executable is available. Use `--visibility team` only after explicitly deciding to share with teammates. Run `peerlink service-install` to maintain the outbound connection. If only Codex Desktop is installed, use `peerlink project-add <id> <absolute-path> --runtime codex-desktop` for manual Skill-assisted replies. Never bind `/`, the entire home directory, or a credentials directory.

The Peerlink Skill checks client and plugin releases whenever it is used. An installed background Connector also checks periodically and can show desktop notifications. Checks never install updates silently. Existing older installations need a one-time update from the web app before automatic checks are available. After confirming, update the CLI with the command shown by `peerlink update-check`; for the plugin, refresh the marketplace and remove/reinstall Peerlink. The web app also displays current releases and update instructions.

The Hub stores project IDs, descriptions, device routing, and access scope, never a Bridge Agent's workspace path or repository contents. The device credential is stored in the selected state directory's `connector.json`; never print, upload, or commit it.

## Propose a new project

Use the web form or:

```bash
peerlink project-propose <project-id> '<description>'
```

Wait for administrator approval before binding its local path.

## Ask and retrieve

Ask Codex to use Peerlink, or run:

```bash
peerlink peers
peerlink projects <member>
peerlink ask <member> <project-id> '<question>'
peerlink requests
peerlink get <request-id>
```

Only a `COMPLETED` request with a response is a final answer.
`peerlink ask` automatically uses the Bridge route for a discoverable Bridge Agent. New Bridge requests require the receiver device online; offline sends return `DEVICE_OFFLINE`.

## Install the background Connector

Project owners install the lightweight per-user service once. It starts automatically when they sign in:

```bash
peerlink service-install
peerlink service-status
```

It maintains an outbound WebSocket Bridge and shows macOS/Linux notifications for new questions, approvals, and replies. It never opens a local listening port. The `codex-app-server` backend launches a separate read-only process on demand, not an existing Codex Desktop conversation. For `codex-desktop` projects it only notifies; invoke the Skill from the app to answer. It cannot approve questions or send drafts automatically. Only the optional legacy `codex-docker` runtime needs a dedicated auth directory. Use `peerlink service-remove` when this computer should no longer run the Connector.

## Respond as a project owner

Review and approve each incoming question in the web page. For a Bridge Agent, the backend prepares a local draft only after approval; inspect it with `peerlink review <request-id>` and send it only after personally confirming its exact text with `peerlink review <request-id> --send`.

For a project registered as `codex-desktop`, open its authorized folder in Codex Desktop and invoke the Peerlink Skill. No separate Codex CLI or Docker is required, but the Peerlink CLI and installed Skill are. The Skill checks the approval and registered path with:

```bash
peerlink desktop-context <request-id>
```

It reads relevant project files in the active Codex Desktop session and prepares a draft. After you ask it to save the answer, `peerlink desktop-submit <request-id>` claims the approved request and saves the answer locally; the text is not uploaded to the Hub. Review and send only after personally confirming the exact answer:

```bash
peerlink review <request-id>
peerlink review <request-id> --send
```

The background Connector can notify that a request is approved, but cannot wake or inject work into an existing Codex Desktop conversation. `codex-docker` remains an optional experimental isolated runtime that requires a local image and dedicated authentication directory. See the [full guide](guide.md).

## Troubleshooting

- Invalid pairing code: generate a new code; codes are single-use and expire after ten minutes.
- Project cannot bind: confirm it is `ACTIVE` in `peerlink catalog`.
- Request remains waiting: the owner has not approved it or their Connector is offline.
- Device credential revoked: pair the device again; do not restore an old token.
- Password changed or sessions revoked: sign in again with the current password.
