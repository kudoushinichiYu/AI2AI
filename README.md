# AI2AI · Personal Agent Collaboration

首版开发原型：**云端管理身份、项目映射和审批，本地 Connector 在指定项目中执行 Agent，答案经本人确认后才上传。** 面向 10 人以内的受信任团队试用，不是可直接暴露公网的生产服务。

## 当前能用到什么程度

- 云端 API + 中文 Web 页面：联系人、注册项目查询、提问、批准/拒绝、取消和查看结果。
- 本地 Connector：注册设备和项目路径、轮询领取已批准请求、租约续期、本地草稿、人工确认发送。
- 用户 Token 和设备 Token 分离；设备无权批准请求或查询别人的请求。
- 本地 CLI 和可复制安装的 Skill；无需第一版就实现 MCP，Agent 可通过 CLI 提问及查结果。
- **Mock Runtime 已提供端到端测试，不读取项目、不调用模型；Codex Docker 适配器需在安装 Docker、配置专用认证后单独验证。**

尚未实现：Claude Code、MCP Server、原会话自动推送、Peer Session 恢复、自动更新/一键后台安装、打包发布的插件。当前每个请求使用独立临时会话，避免不同提问者共享会话造成信息串流。

## 1. 本机启动 Hub

需要 Python 3.10+（服务器镜像使用 3.12）。以下命令在仓库根目录执行，先确认 `python3 --version` 满足要求：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
ai2ai add-user alex
ai2ai add-user bob
ai2ai hub
```

`add-user` 分别输出一次用户 Token，请私下交给对应用户，不要提交 Git、截图或粘贴到聊天。它们是长期有效的 MVP 凭证，无公开注册接口。默认数据库为当前目录的 `.ai2ai/hub.db`，不要切换工作目录后误用另一份数据库。

打开 `http://127.0.0.1:8000`，使用用户 Token 登录。页面只在内存保存 Token，刷新后需重新输入；测试 Alex / Bob 时建议使用两个浏览器窗口。`/docs` 提供接口文档，`/health` 提供健康检查。

## 2. Bob 安装 Connector 并注册项目

每位用户在自己的电脑安装 Python 包（试用期先取得本仓库，再执行上述安装命令）。在 Bob 的终端：

```bash
export AI2AI_HUB=http://127.0.0.1:8000
read -s AI2AI_TOKEN
export AI2AI_TOKEN
ai2ai connect --name bob-macbook
ai2ai project-add recommendation /实际/项目/绝对路径 --runtime mock --description '推荐排序项目'
unset AI2AI_TOKEN
ai2ai work
```

`read -s` 后粘贴 Bob 的 Token 并回车，避免直接写入 shell 历史。状态默认位于 `~/.ai2ai`，可用命令前的 `--state /独立/目录` 或 `AI2AI_STATE` 修改。初次注册后只保存设备 Token，不保存用户 Token。配置文件权限为 600，新建状态目录权限为 700。

**`work` 需要持续运行**，审批页面在云端并不意味着本地无需进程。当前先在终端运行；后续可用 macOS launchd / Linux systemd 托管，Skill 本身不是后台服务。设备令牌可以由本人通过 `DELETE /api/devices/{id}` 撤销。

一期每个“用户＋项目”绑定一台设备。变更路径、Runtime 或设备前先用 `ai2ai project-remove recommendation` 撤销，旧请求随之取消，再重新注册和发起请求。

## 3. 提问、审批、确认答案

Alex 在页面提问，或者在设置自己的 `AI2AI_TOKEN` 后调用：

```bash
ai2ai peers
ai2ai projects bob
ai2ai ask bob recommendation '为什么从 DIN 换成 Transformer？'
ai2ai get <请求ID>
```

Bob 在云端页面点“批准本地执行”。Connector 生成草稿后，在 Bob 的另一个终端查看并确认：

```bash
ai2ai review
ai2ai review <请求ID>
ai2ai review <请求ID> --send
# 或使用手动编辑过的文本
ai2ai review <请求ID> --send --answer-file /实际/修改后的答案.txt
# 不允许分享时
ai2ai review <请求ID> --reject
```

`--send` 是本人对该答案的明确发送确认，不应由无人值守脚本自动调用。当前信任本机用户和 Connector，不能防止已被攻陷的设备伪造该确认。

Hub 只收到“等待答案确认”状态，**未确认草稿不上传**。本地草稿含问题和执行租约，按私密资料保护；发送或终止后会保留 `.done` / `.stopped` 文件供排查，用户可自行删除。Alex 用页面刷新或 `ai2ai get` 收取结果，暂不自动注入原 Codex 会话。

## 4. 安装 Skill

先确保 `ai2ai` 在目标 Agent 的 PATH 中，并以安全方式为其配置 Hub URL 和自己的用户 Token。用户明确需要跨个人提问时才使用该凭证；不要把 Token 写入 Skill。

