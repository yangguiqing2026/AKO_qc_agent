---
title: "AKO_qc_agent 白皮书"
description: "AKO_qc_agent出厂质量门顶层设计，定义五层检测体系、双态运行、规则引擎与健康监控"
author: "AKO_studio"
date: "2026-08-21"
version: "v1.0.0"
tags: ["quality", "standard", "agent", "document", "whitepaper"]
instance_id: "AKO_qc_agent"
legal_entity: "91520198MAC8N3YB6U"
lineage:
  - family: "rule_engine"
    version: "v1.0.0"
    base_model: "deterministic"
former_names: []
lifecycle_state: "staging"
---

# AKO_qc_agent 白皮书

## 1. 概述

**AKO_qc_agent**（阿格质检 Agent）是 AKO_Hub 的出厂质量门（Quality Gate）。它按照 law_v1.0 标准对所有生产型 Agent 输出执行五层检测（L1 契约 → L2 知识库 → L3 品牌 → L4 业务逻辑 → L5 安全），输出结构化 qc_report.json。支持审计模式与拦截模式双态运行，确保 AKO 体系所有输出均达到质量基线。

## 2. 核心能力

### 2.1 L1 契约合规检测（cap_l1_contract）

JSON Schema 验证、字段必填、类型正确、工程编号格式、材料标号白名单校验。

- **输入**：`upstream_output`（上游 Agent 完整输出）、`expected_schema`（预期 JSON Schema）
- **输出**：`l1_report`，契约合规报告
- **优先级**：P0

### 2.2 L2 知识库一致性（cap_l2_kb_consistency）

关键事实可溯源、禁止通用填补、来源标注、版本时效、引用完整性校验。

- **输入**：`upstream_output`、`kb_context`（知识库检索上下文）
- **输出**：`l2_report`，知识库一致性报告
- **优先级**：P0

### 2.3 L3 品牌与格式规范（cap_l3_brand）

AKO 色系合规（#EBDAB9 / #231E1C 等）、AI 痕迹检测、编号体系统一。

- **输入**：`upstream_output`（JSON 或文本）
- **输出**：`l3_report`，品牌格式报告（WARN 级不拦截）
- **优先级**：P1

### 2.4 L4 业务逻辑校验（cap_l4_logic）

数值区间校验、参数自洽、逻辑一致性、精度单位检查，调用 ako_qc_rules_engine 确定性规则引擎，与 LLM 推理完全解耦。

- **输入**：`upstream_output`（JSON）
- **输出**：`l4_report`，业务逻辑校验报告
- **优先级**：P0

### 2.5 L5 安全与敏感信息（cap_l5_security）

本地路径泄露、凭证 Token 泄露、内网域名暴露检测。

- **输入**：`upstream_output`（JSON 或文本）
- **输出**：`l5_report`，安全检测报告
- **优先级**：P0

### 2.6 规则引擎（cap_rules_engine）

加载 ako_qc_rules collection 中的结构化规则（YAML/JSON），执行 L4 数值判定，与 LLM 推理完全解耦。

- **输入**：`ruleset_name`（规则集名称）、`version`（版本）
- **输出**：`rule_report`，规则引擎专项报告
- **优先级**：P0

## 3. 架构设计

| 要素 | 说明 |
|------|------|
| 语言 | Python |
| 框架 | LangGraph |
| 入口点 | src/core/main.py |
| 配置文件 | config/AKO_qc_agent_config.yaml、.env |
| 依赖文件 | requirements.txt、ako_qc_rules_engine.py、ako_qc_audit_log.py、ako_qc_inbound_agent.py |
| 运行时端点 | http://localhost:5001（`--serve` 提供 /health） |
| 心跳间隔 | 30s |
| 状态 | staging（首部署 offline） |

## 4. 组织关系

- **上级**：AKO_hub_agent（任务分发）
- **通知**：AKO_law_agent（严重违规触发审查）
- **读取**：AKO_registry_agent（读取 Agent 注册信息）

## 5. 运行模式

| 模式 | 说明 |
|------|------|
| 审计模式 | 仅记录问题，不拦截，允许输出继续流转 |
| 拦截模式 | 发现 P0 级别问题则阻断输出流转，触发 law_agent 审查 |

## 6. 健康监控

- **健康检查**：`GET /health` → `ok`，探测间隔 30s
- **心跳**：间隔 30s
- **业务探针**：核心功能自检（30s）、规则引擎加载（10s）、依赖服务可用（5s）
- **系统探针**：CPU/内存/磁盘阈值 80%、网络连通（5s）

## 7. 合规自评

| 维度 | 分值 |
|------|------|
| P1 元数据 | 22 |
| P2 核心功能 | 28 |
| P3 接口规范 | 24 |
| P4 健壮性 | 14 |

| 否决项 | 状态 |
|--------|------|
| V1 无硬编码密钥 | 通过 |
| V2 无 GUI 残留 | 通过 |
| V3 Card 非占位符 | 通过 |
| V4 无循环依赖 | 通过 |
| V5 架构合规 | 通过 |

## 8. 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| v1.0.0 | 2026-07-29 | 初始版本 |
| v1.0.0 | 2026-08-21 | 对齐 law_v1.0 文档标准，修正入口与配置声明 |

---

> **签章区**  
> 起草：AKO_studio  
> 审签：AKO_studio  
> 生效日期：2026-08-21  
> 下次审阅：2026-11-21