# Peerlink administrator handbook

[Member handbook](member-guide.md) | [简体中文](admin-guide.zh-CN.md) | [Full guide](guide.md) | [Project home](../README.md)

This handbook covers Hub initialization, account approval, the governed project catalog, device handling, and routine operations. Members remain responsible for their own local paths and Codex environments.

## Administrator workflow

1. Sign in at [https://peerlink.jd.com/](https://peerlink.jd.com/) with the administrator username and password. Do not share the account or store credentials in Git.
2. Seed known projects under **Cloud project catalog**. Use stable IDs containing letters, digits, underscores, or hyphens. Administrator-created entries become `ACTIVE` immediately.
3. Review `PENDING` member registrations. Approval grants Hub membership; it does not grant access to another member's local files.
4. Review member-proposed catalog entries. Check for duplicate IDs and clear descriptions. Members cannot bind a local path until the proposal is approved.
5. Ask members to pair their own devices and explicitly bind active catalog projects to local directories. Cloud Agent metadata contains only IDs, descriptions, devices, and access scope, never an absolute local workspace path or repository contents.
6. Revoke unused devices. Revocation removes that device's bindings and cancels its unfinished work.
7. Disable a departing or compromised member from **User management**. This revokes their sessions, devices, and bindings and cancels unfinished requests; re-enabling the account requires the member to pair again. The last active administrator cannot be disabled.
8. Retire a project that should no longer accept requests. Its unfinished requests are cancelled and audited; the project can be reactivated later.

Project owners, including administrators, must personally approve incoming execution and explicitly confirm any answer before it is shared. Administrator status does not authorize overriding another owner's approval.

## Operations

```bash
ssh test-198 'systemctl status peerlink-hub --no-pager'
curl -sS https://peerlink.jd.com/health
```

Restart only `peerlink-hub`, not the existing `jdme-bot` container. Use SQLite online backup or stop Peerlink before copying all database files. See the [full guide](guide.md) for deployment, upgrade, backup, and security details.

## Routine checklist

- Health endpoint and web page are reachable.
- Pending members have been identity-checked.
- Catalog IDs are stable, unique, and free of secrets.
- Pending project proposals have been reviewed.
- Unused devices have been revoked.
- No password, session, pairing code, or device credential is stored in Git.
