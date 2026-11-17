# gemini-app-as-subagent

[English](README_EN.md) | **中文**

把 **macOS `Gemini.app`（非 Antigravity 普通模式）**、**Google Developer Program 每月 `$40` / `$100` `gemini-api` 赠金** 以及 **独立登录的 `agy -p` 账号** 变成可被任何 AI 编程助手（Antigravity、Claude Code、Codex、WorkBuddy、ZCode、Cursor 等）直接调用的 **Subagent（子智能体）** 与 **本地文件协同工具**。

---

## 为什么需要这个项目？

很多同时使用 **Google AI Ultra / Pro + Antigravity + 其他编码 Agent** 的开发者都会遇到三个额度闲置痛点：
1. **主对话用的是别的模型**（例如 Claude / Codex），导致 Google AI Ultra 附带的每月 **`$40` / `$100` `gemini-api` 赠金**、Deep Research 与云端沙箱月底直接清零；
2. **`Gemini.app` 普通模式（非 Antigravity 视图）其实自带超强的本地桌面能力**——它能直接读写 `~/Downloads` / `~/Documents` / `~/Desktop`、调用 Python 与 Google Drive 工具、运行 **macOS Computer Use + AppleScript**（操作日历/提醒事项/Finder/原生 App/修 PDF 表单）、挂 **Custom Local MCP** 和 **定时任务（Scheduled Tasks）**，但默认和外部编码 Agent 互不相通；
3. **多账号额度无法并行**：手里有第二个 Google 订阅账号，却不想切掉当前主 IDE/桌面端登录态。

`gemini-app-as-subagent` 通过 **纯 Python 标准库（零第三方依赖）** 的单一 CLI + Stdio MCP 服务，打通了三条协同轨道。

---

## 三轨子智能体架构

```text
Host Agent (Antigravity / Codex / Claude Code / WorkBuddy / ZCode / Terminal)
  │
  ├── Track 1: gemini-api 无头赠金子代理 (ask / review / research / sandbox)
  │     └── 消耗每月 $40/$100 赠金；自动解决非终端 stdin 阻塞、macOS 代理注入、>14MB 自动上传
  │
  ├── Track 2: Gemini.app 普通模式协同 (handoff / collect + gemini_collab_mcp.py)
  │     └── 通过 ~/Downloads/Gemini-Collab/{inbox,outbox,archive} + Stdio MCP 接力
  │         让 Gemini.app 使用 DesktopTools / AppleScript / Computer Use / Scheduled Tasks
  │
  └── Track 3: 多账号 agy -p 隔离派单 (agy-ask --account-home <dir>)
        └── 独立 $HOME 绑定第二个 Google 账号，--mode plan 只读审计或隔离改代码
```

### Track 1：`gemini-api` 赠金子智能体（内置四大防坑修复）
直接调用 `gemini-api` 当子智能体时，脚本或 Agent 子进程常遇到几个隐蔽坑，本项目已全部封装兜底：
- **修复非 TTY `stdin` 永久阻塞**：Agent 工具拉起子进程时若不关闭 `stdin`，`gemini-api` 会把管道误判成等待 JSON `--body` 输入而卡死；封装层默认显式关闭 `stdin`（仅在 `--stdin` 时读取）；
- **自动注入 macOS 系统代理**：在无交互子 Shell 丢失代理环境变量时，自动读取 `scutil --proxy` 注入 `HTTP_PROXY` / `HTTPS_PROXY`；
- **隔离 `$HOME` 凭证自动回退**：若当前桌面 Agent 运行在隔离 `$HOME` 下找不到 `gemini-api` 凭证，自动回退读取真实用户目录的钥匙串配置；
- **大文件自适应上传**：附件超过 `14 MB` 自动先走 `gemini-api files upload --wait` 获取 `files/<id>` 再分析。

### Track 2：`Gemini.app` 非 Antigravity 桌面端协同
`Gemini.app` 原生模式是唯一能操作 **macOS 个人目录 + AppleScript + Computer Use + 定时任务** 的入口：
- **文件信箱模式**：`gemini-subagent handoff` 在 `~/Downloads/Gemini-Collab/inbox/` 生成包含任务目标、本地文件绝对路径、临时目录与结果回传路径的 Markdown 任务单（支持 `--copy` 复制触发词和 `--open` 唤起 `googlegemini://newchat`）；处理完后用 `gemini-subagent collect` 回收结果；
- **Custom Local MCP 模式**：把 `scripts/gemini_collab_mcp.py` 挂到 `Gemini.app` 的本地 MCP（`open "googlegemini://?target=customize"`），即可在 `Gemini.app` 聊天或定时任务（`googlegemini://?target=scheduled`）里直接调用：
  - `collab_list_tasks`
  - `collab_read_task`
  - `collab_submit_result`

