# Peerlink user and deployment guide

**English** | [简体中文](guide.zh-CN.md) · [Project home](../README.md)

This guide covers shared-server deployment, member setup, collaboration, the Codex Skill, experimental model execution, and operations. Run shell commands from the repository root. Replace values inside angle brackets with actual values before running commands.

## 1. Deploy a shared Hub

An administrator deploys one Hub for the team. Members receive its URL and individual credentials; they do not each need to deploy a server. A research lab can host the Hub on an existing server while members keep projects and agent execution on their own machines.

### Server deployment

Install Docker and Docker Compose, obtain this repository, and run:

```bash
docker compose up -d --build
docker compose exec hub peerlink add-user <username>
```

Create a distinct account for each member. Usernames accept letters, digits, underscores, and hyphens, up to 80 characters. Each `add-user` call prints a user Token once. Deliver it privately; never commit it or include it in screenshots or reports. Tokens are long-lived in this preview, and there is no self-service registration.

Compose binds port 8000 to the server's loopback interface only. Configure an HTTPS reverse proxy using the [Caddy example](../deploy/Caddyfile.example) or your own Nginx configuration. Use a certificate trusted by member devices; remote clients do not accept plain HTTP or offer an option to disable TLS verification. Start on a private network or VPN rather than exposing the preview to the public internet.

Give each member the Hub's HTTPS URL, their individual Token, and access to this repository or a package built from it. The current web interface is in Chinese. Tokens are kept only in page memory, so reloading requires signing in again. `/docs` exposes API documentation and `/health` provides a health check.

A 4-vCPU / 8-GB host is a reasonable starting point for a trial group of fewer than 10 members, not a benchmarked capacity claim. Each member supplies their local execution resources and model access; the Hub does not perform model inference.

### Local evaluation without Docker

Requires Python 3.10+:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
peerlink add-user <username>
peerlink hub
```

Open [localhost:8000](http://127.0.0.1:8000). To simulate multiple members, create separate accounts and use separate browser windows. The default database is `.peerlink/hub.db` relative to the working directory. Keep the same working directory or use an explicit `--db` path to avoid accidentally creating a new database.

## 2. Install and connect a member's client

The local Connector targets macOS and Linux with Python 3.10+. Obtain the repository, then install it on the member's machine:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Configure the administrator-provided URL and enter your own Token when `read` waits for input:

```bash
export PEERLINK_HUB=https://<team-service-domain>
read -s PEERLINK_TOKEN
export PEERLINK_TOKEN
```

Use `http://127.0.0.1:8000` only when the Hub runs on the same machine. Entering the Token interactively avoids putting it directly in shell history.

**Only asking questions?** You can now use the web interface or CLI without registering a device or running a Connector.

**Sharing a project?** Register your device and an explicitly selected project:

```bash
peerlink connect --name <device-name>
peerlink project-add <project-id> /absolute/path/to/project --runtime mock --description 'Project description'
unset PEERLINK_TOKEN
peerlink work
```

Project IDs accept letters, digits, underscores, and hyphens, up to 80 characters. The directory must exist. Mock validates the coordination flow only; it does not read the project or call a model. See [real Codex execution](#5-real-codex-execution-experimental) for the experimental adapter.

State defaults to `~/.peerlink`. Override it with `PEERLINK_STATE` or `peerlink --state /path/to/state ...`. Newly created state directories use mode 700 and configuration files use mode 600. Registration stores a device Token, not the user Token. Clearing `PEERLINK_TOKEN` does not stop the Connector, but subsequent user-level CLI requests need it configured again.

Keep `peerlink work` running. Approved requests wait when the assigned device is offline; the server cannot start an agent on a disconnected machine. Background installation is not automated yet. A future launchd/systemd integration is separate from the Skill.

Each user/project pair currently maps to one device. Before changing its directory, runtime, or device, run `peerlink project-remove <project-id>`. This cancels outstanding requests for that registration. Register again and request fresh approval. Owners can revoke a device through `DELETE /api/devices/{id}` using their user credentials.

## 3. Ask, approve, and share an answer

### Requester

Choose a member and project in the web interface, or configure your Hub URL and user Token and run:

```bash
peerlink peers
peerlink projects <owner-username>
peerlink ask <owner-username> <project-id> 'What are the experiment settings and the reasoning behind them?'
peerlink get <request-id>
```

Use `peerlink cancel <request-id>` to cancel an unfinished request you sent.

### Project owner

Review the question in the web interface and approve or reject execution. Once approved, the Connector runs the selected runtime. When a draft is ready, open another terminal on the same machine and activate the same virtual environment:

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

Ensure `peerlink` is on the target agent's PATH and securely configure the Hub URL and that user's Token. Never embed Tokens in a Skill file. From the repository root:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/peerlink "${CODEX_HOME:-$HOME/.codex}/skills/"
```

Review any existing same-named Skill before replacing it. Reload the agent, then ask it to use Peerlink to contact a specific member about a registered project. The Skill guides project discovery, request submission, and progress checks through the CLI. It must not approve execution or send answers on the owner's behalf without explicit authorization.

Installing the Skill does not install the Python package, provision credentials, register a device, or start a background process. This repository includes Skill and package source, not a published one-click plugin installer. See the [Skill instructions](../skills/peerlink/SKILL.md).

## 5. Real Codex execution (experimental)

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

## 6. Operations, backups, and upgrades

### Storage and recovery

- Compose stores data in the `hub-data` named volume. Rebuilding the container preserves it; **`docker compose down -v` deletes it**.
- Use SQLite's online backup API for a consistent backup. Do not copy only a live `.db` file and ignore its WAL.
- To migrate, stop the service or take a consistent backup, restore it as `/data/hub.db` in the target volume, and ensure container UID 10001 can read and write it.
- A Hub URL change also requires updating the `hub` value in each Connector's local configuration. Moving the Hub does not move project files or runtimes to the server.

The implementation uses SQLite WAL, one Hub instance, and HTTP polling. Expired tasks are marked failed rather than automatically reassigned; a new request requires new approval. This avoids automatically running a second copy while a disconnected worker may still be executing.

### Upgrading earlier development installations

The project and package are named **Peerlink** / `peerlink`, with `PEERLINK_` environment variables and `~/.peerlink` as the default state directory. Reinstall the package and update commands, environment variables, and the Skill when upgrading an earlier naming scheme.

Existing databases and device configurations are not automatically migrated. Use `--db` and `--state` to retain their previous locations, or back them up and migrate while services are stopped. Do not accidentally create a new empty database or duplicate device registration.

The Compose project name is `peerlink`. To retain an existing deployment's volume namespace, use `docker compose -p <existing-project-name> up -d --build`, or migrate data explicitly before using the new project name. A different Compose project name creates a separate volume.

### Before broader deployment

All registered users currently belong to a single trusted trial group. They can discover project names and submit questions, but execution still needs the owner's approval. Public deployment needs further work on SSO or short-lived credentials, rotation, contact/access policies, rate limiting, retention, audit queries, monitoring, backup/restore drills, load testing, and browser validation.

## 7. Development and verification

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
