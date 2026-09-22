<h1 align="center">Peerlink</h1>

<p align="center"><strong>Your team's project knowledge. Your agents. Your approval.</strong></p>
<p align="center">Self-hosted project agent collaboration for research labs and small engineering teams.</p>
<p align="center"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>
<p align="center"><a href="#quick-start">Quick start</a> · <a href="docs/admin-guide.md">Administrator handbook</a> · <a href="docs/member-guide.md">Member handbook</a> · <a href="docs/guide.md">Full guide</a></p>

---

Peerlink lets teammates ask questions of each other's project agents without handing over unrestricted access to their computers. A shared **Hub** routes requests and manages approvals. A lightweight **Connector** runs the agent on the project owner's machine. The owner decides whether to run a request and what answer to share.

Deploy one Hub on a lab server, an internal host, or a cloud VM. Members connect their own machines and explicitly register the projects they want to make available for collaboration.

> **Developer preview · v0.2.0.** Start with a small, trusted group. The Mock workflow has automated end-to-end coverage; real Codex execution and container deployment still require validation on the target machines. Peerlink is not yet production-hardened.

## Why Peerlink?

- **Project-aware collaboration.** Ask about experiment settings, repository structure, or design decisions in a specific teammate's project.
- **Human approval at both ends of execution.** The owner approves the request, then reviews, edits, or rejects the generated answer before sending it.
- **Local execution, shared coordination.** Register project locations without uploading a copy of the repository to the Hub.
- **Offline request storage.** Approved requests wait for the assigned device to come online. Execution leases prevent concurrent claims of the same task.
- **CLI and Skill access.** Use the web interface or `peerlink` commands; a Codex Skill can guide an agent through the CLI workflow.

## How it works

**Ask → Owner approves → Local agent runs → Owner reviews → Answer is shared**

| Component | Runs on | Responsibility |
| --- | --- | --- |
| Hub | Shared server | Accounts, project mappings, request storage, approvals, routing, and status |
| Connector | Member's machine | Device registration, local project checks, task execution, and draft review |
| Agent runtime | Member's machine | Answering questions using the registered project; Mock or experimental Codex Docker adapter |

Members who only ask questions do not need a running Connector. Members who share projects do. The Hub knowing a project path does not give it direct access to that machine.

## Quick start

### 1. Start a local Hub

Requires **Python 3.10+**. The local Connector currently targets **macOS and Linux**. Run these commands from a checkout of this repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
peerlink init-admin your-username
peerlink hub
```

Replace `your-username` with an actual username. `init-admin` securely prompts for a password. Open [localhost:8000](http://127.0.0.1:8000) and sign in with the username and password. Other members register on the web page and can sign in after administrator approval.

### 2. Connect a project

Sign in on the web page, generate a one-time code under **My devices**, then run locally:

```bash
peerlink connect --hub http://127.0.0.1:8000 --name my-laptop --code <pairing-code>
peerlink skill-install
peerlink catalog
peerlink project-add my-project /absolute/path/to/project --runtime mock
peerlink service-install
```

Administrators seed the cloud project catalog in the web interface. After pairing, each member uses `catalog` and binds the corresponding local directories on their own computer. Members propose additional catalog entries with `peerlink project-propose <id> '<description>'`; binding is allowed only after administrator approval. **Mock only demonstrates the collaboration flow.**

### 3. Try the approval flow

Use the web interface to select a member and their registered project, then submit a question. The project owner approves execution in the web interface and reviews the resulting draft locally in another activated terminal:

```bash
peerlink review
peerlink review REQUEST_ID
peerlink review REQUEST_ID --send
```

Replace `REQUEST_ID` with the ID shown by `review`. Run `--send` only after reviewing and explicitly approving the answer. The requester can then view the answer in the web interface.

**Deploying for a lab or team?** Follow the [deployment guide](docs/guide.md#1-deploy-a-shared-hub). Docker Compose and an HTTPS reverse-proxy example are included. A 4-vCPU / 8-GB server is a reasonable starting point for a trial group of fewer than 10 members, not a measured capacity guarantee. Model execution remains on member machines.

## Project status

| Capability | Current state |
| --- | --- |
| Request API, approval interface, local review, and CLI | Implemented; the web interface is currently in Chinese |
| Separate user/device credentials and persistent requests | Implemented |
| Web self-service registration and administrator approval | Implemented |
| Mock runtime | Automated end-to-end test coverage |
| Codex Docker adapter | Experimental; real runtime validation pending |
| Docker deployment configuration and Codex Skill | Included; not a one-click installer |
| Claude Code, MCP server, session recovery, and automatic replies in the original agent session | Not yet implemented |

The current Hub uses **SQLite WAL, a single service instance, and HTTP polling**. Each request starts an independent temporary agent session. Expired executions fail rather than being automatically reassigned.

## Security and trust

- Use Peerlink within a trusted group, preferably over a private network or VPN. Remote clients require HTTPS.
- Project registration sends location metadata, not repository contents, to the Hub. Questions and approved answers are stored there; unapproved drafts stay on the owner's machine.
- Local execution does **not** mean offline inference. Model services may receive project context, and the experimental runtime still needs model credentials and network access.
- The system trusts the local user and Connector. Human review is not a data-loss-prevention system, and it cannot protect against a compromised device.
- Public deployment needs further work on authentication, credential rotation, authorization policies, rate limiting, and operational security. See the [guide](docs/guide.md) before using sensitive projects.

## Documentation

| Guide | English | 简体中文 |
| --- | --- | --- |
| Administrator setup, approvals, catalog, and operations | [Administrator handbook](docs/admin-guide.md) | [管理员手册](docs/admin-guide.zh-CN.md) |
| Member registration, pairing, path mapping, and collaboration | [Member handbook](docs/member-guide.md) | [成员手册](docs/member-guide.zh-CN.md) |
| Installation, deployment, CLI, Skill, and security boundaries | [Full guide](docs/guide.md) | [完整指南](docs/guide.zh-CN.md) |
| Original phase-one design and scope | — | [方案文档](Peerlink-一期方案-精简版.md) |

API documentation is available at `/docs` on a running Hub; `/health` is the health-check endpoint.

## Roadmap

- [ ] Validate real Codex execution and Docker deployment on target machines.
- [x] Provide per-user Connector background installation and desktop notifications on macOS/Linux.
- [ ] Add Claude Code support and an MCP interface.
- [ ] Introduce safely isolated session recovery and response notifications.
- [ ] Strengthen authentication, access policies, auditing, and operations for broader use.

These are planned directions, not supported features or release commitments.

## Development and contributions

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

Tests cover authorization, approval transitions, task claiming, offline persistence, local path checks, and an HTTP + CLI + Mock Connector round trip. They do not establish real-model quality or production readiness.

Bug reports, reproducible deployment feedback, and focused contributions are welcome. Keep behavior changes covered by tests, update both README languages when changing user-facing instructions, and never include Tokens, private drafts, or sensitive project contents in reports.

Core code: [`peerlink/`](peerlink/) · Deployment: [`deploy/`](deploy/) · Skill: [`skills/peerlink/`](skills/peerlink/) · Tests: [`tests/`](tests/)