### Track 3：`agy -p` 多账号无头派单
为备用 Google 账号建立一次性的隔离 `$HOME`：
```zsh
mkdir -p ~/.gemini-subagent-home
HOME=~/.gemini-subagent-home agy   # 浏览器登录备用账号后输入 /exit
```
之后就能随时用 `gemini-subagent agy-ask` 当无头子智能体调用：
```zsh
gemini-subagent agy-ask --account-home ~/.gemini-subagent-home --cwd /path/to/repo --mode plan --effort high "审查状态机竞态问题"
```

---

## 快速安装

```zsh
git clone https://github.com/Harzva/gemini-app-as-subagent.git
cd gemini-app-as-subagent
./install.sh
```

`install.sh` 会完成：
1. 安装技能到 `~/.agents/skills/gemini-subagent` 并软链可执行文件 `~/.local/bin/gemini-subagent`；
2. 自动检测并注册到 `~/.gemini/config/skills`、Antigravity、Claude Code、Codex、WorkBuddy 等已存在的多智能体技能目录。

验证环境：
```zsh
~/.local/bin/gemini-subagent doctor
```

---

## 常用命令速查

| 命令 | 用途 | 示例 |
|---|---|---|
| `doctor` | 检查 `gemini-api`、`agy`、凭证、代理、存储与 `Gemini.app` | `gemini-subagent doctor` |
| `ask` | 同步问答与本地文件/媒体分析（支持 `lite`/`fast`/`balanced`/`coding`/`frontier`） | `gemini-subagent ask -t balanced -f spec.md "总结核心风险"` |
| `review` | 默认 `gemini-4-argon` 独立审阅代码或 `git diff` | `gemini-subagent review --git-diff --cwd . "检查并发与安全边界"` |
| `research` | 拉起后台 `deep-research-preview-04-2026`（加 `--wait` 自动轮询） | `gemini-subagent research "对比各端实时音视频架构"` |
| `sandbox` | 调用 `antigravity-preview-09-2026` 远程 Linux 沙箱并拉回产物 | `gemini-subagent sandbox "跑 Python 基准测试输出 results.csv" --download results.csv` |
| `status` | 按 `run_id` 或 `v1_...` 查询并同步后台任务结果 | `gemini-subagent status <id>` |
| `agy-ask` | 用隔离 `$HOME` 调 `agy -p` 消耗其他 Google 账号额度 | `gemini-subagent agy-ask --account-home ~/.gemini-subagent-home "只读审查 src/"` |
| `image` | 调 `gemini-nano-banana-2.1` / `gemini-3-pro-image` 生图（内置 `knowledge-card` 风格预设） | `gemini-subagent image --style knowledge-card -t pro -f ref.jpg --out card.png "..."` |
| `video` | 调 `gemini-omni-1.2-flash` 生成/续接/恢复视频 | `gemini-subagent video "运动图形转场" --aspect-ratio 16:9 --resolution 1080p` |
| `open-app` | 通过 `googlegemini://` 一键打开桌面端生图/Veo 视频/素材库等面板 | `gemini-subagent open-app images` / `videos` / `library` |
| `handoff` | 向 `~/Downloads/Gemini-Collab/inbox/` 派发桌面任务单（支持 `--target`） | `gemini-subagent handoff "整理发票并建提醒事项" -f ~/Downloads/a.pdf --copy --open` |
| `collect` | 查看任务状态或回收 `outbox/` 结果 | `gemini-subagent collect --list` / `gemini-subagent collect <id> --archive` |

### Gemini 生图与知识卡片（小红书分层图）三条接入路径

| 路径 | 适用场景 | 实战用法 |
|---|---|---|
| **路径 A：`gemini-subagent image`（API 赠金精控出图）** | **最适合批量生成 2K/4K 知识卡片、架构图**，支持垫图锁版式、精准控字与多轮 `--continue-id` 微调 | `gemini-subagent image --style knowledge-card -t pro -f 参考图.jpg --aspect-ratio 3:4 --size 2K --out card.png "卡片文案..."` |
| **路径 B：`Gemini.app` 桌面端 `?target=images`** | **白嫖订阅日常生图配额**（不扣 API 赠金），适合快速灵感试图与交互式重绘 | `gemini-subagent open-app images` 或 `gemini-subagent handoff --target images --copy --open` |
| **路径 C：Antigravity `image-generator` 子代理** | 同账号对话内直接委派生成/改图 | 在 Antigravity 对话里附带参考图直接下令生成 |

