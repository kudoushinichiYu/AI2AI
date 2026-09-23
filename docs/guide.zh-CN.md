# Peerlink 使用与部署指南

[English](guide.md) | **简体中文** | [管理员手册](admin-guide.zh-CN.md) | [成员手册](member-guide.zh-CN.md) | [返回项目首页](../README.zh-CN.md)

本文包含管理员部署、成员安装、协作流程、Skill、实验性 Codex 接入及运维说明。所有 shell 命令均在仓库根目录执行；带尖括号的参数需要替换为实际值。

> 本文仍保留旧版 Connector/Mock/Docker 操作细节。新成员请先按[新版成员手册](member-guide.zh-CN.md)使用 Bridge。0.5.0 已上线；公网 WSS Echo 测试的范围与未完成项见[迁移说明](peerlink-bridge-migration.zh-CN.md)。

Peerlink 是一个可自行部署的轻量级项目 Agent 协作工具，适用于学校实验室、研究小组和小型研发团队。团队部署一套共享服务，成员安装本地客户端，就能在本人授权下，让其他成员向自己的项目 Agent 提问。

**服务端统一管理身份、Agent 元数据和审批；本地 Bridge 在成员自己的项目中执行 Agent，答案经本人确认后才上传。** 本机绝对路径不发给云端。服务端可以部署在实验室服务器、团队内网服务器或云服务器，不要求使用公有云。

例如，实验室在一台共享服务器上部署 Peerlink，每位成员注册自己的研究项目。其他成员可以询问实验设置、代码结构或设计决策，项目负责人批准后，由其本地 Agent 整理答案，再由本人确认发送。成员既可以是提问方，也可以是项目提供方，不绑定任何特定人物或项目。

当前版本适合先在 10 人以内的受信任团队中试用，尚不是可直接暴露公网的生产服务。下面分为**管理员部署**和**成员使用**两部分；普通成员无需重复部署服务端。

项目名称为 **Peerlink**，命令和 Python 包名为 `peerlink`，配置变量统一使用 `PEERLINK_` 前缀。若已安装早期开发版本，请重新安装本项目并更新命令、环境变量和 Skill。已有数据库和设备配置不会自动迁移：可通过 `--db`、`--state` 显式指定原位置，或在停服备份后迁移至新的默认目录；不要误建空数据库或重复注册设备。

Compose 项目名也统一为 `peerlink`。已有 Compose 部署升级时，应使用 `docker compose -p <既有部署项目名> up -d --build` 保留原卷，或先迁移数据；直接使用新项目名会创建独立数据卷。

## 当前能用到什么程度

- 云端 API + 中文 Web 页面：联系人、注册项目查询、提问、批准/拒绝、取消和查看结果。
- 本地 Connector：注册设备和项目路径、审批后通知、轻量运行时轮询、本地草稿、人工确认发送。
- 用户名密码登录与设备凭证分离；设备无权批准请求或查询别人的请求。
- 本地 CLI 和可复制安装的 Skill；无需第一版就实现 MCP，Agent 可通过 CLI 提问及查结果。
- **推荐轻量模式 `codex-desktop`：通过 Codex 桌面端的 Peerlink Skill 处理已批准请求，无需 Codex CLI 或 Docker；需要安装 Peerlink CLI/Skill，用户主动调用，不会后台唤醒桌面应用。**
- Mock Runtime 已提供端到端测试，不读取项目、不调用模型；可选的 `codex-docker` 隔离适配器仍需在目标机器单独验证。

尚未实现：后台自动唤醒 Codex 桌面会话、Claude Code、MCP Server、Peer Session 恢复。后台 Connector 可通知请求获批，但成员要在 Codex Desktop 主动调用 Peerlink Skill。Docker 运行时使用独立临时会话；桌面 Skill 在当前会话中处理问题。

## 1. 管理员：部署共享服务

以实验室服务器为例，管理员只需部署一套 Hub，向成员提供访问地址和各自的登录凭证。

### 服务器部署（推荐团队使用）

