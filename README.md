# Peerlink

Peerlink 是一个可自行部署的轻量级项目 Agent 协作工具，适用于学校实验室、研究小组和小型研发团队。团队部署一套共享服务，成员安装本地客户端，就能在本人授权下，让其他成员向自己的项目 Agent 提问。

**服务端统一管理身份、项目映射和审批；本地 Connector 在成员自己的项目中执行 Agent，答案经本人确认后才上传。** 服务端可以部署在实验室服务器、团队内网服务器或云服务器，不要求使用公有云。

例如，实验室在一台共享服务器上部署 Peerlink，每位成员注册自己的研究项目。其他成员可以询问实验设置、代码结构或设计决策，项目负责人批准后，由其本地 Agent 整理答案，再由本人确认发送。成员既可以是提问方，也可以是项目提供方，不绑定任何特定人物或项目。

当前版本适合先在 10 人以内的受信任团队中试用，尚不是可直接暴露公网的生产服务。下面分为**管理员部署**和**成员使用**两部分；普通成员无需重复部署服务端。

项目名称为 **Peerlink**，命令和 Python 包名为 `peerlink`，配置变量统一使用 `PEERLINK_` 前缀。若已安装早期开发版本，请重新安装本项目并更新命令、环境变量和 Skill。已有数据库和设备配置不会自动迁移：可通过 `--db`、`--state` 显式指定原位置，或在停服备份后迁移至新的默认目录；不要误建空数据库或重复注册设备。

Compose 项目名也统一为 `peerlink`。已有 Compose 部署升级时，应使用 `docker compose -p <既有部署项目名> up -d --build` 保留原卷，或先迁移数据；直接使用新项目名会创建独立数据卷。

## 当前能用到什么程度

- 云端 API + 中文 Web 页面：联系人、注册项目查询、提问、批准/拒绝、取消和查看结果。
- 本地 Connector：注册设备和项目路径、轮询领取已批准请求、租约续期、本地草稿、人工确认发送。
- 用户 Token 和设备 Token 分离；设备无权批准请求或查询别人的请求。
- 本地 CLI 和可复制安装的 Skill；无需第一版就实现 MCP，Agent 可通过 CLI 提问及查结果。
- **Mock Runtime 已提供端到端测试，不读取项目、不调用模型；Codex Docker 适配器需在安装 Docker、配置专用认证后单独验证。**

尚未实现：Claude Code、MCP Server、原会话自动推送、Peer Session 恢复、自动更新/一键后台安装、打包发布的插件。当前每个请求使用独立临时会话，避免不同提问者共享会话造成信息串流。

## 1. 管理员：部署共享服务

以实验室服务器为例，管理员只需部署一套 Hub，向成员提供访问地址和各自的登录凭证。

### 服务器部署（推荐团队使用）

4 核 8G 可作为 10 人以内协调服务的试用起点，但尚未经容量压测。服务器不运行成员的模型推理；Agent 执行资源和模型调用费用仍由成员侧承担。

在服务器安装 Docker Compose，取得本仓库后，在仓库根目录执行：

```bash
docker compose up -d --build
docker compose exec hub peerlink add-user <成员用户名>
```

命令中的 `<成员用户名>` 是占位符，执行前替换为实际用户名，不保留尖括号。用户名支持字母、数字、下划线和短横线。为每位成员分别运行一次 `add-user`，并通过安全渠道交付其 Token。**当前由管理员创建账户，尚不支持成员自助注册。**

然后完成访问配置：

- Compose 只向服务器回环地址发布 8000 端口。安装 Caddy/Nginx，参考 `deploy/Caddyfile.example` 配置实验室域名和 HTTPS，再让成员访问该地址。
- 建议先限制在实验室内网或 VPN 内使用；即使在内网，远程客户端也要求 HTTPS，且不提供关闭 TLS 校验的选项。
- 向成员提供 **Hub 地址、个人 Token、项目源码或安装包的获取方式**。当前尚无公开发布的一键安装器。
- 成员在浏览器打开 Hub 地址，用自己的 Token 登录；`/docs` 提供接口文档，`/health` 提供健康检查。

Token 是长期有效的 MVP 凭证，不要提交 Git、截图或粘贴到聊天。页面只在内存保存 Token，刷新后需重新输入。

### 本机体验（可选）

如果只想先在一台电脑上验证流程，可以不用 Docker。需要 Python 3.10+，以下命令在仓库根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
peerlink add-user <成员用户名>
peerlink hub
```

打开 `http://127.0.0.1:8000` 登录。模拟多人协作时创建不同账户，并使用不同浏览器窗口登录。默认数据库为当前目录的 `.peerlink/hub.db`，不要切换工作目录后误用另一份数据库。

## 2. 成员：安装客户端并连接团队服务

向管理员获取 Hub 地址、自己的 Token 和本仓库。当前本地 Connector 面向 macOS / Linux，需要 Python 3.10+。在自己的电脑上进入仓库根目录安装：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

连接团队服务：

```bash
export PEERLINK_HUB=https://<团队服务域名>
read -s PEERLINK_TOKEN
export PEERLINK_TOKEN
```

将 `<团队服务域名>` 替换为管理员提供的实际域名。仅在 Hub 和客户端位于同一台电脑时，使用 `http://127.0.0.1:8000`。`read -s` 后输入自己的 Token 并回车，避免直接写入 shell 历史。

**只需要向别人提问**：配置完成后即可使用页面或 CLI，不必注册本地项目，也不必运行 Connector。

**希望别人向自己的项目提问**：继续注册设备及愿意开放协作的项目：

```bash
peerlink connect --name <本机设备名称>
peerlink project-add <项目标识> /实际/项目/绝对路径 --runtime mock --description '项目简介'
unset PEERLINK_TOKEN
peerlink work
```

