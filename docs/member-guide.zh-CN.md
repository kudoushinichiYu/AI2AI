# Peerlink 成员手册

[管理员手册](admin-guide.zh-CN.md) | [English](member-guide.md) | [完整使用指南](guide.zh-CN.md) | [返回项目首页](../README.zh-CN.md)

本手册面向普通成员和项目负责人，覆盖注册、安装 Codex 插件、设备配对、项目路径绑定、提问和回复。

## 1. 注册与登录

1. 打开 [https://peerlink.jd.com/](https://peerlink.jd.com/)。
2. 使用自己的 ERP 用户名和独立密码提交注册。
3. 等待管理员批准。
4. 批准后使用同一用户名和密码登录。

不要使用他人账号，也不要把密码提供给 Codex。Codex 只使用一次性配对码绑定这台电脑。

## 2. 安装轻量客户端和 Codex 插件

需要 Python 3.10+ 的 macOS 或 Linux。

```bash
python3 -m pip install --user https://peerlink.jd.com/downloads/peerlink-0.2.1-py3-none-any.whl
codex plugin marketplace add kudoushinichiYu/peerlink --ref main
codex plugin add peerlink@peerlink-team
```

安装后新建一个 Codex 任务，使插件与 Skill 生效。可用以下命令检查：

```bash
peerlink --help
peerlink status
codex plugin list
```

`status` 在未配对时会提示没有本地配置，这是正常状态。

## 3. 配对这台电脑

1. 登录 Peerlink 网页。
2. 在“我的设备”点击“生成设备配对码”。
3. 在十分钟内对 Codex 说：“帮我绑定 Peerlink，配对码是 ……”。

Codex 会调用：

```bash
peerlink connect --hub https://peerlink.jd.com --name <设备名称> --code <配对码>
```

配对码仅限一次。本机最终只保存 `~/.peerlink/connector.json` 中的设备凭证；不要打印、上传或提交该文件。

## 4. 首次绑定项目路径

配对后，对 Codex 说：“用 Peerlink 完成本机项目初始化。”Codex 会先读取：

```bash
peerlink catalog
```

然后逐个向你确认本地路径和 Runtime。你可以跳过本机没有或不愿分享的项目。确认后会执行：

```bash
peerlink project-add <项目标识> /本地/绝对路径 --runtime <mock|codex-docker> --description '<说明>'
```

- 不允许绑定 `/` 或整个 Home 目录。
- 云端只收到路径映射和说明，不会因此上传仓库内容。
- `mock` 只用于流程验证；`codex-docker` 需要单独准备镜像和专用认证目录。

## 5. 申请新项目

云端目录中没有目标项目时，可在网页填写项目标识和说明，或执行：

```bash
peerlink project-propose <项目标识> '<项目说明>'
```

申请状态为 `PENDING`。管理员批准后，重新运行 `peerlink catalog`，再绑定本地路径。

## 6. 向其他项目提问

可以直接对 Codex 说：“通过 Peerlink 向 owner 的 ai-outbound 项目询问……”Codex 会先确认成员和项目：

```bash
peerlink peers
peerlink projects <成员>
peerlink ask <成员> <项目标识> '<问题>'
```

提交后保留请求 ID。查询进度和答案：

```bash
peerlink requests
peerlink get <请求ID>
```

只有 `COMPLETED` 且包含 `response` 时才是最终答案。

## 7. 安装后台 Connector

项目提供方只需安装一次轻量后台服务，之后登录电脑时会自动启动：

```bash
peerlink service-install --auth-dir /实际/专用/Codex认证目录
peerlink service-status
```

它会定期向 Hub 查询本人的任务，收到待审批问题、本地草稿完成或自己的问题收到回复时，弹出 macOS/Linux 系统通知。后台服务不能自动批准问题，也不能自动发送草稿。

如果只做 Mock 流程验证，可以不传 `--auth-dir`。不再共享本机项目时，可运行 `peerlink service-remove`。

## 8. 处理别人对自己项目的问题

1. 在网页审查问题，由本人批准或拒绝执行。
2. 后台 Connector 会自动读取已批准任务。如果没有安装后台服务，可手动运行一次：

   ```bash
   peerlink work --once
   ```

3. 检查本地草稿：

   ```bash
   peerlink review
   peerlink review <请求ID>
   ```

4. 只有在阅读并明确确认答案可以分享后，才执行：

   ```bash
   peerlink review <请求ID> --send
   ```

Codex 不能替你批准请求，也不能把未经阅读的草稿自动发送。

## 9. 常见问题

- **`peerlink: command not found`**：重新安装客户端，并确认用户级 Python bin 目录在 `PATH` 中。
- **配对码无效**：配对码已过期或使用过，在网页重新生成。
- **项目无法绑定**：先确认 `peerlink catalog` 中项目为 `ACTIVE`。
- **请求一直等待**：接收方尚未批准，或其 Connector 没有在线。
- **设备凭证失效**：在网页重新配对，不要恢复旧 Token。

更详细的 Docker Runtime、运维和安全边界见[完整指南](guide.zh-CN.md)。
