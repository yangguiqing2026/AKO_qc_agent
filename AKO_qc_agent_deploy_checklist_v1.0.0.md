---
title: "AKO_qc_agent 部署前自检清单"
description: "AKO_qc_agent 部署前逐项自检清单，对照 law_v1.0 通用项与专项项"
author: "AKO_studio"
date: "2026-08-21"
version: "v1.0.0"
tags: ["deploy", "document", "standard", "quality", "compliance"]
---

# AKO_qc_agent 部署前自检清单

> **Agent ID**：AKO_qc_agent
> **版本**：v1.0.0
> **等级**：B/C（未在 agent_card 中标注 level，默认 B/C 级）
> **检查人**：{姓名}
> **检查日期**：{YYYY-MM-DD}

---

## 通用项（36项全部通过方可部署）

| 序号 | 检查项 | 结果 | 备注 |
|:----:|--------|:----:|------|
| G-01 | `agent_id` 与目录名一致 | □通过 □未通过 | |
| G-02 | `level` 与公民权规范一致 | □通过 □未通过 | |
| G-03 | `status` 为 `offline`（首次部署） | □通过 □未通过 | |
| G-04 | `port` 在 5000-5033 范围内 | □通过 □未通过 | |
| G-05 | `description` ≤30字 | □通过 □未通过 | |
| G-06 | 目录名符合 `AKO_{func}_agent` | □通过 □未通过 | |
| G-07 | 入口文件存在（app.py 或 main.py） | □通过 □未通过 | |
| G-08 | 版本号文件存在 | □通过 □未通过 | |
| G-09 | Frontmatter `version` 带 `v` 前缀 | □通过 □未通过 | |
| G-10 | Frontmatter `author` 为 `AKO_studio` | □通过 □未通过 | |
| G-11 | Frontmatter `tags` ≤5个 | □通过 □未通过 | |
| G-12 | `commands` 数量 ≥4 | □通过 □未通过 | |
| G-13 | 每个命令有 `name` 和 `description` | □通过 □未通过 | |
| G-14 | 命令名符合 snake_case | □通过 □未通过 | |
| G-15 | API接口文档存在 | □通过 □未通过 | |
| G-16 | `health.enabled: true` | □通过 □未通过 | |
| G-17 | `health.endpoint` 为 `/health` | □通过 □未通过 | |
| G-18 | `health.interval_seconds` ≤30 | □通过 □未通过 | |
| G-19 | `heartbeat.enabled: true` | □通过 □未通过 | |
| G-20 | `heartbeat.interval_seconds` ≤30 | □通过 □未通过 | |
| G-21 | `silent_window.enabled: true` | □通过 □未通过 | |
| G-22 | `silent_window.duration_minutes` ≥30 | □通过 □未通过 | |
| G-23 | `registry.enabled: true` | □通过 □未通过 | |
| G-24 | `alert.enabled: true` | □通过 □未通过 | |
| G-25 | `memory_watch.enabled` 已配置 | □通过 □未通过 | |
| G-26 | `sync` 字段与等级匹配 | □通过 □未通过 | |
| G-27 | `.env` 文件存在 | □通过 □未通过 | |
| G-28 | 无硬编码凭证 | □通过 □未通过 | |
| G-29 | `secrets.env_file` 指向 `.env` | □通过 □未通过 | |
| G-30 | 白皮书存在 | □通过 □未通过 | |
| G-31 | 手册存在 | □通过 □未通过 | |
| G-32 | README.md 存在 | □通过 □未通过 | |
| G-33 | CHANGELOG.md 存在 | □通过 □未通过 | |
| G-34 | 部署清单存在（本文档） | □通过 □未通过 | |
| G-35 | API文档存在 | □通过 □未通过 | |
| G-36 | 标签仅写在Frontmatter | □通过 □未通过 | |

---

## 专项项（BC级）

- [ ] BC-01：异步调用模式（`sync: false`）
- [ ] BC-02：不得签署对外交付工单（C级）

---

## 检查结论

| 项目 | 结果 |
|------|------|
| 通用项通过数 | ___ / 36 |
| 专项项通过数 | ___ / 2 |
| **总体结论** | □ 全部通过，可部署  □ 有项未通过，待整改 |

---

*作者：AKO_studio*
