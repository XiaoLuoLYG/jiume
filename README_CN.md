<div align="center">

# JiuMe

本地优先的个人 Agent 桌面数字分身。

[![CI](https://github.com/XiaoLuoLYG/jiume/actions/workflows/ci.yml/badge.svg)](https://github.com/XiaoLuoLYG/jiume/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

</div>

JiuMe 是构建在 JiuwenSwarm Agent Runtime 之上的桌面分身层。它把个人 Agent 变成一个常驻桌面的轻量头像入口，支持一句话发起任务、本地分身档案与状态、挂载个人技能，以及需要用户确认的持续个人蒸馏流程。

项目刻意保持本地优先：运行配置、分身档案、头像资产、审计日志、蒸馏后的个人记忆与技能草稿都存储在用户自己的机器上。外部模型或图片生成服务是可选项，必须由用户显式配置。

## 当前状态

JiuMe 目前是早期源码发布项目。桌面头像、Setup 服务、Runtime 桥接、本地分身存储、技能挂载和个人蒸馏基础链路已经存在。当前目标是把本地 MVP 做真实、可靠、可检查，而不是把还没产品化的能力包装成完成态。

目前主平台是 macOS + Python 3.11+。底层 Web/Runtime 服务是 Python 实现，核心测试不依赖云端凭证。

## 已包含能力

- 桌面头像外壳：通过 `jiume` 或 `jiume-avatar` 启动透明置顶头像。
- 一句话任务循环：点击、输入、发送，然后把 Agent 进度、工具调用、等待审批、完成和失败映射为克制的桌面状态。
- Setup 服务：用于首次配置分身身份、模型/图片提供方和 Runtime 诊断。
- JiuwenSwarm Runtime 桥接：带 `twin_id` 的 `chat.send` 可以把当前 JiuMe 分身上下文注入真实 Agent 路径。
- 本地分身数据：profile、memories、permissions、mounted skills、avatar assets、audit events 和桌面状态都位于 `~/.jiuwenswarm/jiume/`。
- 个人蒸馏引擎：把经过审阅的聊天、任务和来源片段转化为 profile/style/procedural/personal-skill 分层产物，再由用户确认安装。
- JiuMe 专属单元测试覆盖 runtime、twin store、setup/settings、one-line companion 和 personal distillation。

## 快速开始

克隆仓库：

```bash
git clone https://github.com/XiaoLuoLYG/jiume.git
cd jiume
```

创建本地环境并安装：

```bash
uv venv --python 3.11 --seed .venv
uv pip install -e ".[test]"
```

一条命令启动 Setup、JiuwenSwarm Runtime 和桌面分身：

```bash
.venv/bin/jiume-launch --open-setup
```

分开调试：

```bash
.venv/bin/jiume-setup --open
.venv/bin/jiume
```

不连接 Gateway，只查看头像 UI：

```bash
.venv/bin/jiume --gateway-url ""
```

## 配置

图片生成是可选能力。未配置图片提供方时，JiuMe 会使用本地生成/mock 头像资产，保证全链路仍可运行。

相关环境变量：

```bash
export JIUME_OPENAI_API_KEY="..."
export JIUME_OPENAI_BASE_URL="https://api.openai.com/v1"
export JIUME_IMAGE_MODEL="gpt-image-2"
export JIUME_IMAGE_PROVIDER="auto"
```

Setup UI 也可以把这些值保存到：

```text
~/.jiuwenswarm/jiume/config.env
```

用户照片上传和持久化个人蒸馏写入都应保持显式授权、本地优先和审阅确认。

## 仓库结构

```text
jiume/                         JiuMe 产品层
  desktop/                     头像外壳、桌面状态、原生交互
  setup/                       首次配置服务
  runtime/                     Gateway 健康检查与分身上下文注入
  twins/                       文件存储的分身档案与记忆
  skills/                      本地技能目录与安装辅助
  personal_distillation/       需要审阅的记忆/技能蒸馏引擎
  avatar/                      头像资产生成与 manifest
jiuwenswarm/                   JiuMe 复用的 JiuwenSwarm runtime
jiuwenbox/                     Runtime 使用的本地沙箱/proxy 包
tests/unit_tests/jiume/        JiuMe 专属单元测试
docs/en/JiuMe.md               英文 MVP 说明
docs/zh/JiuMe.md               中文 MVP 说明
```

## 开发与验证

运行 JiuMe 重点检查：

```bash
.venv/bin/python -m compileall -q jiume jiuwenswarm/start_services.py
.venv/bin/python -m pytest -q --no-cov tests/unit_tests/jiume
git diff --check
```

启动器 smoke check：

```bash
.venv/bin/python -m jiume.launcher --help
.venv/bin/python -m jiume.launcher --login-item-status
```

## 文档

- [JiuMe MVP 说明](docs/zh/JiuMe.md)
- [English README](README.md)
- [JiuwenSwarm 记忆文档](docs/zh/记忆.md)
- [JiuwenSwarm Skill 自演进文档](docs/zh/Skill自演进.md)
- [测试指南](TESTING.md)

## 参与贡献

欢迎贡献，但请保持项目对真实运行状态的诚实描述。提交 PR 前请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 安全

请不要在 issue 或 PR 中发布真实 API Key、个人聊天导出、私人头像源图或本地分身数据。安全问题请参考 [SECURITY.md](SECURITY.md)。

## 开源协议

JiuMe 使用 [Apache License 2.0](LICENSE) 发布。仓库中复用的 JiuwenSwarm 代码同样采用 Apache-2.0 协议。