4 核 8G 可作为 10 人以内协调服务的试用起点，但尚未经容量压测。服务器不运行成员的模型推理；Agent 执行资源和模型调用费用仍由成员侧承担。

在服务器安装 Docker Compose，取得本仓库后，在仓库根目录执行：

```bash
docker compose up -d --build
docker compose exec hub peerlink init-admin <管理员用户名>
```

命令中的 `<管理员用户名>` 是占位符。用户名支持 ERP 常见的字母、数字、点、下划线和短横线。`init-admin` 会在终端安全提示两次输入密码，不再生成登录 Token。

然后完成访问配置：

- Compose 只向服务器回环地址发布 8000 端口。安装 Caddy/Nginx，参考 `deploy/Caddyfile.example` 配置实验室域名和 HTTPS，再让成员访问该地址。
- 建议先限制在实验室内网或 VPN 内使用；即使在内网，远程客户端也要求 HTTPS，且不提供关闭 TLS 校验的选项。
- 向成员提供 **Hub 地址，以及项目源码或安装包的获取方式**。当前尚无公开发布的一键安装器。
- 成员在浏览器使用 ERP 用户名和密码注册。管理员批准后即可登录，再从“我的设备”生成一次性配对码。

登录会话由 HTTP-only Cookie 维持；可在“账号安全”中修改密码或撤销所有登录会话。

### 本机体验（可选）

如果需要复用已有容器、且不能中断其中的原服务，请参阅[已有容器部署说明](../deploy/existing-container/README.md)，使用独立虚拟环境及宿主机托管服务。

如果只想先在一台电脑上验证流程，可以不用 Docker。需要 Python 3.10+，以下命令在仓库根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
peerlink init-admin <管理员用户名>
peerlink hub
```

打开 `http://127.0.0.1:8000` 登录。模拟多人协作时创建不同账户，并使用不同浏览器窗口登录。默认数据库为当前目录的 `.peerlink/hub.db`，不要切换工作目录后误用另一份数据库。

## 2. 成员：安装客户端并连接团队服务

本地 Connector 面向 macOS / Linux，需要 Python 3.10+。可从 Hub 下载已发布客户端：

```bash
python3 -m pip install --user https://peerlink.jd.com/downloads/peerlink.whl
peerlink skill-install
```

登录网页，在“我的设备”生成 10 分钟有效的一次性配对码，然后连接：

```bash
peerlink connect --hub https://<团队服务域名> --name <本机设备名称> --code <配对码>
peerlink catalog
```

将 `<团队服务域名>` 替换为管理员提供的实际域名。仅在 Hub 和客户端位于同一台电脑时，使用 `http://127.0.0.1:8000`。一次性配对码使用后立即失效，不要把它写入文件或提交到 Git。

**只需要向别人提问**：配置完成后即可使用页面或 CLI，不必注册本地项目，也不必运行 Connector。

**希望别人向自己的项目提问**：继续注册设备及愿意开放协作的项目：

```bash
peerlink project-add <项目标识> /实际/项目/绝对路径 --runtime codex-desktop --description '项目简介'
peerlink service-install
```

管理员在网页冷启动项目目录；每位成员的 Codex 读取 `catalog` 后，对本人明确确认的项目上传“项目标识→本地绝对路径”绑定，不上传仓库内容。本机不存在的项目可跳过。新项目先用 `peerlink project-propose <id> '<说明>'` 申请，批准前无法绑定。

配对后的设备凭证也可以执行 `project-propose`，申请会进入 `PENDING` 等待管理员审批。管理员可将 `ACTIVE` 项目退役，也可重新启用；退役后该项目不再出现在可发现项目中，未完成请求会被取消并写入审计记录。

状态默认位于 `~/.peerlink`。配对后只保存可单独撤销的设备凭证，不保存账号密码。该设备凭证可用于提问和查收回复，但不能代替用户审批请求。

`service-install` 会安装 macOS launchd 或 Linux systemd 用户级服务，登录后自动运行，并在新问题、审批完成和收到回复时弹出系统通知。对 `codex-desktop` 项目，它只通知，不领取任务或自动唤醒 Codex Desktop；需要在桌面端主动调用 Peerlink Skill。用 `peerlink service-status` 检查状态。Hub 仍不能越过本人审批，也不能自动发送未审核草稿。

