# Peerlink 本地 Agent 通信桥重构进度

[目标方案](peerlink-local-agent-bridge-proposal.zh-CN.md) | [项目首页](../README.zh-CN.md)

## 当前系统

旧版 `peerlink/hub.py` 同时承担账号、设备、项目目录、请求审批、HTTP 轮询领取任务和结果存储；`peerlink/connector.py` 管理本机项目映射、通知、Mock/Docker 执行和草稿。本轮已在同一个 Hub 中增加 Relay 路由和本机 Bridge；旧请求路径在迁移期保留。Remote MCP 尚未实现。

## 目标差异与保留模块

| 职责 | 当前 | 目标与迁移处理 |
| --- | --- | --- |
| 身份和设备 | 用户名密码、管理员审批、一次性设备配对 | 保留；Bridge 复用设备凭证 |
| 项目映射 | Hub 的 `projects` 表保存本地绝对路径 | 新 Agent 注册只上传名称、描述、设备和访问策略；路径留在本机。旧表及旧 API 需要兼容迁移并清理已有路径 |
| 通信 | Connector 每 3 秒 HTTP 轮询 | 新 Bridge 主动建立 WSS；Relay 仅向在线设备推送，断线重连。旧轮询可在迁移期保留 |
| 本地执行 | Mock 或实验性 Docker 适配器；桌面 Skill 需成员主动处理 | 抽象 Backend；先 Echo，再以独立 Codex app-server 进程接入。Docker 降为可选兼容路径 |
| 问答数据 | Hub 长期保存问题和最终答案 | 新协议使用限时消息；超时清理。旧请求历史须先制定保留和迁移策略，不直接删除 |
| 分享许可 | 每条请求执行前由接收方审批，草稿发送前再次审核 | 新 Bridge 延续同样的逐条审批与审核；Agent 默认不向其他成员开放 |
| ChatGPT 入口 | Codex Skill 通过 Peerlink CLI 调用 Hub | 新增 Remote MCP，提供发现 Agent、发送消息和查询结果；Skill 继续可用 |

## 实施顺序与独立验收点

1. **Protocol**：定义带 `message_id` 的 Agent 消息和响应，约束大小、状态与幂等。
2. **Relay**：增加设备 WebSocket、在线状态、Agent 元数据注册、在线路由与限时消息；不接收本地路径。
3. **Bridge**：本地 Agent 注册表、SQLite 消息去重和线程映射、设备主动连接及断线重连。
4. **Echo Backend**：在两位独立账号间验证发送、审批、路由、去重、本地草稿、审核发送和离线错误，不需要 Docker 或模型。
5. **Codex Backend**：调用本地 Codex app-server 的公开协议，强制项目工作目录、只读沙箱、执行超时和独立线程；在目标机器做真实模型验证。
6. **MCP 与发布**：将发现、发送、查询封装为远程工具，接入 ChatGPT/Codex；准备安装包和迁移指南。

## Codex 桌面端的实际边界

