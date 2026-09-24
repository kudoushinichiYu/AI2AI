# Peerlink 双成员首次联调：yujunjie.50 → chenyang.720

[成员手册](member-guide.zh-CN.md) | [项目首页](../README.zh-CN.md)

本文用于第一次在**两台电脑、两个 ERP 账号**之间验证线上 Peerlink 0.5.0。由 `chenyang.720` 在自己的电脑上开放测试 Agent，`yujunjie.50` 从自己的账号提问。此轮使用 Echo：只验证消息、审批与回传，不读取项目文件，也不调用 Codex 模型。不要交换账号密码、配对码或设备凭证。其他成员可按相同流程替换各自的 ERP 名称。

## 1. chenyang.720：准备接收端

1. 在 [Peerlink 网页](https://peerlink.jd.com/) 用自己的账号登录，确认注册已获批准。终端运行 `peerlink status`，确认 `owner` 是 `chenyang.720`、`hub` 是 `https://peerlink.jd.com`。如果 `paired` 为 `false`，在网页“连接这台电脑”生成一次性配对码，并按网页给出的命令完成 `peerlink connect`。不要把配对码发给别人。
2. 运行 `peerlink update-check`，确认 CLI 目标版本为 `0.5.0`。如果旧 CLI 不认识该命令，或提示有更新，先在本人电脑执行：

   ```bash
   python3 -m pip install --user --upgrade https://peerlink.jd.com/downloads/peerlink-0.5.0-py3-none-any.whl
   peerlink update-check
   ```

   核对输出中 `cli.installed` 和 `cli.latest` 均为 `0.5.0`；若安装后仍显示旧版，先运行 `command -v peerlink` 检查当前调用的命令位置。线上 0.5.0 的 `update-check` 仍可能打印无效的 `peerlink.whl` 简写安装地址，请始终使用上面带版本号的命令。已安装旧后台服务时，更新 CLI 后在第 4 步重新运行 `service-install`。本轮直接用 CLI 测试，不要求先更新 Codex 插件。
3. 运行 `peerlink catalog`，确认 `ai-outbound` 为 `ACTIVE`，并由本人确认电脑上对应的**具体项目目录**。只有确实拥有该目录时才运行下面的命令；把示例路径替换为自己的绝对路径，不要填 `/`、整个 Home 或凭证目录：

   ```bash
   peerlink agent add ai-outbound /你的实际项目目录 --backend echo --visibility allowlist --allow-user yujunjie.50
   ```

   `allowlist` 只让指定成员发现该 Agent。如果本机已有同名 Agent，不要直接覆盖或删除，先确认现有配置。若没有 `ai-outbound` 的本机目录，先联系测试双方选择另一个已获管理员批准的项目标识。
4. 运行：

   ```bash
   peerlink service-install
   peerlink service-status
   peerlink agent list
   ```

   保持电脑在线，确认后台服务正在运行。若配对时使用了非默认状态目录，**本页每条 Peerlink 命令都必须使用同一个状态目录**：在命令 `peerlink` 后、子命令前加 `--state /该账号的状态目录`，或在该终端设置 `PEERLINK_STATE`。从 Dock 启动的 Codex 不会自动继承终端环境变量。

## 2. yujunjie.50：从自己的账号发问

在自己的电脑和 `yujunjie.50` 对应状态目录中，确认身份并检查对方 Agent 在线；确认目标是 `chenyang.720` 后，再发送一条不含敏感内容的测试问题：

```bash
peerlink status
peerlink projects chenyang.720
peerlink ask chenyang.720 ai-outbound 'Peerlink 双机 Echo 测试：请确认你收到这条消息。'
```

记录 `ask` 返回的请求 ID。若 `projects` 看不到目标，先让接收端检查版本、白名单和服务状态；若返回 `DEVICE_OFFLINE`，检查接收端 Bridge 是否在线。不要为了让测试通过而改用对方账号。

## 3. chenyang.720：本人批准并审核发送

1. 在自己登录的网页“提问与请求”中核对发送方、项目和测试问题，**本人**点击批准。批准前不会调用本机 Echo。
2. 本机运行 `peerlink review` 找到请求，执行 `peerlink review <请求ID>` 阅读草稿。确认草稿可发送后，**本人**执行 `peerlink review <请求ID> --send`。如果不想分享，不要执行 `--send`。
3. 若一直没有草稿，检查 `peerlink service-status`、当前命令的状态目录和后台日志；不要反复批准或重复发送。

## 4. yujunjie.50：核对结果

运行 `peerlink get <请求ID>` 或在网页查看。只有状态 `COMPLETED`，且返回内容是以 `echo:` 开头的原测试问题，才算此轮通过。`WAITING_APPROVAL`、`WAITING_DEVICE` 或“草稿待审核”都不是完成。

双机 Echo 通过后，才能单独安排真实 Codex 回答测试：若接收端有可用的 `codex app-server`，可评估独立进程自动起草；若只有 Codex 桌面端，则使用成员手册中的 `codex-desktop` 手动 Skill 流程。无论哪种方式，仍须本人逐条批准请求、审核答案后发送。**本轮 Echo 成功不代表真实模型或项目访问隔离已经验收。**
