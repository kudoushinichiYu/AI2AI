> 本文保存用户提供的原始重构方案，统一使用 Peerlink 名称。以下为目标设计，不表示功能均已完成。当前实现差异与迁移状态见 [重构进度](peerlink-bridge-migration.zh-CN.md)。
>
> Codex app-server 是独立本地进程，需要可用的 Codex 可执行程序；它不是向已打开的 Codex 桌面会话注入消息的接口。已有的本人审批和人工审核发送要求在迁移中继续保留。

# Peerlink 本地 Agent 通信桥重构方案

## 1. 项目目标

当前系统目标是实现：

> 用户 A 可以从自己的 ChatGPT / Agent 中发送一条消息给用户 B 的 Agent，由用户 B 本地电脑上的 Agent 基于其本地项目上下文处理，并将结果返回给用户 A。

核心使用场景例如：

```text
Jay:
“帮我问 Alice 的 recommendation agent，
她现在 feature pipeline 是怎么设计的？”
```

系统需要完成：

```text
Jay ChatGPT
    ↓
Peerlink
    ↓
找到 Alice 的 recommendation agent
    ↓
消息发送到 Alice 本地电脑
    ↓
Alice 本地 Agent 基于对应项目上下文执行
    ↓
生成回答
    ↓
返回 Jay
```

本次重构的核心目标是：

1. **不再要求每个用户安装 Docker。**
2. **不再要求用户手动运行 Codex CLI。**
3. **Agent、Repo、Memory、Project Context 尽量保留在用户本地。**
4. **中心服务器只负责身份、寻址、路由和临时消息转发。**
5. **用户电脑无需公网 IP，无需开放端口。**
6. **支持多个用户，每个用户拥有多个 Project Agent。**
7. **优先支持 Codex，但架构不能绑定 Codex。**
8. 后续可以扩展 Claude Code、Cursor、Local LLM 等 Agent Backend。

---

# 2. 当前方案存在的问题

旧方案大致为：

```text
每个用户电脑

Docker
    ↓
Codex CLI
    ↓
Local MCP
    ↓
WebSocket
    ↓
中心服务器
```

存在几个问题：

### 2.1 部署过重

每个用户都需要：

```text
安装 Docker
clone repo
docker compose up
安装 Codex
登录 Codex
配置环境变量
配置 MCP
运行 daemon
```

对于普通用户而言 onboarding 成本太高。

---

### 2.2 CLI 不适合作为长期 Runtime

当前方案本质上是在：

```text
启动 shell
cd project
codex
```

或者：

```text
codex resume
```

远程驱动 CLI。

这会产生很多状态管理问题：

* 当前 Codex 在哪个目录
* 当前 session 是谁的
* CLI 是否启动
* Terminal 是否还活着
* 如何 resume
* 多任务是否冲突
* 多个 project 如何隔离
* 用户关闭 terminal 后怎么办

因此应该把 Codex CLI 从系统核心架构中移除。

---

### 2.3 中心服务器承担太多 Agent 状态

Peerlink 的云端服务器不应该存储大量：

```text
代码
项目文件
完整 conversation
Codex memory
长期 session
项目知识
```

这些数据原则上应尽量保留在用户本地。

---

# 3. 新架构核心思想

新架构采用：

> **Local Agent + Thin Cloud Relay**

即：

```text
云端只负责通信

本地负责智能
```

最终架构：

