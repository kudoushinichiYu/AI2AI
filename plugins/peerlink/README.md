# Peerlink Codex plugin

This plugin teaches Codex the human-approved Peerlink workflow. It uses the lightweight `peerlink` CLI installed on the same computer; account passwords and project files are never bundled into the plugin.

After installing the plugin and the current Peerlink client, pair the computer once from the signed-in Peerlink web page. Project owners can then install the background receiver:

```bash
peerlink service-install --auth-dir /path/to/dedicated-codex-auth-directory
peerlink service-status
```

The receiver starts at user login, notifies the user about incoming approval requests, and invokes the configured local runtime only after web approval. Generated answers remain local drafts until the project owner reviews and explicitly sends them.

The client checks the public release metadata when the Skill is used, and the background receiver checks periodically. It can notify about newer releases, but it never installs them silently. Members can review available versions on the Peerlink web page and confirm an update from Codex.

The current plugin uses the CLI through its Skill. A native MCP server and automatic delivery into an existing Codex conversation remain future work.
