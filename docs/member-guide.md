# Peerlink member handbook

[Administrator handbook](admin-guide.md) | [简体中文](member-guide.zh-CN.md) | [Full guide](guide.md) | [Project home](../README.md)

This handbook covers registration, Codex plugin installation, device pairing, local-path mapping, asking questions, and responding as a project owner.

## Get connected

1. Register at [https://peerlink.jd.com/](https://peerlink.jd.com/) with your own ERP username and password, then wait for administrator approval.
2. Install the lightweight client and Codex plugin:

   ```bash
   python3 -m pip install --user https://peerlink.jd.com/downloads/peerlink.whl
   codex plugin marketplace add kudoushinichiYu/peerlink --ref main
   codex plugin add peerlink@peerlink-team
   ```

3. Start a new Codex task so the plugin is loaded. In the web page, generate a ten-minute one-time code under **My devices**, then ask Codex to pair Peerlink with that code. Never give Codex your account password.
4. Ask Codex to initialize local Peerlink projects. It runs `peerlink catalog`, asks you to confirm each concrete path and runtime, and binds only the projects you approve. Missing projects may be skipped. Never bind `/`, the entire home directory, or a credentials directory.

The Hub stores project-to-path metadata, not repository contents. The device credential is stored in `~/.peerlink/connector.json`; never print, upload, or commit it.

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

## Install the background Connector

Project owners install the lightweight per-user service once. It starts automatically when they sign in:

```bash
peerlink service-install --auth-dir /path/to/dedicated-codex-auth-directory
peerlink service-status
```

It polls the Hub for the signed-in member's work and shows a macOS/Linux desktop notification for a new approval request, a locally completed draft, or an answer to the member's own question. It cannot approve a question or send a draft automatically. Omit `--auth-dir` only for the Mock workflow. Use `peerlink service-remove` when this computer should no longer run the Connector.

## Respond as a project owner

Review and approve the incoming question in the web page. The background Connector picks it up automatically. Without the service, run `peerlink work --once`. Inspect drafts with `peerlink review`, and send only after personally confirming the exact answer:

```bash
peerlink review <request-id>
peerlink review <request-id> --send
```

Mock is a connectivity demonstration. Real project execution uses the experimental `codex-docker` runtime and requires a dedicated authentication directory and the local runtime image. See the [full guide](guide.md).

## Troubleshooting

- Invalid pairing code: generate a new code; codes are single-use and expire after ten minutes.
- Project cannot bind: confirm it is `ACTIVE` in `peerlink catalog`.
- Request remains waiting: the owner has not approved it or their Connector is offline.
- Device credential revoked: pair the device again; do not restore an old token.
- Password changed or sessions revoked: sign in again with the current password.
