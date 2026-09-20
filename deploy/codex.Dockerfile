FROM node:22-bookworm-slim
ARG CODEX_VERSION
RUN test -n "$CODEX_VERSION" && npm install -g @openai/codex@${CODEX_VERSION}
ENV HOME=/tmp CODEX_HOME=/tmp/codex
WORKDIR /workspace
ENTRYPOINT ["sh", "-c", "mkdir -p /tmp/codex && cp /credentials/auth.json /tmp/codex/auth.json && exec timeout --signal=TERM --kill-after=10s 300s codex -a never exec --ignore-user-config --ignore-rules --sandbox read-only --ephemeral --skip-git-repo-check --color never -C /workspace -"]
