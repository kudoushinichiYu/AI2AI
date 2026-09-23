---
name: peerlink
description: Connect this computer to a Peerlink team Hub, share explicitly approved local projects, send questions to teammates' project agents, and retrieve replies. Use when the user asks to bind Peerlink, collaborate through Peerlink, check Peerlink messages, or expose a project to teammates.
---

# Peerlink

This Skill release is `0.4.0+codex.20260923`. Use the installed `peerlink` CLI. At the start of each Peerlink task, run `peerlink status` and `peerlink update-check`. If the CLI reports that `update-check` is an unknown command, it predates update checking: explain that this is a one-time bootstrap and ask before running `python3 -m pip install --user --upgrade https://peerlink.jd.com/downloads/peerlink.whl`. Compare `plugin.latest` to this Skill release too, because the active plugin can lag behind the CLI package. If either component has a newer release, explain the exact suggested commands and ask the user before installing anything. For a CLI update, use the command returned in `cli.install_command`. For a plugin update, run the returned marketplace refresh command, then remove and re-add the Peerlink plugin only after the user confirms. Never install updates silently. If the check is unavailable, continue normal work and do not treat it as a pairing failure. Never request, print, or store the user's account password. Device pairing uses a short-lived one-time code from the signed-in Peerlink web page.

If no configuration exists, ask the user to sign in at `https://peerlink.jd.com`, generate a code under **My devices**, then run `peerlink connect --hub https://peerlink.jd.com --name <device-name> --code <code>`. Do not echo the code after use or expose `~/.peerlink/connector.json`.

After first pairing, run `peerlink catalog`. For each active cloud project the user wants available on this computer, ask them to confirm the exact local directory and runtime, then run `peerlink project-add <id> <absolute-path> --runtime <mock|codex-docker> --description <text>`. Allow missing or irrelevant projects to be skipped. Never search the whole computer, infer a path, or upload file contents.

Discover targets with `peerlink peers` and `peerlink projects <member>`. Send only on request with `peerlink ask <member> <project> '<question>'`. Check with `peerlink requests` and `peerlink get <request-id>`; do not present unfinished work as an answer. Cancel only on request.

`project-add` only binds an active cloud-catalog project. To add a new catalog item, explain that administrator approval is required and, after user confirmation, run `peerlink project-propose <id> '<description>'`. Wait for approval before asking for or binding its local path. Never register `/`, the home directory, credentials, or an inferred path. Mock is only a connectivity demo.

Incoming execution still requires web approval. Use `peerlink work --once` for an explicit check. Review local drafts with `peerlink review`; send with `peerlink review <id> --send` only after the user confirms the exact answer. Never approve or send on the user's behalf.

For a project owner who wants automatic receiving, install the per-user background Connector with `peerlink service-install [--auth-dir <dedicated-codex-auth-dir>]` and check it with `peerlink service-status`. It starts at login and shows desktop notifications for new approval requests, ready drafts, and completed answers. It still cannot approve incoming work or send a draft automatically. Remove it only on explicit request with `peerlink service-remove`.