```text
                   ┌──────────────────────┐
                   │ ChatGPT / Codex / UI │
                   │                      │
                   │     Peerlink Plugin     │
                   └──────────┬───────────┘
                              │
                              │ HTTPS / MCP
                              ▼
                   ┌──────────────────────┐
                   │     Peerlink Relay      │
                   │                      │
                   │ Auth                 │
                   │ Routing              │
                   │ Presence             │
                   │ Message Forwarding   │
                   └──────────┬───────────┘
                              │
                        WebSocket
                              │
                 outbound connection
                              │
                              ▼
┌──────────────────────────────────────────────────────┐
│                  User Local Machine                  │
│                                                      │
│  ┌────────────────────────────────────────────────┐ │
│  │               Peerlink Bridge                    │ │
│  │                                                │ │
│  │ Device Auth                                    │ │
│  │ WebSocket Client                               │ │
│  │ Agent Registry                                 │ │
│  │ Message Router                                 │ │
│  │ Permission Manager                             │ │
│  │ Local State                                    │ │
│  └───────────────────┬────────────────────────────┘ │
│                      │                               │
│                      ▼                               │
│  ┌────────────────────────────────────────────────┐ │
│  │              Agent Backend                    │ │
│  │                                                │ │
│  │ Codex Backend                                  │ │
│  │ Claude Backend             future              │ │
│  │ Local LLM Backend          future              │ │
│  └───────────────────┬────────────────────────────┘ │
│                      │                               │
│                      ▼                               │
│                Local Project                        │
│                                                      │
│ Repo / files / AGENTS.md / memory / tools / MCP     │
└──────────────────────────────────────────────────────┘
```

---

# 4. 核心设计原则

## 4.1 Cloud 不负责运行 Agent

不要使用：

```text
Cloud Agent Session
```

作为系统主 Agent。

因为这样：

```text
conversation
project context
agent state
```

会长期存在云端。

新架构中：

```text
Cloud = Transport Layer

Local = Agent Runtime Layer
```

---

## 4.2 中心服务器只做 Relay

Relay Server 只负责：

```text
Authentication
User lookup
Agent lookup
Device lookup
Online presence
Message routing
Temporary queue
Response routing
```

它不理解：

```text
代码
项目
Agent reasoning
项目 memory
```

---

## 4.3 Local Bridge 主动连接服务器

不要让服务器连接：

```text
AliceLaptop:3000
```

因为现实中会遇到：

```text
NAT
Firewall
公司网络
校园网络
家庭路由器
动态 IP
```

应该让本地 Bridge 主动连接：

```text
wss://peerlink.jd.com/ws
```

即：

```text
Local Bridge
      │
      │ outbound WebSocket
      ▼
Peerlink Relay
```

这样用户不需要：

```text
公网 IP
端口映射
ngrok
VPN
```

---

# 5. 用户侧架构

用户不应该再“部署 Peerlink”。

用户只需要“安装 Peerlink”。

例如 Mac：

```text
Peerlink.app
```

Windows：

```text
Peerlink.exe
```

Linux：

```text
peerlink-agent
```

启动以后运行一个非常轻量的：

```text
peerlink-bridge
```

---

# 6. Peerlink Bridge

Peerlink Bridge 是整个本地架构的核心。

职责：

```text
1. 登录 Peerlink
2. 获取 device identity
3. 和 Relay 建立 WebSocket
4. 上报在线状态
5. 注册当前机器上的 Agents
6. 接收其他用户发送过来的消息
7. 根据 agent_id 找到对应 project
8. 调用对应 Agent Backend
9. 获取回答
10. 返回结果
```

Bridge 本身不负责 LLM reasoning。

---

# 7. Agent Registry

每个用户不能只对应一个 Agent。

需要：

```text
User
    ├── Project Agent A
    ├── Project Agent B
    └── Project Agent C
```

例如：

```text
Alice
├── recommendation
├── infra
└── thesis
```

Registry 维护：

```text
agent_id
agent_name
workspace_path
backend
instructions
permissions
thread_id
```

例如：

```json
{
  "id": "agent_alice_recommendation",
  "name": "recommendation",
  "workspace": "/Users/alice/code/recommendation",
  "backend": "codex",
  "thread_id": "local_thread_xxx"
}
```

---

# 8. 为什么必须 Project → Agent 映射

不能：

```text
Alice
   ↓
随机启动一个 Codex
```

而要：

```text
Alice + recommendation
        ↓
~/code/recommendation
        ↓
对应 Agent
        ↓
对应 thread/context
```

这样用户问：

```text
@Alice/recommendation
```

系统才能保证使用：

```text
Recommendation Repo
Recommendation AGENTS.md
Recommendation Context
Recommendation Tools
```

而不会跑到其他 project。

---

# 9. Agent Backend 抽象

不要让 Peerlink Bridge 和 Codex 强绑定。

定义统一接口：

