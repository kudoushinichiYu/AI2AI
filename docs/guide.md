# Peerlink user and deployment guide

**English** | [简体中文](guide.zh-CN.md) | [Administrator handbook](admin-guide.md) | [Member handbook](member-guide.md) | [Project home](../README.md)

This guide covers shared-server deployment, member setup, collaboration, the Codex Desktop Skill, optional experimental Docker execution, and operations. Run shell commands from the repository root. Replace values inside angle brackets with actual values before running commands.

> This guide retains legacy Connector/Mock/Docker details. New members should start with the [updated member handbook](member-guide.md). Bridge 0.5.0 is deployed online; see the [migration status](peerlink-bridge-migration.zh-CN.md) for what the public-WSS Echo test did and did not verify.

## 1. Deploy a shared Hub

An administrator deploys one Hub for the team. Members receive its URL and individual credentials; they do not each need to deploy a server. A research lab can host the Hub on an existing server while members keep projects and agent execution on their own machines.

### Server deployment

Install Docker and Docker Compose, obtain this repository, and run:

```bash
docker compose up -d --build
docker compose exec hub peerlink init-admin <administrator-username>
```

Replace `<administrator-username>` with an actual username before running the command; do not keep the angle brackets. Usernames accept letters, digits, dots, underscores, and hyphens, up to 80 characters. `init-admin` securely prompts for a password twice; the administrator signs in with that username and password. When starting from an older database, the earliest existing account is upgraded to administrator automatically.

Compose binds port 8000 to the server's loopback interface only. Configure an HTTPS reverse proxy using the [Caddy example](../deploy/Caddyfile.example) or your own Nginx configuration. Use a certificate trusted by member devices; remote clients do not accept plain HTTP or offer an option to disable TLS verification. Start on a private network or VPN rather than exposing the preview to the public internet.

Give members the Hub's HTTPS URL and access to this repository or a package built from it. Members register with their own username and password, then sign in after an administrator approves the account. The current web interface is in Chinese. The login session is held in an HTTP-only cookie; users can change their password or revoke all sessions from **Account security**. `/docs` exposes API documentation and `/health` provides a health check.

A 4-vCPU / 8-GB host is a reasonable starting point for a trial group of fewer than 10 members, not a benchmarked capacity claim. Each member supplies their local execution resources and model access; the Hub does not perform model inference.

### Local evaluation without Docker

If you must reuse an existing container without restarting its application, see the [existing-container deployment guide](../deploy/existing-container/README.md) for an isolated virtual environment and host-managed service approach.

Requires Python 3.10+:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
peerlink init-admin <username>
peerlink hub
```

Open [localhost:8000](http://127.0.0.1:8000). To simulate additional members, register them in separate browser windows and approve them with the administrator account. The default database is `.peerlink/hub.db` relative to the working directory. Keep the same working directory or use an explicit `--db` path to avoid accidentally creating a new database.

## 2. Install and connect a member's client

The local Connector targets macOS and Linux with Python 3.10+. Install the published client and its bundled Codex Skill:

```bash
python3 -m pip install --user https://peerlink.jd.com/downloads/peerlink.whl
peerlink skill-install
```

Sign in to the web page, generate a ten-minute one-time code under **My devices**, and pair this computer:

```bash
peerlink connect --hub https://<team-service-domain> --name <device-name> --code <pairing-code>
peerlink catalog
```

Use `http://127.0.0.1:8000` only when the Hub runs on the same machine. The pairing code is single-use; the client stores a separately revocable device credential, never the account password.

**Only asking questions?** You can now use the web interface or CLI without registering a device or running a Connector.

**Sharing a project?** Register your device and an explicitly selected project:

```bash
peerlink project-add <project-id> /absolute/path/to/project --runtime codex-desktop --description 'Project description'
peerlink service-install
```

Administrators seed the cloud catalog. Each member's Codex reads `catalog` and uploads only explicitly confirmed project-to-local-path bindings, not repository contents; missing projects may be skipped. Members use `peerlink project-propose <id> '<description>'` for new entries and cannot bind them before administrator approval. The recommended Desktop Skill workflow is described below; Docker remains an optional adapter.

The proposal command also works with a paired device credential; it creates a `PENDING` catalog entry for administrator review. Administrators can retire an active entry and reactivate it later. Retiring hides its project bindings from discovery and cancels unfinished requests for that project.