OpenAI 官方文档中的 [Codex app-server](https://developers.openai.com/codex/app-server) 是独立的本地进程，官方示例通过 `codex app-server` 启动。它提供线程、Turn、事件和审批协议；文档并未提供向已经打开的 Codex 桌面会话直接注入消息的接口。因此自动回复的 Codex Backend 需要可用的 app-server 可执行程序及其认证，Bridge 可以负责启动它，成员无需手动运行命令。只有 Codex 桌面应用而没有可用 app-server 时，保留现有的桌面 Skill 人工处理方式，不能称为无人值守自动答复。

## 本轮边界

不在第一轮实现 E2EE、离线队列、Peerlink 桌面应用、多 Agent 编排，也不在未经验证的情况下替换线上 Hub。新旧路径并存，在线部署前需要数据库备份、客户端升级和双机端到端测试。

## 0.5.0 实现与上线进度

- 已保存目标方案并保留 Peerlink 品牌、包名和 CLI。
- 已实现 Agent/Response 协议、路径不入云的 Agent Registry、出站 WebSocket Relay/Bridge、在线发现、默认私有访问范围、消息 ID 幂等、24 小时延迟清理和本机 SQLite 去重/线程映射。
- 已接入 Echo Backend、Codex app-server 协议适配、CLI、网页提问与绑定入口、后台服务、Codex Skill 说明。新请求仍使用“网页逐条批准 → 本机起草 → 本人审核发送”。
- 已通过 TestClient 双用户审批闭环、真实本机 HTTP/WebSocket Bridge 链路以及模拟 app-server 进程的协议测试。线上公网 WSS Echo 闭环也已通过；尚未对真实 Codex 模型回合和两台不同成员电脑做验收。
- Remote MCP 尚未实现。ChatGPT 的远程 MCP 接入还需要按 [OpenAI MCP 认证要求](https://developers.openai.com/plugins/build/auth)设计 OAuth 2.1，并通过公网 HTTPS 安全暴露；不能把现有设备 Bearer Token 当作 ChatGPT 用户授权方案。

现有 `codex app-server` 的只读沙箱禁止写入和工具侧网络访问，但当前本机协议没有可验证的“仅可读取某一个项目目录”强制边界。Bridge 用固定项目工作目录和提示词限制读取范围，**这不是操作系统级文件隔离**；敏感项目在补齐强隔离与真实执行验收前，不应启用自动 Codex Backend。Echo 联通测试不读取项目文件。

升级旧 Hub 前必须先停写并备份数据库：启动新版本会清空旧 `projects.path` 字段里的绝对路径；路径应从各成员本机 `connector.json` 读取，不能从云端恢复。旧请求历史不会主动删除，新 Bridge 请求按保留期清理。Relay 连接状态目前存于单进程内存，因此不能直接把 Hub 扩成多个 worker 而不增加共享路由层。

新客户端为每个 `--state` 使用独立的 macOS/Linux 后台服务名，支持同一电脑上的多个账号。若旧版固定名称的 Connector 服务仍在运行，升级前先用旧版的 `peerlink service-remove` 停掉旧服务，再按各账号状态目录分别执行新版 `service-install`，避免两个版本同时接收任务。

## 2026-09-23 本机身份与双向链路实测

- 状态目录：`~/.peerlink-yujunjie.50`；本机配置的 ERP 身份为 `yujunjie.50`。使用该设备凭证只读访问现有线上 Hub 的联系人、项目目录、请求 API 成功，证明凭证仍有效；未打印或提交 Token。
- 使用同一设备凭证启动新版 Bridge，连接一次性的本机 Relay：Bridge 的 WebSocket 心跳上行到达 Relay；Relay 下发的 `agent.approval_requested` 通知由 Bridge 接收。通过 HTTP 创建的自发自收探针保持 `WAITING_APPROVAL`，未经本人网页审批没有进入执行，随后由发送方取消。测试数据和凭证副本只存在于临时目录，测试退出即清理。
- 可复测命令：在仓库根目录运行 `./.venv/bin/python scripts/verify_local_bridge_link.py --state ~/.peerlink-yujunjie.50 --owner yujunjie.50`。脚本只连接本机临时 Relay，不创建或修改线上请求。
- 此项是上线前的本机测试，当时线上仍为 `0.4.0`；上线后的验证结果见下一节。

## 2026-09-23 线上重新部署与 Echo 闭环

- 已在停止 Peerlink 服务后备份旧 SQLite 数据库，并在独立发布目录上线 Hub/Relay 0.5.0；公开版本 API、网页和 CLI wheel 均已更新。原 `jdme-bot` 容器未重启，原服务健康检查仍为 HTTP 200。旧请求保留；旧 `projects.path` 云端绝对路径按迁移设计清空，备份可用于核对历史值。
- 线上服务器以非 root 身份运行全量测试：70 项通过。公网 `wss://peerlink.jd.com/api/bridge/ws` 配对设备握手和心跳通过。
- 使用 `yujunjie.50` 的已配对设备创建临时**私有 Echo Agent**，对现有 `ai-outbound` 目录发送明确标记的测试请求 `81a29fab7282eca2c9c66c01`。本人在网页批准后，本机 Bridge 接收并生成草稿；本人运行 `peerlink review ... --send`，线上请求最终为 `COMPLETED`，回文精确匹配。临时 Agent 已移除；测试没有读取真实项目文件。
- 这证明了公网 WSS 下行、HTTP 审核上行及逐条人工确认闭环；**不证明**真实 Codex 模型回答、不同成员间双机通信或项目目录访问隔离。下一验收应由两位成员各自升级当前客户端、显式绑定测试项目，先做 Echo 双机，再在安全边界确认后测试真实 Codex Backend。

## 2026-09-24 wheel 安装说明勘误

线上 0.5.0 的网页复制按钮和 `update-check` 仍把 `/downloads/peerlink.whl` 用于 `pip install`。该浏览器下载别名虽然返回 HTTP 200，URL 文件名却不符合 wheel 命名规则，pip 在安装前报 `Invalid wheel filename`。**本轮只修文档，不发布新安装包或改线上网页。** 请从[成员手册](member-guide.zh-CN.md)复制带版本号的 `/downloads/peerlink-0.5.0-py3-none-any.whl` 安装命令；已用真实 pip 从公网安装验证。已暴露在截图或聊天中的一次性配对码应废弃并重新生成。

**已确认的产品决策：** 新 Bridge 保持每条请求由项目提供方本人批准，答案由本人审核并确认发送。因此“电脑在线即可完全自动回答并分享”不是这一版的行为；后台常驻解决的是接收与执行启动，不代替两次人工确认。