```python
class AgentBackend:

    async def start_agent(...):
        ...

    async def send_message(...):
        ...

    async def resume(...):
        ...

    async def cancel(...):
        ...

    async def get_status(...):
        ...
```

实现：

```text
AgentBackend
│
├── CodexBackend
│
├── ClaudeCodeBackend
│
├── CursorBackend
│
└── LocalLLMBackend
```

第一期只实现：

```text
CodexBackend
```

但所有 Relay、Bridge、Protocol 都不要出现大量 Codex-specific logic。

---

# 10. Codex Backend

不要继续以：

```text
shell → codex CLI
```

作为主要集成方式。

优先：

```text
Peerlink Bridge
      ↓
Codex app-server
```

让 Bridge 程序化管理：

```text
Thread
Turn
Streaming
Tool Calls
Approval
Resume
Cancel
```

而不是模拟人在 Terminal 输入命令。

逻辑：

```text
Incoming Message
      ↓
Agent Registry
      ↓
workspace_path
      ↓
Codex Backend
      ↓
resume/create thread
      ↓
send user message
      ↓
Codex accesses local repo
      ↓
result
```

---

# 11. Local Thread

每个 Project Agent 可以维护自己的 thread。

例如：

```text
alice/recommendation
    ↓
thread_001

alice/infra
    ↓
thread_002
```

本地保存：

```text
~/.peerlink/
```

建议结构：

```text
~/.peerlink/

config.json

device.json

agents.json

state.db

logs/

cache/
```

或者：

```text
state.db
```

统一使用 SQLite。

---

# 12. 本地数据

以下数据默认只保留在本机：

```text
Repo source code

Workspace files

AGENTS.md

Project instructions

Local memory

Agent thread mapping

Tool configuration

Project MCP config

Historical project context
```

服务器原则上不要保存。

---

# 13. Cloud 数据模型

Relay Server 可以只保留极少量数据。

## users

```text
id
username
display_name
created_at
```

---

## devices

```text
id
user_id
device_name
public_key
online
last_seen
created_at
```

---

## agents

云端只保存可发现信息：

```text
id
user_id
device_id
name
description
online
```

例如：

```text
alice/recommendation
alice/infra
bob/frontend
```

不要存：

```text
workspace_path
project files
memory
thread content
```

workspace_path 只存在本地。

---

## messages

MVP：

```text
id
from_user
to_user
to_agent
status
created_at
expires_at
payload
```

消息完成后：

```text
delete / expire
```

---

# 14. 消息协议

建议自定义一个非常简单的 Agent Message Protocol。

例如：

```json
{
  "version": "1",
  "type": "agent.message",
  "message_id": "msg_123",
  "thread_id": "thread_abc",
  "from": {
    "user_id": "jay"
  },
  "to": {
    "user_id": "alice",
    "agent_id": "recommendation"
  },
  "content": {
    "type": "text",
    "text": "你现在 feature pipeline 是怎么设计的？"
  }
}
```

---

# 15. Relay → Local Bridge

服务器收到：

```text
Jay
   ↓
Alice/recommendation
```

查找：

```text
Agent Registry Cloud Metadata

recommendation
    ↓
device_alice_mac
```

如果：

```text
device online
```

通过对应 WebSocket：

```text
send(msg)
```

---

# 16. Local Message Processing

Alice Bridge 收到：

```text
agent.message
```

处理：

```text
1. 校验 sender 权限

2. 查找 agent_id

3. 获取：
   workspace
   backend
   thread

4. 调用 AgentBackend

5. Agent 本地执行

6. 收集 answer

7. 返回 agent.response
```

---

# 17. Response

例如：

```json
{
  "version": "1",
  "type": "agent.response",
  "message_id": "msg_123",
  "status": "completed",
  "content": {
    "type": "text",
    "text": "当前 feature pipeline 分为..."
  }
}
```

Relay：

```text
Alice Device
     ↓
Relay
     ↓
Jay
```

---

# 18. Thread 设计

Peerlink 自己应该拥有：

```text
Peerlink Thread
```

而不是直接暴露 Codex thread。

例如：

```text
Peerlink thread:
thread_abc
```

内部 Alice Bridge 可以映射：

```text
thread_abc
    ↓
codex_thread_xyz
```

这样以后切换 Agent Backend 时：

