---
name: peerlink
description: Connect Codex to a Peerlink team Hub, send questions to teammates' approved project agents, check requests, and review local reply drafts.
---

# Peerlink

Use the installed `peerlink` command. Start with `peerlink status`. Never ask for or expose a password, pairing code after use, device token, `connector.json`, or model credential.

If the device is not paired, tell the user to sign in to the Peerlink web page and create a one-time pairing code, then run `peerlink connect --hub https://peerlink.jd.com --name <device-name> --code <code>`. Do not repeat the code in the response.

For a member who shares projects, use `peerlink catalog` and bind only a directory the user explicitly selected with `peerlink project-add <id> <absolute-path> --runtime <mock|codex-docker>`. Never infer or scan for paths, and never bind `/` or the home directory. A new catalog project uses `peerlink project-propose` and requires administrator approval.

Install the lightweight background receiver with `peerlink service-install [--auth-dir <dedicated-codex-auth-dir>]`. Check it with `peerlink service-status`. This service automatically claims only requests the project owner already approved in the web page. It generates a local draft and sends a desktop notification; it does not approve incoming requests or send answers automatically.

Discover recipients with `peerlink peers` and `peerlink projects <member>`. Send only at the user's request with `peerlink ask <member> <project> '<question>'`. Check results with `peerlink requests` and `peerlink get <request-id>`.

Incoming execution always requires the project owner's web approval. Inspect local drafts with `peerlink review` and `peerlink review <id>`. Run `peerlink review <id> --send` only after the user has reviewed and explicitly confirmed the exact answer. Never approve, reject, cancel, remove the service, or send on the user's behalf.