> **知识卡片高还原秘诀**：`--style knowledge-card`（内置 `3:4` 暖白底色、左竖条编号色卡、虚线标签胶囊与底部靶心总结框规范） + `-f 参考图.jpg` 锁死版式与配色 + `--size 2K` 保证中文小字清晰锐利 + `--continue-id <v1_id>` 二次局部改字！

### 在 `Gemini.app` 中挂载本地 MCP
打开 `open "googlegemini://?target=customize"`，添加一条 Stdio MCP：
- **Command**: `/usr/bin/python3`
- **Args**: `["/你的HOME路径/.agents/skills/gemini-subagent/scripts/gemini_collab_mcp.py"]`

---

## 可选自定义配置（`~/.config/gemini-subagent/config.json`）

如果希望把运行日志、Diff 快照和沙箱下载产物统一放到外置高速磁盘（并做卷挂载与 UUID 校验），可创建 `~/.config/gemini-subagent/config.json`：

```json
{
  "state_dir": "/Volumes/YourFastSSD/Builds/gemini-subagent",
  "collab_dir": "~/Downloads/Gemini-Collab",
  "require_volume_mount": "/Volumes/YourFastSSD",
  "require_volume_uuid": "YOUR-VOLUME-UUID",
  "min_free_gib": 10
}
```
也支持直接通过环境变量 `GEMINI_SUBAGENT_STATE_DIR`、`GEMINI_COLLAB_DIR`、`GEMINI_API_BIN`、`AGY_BIN` 覆盖。

---

## 举一反三：WorkBuddy、ZCode 等其他 Agent App 也能这么当子智能体吗？

**完全可以，而且很多国产/IDE 类桌面 Agent App 比 `Gemini.app` 更容易直接无头调用。** 核心遵循 **“三层通用接入法则”**：

| 桌面应用 | 首选接入轨道 | 实际调用机制 / 关键参数 | 说明 |
|---|---|---|---|
| **Gemini.app** | Track 1 (`gemini-api`) + Track 2 (文件信箱 & MCP) + Track 3 (`agy -p`) | 普通模式用 `~/Downloads/Gemini-Collab/` + `gemini_collab_mcp.py`；编程配额用 `agy -p`；API 赠金用 `gemini-api` | 普通模式偏向原生桌面 `DesktopTools` / AppleScript / Computer Use |
| **WorkBuddy** | **内置无头 CLI（Layer 1）** + Stdio MCP（Layer 2） | App 包内自带 `WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy`（或全局 `codebuddy`）：支持 `-p` (`--print`)、`--output-format json`、`--permission-mode plan`、`-w/--worktree` | 可直接以无头模式派生只读审查或独立 git worktree 子代理 |
| **ZCode** | **内置无头运行器（Layer 1）** + Stdio MCP（Layer 2） | App 包内自带 `ZCode.app/Contents/Resources/glm/zcode.cjs`，共享 `~/.zcode/v2` GLM Coding Plan 订阅，支持 `--mode plan\|build\|edit\|guarded --json`（可套一层轻量 Node 适配器如 `zcode-agent run`） | 直接白嫖/复用桌面端 GLM 套餐额度跑只读规划或编码子任务 |
| **Claude Desktop / Claude Code** | **无头 CLI（Layer 1）** + MCP（Layer 2） | `claude -p "<prompt>" --output-format json --permission-mode plan` | 可与 `gemini_collab_mcp.py` 共享同一套本地信箱 |
| **Codex App / CLI** | **无头 CLI（Layer 1）** + 独立 `CODEX_HOME` | `codex exec` + `CODEX_HOME=/path/to/isolated-home` | 类似 `agy -p` 的多账号隔离模式 |

**通用落地三步法**：
1. **先找包内无头 CLI**（查看 `.app/Contents/Resources` 或 `Helpers`）：只要支持 `-p` / `--print` / `exec` + `--output-format json` + 只读权限档位，就能用和本项目相同的薄封装把它变成命令行子智能体；
2. **被 GUI/权限锁死的桌面专属能力走“信箱 + MCP”**：把 `scripts/gemini_collab_mcp.py` 挂进任何支持本地 MCP 的桌面 App，所有智能体就能跨应用读写同一个 `inbox/` 与 `outbox/`；
3. **订阅附带 API 赠金走官方 CLI + 代理/stdin 兜底**：避免端到端工具调用在非交互环境挂起。

---

## 本地测试

```zsh
python3 -m unittest discover -s tests -p "test_*.py" -v
```

## License

[MIT](LICENSE)