State defaults to `~/.peerlink`. Override it with `PEERLINK_STATE` or `peerlink --state /path/to/state ...`. Newly created state directories use mode 700 and configuration files use mode 600. The device credential can send questions and retrieve replies for its owner, but cannot approve incoming execution.

`service-install` creates a per-user macOS launchd or Linux systemd service that starts at login and shows notifications for new requests, approvals, and completed answers. For `codex-desktop` projects it notifies but does not claim work or wake Codex Desktop; invoke the Skill in the app. Check it with `peerlink service-status`. The Hub still cannot bypass owner approval or send an unreviewed draft.

Each user/project pair currently maps to one device. Before changing its directory, runtime, or device, run `peerlink project-remove <project-id>`. This cancels outstanding requests for that registration. Register again and request fresh approval. Owners can revoke a device through `DELETE /api/devices/{id}` using their user credentials.

## 3. Ask, approve, and share an answer

### Requester

Choose a member and project in the web interface, or run from a paired computer:

```bash
peerlink peers
peerlink projects <owner-username>
peerlink ask <owner-username> <project-id> 'What are the experiment settings and the reasoning behind them?'
peerlink get <request-id>
```

Use `peerlink cancel <request-id>` to cancel an unfinished request you sent.

### Project owner

Review the question in the web interface and approve or reject execution. For a `codex-desktop` project, open its registered folder in Codex Desktop and invoke the Peerlink Skill. The Skill verifies approval and the locally bound path with:

```bash
peerlink desktop-context <request-id>
```

It then reads relevant project files in the active Codex Desktop session and prepares a draft. Once asked to save it, `peerlink desktop-submit <request-id>` claims that approved task and stores the answer locally; the answer text is not uploaded to the Hub. No Codex CLI or Docker image is required, but the Peerlink CLI and Skill are. The background Connector can notify about approval but cannot wake or control the app. Review and send only after explicit confirmation:

```bash
peerlink review
peerlink review <request-id>
```

After reading the draft, choose **one** of the following:

```bash
peerlink review <request-id> --send
peerlink review <request-id> --send --answer-file /path/to/edited-answer.txt
peerlink review <request-id> --reject
```

`--send` represents the owner's explicit approval to share that answer. Do not invoke it in an unattended approval loop. The system trusts the owner and local Connector; it cannot prevent a compromised device from forging this confirmation.

The Hub receives only the waiting-for-review status until an answer is sent. **Unapproved drafts remain local.** Local files include the question and execution lease and should be treated as private. Completed or stopped drafts are retained as `.done` / `.stopped` files for troubleshooting and can be deleted by their owner.

The requester retrieves the approved answer through the web interface or `peerlink get`. Delivery into the original Codex conversation is not automatic yet.

## 4. Install the Codex Skill

The published client bundles the Codex Skill. After installing the client, run:

```bash
peerlink skill-install
```

Reload Codex, then ask it to use Peerlink to contact a member, check replies, or share an explicitly selected project. The Skill uses the paired device credential and never stores the account password. It cannot approve incoming execution or send a draft without the owner's explicit authorization. See the [Skill instructions](../skills/peerlink/SKILL.md).

## 5. Codex Desktop Skill (lightweight)

Register a project with `--runtime codex-desktop`, install the Peerlink Skill, and install the lightweight background Connector if notifications are wanted. No Codex CLI or Docker is required. The separate Peerlink CLI remains the local client for device credentials and Hub communication.

The Desktop Skill works in the active Codex Desktop conversation. It checks that the request is `WAITING_DEVICE` (approved) and that the locally registered project path is accessible to that session. It reads relevant files, prepares a draft, and only claims the task when saving the user's chosen draft. The Connector heartbeat keeps the review window active when the background service is installed. The answer stays local until the owner explicitly sends it.

