<h1 align="center">Peerlink</h1>

<p align="center"><strong>让项目知识参与协作，让访问与分享由本人决定。</strong></p>
<p align="center">面向研究实验室与小型研发团队的自托管项目 Agent 协作工具。</p>
<p align="center"><a href="README.md">English</a> · <strong>简体中文</strong></p>
<p align="center"><a href="#快速开始">快速开始</a> · <a href="docs/admin-guide.zh-CN.md">管理员手册</a> · <a href="docs/member-guide.zh-CN.md">成员手册</a> · <a href="docs/guide.zh-CN.md">完整指南</a></p>

---

Peerlink 让团队成员可以向彼此的项目 Agent 提问，而不必开放对整台电脑的访问权限。共享的 **Hub / Relay** 负责登录、发现、审批和消息路由，轻量的本机 **Bridge** 主动连接 Relay 并在项目提供方电脑上执行 Agent。每条问题是否执行、最终分享什么答案，都由项目提供方本人决定。完整目标见[重构方案](docs/peerlink-local-agent-bridge-proposal.zh-CN.md)，当前实现与未完成项见[迁移说明](docs/peerlink-bridge-migration.zh-CN.md)。

在实验室服务器、团队内网主机或云服务器上部署一套 Hub，成员连接自己的电脑，并显式注册愿意参与协作的项目即可。

> **开发者预览版。** 0.5.0 已部署到 `peerlink.jd.com`；一次公网 WSS Echo 请求通过了本人批准、本机起草与审核发送的完整闭环。真实 Codex 模型回合、两台不同成员电脑及远程 MCP/OAuth 仍未验收或实现，当前版本尚未完成生产级加固。

## 为什么使用 Peerlink？

- **围绕具体项目协作。** 向成员的项目 Agent 询问实验设置、代码结构或历史设计决策。
- **执行和发送分别确认。** 项目提供方先批准请求，再审核、修改或拒绝生成的答案。
- **本地执行，集中协调。** 注册项目位置，无需因此将整个代码仓库上传到 Hub。
- **在线直达。** 新 Bridge 通过出站 WebSocket 在线路由；设备离线时明确返回错误。旧轮询请求在迁移期保留。
- **CLI 与 Skill 入口。** 使用网页或 `peerlink` 命令；Codex Skill 可以引导 Agent 通过 CLI 完成协作。

## 工作方式

**发起提问 → 本人批准 → 本地 Agent 执行 → 本人审核 → 分享答案**

| 组件 | 运行位置 | 职责 |
| --- | --- | --- |
| Hub / Relay | 团队共享服务器 | 账号、Agent 元数据、短期请求、审批和在线路由；不保存本机项目路径 |
| Bridge | 成员电脑 | 出站 WebSocket、本机项目路径、任务执行和草稿审核 |
| Agent Backend | 成员电脑 | Echo 联通测试、实验性 Codex app-server；旧 Mock/Docker 兼容保留 |

只提问的成员无需运行 Bridge；开放项目的成员需要保持 Bridge 在线。本机路径只留在 Bridge 配置中，不发送给 Hub。

## 快速开始

### 1. 启动本机 Hub