Codex 用户可将仓库的 `skills/ai2ai-collaboration` 文件夹复制到自己的 Skill 目录：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/ai2ai-collaboration "${CODEX_HOME:-$HOME/.codex}/skills/"
```

若同名 Skill 已存在，先自行确认覆盖范围。重新加载 Agent 后可说：“通过 AI2AI 帮我问 Bob 的 recommendation 项目……”。安装 Skill 不会自动安装 Python 包、取得凭证、注册设备或启动 Connector。

后续插件可把 CLI/Skill、安装引导和后台服务管理打包在一起。当前交付的是 Skill 源文件和 Python 包源码，**不是已发布插件或一键安装器**。

## 5. 真实 Codex 接入（实验性）

仅设置 `codex --sandbox read-only` 不代表只能读项目目录。因此该适配器不直接在宿主机运行 Codex，而是在本地 Docker 容器里挂载项目只读目录，不挂载整个 Home、SSH 密钥、Docker Socket 或其他项目。

1. 安装并启动 Docker，以及一个支持下述参数的 Codex 版本。
2. 准备一个**专用 CODEX_HOME 认证目录**，使用 Codex 的登录方式生成 `auth.json`；不要把个人完整 `~/.codex` 复制进去。此版本仅支持标准认证，不自动迁移自定义模型路由、MCP、插件或代理配置。
3. 按已核对的版本构建镜像，不隐式安装 latest：

```bash
docker build -f deploy/codex.Dockerfile --build-arg CODEX_VERSION=<已核对的版本号> -t ai2ai-codex:local .
ai2ai project-remove recommendation
ai2ai project-add recommendation /实际/项目/绝对路径 --runtime codex-docker
ai2ai work --auth-dir /实际/专用认证目录
```

容器设置只读根文件系统、项目只读挂载、去除 capabilities、限制内存/CPU/进程数和五分钟执行超时。Codex 使用显式只读沙箱、关闭交互式执行批准、忽略用户配置及规则文件、临时会话，不使用绕过沙箱参数。取消/撤销通过续期检查传播，正常联网下约 15 秒内发现并停止执行；断网时不能保证立即收到取消，云端仍拒绝过期结果。

**剩余边界：** 容器内仍有模型认证材料，模型服务调用会出网，注册项目内部也可能包含秘密。请选择经过清理的共享项目目录，使用专用最小权限模型凭证；这不是严格的数据防泄漏系统。正式接入敏感仓库前，还需要凭证代理、网络出口控制和独立安全验收。模型生成答案仅由本人审核后发送，不自动信任模型判断。

适配参数参考：[Codex 非交互执行官方文档](https://developers.openai.com/codex/noninteractive)。Docker 镜像和真实模型调用必须在目标机器上另行验收，Mock 流程通过不能证明真实模型适配已通过。

## 6. 迁移到 4 核 8G 服务器

**对 10 人内的协调服务，可作为合理试用起点；不包含云端模型推理，也未经容量压测。** 本地用户仍各自承担 Codex 执行资源和模型调用费用。

服务器安装 Docker Compose 后，在仓库目录：

```bash
docker compose up -d --build
docker compose exec hub ai2ai add-user alex
docker compose exec hub ai2ai add-user bob
```

- Compose 只向服务器回环地址发布 8000 端口，避免无 TLS 暴露公网。
- 在宿主机安装 Caddy/Nginx，参考 `deploy/Caddyfile.example` 配置自己的域名及 HTTPS；建议先仅通过 VPN/内网访问。
- 所有人设置 `AI2AI_HUB=https://你的域名`。客户端拒绝非本机明文 HTTP，且没有关闭 TLS 校验的选项。
- 数据位于持久化卷 `hub-data`。重建容器不会丢数据，`docker compose down -v` 会删除数据，不要误用。
- 数据库备份建议用 SQLite 在线 backup API；不要只复制正在使用中的 `.db` 而遗漏 WAL。迁移现有数据库时，先停服务或制作一致性备份，再恢复到卷中的 `/data/hub.db`，确保容器 UID 10001 可读写。URL 更改也需要更新每位用户本地配置中的 `hub`。

当前使用 **SQLite WAL + 单实例 Hub + HTTP 轮询**，便于首版部署；不是原方案中 PostgreSQL/WebSocket 的完整实现。不做自动租约接管：执行超时标记失败，重新提问需重新审批，以避免失联的旧进程和新设备重复执行。生产化后再迁移 PostgreSQL、加入通知推送与安全的任务恢复机制。

正式对外前还需：SSO/短期凭证及轮换、联系人权限策略、限流、数据保留与清理、审计查询、监控告警、备份恢复演练、并发压测和前端浏览器验收。当前所有注册用户属于同一受信任试用组，可看到项目名称并发起请求，但执行仍需本人批准。

## 7. 开发与验证

```bash
python -m pytest -q
```

测试覆盖 API 权限、项目路径不向其他用户展示、未批准不执行、草稿不上传、并发唯一领取、Hub 重启后请求留存、取消/过期/撤销后的结果拒收、本地路径校验和真实 HTTP + CLI + Mock Connector 端到端流程。

目录：`ai2ai/hub.py` 云端接口；`ai2ai/connector.py` 本地执行与审核；`ai2ai/cli.py` 命令入口；`ai2ai/static/` 审批页面；`deploy/` 部署示例；`skills/` Agent 调用指南；`tests/` 自动化测试。