The background Connector cannot programmatically wake an existing Codex Desktop conversation or inject a task into it. After approval, the owner invokes the Skill in Codex Desktop. Codex Desktop can open local folders and use them within the access the user grants; see [OpenAI's desktop guidance](https://help.openai.com/en/articles/20001275/).

The Desktop Skill has a different security boundary from a container: Peerlink validates the registered path but cannot impose OS-level read isolation on the Codex Desktop session. Use trusted collaborators, open only the intended project folder, and do not bind sensitive project trees unless appropriate for that session.

## 6. Optional Codex Docker runtime (experimental)

`codex --sandbox read-only` alone does not confine reads to a project directory. The adapter runs Codex in a local Docker container with a read-only project mount, rather than directly on the host. It does not mount the entire home directory, SSH keys, Docker socket, or unrelated projects.

1. Install and start Docker. Select a Codex version that supports the required flags.
2. Use Codex's login flow with a **dedicated authentication directory** to create `auth.json`. Do not copy your entire personal `~/.codex` directory. The adapter supports standard authentication; it does not migrate custom model routing, MCP servers, plugins, or proxy settings.
3. Build the runtime image with an explicitly chosen version:

```bash
docker build -f deploy/codex.Dockerfile --build-arg CODEX_VERSION=<verified-version> -t peerlink-codex:local .
peerlink project-remove <project-id>
peerlink project-add <project-id> /absolute/path/to/project --runtime codex-docker
peerlink work --auth-dir /path/to/dedicated-auth-directory
```

Remove the old registration only if you previously registered this project. Stop any existing Connector worker before starting the new one.

The container uses a read-only root filesystem and project mount, dropped capabilities, CPU/memory/process limits, and a five-minute execution timeout. Codex uses a read-only sandbox, non-interactive approval settings, ignored user configuration and rules, and an ephemeral session. No sandbox-bypass flag is used.

Cancellation and revocation propagate through lease checks, normally on a roughly 15-second heartbeat interval. Network loss prevents guaranteed immediate cancellation, but the Hub rejects expired results.

**Remaining risks:** The container still contains model authentication material, model calls use the network, and the registered project itself may contain secrets. Use a sanitized project directory and dedicated least-privilege credentials. This is not a strict data-loss-prevention system. Sensitive use requires further credential isolation, egress controls, and independent security validation.

Reference: [Codex non-interactive execution](https://developers.openai.com/codex/noninteractive). Real model calls and container behavior must be validated on target machines; passing Mock tests does not validate the Codex adapter.

## 7. Operations, backups, and upgrades

### Storage and recovery

- Compose stores data in the `hub-data` named volume. Rebuilding the container preserves it; **`docker compose down -v` deletes it**.
- Use SQLite's online backup API for a consistent backup. Do not copy only a live `.db` file and ignore its WAL.
- To migrate, stop the service or take a consistent backup, restore it as `/data/hub.db` in the target volume, and ensure container UID 10001 can read and write it.
- A Hub URL change also requires updating the `hub` value in each Connector's local configuration. Moving the Hub does not move project files or runtimes to the server.

The implementation uses SQLite WAL and one Hub instance. The new Bridge uses outbound WebSocket, while legacy runtimes still poll over HTTP during migration. Expired tasks are marked failed rather than automatically reassigned; a new request requires new approval.

### Upgrading earlier development installations

The project and package are named **Peerlink** / `peerlink`, with `PEERLINK_` environment variables and `~/.peerlink` as the default state directory. Reinstall the package and update commands, environment variables, and the Skill when upgrading an earlier naming scheme.

Existing databases and device configurations are not automatically migrated. Use `--db` and `--state` to retain their previous locations, or back them up and migrate while services are stopped. Do not accidentally create a new empty database or duplicate device registration.

The Compose project name is `peerlink`. To retain an existing deployment's volume namespace, use `docker compose -p <existing-project-name> up -d --build`, or migrate data explicitly before using the new project name. A different Compose project name creates a separate volume.

### Before broader deployment

All approved users currently belong to a single trusted trial group. They can discover project names and submit questions, but execution still needs the owner's approval. Administrator approval is a human trust decision, not identity verification. Public deployment needs further work on SSO or short-lived credentials, rotation, registration abuse controls, contact/access policies, rate limiting, retention, audit queries, monitoring, backup/restore drills, load testing, and browser validation.

## 8. Development and verification

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

Tests cover API authorization, project-path privacy, approval gating, rejection of draft uploads, atomic task claims, persistence across Hub restart, rejection of cancelled/expired/revoked results, local path validation, and a real HTTP + CLI + Mock Connector round trip.

| Location | Purpose |
| --- | --- |
| [`peerlink/hub.py`](../peerlink/hub.py) | Shared Hub API |
| [`peerlink/connector.py`](../peerlink/connector.py) | Local execution and draft review |
| [`peerlink/cli.py`](../peerlink/cli.py) | CLI commands |
| [`peerlink/static/`](../peerlink/static/) | Approval interface |
| [`deploy/`](../deploy/) | Deployment examples |
| [`skills/peerlink/`](../skills/peerlink/) | Agent-facing workflow instructions |
| [`tests/`](../tests/) | Automated tests |
