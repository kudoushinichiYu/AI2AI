# Deploying inside an existing container / 复用已有容器

This is an alternative to starting a new Compose service. It requires a Linux container with Python 3.10+, an existing persistent bind mount, and a systemd-managed Docker host. It does not require Docker-in-Docker or replacing the container's main process.

这是新建 Compose 服务之外的一种部署方式：在已有 Linux 容器中以独立进程运行 Hub。需要 Python 3.10+、已有持久化挂载，以及使用 systemd 的 Docker 宿主机。无需嵌套 Docker，也不替换原容器的主进程。

## Isolation / 隔离原则

- Use a dedicated directory beneath an existing persistent mount. Keep source releases and a separate virtual environment under `releases/<release>/`, with `current` pointing to the selected release.
- Keep `data`, `run`, `home`, and `private` alongside `current`. These directories should belong to a dedicated non-root UID/GID and use mode 700. Source and virtual-environment files must be readable by that UID.
- Run with `env -i` so credentials belonging to the original application are not inherited through environment variables. Do not install dependencies into its global Python environment.
- Pick an unused container port. Do not recreate an existing container merely to add a published port; use an SSH tunnel or an approved HTTPS proxy instead.

在已有挂载下创建独立发布目录和虚拟环境；数据、运行状态、私密凭证单独持久化并由非 root 用户持有。清空继承环境变量，不复用原服务的凭证，不修改全局依赖，也不为增加端口映射而重建容器。

This is process/dependency isolation, not a hardened security boundary against the container administrator. The container's other workloads share its kernel namespace and resource budget. For stronger isolation, deploy Peerlink in its own container instead.

这种方式提供进程和依赖隔离，不构成针对容器管理员的强安全边界；不同服务仍共享容器资源。需要更强隔离时，应使用独立容器。

## Service management / 服务托管

1. Build the client wheel from the source checkout with `./scripts/build_wheel.sh` (uses `uv build` when `uv` is installed; otherwise install the `build` package first). The script writes `dist/peerlink-<version>-py3-none-any.whl`; copy that artifact to the Hub's `downloads/` directory as `peerlink-<version>-py3-none-any.whl`. The Hub serves it from the stable URL `/downloads/peerlink.whl`. Install `requirements.lock` into the release's virtual environment, then install the server package with `pip install --no-deps <release-directory>`. Use the environment's trusted package mirror if necessary.

2. Run the test suite in that environment before activation. Older Docker versions may not support `docker exec --workdir`; use absolute paths instead.
3. Copy [the service example](peerlink-hub.service.example), replacing `@CONTAINER@`, `@ROOT@`, `@UID@`, and `@GID@` with the verified container name, container-visible persistent root, and dedicated numeric user/group IDs. Do not leave placeholders in the installed unit.
4. Install it as `/etc/systemd/system/peerlink-hub.service` on the Docker host, then run `systemctl daemon-reload` and `systemctl enable --now peerlink-hub`.
5. Check `/health`, restart only the new service, verify persistence, and verify the original application still runs.

在源码仓库根目录运行 `./scripts/build_wheel.sh`，生成 `dist/peerlink-<版本>-py3-none-any.whl`。打包源码归档时需保留这个 wheel 于 `dist/`；首次引导脚本会将与源码版本匹配的 wheel 复制到 Hub 下载目录，成员通过稳定地址 `/downloads/peerlink.whl` 安装。首次引导脚本不会覆盖已存在的 `peerlink-hub.service`。

先在独立虚拟环境安装并测试；替换服务模板中的容器、挂载路径、UID/GID 后，将 unit 安装到宿主机。启用后验证健康检查、服务重启、数据留存及原服务健康状态。不要改动原容器的启动命令。

[`manage.py`](manage.py) holds an exclusive process lock, records the container PID and process start time, and verifies process identity before sending a shutdown signal. The host unit supervises `docker exec`; expected SIGTERM exit code 143 is treated as a clean shutdown.

`manage.py` 通过独占锁防止同实例重复启动，停止前校验 PID、进程启动时间和命令身份，避免误杀其他进程。宿主机 unit 管理 `docker exec`，将正常 SIGTERM 对应的 143 状态视为正常退出。

## Access / 访问方式

For initial evaluation, bind an SSH tunnel to localhost:

```bash
ssh -N -L 127.0.0.1:18083:CONTAINER_IP:18083 SSH_HOST
```

Replace `CONTAINER_IP` and `SSH_HOST` with verified values. Open `http://127.0.0.1:18083` on that client and set `PEERLINK_HUB` to the same URL. HTTP stays on loopback or the private container network; the remote transport is SSH-encrypted. Recheck the container IP if the container is recreated.

初次验证可以使用仅绑定本机的 SSH 隧道，浏览器和客户端均访问 `http://127.0.0.1:18083`。SSH 承担远程传输加密，容器重建后需重新确认容器 IP。多人正式接入仍建议配置受信任的 HTTPS 地址。

Only the Hub moves to the shared server. Members sharing local projects still run their own Connector. Installing this service does not automatically configure real model credentials, register projects, or validate an experimental runtime.

迁移到共享服务器的是 Hub；开放本地项目的成员仍需运行各自的 Connector。此部署不会自动配置真实模型凭证、注册项目或完成实验性 Runtime 验收。