需要 **Python 3.10+**，本地 Connector 当前面向 **macOS 和 Linux**。取得本仓库后，在仓库根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
peerlink init-admin your-username
peerlink hub
```

将 `your-username` 替换为实际用户名。`init-admin` 会安全提示输入密码。打开 [localhost:8000](http://127.0.0.1:8000) 使用用户名和密码登录；普通成员在页面注册，管理员批准后即可登录。

### 2. 接入本地项目

登录网页，在“我的设备”生成一次性配对码，然后在本机执行：

```bash
peerlink connect --hub http://127.0.0.1:8000 --name my-laptop --code <配对码>
peerlink skill-install
peerlink catalog
peerlink agent add my-project /absolute/path/to/project --backend echo --visibility team
peerlink service-install
```

管理员先在网页的“云端项目目录”建立项目。每位成员配对后用 `catalog` 查看目录，再将自己电脑上的对应路径逐个绑定。成员可用 `peerlink project-propose <id> '<说明>'` 申请新项目，管理员批准后才能绑定。**Echo 仅演示消息链路，不调用模型。**真实本机自动起草使用 `--backend codex-app-server`，要求本机有可用的 app-server 可执行程序；只有 Codex 桌面端时可改用 `project-add ... --runtime codex-desktop` 手动 Skill 模式。

### 3. 体验审批流程

在网页中选择成员及其注册项目，提交问题。项目提供方在网页批准执行后，在本机另一个已激活虚拟环境的终端查看并确认草稿：

```bash
peerlink review
peerlink review REQUEST_ID
peerlink review REQUEST_ID --send
```

将 `REQUEST_ID` 替换为 `review` 列出的请求 ID。只有本人阅读并明确确认答案可以分享后，才执行 `--send`。提问方随后可以在网页中查看答案。

**要部署到实验室或团队服务器？** 请参阅[部署指南](docs/guide.zh-CN.md#1-管理员部署共享服务)。仓库提供 Docker Compose 和 HTTPS 反向代理配置示例。4 核 8G 可作为不足 10 人试用组的起点，但不是经过压测的容量保证；模型执行仍在成员侧进行。

## 项目状态

| 能力 | 当前状态 |
| --- | --- |
| 请求 API、审批页面、本地审核和 CLI | 已实现；网页界面目前为中文 |
| 用户与设备凭证分离、请求持久化 | 已实现 |
| 网页自助注册、管理员审批 | 已实现 |
| Bridge WebSocket、Agent 发现、Echo、逐条审批和本地审核 | 0.5.0 已上线；一次公网 WSS Echo 请求完成本人批准和审核发送 |
| Codex app-server Backend | 协议适配和模拟进程测试已完成；真实模型回合及访问隔离待验证 |
| Codex Desktop Skill 手动模式 | 已实现；不需要单独安装 Codex CLI，也不会自动操控桌面会话 |
| 旧 Mock/Docker 适配器 | 兼容保留，Docker 仍属实验性 |
| Remote MCP/OAuth、Claude Code、原 Agent 会话自动收信 | 尚未实现 |

当前 Hub 使用 **SQLite WAL 和单实例服务**。新 Bridge 使用 WebSocket；旧 Runtime 仍使用 HTTP 轮询。Bridge 消息按 24 小时保留期清理，超时执行标记失败，不自动转交其他设备重跑。

## 安全与信任边界

- 在受信任团队内使用，优先通过内网或 VPN 接入。远程客户端要求 HTTPS。
- Bridge 注册只向 Hub 同步 Agent 名称、说明、设备和访问范围，不上传绝对路径或仓库内容。问题和已批准的答案在短期保留期内存储于 Hub，未确认草稿留在项目提供方本机。
- 本地执行**不等于离线推理**。模型服务可能接收到项目上下文，实验性 Runtime 仍需要模型凭证和网络访问。
- 系统信任本机用户与 Connector。人工审核不是数据防泄漏系统，也无法保护已被攻陷的设备。
- 面向公网部署前，还需完善身份认证、凭证轮换、权限策略、限流及运维安全。使用敏感项目之前请阅读[完整指南](docs/guide.zh-CN.md)。

## 文档导航

| 文档 | English | 简体中文 |
| --- | --- | --- |
| 管理员：初始化、审批、项目目录与运维 | [Administrator handbook](docs/admin-guide.md) | [管理员手册](docs/admin-guide.zh-CN.md) |
| 成员：注册、配对、路径绑定与协作 | [Member handbook](docs/member-guide.md) | [成员手册](docs/member-guide.zh-CN.md) |
| 安装、团队部署、CLI、Skill 与安全边界 | [Full guide](docs/guide.md) | [完整指南](docs/guide.zh-CN.md) |
| 原始一期设计与范围 | — | [方案文档](Peerlink-一期方案-精简版.md) |

运行 Hub 后，`/docs` 提供 API 文档，`/health` 提供健康检查。

## 路线图

- [ ] 在目标机器上验证真实 Codex 执行与 Docker 部署。
- [x] 提供 macOS/Linux 用户级 Connector 后台安装与系统通知。
- [ ] 增加 Claude Code 支持与 MCP 接口。
- [ ] 增加具备安全隔离的会话恢复与回复通知。
- [ ] 完善认证、访问策略、审计和运维能力，支持更广泛的使用。

以上为计划方向，不代表当前已支持的功能，也不是发布时间承诺。

## 开发与贡献

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

测试覆盖权限控制、审批状态转换、任务领取、离线持久化、本地路径校验，以及 HTTP + CLI + Mock Connector 完整流程；不代表真实模型质量或生产就绪程度已经验证。

欢迎提交问题报告、可复现的部署反馈与范围明确的改进。修改行为时请补充测试；调整面向用户的说明时请同步中英文 README。不要在反馈中包含 Token、私密草稿或敏感项目内容。

核心代码：[`peerlink/`](peerlink/) · 部署配置：[`deploy/`](deploy/) · Skill：[`skills/peerlink/`](skills/peerlink/) · 测试：[`tests/`](tests/)