```text
Peerlink thread
```

仍然可以保持兼容。

---

# 19. Online / Offline

## Online

如果目标设备在线：

```text
send
 ↓
Relay
 ↓
WebSocket
 ↓
Local Bridge
 ↓
Agent
```

---

## Offline

MVP 最简单：

```text
DEVICE_OFFLINE
```

直接返回：

```text
Alice 的设备当前离线
```

不要一开始做复杂 offline queue。

---

## 第二阶段

可以增加：

```text
Encrypted Offline Queue
```

例如：

```text
TTL = 24h
```

流程：

```text
message
 ↓
encrypted
 ↓
Relay temporary queue
 ↓
Alice 上线
 ↓
pull
 ↓
delete
```

---

# 20. 隐私设计

目标：

> Relay 尽量无法看到用户具体内容。

第一期可以先不做完整 E2EE。

第二期实现：

```text
每个 device：

private key
    ↓
local only

public key
    ↓
server
```

Jay 发 Alice：

```text
plaintext
   ↓
Alice public key
   ↓
ciphertext
   ↓
Relay
   ↓
Alice device
   ↓
Alice private key
   ↓
plaintext
```

这样 Relay 只能看到：

```text
Jay → Alice
Agent ID
message metadata
ciphertext
```

无法读取内容。

---

# 21. 权限模型

这是整个系统必须预留的能力。

不能默认：

```text
任何人
   ↓
都可以问任何 Agent
```

Agent 至少支持：

```text
private
friends
team
public
allowlist
```

例如：

```json
{
  "agent": "recommendation",
  "access": "allowlist",
  "users": [
    "jay",
    "bob"
  ]
}
```

本地 Bridge 在真正执行 Agent 前再次校验。

即：

```text
Cloud ACL
+
Local ACL
```

双层校验。

---

# 22. Agent 可执行权限

还要进一步区分：

```text
Ask-only Agent

Read-only Agent

Execution Agent
```

例如推荐默认：

```text
remote user
    ↓
Read-only mode
```

允许：

```text
read code
search project
answer question
```

不允许：

```text
git push
delete files
run dangerous commands
```

否则 Alice 的 Agent 被远程问一句话，就能操作 Alice 整台电脑，风险过高。

---

# 23. Tool Permission

Agent 注册时配置：

```text
permissions:

filesystem.read = true
filesystem.write = false

shell.readonly = true

git.commit = false
git.push = false

network = limited
```

未来可以：

```text
trusted user
    ↓
write permission
```

---

# 24. Peerlink Plugin

Plugin 只是发送入口。

不是 Agent Runtime。

架构：

```text
ChatGPT
   ↓
Peerlink Plugin
   ↓
Remote MCP
   ↓
Relay
```

Plugin 可以暴露：

```text
list_users()

list_agents(user)

send_message(
    user,
    agent,
    message
)

get_thread(thread_id)

reply(
    thread_id,
    message
)
```

---

# 25. Plugin 示例

用户：

```text
帮我问 Alice 的 recommendation agent
feature pipeline 怎么设计的？
```

ChatGPT 调：

```python
send_message(
    user="alice",
    agent="recommendation",
    message="feature pipeline 怎么设计的？"
)
```

之后：

```text
Relay
 ↓
Alice Local Bridge
 ↓
Alice Local Agent
```

---

# 26. 必须明确的系统边界

Plugin：

```text
负责：
ChatGPT → Peerlink
```

Relay：

```text
负责：
Peerlink → Device
```

Bridge：

```text
负责：
Device → Local Agent
```

Agent Backend：

```text
负责：
调用具体 Agent Runtime
```

Project：

```text
真正的数据与上下文
```

不要把这些职责混在一起。

---

# 27. 不要试图直接操控另一个人的 ChatGPT

Peerlink 的目标不应该是：

```text
远程打开 Alice 的 ChatGPT
找到 Alice 的某个 conversation
在 UI 里输入消息
```

这条路线非常脆弱。

应该定义：

```text
Alice's Agent
```

它拥有：

```text
Project
Memory
Instructions
Tools
Agent Backend
```

Peerlink 和这个 Agent 通信。

---

# 28. Memory 设计

