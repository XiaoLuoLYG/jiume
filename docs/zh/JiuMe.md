# JiuMe 人形桌面分身 MVP

JiuMe 是一个常驻桌面的个人 Agent 分身。它的日常界面刻意保持很轻：默认只显示头像，让用户愿意一直放在桌面上。Setup 和高级管理仍然保留，但日常使用不再是一排按钮或一个控制面板。

## 已包含能力

- 头像常驻日常面：`jiume` 或 `jiume-avatar` 会打开透明置顶头像，支持拖动到任意屏幕，并记住位置、大小和透明度。默认不展示工具栏、按钮宫格或技能货架。
- 一句话任务流：默认只显示头像；单击头像，输入一句话，JiuMe 会把任务交给 Agent。需要材料、确认或澄清时，它只问一个问题；完成后用一句短结果收起。
- 安静的外壳菜单：右键和应用菜单只暴露 `设置` 和 `退出 JiuMe`。这样 JiuMe 可以长期停在桌面上，不像一个总在抢注意力的工具面板。
- Setup 和高级设置：首次配置仍然是创建和启用分身的必经流程。模型/API、Gateway 诊断、skill 管理、artifacts、完整任务历史、桌面位置、头像身份、权限和排障入口都在 Settings/Advanced。
- Gateway 桥接：桌面分身默认连接 `ws://127.0.0.1:19000/ws`，通过 `chat.send` 把用户输入发给真实 Agent，并把流式回复、工具调用、等待确认、完成和错误映射成头像状态与短任务胶囊。
- 本地身份数据：每个分身会保存 profile、本地头像资产、桌面状态、最近对话和任务状态，供重启后恢复。

## 快速运行

```bash
git clone https://github.com/XiaoLuoLYG/jiume.git
cd jiume

# 首次或依赖变更后
uv venv --python 3.11 --seed .venv
uv pip install -e ".[test]"

# 一条命令启动 Setup、Agent/Gateway 和桌面分身
.venv/bin/jiume-launch --open-setup
```

安装为登录后自动出现：

```bash
.venv/bin/jiume-launch --install-login-item
.venv/bin/jiume-launch --login-item-status
.venv/bin/jiume-launch --uninstall-login-item
```

默认情况下，`jiume-launch` 会复用已运行的 Setup/Gateway，并只恢复它自己启动的子进程。调试时可以关闭恢复：

```bash
.venv/bin/jiume-launch --no-service-restart
```

如果只想分开调试，也可以分别启动：

```bash
# 启动配置页
.venv/bin/jiume-setup --open

# 新开一个终端启动桌面分身
.venv/bin/jiume
```

如果只想离线查看分身 UI，可以关闭 Gateway 桥接：

```bash
.venv/bin/jiume --gateway-url ""
```

## 图片生成配置

JiuMe 的图片生成配置可以在 Setup 页保存，也可以在启动 `jiume-setup` 前手动 export 环境变量。

- `JIUME_OPENAI_API_KEY`：图片生成 API Key，优先于 `OPENAI_API_KEY`。
- `JIUME_OPENAI_BASE_URL`：OpenAI-compatible Base URL，优先于 `OPENAI_BASE_URL`。
- `JIUME_IMAGE_MODEL`：图片生成模型，默认 `gpt-image-2`。
- `JIUME_IMAGE_PROVIDER`：`openai`、`mock` 或 `auto`。

用户上传照片必须先勾选授权。未配置图片生成 API Key 时，JiuMe 会使用本地透明 Q 版头像资产。

## 状态控制

```bash
.venv/bin/jiume-state idle
.venv/bin/jiume-state thinking
.venv/bin/jiume-state working
.venv/bin/jiume-state waiting_approval
.venv/bin/jiume-state success
.venv/bin/jiume-state error
.venv/bin/jiume-state sleep
```

## 数据目录

```text
~/.jiuwenswarm/
  jiume/config.env
  jiume/desktop_state.json
  jiume/window_state.json
  jiume/conversation_state.json
  jiume/companion_state.json
  jiume/screen_context/
  jiume/twins/{twin_id}/profile.json
  jiume/twins/{twin_id}/memory.json
  jiume/twins/{twin_id}/avatar/
  jiume/twins/{twin_id}/audit/events.jsonl
  jiume/twins/{twin_id}/distill/jobs/{job_id}/job.json
```

## 验证

```bash
.venv/bin/python -m compileall -q jiume jiuwenswarm/start_services.py
.venv/bin/python -m pytest -q --no-cov tests/unit_tests/jiume/test_twin_store.py
.venv/bin/python -m jiume.launcher --help
.venv/bin/python -m jiume.launcher --login-item-status
git diff --check
```

## 当前 MVP 边界

- JiuMe 当前优先保证低打扰的桌面日常循环，而不是把所有功能摊在头像旁。复杂控制先放在 Settings/Advanced，等交互足够轻之后再逐步回到日常面。
- 富媒体产物编辑、远端 skill marketplace 安装、更完整的任务历史浏览，仍需要继续在高级界面里产品化。