一期每个“用户＋项目”绑定一台设备。变更路径、Runtime 或设备前先用 `peerlink project-remove <项目标识>` 撤销，旧请求随之取消，再重新注册和发起请求。

## 3. 提问、审批、确认答案

### 提问方：向其他成员的项目提问

在页面选择成员和项目后提问，或者在已配对的电脑上调用：

```bash
peerlink peers
peerlink projects <对方用户名>
peerlink ask <对方用户名> <项目标识> '这个项目的实验设置和主要设计依据是什么？'
peerlink get <请求ID>
```

需要取消尚未结束的请求时，由提问方运行 `peerlink cancel <请求ID>`。

### 项目提供方：批准执行并审核答案

在共享服务页面查看问题，选择“批准本地执行”或拒绝。批准后，由自己的 Connector 在对应项目中执行 Agent。生成草稿后，在本机另一个终端激活相同虚拟环境，查看并确认：

```bash
peerlink review
peerlink review <请求ID>
peerlink review <请求ID> --send
# 或使用手动编辑过的文本
peerlink review <请求ID> --send --answer-file /实际/修改后的答案.txt
# 不允许分享时
peerlink review <请求ID> --reject
```

`--send` 是本人对该答案的明确发送确认，不应由无人值守脚本自动调用。当前信任本机用户和 Connector，不能防止已被攻陷的设备伪造该确认。

Hub 只收到“等待答案确认”状态，**未确认草稿不上传**。本地草稿含问题和执行租约，按私密资料保护；发送或终止后会保留 `.done` / `.stopped` 文件供排查，用户可自行删除。提问方用页面刷新或 `peerlink get` 收取结果，暂不自动注入原 Codex 会话。

## 4. 安装 Skill

Peerlink 客户端包含 Codex Skill，安装客户端后执行：

```bash
peerlink skill-install
```

重新加载 Codex 后，可直接说“通过 Peerlink 向某成员的某项目提问”或“查看 Peerlink 回复”。Skill 使用已配对设备的凭证，不保存账号密码，也不能替本人审批或发送草稿。

## 5. Codex 桌面端轻量接入

项目提供方绑定路径时推荐选择：

```bash
peerlink project-add <项目标识> /实际/项目/绝对路径 --runtime codex-desktop
peerlink service-install
```

不需要安装 Codex CLI、下载 Docker 虚拟机或构建 Peerlink 专用镜像；仍需安装 Peerlink CLI 和 Codex Peerlink Skill。`service-install` 是轻量本地通知/轮询服务：请求获批时通知成员，但不会自动启动、唤醒或控制 Codex Desktop。

收到通知后，在 Codex Desktop 中主动调用 Peerlink Skill。Skill 使用 `peerlink desktop-context <请求ID>` 检查审批状态和本机已绑定路径；路径必须与当前 Codex 工作区对应。Codex 读取相关文件并先展示答案。用户要求保存后，Skill 执行 `peerlink desktop-submit <请求ID>`：它才向 Hub 领取该请求并把答案保存为本地草稿，答案正文仍不上传。最后由用户运行 `peerlink review <请求ID>` 检查，并在明确确认后运行 `--send`。