长期 memory 应该保留在本地。

推荐：

```text
project/
    AGENTS.md

.peerlink/
    memory.db
```

其中保存：

```text
project summary

important decisions

Peerlink conversation summaries

local thread mapping
```

Peerlink 不需要把所有历史 conversation 发给 Agent。

可以只保留：

```text
summary
+
最近 N 条
```

---

# 29. Server 技术栈

对于第一期：

```text
FastAPI
PostgreSQL
WebSocket
Redis optional
```

即可。

甚至前期：

```text
FastAPI
SQLite
WebSocket
```

都能跑。

如果只有：

```text
10
50
100
```

个用户，没有必要微服务化。

---

# 30. Local Bridge 技术栈

第一版可以直接 Python：

```text
Python
asyncio
websockets
SQLite
```

以后需要桌面体验：

```text
Tauri
```

或者：

```text
Electron
```

但 UI 不是第一优先级。

---

# 31. Local Bridge 生命周期

启动：

```text
peerlink bridge start
```

流程：

```text
load config

authenticate

register device

register agents

connect WebSocket

heartbeat

wait messages
```

---

# 32. Mac 常驻

不要要求用户开 terminal。

最终可以通过：

```text
launchd
```

启动：

```text
peerlink-bridge
```

登录电脑以后自动运行。

用户体验：

```text
安装 Peerlink.app
 ↓
Login
 ↓
后台常驻
```

---

# 33. 第一版可以暂时使用 CLI

为了先验证功能，可以先实现：

```bash
peerlink login

peerlink agent add recommendation ~/code/recommendation

peerlink agent list

peerlink bridge start
```

例如：

```bash
peerlink agent add \
  --name recommendation \
  --workspace ~/code/recommendation \
  --backend codex
```

---

# 34. Agent Registration

本地：

```text
workspace:
/Users/alice/code/recommendation
```

但是上传服务器时：

```text
agent:
alice/recommendation
```

不要上传：

```text
/Users/alice/code/recommendation
```

这种本地路径。

---

# 35. Device Registration

第一次：

```text
peerlink login
```

服务端：

```text
user
 ↓
device token
```

本地保存：

```text
~/.peerlink/device.json
```

例如：

```json
{
  "device_id": "device_123",
  "access_token": "...",
  "device_name": "Alice MacBook"
}
```

---

# 36. WebSocket 消息类型

建议至少包含：

```text
device.hello

device.heartbeat

agent.register

agent.message

agent.response

agent.error

agent.cancel

agent.status
```

---

# 37. Agent Status

例如：

```text
idle
running
offline
error
```

用户可以：

```text
list_agents("alice")
```

看到：

```text
recommendation   online
infra            online
thesis           offline
```

---

# 38. Running 状态

如果：

```text
Alice/recommendation
```

正在执行任务：

第一期可以简单串行。

例如：

```text
one agent
    ↓
one running task
```

新消息：

```text
queue
```

以后再支持：

```text
parallel session
```

---

# 39. Timeout

必须设置执行 timeout。

例如：

```text
default = 5 min
```

超时：

```text
agent.error
reason=timeout
```

否则坏任务可能永久占用 Agent。

---

# 40. Message ID

所有消息必须有：

```text
message_id
```

用于：

```text
deduplication

retry

response matching

logging
```

---

# 41. Idempotency

Bridge 收到：

```text
msg_123
```

如果之前已经执行：

```text
不要重复执行
```

本地 SQLite：

```text
processed_messages
```

保存：

```text
message_id
status
result
```

---

# 42. Retry

WebSocket 断开：

```text
Bridge reconnect
```

采用：

```text
1s
2s
4s
8s
...
max 30s
```

指数退避。

---

# 43. Heartbeat

例如：

```text
每 30 秒 ping
```

服务器：

```text
90 秒未 heartbeat
    ↓
device offline
```

---

# 44. MVP 不要做的事情

第一阶段不要：

```text
Docker

Kubernetes

复杂 Workflow Engine

Kafka

多 Region

完整 E2EE

复杂离线消息

多人群聊

Agent Market

远程 Desktop

ChatGPT UI 自动化
```

先把：

```text
A → Relay → B Local Agent → Relay → A
```

