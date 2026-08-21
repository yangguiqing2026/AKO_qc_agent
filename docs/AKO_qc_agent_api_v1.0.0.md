---
title: "AKO_qc_agent API 接口文档"
description: "AKO_qc_agent 命令行与健康检查接口说明"
author: "AKO_studio"
date: "2026-08-21"
version: "v1.0.0"
tags: ["api", "standard", "agent", "document"]
instance_id: "AKO_qc_agent"
legal_entity: "91520198MAC8N3YB6U"
lineage:
  - family: "rule_engine"
    version: "v1.0.0"
    base_model: "deterministic"
former_names: []
lifecycle_state: "staging"
---

# AKO_qc_agent API 接口文档

## 1. 命令行接口（CLI）

入口：`python src/core/main.py`（或 `python app.py`）

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `--config` | string | 否 | 配置文件路径，默认 `config/AKO_qc_agent_config.yaml` |
| `--input` | string | 否 | 待检上游输出 JSON 文件路径；缺省时运行内置自检示例 |
| `--output` | string | 否 | QC 报告输出路径，默认 `qc_report.json` |
| `--log-level` | string | 否 | 日志级别：DEBUG/INFO/WARNING/ERROR，默认 INFO |
| `--serve` | flag | 否 | 启动健康检查 HTTP 服务 |
| `--port` | int | 否 | 健康检查端口，默认 5001 |

示例：

```bash
python src/core/main.py --input sample_output.json --output qc_report.json
python src/core/main.py --serve --port 5001
```

## 2. 健康检查接口（HTTP）

| 项 | 说明 |
|------|------|
| 方法 | GET |
| 路径 | `/health` |
| 成功响应 | `200 ok` |
| 端点 | `http://localhost:5001/health` |

## 3. Python 库接口

核心类 `AKOQCAgent`（`ako_qc_agent.py`）：

```python
from ako_qc_agent import AKOQCAgent

agent = AKOQCAgent()
report = agent.run(
    upstream_output={...},
    expected_schema={...},
    kb_context=[...],
    rules_version=None,
)
```

`report` 结构符合 `QC_REPORT_SCHEMA`，包含 `qc_status`、`overall_risk_level`、`rules_version`、`report`。

规则引擎 `AKOQCRulesEngine`（`ako_qc_rules_engine.py`）提供 `validate_struct` / `validate_material` / `validate_logic` / `validate_all`。

入站检测 `AKOQCInboundAgent`（`ako_qc_inbound_agent.py`）提供 `run(inbound_data, source, expected_schema)`。

审计日志 `QCAuditLog`（`ako_qc_audit_log.py`）提供 `write` / `query` / `summary` / `clear`。

---

> **签章区**  
> 起草：AKO_studio  
> 审签：AKO_studio  
> 生效日期：2026-08-21  
> 下次审阅：2026-11-21