# Peerlink 成员手册

[管理员手册](admin-guide.zh-CN.md) | [English](member-guide.md) | [完整指南](guide.zh-CN.md) | [返回项目首页](../README.zh-CN.md)

准备和另一位成员第一次联调？先看[两台电脑、两个账号的 Echo 测试操作单](two-member-echo-test.zh-CN.md)，再按本文了解完整功能。

Peerlink 把云端项目名册与本机 Agent 分开：服务器只负责账号、审批和转发；项目路径与执行留在成员电脑。每条请求必须由项目负责人在网页批准，生成的草稿也必须由本人审核后发送。

> **发布状态：** Bridge 0.5.0 与 CLI wheel 已发布到 `peerlink.jd.com`；一次公网 WSS Echo 请求完成了本人批准和审核发送。已有旧版 CLI 或插件的成员须先更新再使用 `agent add`；真实 Codex 模型和两个不同成员的实测仍待完成。

## 1. 注册、安装和配对

1. 打开 [Peerlink](https://peerlink.jd.com/)，用自己的 ERP 用户名和 Peerlink 密码申请注册，等待管理员批准。
2. 在 macOS 或 Linux 上安装 Python 3.10+ 和 Peerlink 轻量客户端：

   ```bash
   python3 -m pip install --user https://peerlink.jd.com/downloads/peerlink.whl
   peerlink skill-install
   peerlink status
   ```

   在 Codex 桌面端新建任务后即可使用 Peerlink Skill；不需要另外安装 Codex CLI 插件。后续更新 CLI 后运行 `peerlink skill-install --force` 更新 Skill，安装前先确认来源与版本。
3. 在网页“连接这台电脑”生成一次性配对码，按网页生成的命令运行 `peerlink connect`。密码不交给 Codex，配对码只使用一次。

多账号分别使用独立 `--state`，例如 `~/.peerlink-yujunjie.50`。以后所有 Peerlink 命令必须显式传同一 `--state`，或在当前终端设置 `PEERLINK_STATE`。从 Dock 启动的 Codex 不会继承此前终端的环境变量；请让 Skill 显式使用正确状态目录。不要打印或上传其中的 `connector.json`。

## 2. 首次开放本机项目

先运行 `peerlink catalog` 查看管理员已创建或批准的项目。逐个决定是否开放，不必把本机所有项目都注册。

推荐的轻量 Bridge 联通测试：

```bash
peerlink agent add ai-outbound /本机/AI外呼目录 --backend echo --visibility team
peerlink service-install
peerlink service-status
```

`echo` 不读取项目、也不调用模型，只用于验证两台电脑之间的审批与消息链路。确认链路正常且本机有支持 `codex app-server` 的可执行程序后，改用 `--backend codex-app-server` 注册真实本地 Agent。该模式启动**独立的本机 app-server 进程**；它不会唤起或操作已打开的 Codex 桌面会话，也不需要 Docker。仅安装 Codex 桌面应用而没有 app-server 可执行程序时，请使用下面的手动 Skill 模式。

`--visibility private` 是默认值，只能本人测试；要让其他成员提问，使用 `team` 或 `allowlist --allow-user <ERP用户名>`。本机路径只保存在 `agents.json`，不会作为 Agent 元数据发到服务器。不要注册 `/`、整个 Home 或凭证目录。服务需要电脑保持在线；Bridge 仅主动连接服务器，不在本机开放监听端口。

如果只有 Codex 桌面端、没有 app-server 可执行程序，可继续手动回答：

```bash
peerlink project-add ai-outbound /本机/AI外呼目录 --runtime codex-desktop
peerlink service-install
```

此模式在网页批准后，由你在已打开对应项目的 Codex 桌面任务中调用 Peerlink Skill；后台服务只通知，不会自动唤醒现有任务。旧版 `codex-docker` 是可选实验模式，不是新成员的默认安装步骤。

云端目录缺少项目时，先在网页申请或运行 `peerlink project-propose <项目标识> '<说明>'`，等待管理员批准后再绑定本机目录。

## 3. 提问与查看答案

网页“提问与请求”会列出可访问的项目及 Bridge 在线状态。也可以让 Codex Skill 调用：

```bash
peerlink peers
peerlink projects <成员ERP用户名>
peerlink ask <成员ERP用户名> <项目标识> '<问题>'
peerlink requests
peerlink get <请求ID>
```

`peerlink ask` 对新 Bridge Agent 自动使用 Relay 消息接口；`peerlink send` 可显式指定 `--thread` 和 `--message-id`。只有状态 `COMPLETED` 且含 `response` 才是最终答案。私有 Agent 对其他人不可见；对方设备离线时，新 Bridge 请求会明确报 `DEVICE_OFFLINE`，而非假装已送达。

## 4. 处理别人发来的问题

1. 在网页逐条查看问题，由本人批准或拒绝。Bridge 获批后才把具体问题交给本机执行；未批准的请求不会自动运行。
2. Bridge Echo 或 Codex app-server 执行完只在本机保存草稿，服务器此时只知道“草稿待审核”，看不到正文。收到通知后运行：

   ```bash
   peerlink review
   peerlink review <请求ID>
   ```

3. 本人读完并确认可分享，才执行 `peerlink review <请求ID> --send`；不应分享则用 `--reject`。不要让自动化代替本人批准或发送。

手动 `codex-desktop` 模式：网页批准后，在 Codex 桌面端调用 Skill。Skill 用 `peerlink desktop-context <请求ID>` 核对项目、授权路径和状态，阅读相关文件，先向你展示答案；你确认保存后才用 `peerlink desktop-submit <请求ID>` 保存本地草稿。之后仍按上面的 `review` 两步审核、发送。

## 5. 常见问题

- `peerlink: command not found`：确认 Python 用户级 bin 目录在 `PATH` 中。
- 项目无法注册：先确认 `peerlink catalog` 中项目为 `ACTIVE`。
- Agent 不可见：检查可见范围、成员是否激活及设备是否在线。
- `DEVICE_OFFLINE`：在项目提供方电脑上检查 `peerlink service-status` 与 Bridge 日志。
- 只有 Codex 桌面应用却无法自动回答：选用手动 `codex-desktop`；自动起草需要独立可执行的 `codex app-server`。
- 配对码无效：在网页重新生成；配对码十分钟有效且仅能用一次。

完整设计与当前阶段边界见[本地 Agent Bridge 迁移说明](peerlink-bridge-migration.zh-CN.md)。
