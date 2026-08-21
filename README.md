# AKO_qc_agent

> **Agent ID**: AKO_qc_agent
> **版本**: v1.0.0
> **作者**: AKO_studio
> **等级**: S（质量门）
> **状态**: staging（首部署 offline）

## 简介

AKO_qc_agent 是 AKO_Hub 的出厂质量门（Quality Gate）。它按 law_v1.0 标准对所有生产型 Agent 输出执行五层检测（L1 契约 → L2 知识库 → L3 品牌 → L4 业务逻辑 → L5 安全），输出结构化 qc_report.json，支持审计模式与拦截模式双态运行。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 单次质检（内置示例）
python src/core/main.py

# 指定输入/输出
python src/core/main.py --input sample.json --output qc_report.json

# 健康检查服务
python src/core/main.py --serve --port 5001
```

## 配置说明

- 主配置：`config/AKO_qc_agent_config.yaml`
- 环境变量：`.env`
- Agent 卡片：`AKO_agent_card.yaml`
- 规则集：`ako_qc_rules/`（映射见 `ako_qc_rules/version.json`）

## 目录结构

```
src/core/        # 业务逻辑入口
config/          # 配置文件
docs/            # API 文档与使用手册
tests/           # 单元测试
ako_qc_rules/    # 规则集
```

## 文档

- 白皮书：`AKO_qc_agent_whitepaper_v1.0.0.md`
- API 文档：`docs/AKO_qc_agent_api_v1.0.0.md`
- 使用手册：`docs/AKO_qc_agent_manual_v1.0.0.md`
- 部署清单：`AKO_qc_agent_deploy_checklist_v1.0.0.md`

## 依赖

- python>=3.9
- pyyaml>=6.0

---

> 作者：AKO_studio
> 日期：2026-08-21