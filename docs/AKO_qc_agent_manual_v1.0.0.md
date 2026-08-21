---
title: "AKO_qc_agent 使用手册"
description: "AKO_qc_agent 安装、运行、配置与规则维护手册"
author: "AKO_studio"
date: "2026-08-21"
version: "v1.0.0"
tags: ["document", "standard", "agent", "quality"]
instance_id: "AKO_qc_agent"
legal_entity: "91520198MAC8N3YB6U"
lineage:
  - family: "rule_engine"
    version: "v1.0.0"
    base_model: "deterministic"
former_names: []
lifecycle_state: "staging"
---

# AKO_qc_agent 使用手册

## 1. 安装

```bash
pip install -r requirements.txt
```

依赖仅 `pyyaml>=6.0`，其余为标准库。

## 2. 运行

```bash
# 单次质检（内置示例）
python src/core/main.py

# 指定输入/输出
python src/core/main.py --input sample.json --output qc_report.json

# 健康检查服务
python src/core/main.py --serve --port 5001
```

## 3. 配置

- 主配置：`config/AKO_qc_agent_config.yaml`
- 环境变量：`.env`（`AKO_QC_AGENT_PORT`、`AKO_QC_AGENT_LOG_LEVEL` 等）

## 4. 规则维护

规则集位于 `ako_qc_rules/`，入口映射见 `ako_qc_rules/version.json`：

| 规则集 | 文件 |
|--------|------|
| L3_brand | ruleset_L3_brand.yaml |
| L4_struct | ruleset_L4_struct.yaml |
| L4_material | ruleset_L4_material.yaml |
| L4_logic | ruleset_L4_logic.yaml |

修改规则后建议运行自检：

```bash
python ako_qc_rules_engine.py
```

## 5. 目录结构

```
src/core/        # 业务逻辑入口
config/          # 配置文件
docs/            # API 文档与手册
tests/           # 单元测试
ako_qc_rules/    # 规则集
```

## 6. 测试

```bash
python -m unittest discover -s tests -v
```

---

> **签章区**  
> 起草：AKO_studio  
> 审签：AKO_studio  
> 生效日期：2026-08-21  
> 下次审阅：2026-11-21