跑通。

---

# 45. 第一阶段 MVP

必须完成：

```text
1. User 登录

2. Device 注册

3. 本地 Bridge

4. WebSocket persistent connection

5. Local Agent Registry

6. 注册 Project Agent

7. Agent Discovery

8. send_message

9. Relay route

10. Local Agent execution

11. result return

12. online/offline status
```

---

# 46. MVP 完整 Demo

Alice：

```bash
peerlink login

peerlink agent add \
    --name recommendation \
    --workspace ~/code/recommendation \
    --backend codex

peerlink bridge start
```

服务器显示：

```text
Alice
└── recommendation
    online
```

Jay：

```text
@Peerlink

Ask Alice/recommendation:
这个项目 feature pipeline 是怎么设计的？
```

系统：

```text
Jay ChatGPT
 ↓
Peerlink MCP
 ↓
Relay
 ↓
Alice Bridge
 ↓
recommendation Agent
 ↓
Codex
 ↓
读取 ~/code/recommendation
 ↓
回答
 ↓
Relay
 ↓
Jay
```

---

# 47. 第二阶段

增加：

```text
Peerlink Desktop App

LaunchDaemon

Project selector

Agent permission UI

encrypted message

offline queue

conversation history

notifications
```

---

# 48. 第三阶段

增加多 Agent Backend：

```text
Codex

Claude Code

Local LLM

Custom Agent
```

形成：

```text
Universal Peerlink Bridge
```

---

# 49. 第四阶段

可以支持：

```text
Agent groups

multi-agent collaboration

delegation

broadcast

task graph

shared project room
```

例如：

```text
Jay Agent
   ↓
Alice Research Agent
   ↓
Bob Coding Agent
   ↓
Carol Review Agent
```

---

# 50. 推荐最终代码结构

建议将项目重构为：

```text
peerlink/

├── server/
│   ├── api/
│   │   ├── auth.py
│   │   ├── users.py
│   │   ├── devices.py
│   │   ├── agents.py
│   │   └── messages.py
│   │
│   ├── websocket/
│   │   ├── manager.py
│   │   ├── protocol.py
│   │   └── router.py
│   │
│   ├── services/
│   │   ├── routing.py
│   │   ├── presence.py
│   │   └── message_service.py
│   │
│   ├── models/
│   │   ├── user.py
│   │   ├── device.py
│   │   ├── agent.py
│   │   └── message.py
│   │
│   └── main.py
│
├── bridge/
│   ├── client.py
│   ├── auth.py
│   ├── registry.py
│   ├── router.py
│   ├── storage.py
│   │
│   ├── backends/
│   │   ├── base.py
│   │   └── codex.py
│   │
│   └── main.py
│
├── protocol/
│   ├── messages.py
│   └── schemas.py
│
├── cli/
│   ├── login.py
│   ├── agent.py
│   └── bridge.py
│
├── mcp/
│   ├── server.py
│   └── tools.py
│
└── tests/
```

---

# 51. 最重要的架构约束

Codex 在重构过程中必须遵守：

### Rule 1

Cloud server 不保存用户 repo。

### Rule 2

Cloud server 不保存长期 Agent context。

### Rule 3

workspace path 永远不上传服务器。

### Rule 4

本地机器主动建立 outbound WebSocket。

### Rule 5

不要求用户开放本地端口。

### Rule 6

不使用 Docker 作为客户端必须依赖。

### Rule 7

Codex CLI 不作为核心 Agent Runtime。

### Rule 8

Bridge 与 Agent Backend 解耦。

### Rule 9

一个 User 可以拥有多个 Agents。

### Rule 10

Agent 必须明确绑定 Project / Workspace。

### Rule 11

Remote request 默认使用受限权限。

### Rule 12

所有消息具有 message_id，并支持 idempotency。

---

# 52. 本次重构建议

Codex 不要在现有架构上继续增加 patch。

首先分析当前 repository：

```text
1. 哪些代码属于 Relay
2. 哪些代码属于 Local Agent
3. 哪些代码属于 Codex CLI wrapper
4. 哪些代码属于 MCP
5. 哪些代码属于 Docker deployment
```

然后按照新的职责边界重新组织。