请替换命令中的设备名称、项目标识和路径；项目标识支持字母、数字、下划线和短横线。这里使用 `mock` 验证连接和审批，不生成真实项目分析；接入真实 Codex 见第 5 节。

状态默认位于 `~/.peerlink`，可用命令前的 `--state /独立/目录` 或 `PEERLINK_STATE` 修改。初次注册后只保存设备 Token，不保存用户 Token。配置文件权限为 600，新建状态目录权限为 700。`unset PEERLINK_TOKEN` 不影响 Connector 运行，之后若要用 CLI 提问，需要重新配置自己的用户 Token。

**`work` 需要持续运行**，团队部署了服务器并不意味着服务器可以直接启动成员电脑上的 Agent。当前先在终端运行；后续可用 macOS launchd / Linux systemd 托管，Skill 本身不是后台服务。设备离线时，已批准请求等待该设备上线。设备令牌可以由本人通过 `DELETE /api/devices/{id}` 撤销。

一期每个“用户＋项目”绑定一台设备。变更路径、Runtime 或设备前先用 `peerlink project-remove <项目标识>` 撤销，旧请求随之取消，再重新注册和发起请求。

## 3. 提问、审批、确认答案

### 提问方：向其他成员的项目提问

在页面选择成员和项目后提问，或者在配置 Hub 地址和自己的 `PEERLINK_TOKEN` 后调用：

```bash
peerlink peers
peerlink projects <对方用户名>
peerlink ask <对方用户名> <项目标识> '这个项目的实验设置和主要设计依据是什么？'
peerlink get <请求ID>
```

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

先确保 `peerlink` 在目标 Agent 的 PATH 中，并以安全方式为其配置 Hub URL 和自己的用户 Token。用户明确需要跨个人提问时才使用该凭证；不要把 Token 写入 Skill。

Codex 用户可将仓库的 `skills/peerlink` 文件夹复制到自己的 Skill 目录：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/peerlink "${CODEX_HOME:-$HOME/.codex}/skills/"
```

若同名 Skill 已存在，先自行确认覆盖范围。重新加载 Agent 后，可指定实际成员和项目，例如：“通过 Peerlink，向项目负责人询问这个研究项目的实验设置。”Skill 会先查询成员及已注册项目，无法确定目标时需要补充信息。安装 Skill 不会自动安装 Python 包、取得凭证、注册设备或启动 Connector。

后续插件可把 CLI/Skill、安装引导和后台服务管理打包在一起。当前交付的是 Skill 源文件和 Python 包源码，**不是已发布插件或一键安装器**。

## 5. 真实 Codex 接入（实验性）

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

容器设置只读根文件系统、项目只读挂载、去除 capabilities、限制内存/CPU/进程数和五分钟执行超时。Codex 使用显式只读沙箱、关闭交互式执行批准、忽略用户配置及规则文件、临时会话，不使用绕过沙箱参数。取消/撤销通过续期检查传播，正常联网下约 15 秒内发现并停止执行；断网时不能保证立即收到取消，云端仍拒绝过期结果。

**剩余边界：** 容器内仍有模型认证材料，模型服务调用会出网，注册项目内部也可能包含秘密。请选择经过清理的共享项目目录，使用专用最小权限模型凭证；这不是严格的数据防泄漏系统。正式接入敏感仓库前，还需要凭证代理、网络出口控制和独立安全验收。模型生成答案仅由本人审核后发送，不自动信任模型判断。

适配参数参考：[Codex 非交互执行官方文档](https://developers.openai.com/codex/noninteractive)。Docker 镜像和真实模型调用必须在目标机器上另行验收，Mock 流程通过不能证明真实模型适配已通过。

## 6. 管理员：运维、备份与迁移

- 数据位于持久化卷 `hub-data`。重建容器不会丢数据，`docker compose down -v` 会删除数据，不要误用。
- 数据库备份建议用 SQLite 在线 backup API；不要只复制正在使用中的 `.db` 而遗漏 WAL。迁移现有数据库时，先停服务或制作一致性备份，再恢复到卷中的 `/data/hub.db`，确保容器 UID 10001 可读写。URL 更改也需要更新每位用户本地配置中的 `hub`。
- 实验室服务器需要允许成员设备通过 HTTPS 访问 Hub。仅部署 Hub 不会把成员项目或模型环境迁移到服务器，也不会让离线的个人设备继续执行任务。

当前使用 **SQLite WAL + 单实例 Hub + HTTP 轮询**，便于首版部署；不是原方案中 PostgreSQL/WebSocket 的完整实现。不做自动租约接管：执行超时标记失败，重新提问需重新审批，以避免失联的旧进程和新设备重复执行。生产化后再迁移 PostgreSQL、加入通知推送与安全的任务恢复机制。

正式对外前还需：SSO/短期凭证及轮换、联系人权限策略、限流、数据保留与清理、审计查询、监控告警、备份恢复演练、并发压测和前端浏览器验收。当前所有注册用户属于同一受信任试用组，可看到项目名称并发起请求，但执行仍需本人批准。

## 7. 开发与验证

```bash
python -m pytest -q
```

测试覆盖 API 权限、项目路径不向其他用户展示、未批准不执行、草稿不上传、并发唯一领取、Hub 重启后请求留存、取消/过期/撤销后的结果拒收、本地路径校验和真实 HTTP + CLI + Mock Connector 端到端流程。

目录：`peerlink/hub.py` 云端接口；`peerlink/connector.py` 本地执行与审核；`peerlink/cli.py` 命令入口；`peerlink/static/` 审批页面；`deploy/` 部署示例；`skills/` Agent 调用指南；`tests/` 自动化测试。