**桌面模式的边界：** Codex Desktop 只能在其自身已授权的工作区/文件访问范围内读取本地项目；Peerlink 能验证注册路径，但不能像容器那样强制系统级文件隔离。只对可信团队开放项目，按 Codex Desktop 的权限提示确认访问范围。OpenAI 说明 Codex Desktop 可打开本地文件夹并在用户授予权限后处理本地文件，参见[桌面端使用说明](https://help.openai.com/en/articles/20001275/)；当前没有依赖桌面 UI 自动化的后台唤醒功能。

## 6. 可选：Codex Docker 隔离运行时（实验性）

仅设置 `codex --sandbox read-only` 不代表只能读项目目录。因此该适配器不直接在宿主机运行 Codex，而是在本地 Docker 容器里挂载项目只读目录，不挂载整个 Home、SSH 密钥、Docker Socket 或其他项目。

1. 安装并启动 Docker，以及一个支持下述参数的 Codex 版本。
2. 准备一个**专用 CODEX_HOME 认证目录**，使用 Codex 的登录方式生成 `auth.json`；不要把个人完整 `~/.codex` 复制进去。此版本仅支持标准认证，不自动迁移自定义模型路由、MCP、插件或代理配置。
3. 按已核对的版本构建镜像，不隐式安装 latest：

```bash
docker build -f deploy/codex.Dockerfile --build-arg CODEX_VERSION=<已核对的版本号> -t peerlink-codex:local .
peerlink project-remove <项目标识>
peerlink project-add <项目标识> /实际/项目/绝对路径 --runtime codex-docker
peerlink work --auth-dir /实际/专用认证目录
```

只有已经注册过该项目时才需要先撤销旧注册。如果已有 Connector 正在运行，请先停止旧进程，再启动新 worker。

容器设置只读根文件系统、项目只读挂载、去除 capabilities、限制内存/CPU/进程数和五分钟执行超时。Codex 使用显式只读沙箱、关闭交互式执行批准、忽略用户配置及规则文件、临时会话，不使用绕过沙箱参数。取消/撤销通过续期检查传播，正常联网下约 15 秒内发现并停止执行；断网时不能保证立即收到取消，云端仍拒绝过期结果。

**剩余边界：** 容器内仍有模型认证材料，模型服务调用会出网，注册项目内部也可能包含秘密。请选择经过清理的共享项目目录，使用专用最小权限模型凭证；这不是严格的数据防泄漏系统。正式接入敏感仓库前，还需要凭证代理、网络出口控制和独立安全验收。模型生成答案仅由本人审核后发送，不自动信任模型判断。

适配参数参考：[Codex 非交互执行官方文档](https://developers.openai.com/codex/noninteractive)。Docker 镜像和真实模型调用必须在目标机器上另行验收，Mock 流程通过不能证明真实模型适配已通过。

## 7. 管理员：运维、备份与迁移

- 数据位于持久化卷 `hub-data`。重建容器不会丢数据，`docker compose down -v` 会删除数据，不要误用。
- 数据库备份建议用 SQLite 在线 backup API；不要只复制正在使用中的 `.db` 而遗漏 WAL。迁移现有数据库时，先停服务或制作一致性备份，再恢复到卷中的 `/data/hub.db`，确保容器 UID 10001 可读写。URL 更改也需要更新每位用户本地配置中的 `hub`。
- 实验室服务器需要允许成员设备通过 HTTPS 访问 Hub。仅部署 Hub 不会把成员项目或模型环境迁移到服务器，也不会让离线的个人设备继续执行任务。

当前使用 **SQLite WAL + 单实例 Hub**；新 Bridge 使用出站 WebSocket，旧 Runtime 在迁移期仍使用 HTTP 轮询。不做自动租约接管：执行超时标记失败，重新提问需重新审批，以避免失联的旧进程和新设备重复执行。

正式对外前还需：SSO/短期凭证及轮换、联系人权限策略、注册防滥用、限流、数据保留与清理、审计查询、监控告警、备份恢复演练、并发压测和前端浏览器验收。当前所有已批准用户属于同一受信任试用组，可看到项目名称并发起请求，但执行仍需本人批准；管理员审批是人工信任判断，不能替代身份验证。

## 8. 开发与验证

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

测试覆盖 API 权限、项目路径不向其他用户展示、未批准不执行、草稿不上传、并发唯一领取、Hub 重启后请求留存、取消/过期/撤销后的结果拒收、本地路径校验和真实 HTTP + CLI + Mock Connector 端到端流程。

目录：`peerlink/hub.py` 云端接口；`peerlink/connector.py` 本地执行与审核；`peerlink/cli.py` 命令入口；`peerlink/static/` 审批页面；`deploy/` 部署示例；`skills/` Agent 调用指南；`tests/` 自动化测试。