优先保留：

```text
已有用户系统

已有消息 protocol

已有 MCP tool

已有 WebSocket 通信逻辑
```

可以删除或逐渐废弃：

```text
Docker-based local deployment

remote shell assumptions

Codex CLI process management

cloud project context storage
```

---

# 53. 推荐重构顺序

## Phase 1：抽象协议

先定义：

```text
User
Device
Agent
Message
Thread
```

以及：

```text
agent.message
agent.response
agent.error
```

---

## Phase 2：Relay

让服务器只实现：

```text
Device WebSocket

Presence

Agent registration

Message routing
```

---

## Phase 3：Bridge

实现：

```text
Local WebSocket client

Agent registry

Local SQLite

incoming router
```

---

## Phase 4：Fake Backend

先不要接 Codex。

实现：

```python
class EchoBackend:
    async def send_message(self, message):
        return "echo: " + message
```

先验证：

```text
A
 ↓
Relay
 ↓
B
 ↓
Echo
 ↓
Relay
 ↓
A
```

---

## Phase 5：Codex Backend

Echo 跑通后再接：

```text
Codex app-server
```

完成：

```text
create/resume thread

workspace binding

send message

stream result

return response
```

---

## Phase 6：MCP

最后让 ChatGPT 可以通过：

```text
Peerlink Remote MCP
```

调用：

```text
list_agents
send_message
get_message
```

---

# 54. 第一版成功标准

第一版只要满足下面这个 Demo，就算成功：

```text
两台电脑：

Mac A
Mac B

Mac B 注册：

Alice/recommendation
→ ~/code/recommendation

Mac A：

send_message(
    alice,
    recommendation,
    "项目的数据 pipeline 是什么？"
)

Mac B：

Local Agent 读取本地项目
生成回答

Mac A：

收到回答
```

整个过程：

```text
无 Docker

无需公网 IP

无需手动启动 Codex CLI

代码不上传 Peerlink Server

Project context 不存 Peerlink Server
```

即可。

---

# 55. 产品最终形态

最终希望用户体验是：

```text
下载安装 Peerlink
      ↓
登录
      ↓
选择：

~/Projects/recommendation

      ↓

Create Agent:
recommendation

      ↓
Done
```

其他人：

```text
@Peerlink

问 Alice 的 recommendation agent：
你们当前召回模型是什么？
```

Alice 不需要：

```text
打开 terminal

启动 Docker

启动 Codex

打开端口
```

只需要：

```text
电脑在线
+
Peerlink Bridge 后台运行
```

即可。

---

# 56. 项目定位

最终 Peerlink 不应该被设计成：

> Codex CLI 的远程控制器

而应该被设计成：

> **一个让不同用户、本地 Project Agent 之间能够安全通信的 Agent-to-Agent Communication Layer。**

Codex 只是第一种 Backend。

最终抽象应该是：

```text
Peerlink

User
 ↓
Agent
 ↓
Project
 ↓
Agent Backend
```

而不是：

```text
User
 ↓
Codex CLI
```

这也是后续系统能扩展到：

```text
Codex
Claude Code
Cursor
Local Agent
Research Agent
Custom Enterprise Agent
```

的关键。

---

# Codex 执行要求

请先读取当前 repository 的代码与 README，理解已有架构，不要直接重写全部代码。

首先输出：

```text
1. 当前系统架构
2. 与目标架构之间的差异
3. 可以保留的模块
4. 需要删除/废弃的模块
5. 需要新增的模块
6. 推荐迁移顺序
```

然后开始重构。

重构优先级：

```text
Protocol
→ Relay
→ Local Bridge
→ Echo Backend
→ Codex Backend
→ MCP
→ Packaging
```

每完成一个阶段都保证系统可以独立运行和测试。

不要一开始实现：

```text
E2EE
复杂 UI
offline queue
多 Agent orchestration
```

这些属于后续阶段。

第一目标是跑通：

```text
A ChatGPT
→ Peerlink Relay
→ B Local Bridge
→ B Local Codex Agent
→ Peerlink Relay
→ A ChatGPT
```

并确保用户侧：

```text
No Docker
No exposed port
No manually running Codex CLI
No cloud project storage
```
