# AGO-WP-QC-2026-001

# AKO_qc_agent 技术白皮书

---

**文档编号**：AGO-WP-QC-2026-001  
**密级**：内部公开  
**版本**：V1.0  
**编制日期**：2026-07-29  
**编制部门**：AKO_studio  

| 角色 | 姓名 | 日期 | 签字 |
|------|------|------|------|
| 编制 | — | 2026-07-29 | — |
| 审核 | 老杨 | — | — |
| 批准 | — | — | — |

---

## 修订记录

| 版本 | 日期 | 修订内容 | 修订人 |
|------|------|----------|--------|
| V1.0 | 2026-07-29 | 初稿发布 | — |

---

## 目 录

1. 引言  
2. 目标与适用范围  
3. 架构定位  
4. 五层检测体系  
5. 规则引擎设计  
6. 实施路线  
7. 输入输出规范  
8. 附录  

---

## 1. 引言

AKO_Hub 已部署 7 个 Agent 与 1 条 Workflow，承担陶粒墙板技术方案编制、省市级申报材料生成、样板房 Vibe Design 输出等核心生产任务。随着 P2 阶段外部接口接入，系统输出的数量与复杂度将显著上升。

缺乏统一质量门（Quality Gate）的情况下，以下风险已实际存在：

- **知识库漂移**：Agent 以通用知识填补空白，与阿格知识库原文冲突；
- **契约失效**：JSON Schema 字段缺失、类型错位，导致下游节点解析失败；
- **品牌失控**：输出文本存在 AI 生成痕迹，工程编号体系不统一；
- **数值错误**：结构计算参数单位混淆、小数精度不足、规范版本过期；
- **信息泄露**：本地绝对路径、内部账号密钥随输出外流。

本白皮书定义 AKO_qc_agent 的技术方案，作为 AKO_Hub LangGraph 状态机中的**强制性质量门节点**，对所有生产型 Agent 的输出执行出厂检测。

---

## 2. 目标与适用范围

### 2.1 目标

建立一套**可配置、可审计、可拦截**的自动化质量检测机制，确保：

1. 所有 Agent 输出符合预设契约（Schema + 字段规则）；
2. 所有技术论断可溯源至阿格知识库或现行有效规范；
3. 所有数值计算经过规则引擎校验，精度与单位受控；
4. 所有输出符合 AKO 品牌格式规范；
5. 敏感信息零泄露。

### 2.2 适用范围

| 对象 | 检测阶段 | 说明 |
|------|----------|------|
| 7 个生产 Agent | 每次输出后 | 强制经过 AKO_qc_agent 节点 |
| Workflow 最终输出 | 流出前 | 作为终点闸门 |
| 外部接口回传数据 | 进入 AKO_Hub 时 | 反向检测，防止污染 |

---

## 3. 架构定位

### 3.1 节点拓扑

AKO_qc_agent 作为 LangGraph 状态机中的**无状态检查节点（Stateless Checkpoint Node）**，串联于每个生产 Agent 之后：

```
上游生产 Agent → AKO_qc_agent（五层检测）→ 路由决策
                                          │
                          ├─ PASS → 流入下游
                          ├─ WARN → 流入下游，标记风险，写入审计日志
                          └─ FAIL → 返回上游修正，附带 QC 报告
```

### 3.2 状态扩展

LangGraph State 新增以下字段：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `qc_status` | `enum` | `PASS` / `WARN` / `FAIL` / `BLOCK` |
| `qc_report` | `object` | 结构化检测报告，见第 7 章 |
| `qc_rules_version` | `string` | 本次检测使用的规则库版本号 |

### 3.3 路由逻辑

条件边（Conditional Edge）根据 `qc_status` 执行路由：

- `PASS`：直接进入下游节点；
- `WARN`：进入下游节点，同步写入 `qc_audit_log`；
- `FAIL` / `BLOCK`：回流至上游 Agent，触发修正循环，最大重试次数 3 次，超限转人工审核。

---

## 4. 五层检测体系

### 4.1 L1：契约合规性

**风险等级**：ERROR（不通过即拦截）  
**执行主体**：JSON Schema 验证器 + 正则表达式引擎

| 检测项 | 判定标准 | 失败示例 |
|--------|----------|----------|
| 结构合法性 | upstream_output 为合法 JSON | 输出含未闭合引号或尾随逗号 |
| Schema 匹配 | 字段名、嵌套层级、数组维度与 expected_schema 一致 | 缺少 `material_spec` 字段 |
| 必填非空 | 所有 `required` 字段存在且非 `null`/空字符串 | `project_id` 为 `""` |
| 类型正确 | 字段值类型符合 Schema 定义 | `string` 字段传入 `number` |
| 编号格式 | 工程编号符合 `AGO-XXX-YYYY-NNN` | `AGO-QC-2026-01`（缺一位序号） |
| 标号有效 | 材料标号（HRB400、LC25、φ 等）在 `ako_material_registry` 名录内 | 出现未注册标号 "LC30X" |

### 4.2 L2：知识库一致性

**风险等级**：ERROR  
**执行主体**：LLM（语义比对）+ 向量检索（上下文供给）

| 检测项 | 判定标准 | 失败示例 |
|--------|----------|----------|
| 事实可溯源 | 所有关键事实、数据（耐火极限、混凝土强度、配筋率、φ 值）在 `kb_context` 中有明确对应 | 声称陶粒墙板耐火极限 4h，但知识库记录为 3h |
| 禁止通用填补 | 不得出现模糊归因词汇："据我所知"、"一般认为"、"通常认为"、"参考相关规范" | 文本含 "根据一般工程经验" |
| 来源标注 | 每条引用须标注 collection 名及文档片段标识 | 只写 "根据规范"，未给出 AGO-QB-2024-003 第 5.2 条 |
| 版本时效 | 引用的规范须为现行有效版本 | 引用已废止的 GB50010-2010，未更新至 2024 版 |
| 引用完整 | 须追溯至具体条款号，不能只写规范名 | "根据 GB50010"（缺条款号） |

### 4.3 L3：品牌与格式规范

**风险等级**：WARN（不拦截，但强制记录）  
**执行主体**：正则表达式 + 规则引擎

| 检测项 | 判定标准 | 失败示例 |
|--------|----------|----------|
| 色系合规 | 可视化输出主色 `#EBDAB9`，锚点 `#231E1C`，辅助 `#A08C64` / `#B99B5F`；禁止纯白 `#FFFFFF` 作主色 | 背景使用 `#FFFFFF` |
| AI 痕迹 | 禁止过度破折号、三段式排比、夸大象征意义 | "在时代的浪潮中，我们以匠心铸就辉煌——这不仅是一面墙，更是未来的脊梁" |
| 编号统一 | 章节：1. / 1.1 / 1.1.1；表格：Tab-1、Tab-2；图：Fig-1 | 混用 "第一章"、"Section 1"、"Part I" |

### 4.4 L4：业务逻辑校验

**风险等级**：ERROR 或 WARN（按规则配置）  
**执行主体**：`ako_qc_rules_engine.py`（Python 规则引擎，非 LLM 推理）

| 检测项 | 判定标准 | 示例 |
|--------|----------|------|
| 数值区间 | 结构计算结果落在经验或规范允许区间 | 配筋率 ρ = 0.15%，低于最小配筋率 ρ_min = 0.2% → ERROR |
| 参数自洽 | 材料参数与工况匹配 | LC25 混凝土轴心抗压强度设计值 11.9 N/mm²，与 C30 混用 → ERROR |
| 逻辑一致 | 结论与前提不自相矛盾 | 前文称 "不考虑地震作用"，后文出现 "抗震构造措施" → ERROR |
| 精度单位 | 所有数值带单位；力保留 0.01 kN，应力保留 0.01 N/mm² | "钢筋面积 500"（缺单位 mm²）→ WARN |

规则引擎加载 `ako_qc_rules` collection 中的结构化规则（YAML/JSON），与 LLM 推理完全解耦，确保数值判定可复现、可审计。

### 4.5 L5：安全与敏感信息

**风险等级**：ERROR  
**执行主体**：正则表达式 + 敏感词库

| 检测项 | 判定标准 | 失败示例 |
|--------|----------|----------|
| 路径泄露 | 禁止包含本地绝对路径 | 文本含 `D:\BaiduSyncdisk\AKO_Hub\...` |
| 凭证泄露 | 禁止泄露账号、密码、Token、API Endpoint | 文本含 `sk-xxxxxxxx` 或 `https://api.ako.internal/...` |
| 内部域名 | 禁止暴露非公开内网域名 | 文本含 `http://nas.ako.local:8080` |

---

## 5. 规则引擎设计

### 5.1 设计原则

L4 业务逻辑检测涉及数值运算与规范条款比对，**不得依赖 LLM 的模糊推理**。规则引擎以确定性代码执行，确保：

- 同一输入，输出恒定；
- 规则变更不修改 Prompt；
- 计算过程可审计、可回放。

### 5.2 架构

```
ako_qc_rules (collection)
    │
    ├─ ruleset_L4_struct.yaml    # 结构计算规则
    ├─ ruleset_L4_material.yaml  # 材料参数规则
    ├─ ruleset_L4_logic.yaml     # 逻辑一致性规则
    └─ version.json              # 规则库版本控制

ako_qc_rules_engine.py
    │
    ├─ load_rules(ruleset_name, version)  # 从 collection 加载
    ├─ validate_struct(data)              # 结构计算校验
    ├─ validate_material(data)            # 材料参数校验
    ├─ validate_logic(data)               # 逻辑一致性校验
    └─ export_report()                    # 输出 L4 专项报告
```

### 5.3 规则配置示例

```yaml
# ruleset_L4_struct.yaml 片段
rule_id: L4-001
name: 最小配筋率校验
description: 受弯构件纵向受拉钢筋最小配筋率
target_field: reinforcement_ratio
condition:
  operator: less_than
  reference: material.min_reinforcement_rate
severity: ERROR
error_msg: "配筋率 {value} 低于规范最小值 {reference}"
```

---

## 6. 实施路线

### 6.1 P0 阶段（本周）

- **范围**：技术方案输出 Agent、申报材料 Agent
- **检测层**：L1（契约）+ L2（知识库一致性）
- **运行模式**：审计模式（Audit Mode）—— 记录报告，不阻断流程，用真实数据校准规则精度
- **交付物**：
  1. `ako_qc_agent.py`（LangGraph 节点）
  2. `ako_qc_rules_engine.py`（L4 骨架）
  3. `ako_qc_rules` collection 初始化

### 6.2 P1 阶段（下周）

- **范围**：全部 7 个 Agent + Workflow
- **检测层**：L1-L5 全量启用
- **运行模式**：拦截模式（Blocking Mode）—— ERROR 级别强制回流修正
- **交付物**：
  1. L3 品牌格式规则库
  2. L4 完整规则集（结构 + 材料 + 逻辑）
  3. `qc_audit_log` 持久化与可视化面板

### 6.3 P2 阶段（外部接口接入时）

- **范围**：外部接口回传数据反向检测
- **新增**：输入侧 QC 节点，防止外部污染数据进入 AKO_Hub
- **交付物**：`ako_qc_inbound_agent.py`

---

## 7. 输入输出规范

### 7.1 AKO_qc_agent 输入

```json
{
  "upstream_output": "<上游 Agent 的完整输出，JSON 或文本>",
  "expected_schema": { "<JSON Schema 定义>" },
  "kb_context": [
    {
      "collection": "陶粒墙板技术方案",
      "doc_id": "AGO-QB-2024-003",
      "fragment": "..."
    }
  ],
  "rules_version": "v1.2.0"
}
```

### 7.2 AKO_qc_agent 输出（QC 报告 Schema）

```json
{
  "qc_status": "PASS | FAIL",
  "overall_risk_level": "INFO | WARN | ERROR | BLOCK",
  "rules_version": "v1.2.0",
  "report": [
    {
      "layer": "L1",
      "item": "JSON Schema 验证",
      "status": "PASS",
      "detail": "输出结构完全符合预期 Schema，所有必填字段非空。",
      "suggestion": ""
    },
    {
      "layer": "L2",
      "item": "关键数据溯源",
      "status": "FAIL",
      "detail": "Agent 在回答「陶粒墙板耐火极限」时引用通用规范 GB50016，未引用阿格知识库中的企业标准 AGO-QB-2024-003。",
      "suggestion": "优先检索并引用 collection: 陶粒墙板技术方案 中的相关标准，补充条款号。"
    }
  ]
}
```

### 7.3 字段说明

| 字段 | 类型 | 约束 |
|------|------|------|
| `qc_status` | `string` | 枚举：`PASS` / `FAIL`。存在任何 ERROR 级别即 `FAIL` |
| `overall_risk_level` | `string` | 枚举：`INFO` / `WARN` / `ERROR` / `BLOCK` |
| `rules_version` | `string` | 本次检测使用的 `ako_qc_rules` 版本号 |
| `report.layer` | `string` | 枚举：`L1` / `L2` / `L3` / `L4` / `L5` |
| `report.status` | `string` | 枚举：`PASS` / `FAIL` |
| `report.detail` | `string` | 失败时必须给出原文片段，不可泛泛而谈 |
| `report.suggestion` | `string` | 修正指令必须可执行，不可模糊 |

---

## 8. 附录

### 附录 A：AKO_qc_agent System Prompt 定稿

```
# AKO_Hub 出厂检测规程 — QC-001

## 输入
- upstream_output: 上游 Agent 完整输出
- expected_schema: 预期 JSON Schema
- kb_context: 从知识库检索到的相关上下文（collection 名 + 原文片段）
- rules_version: 规则库版本

## 输出
严格按 QC_REPORT_SCHEMA 输出 JSON，禁止附加任何解释性文本。

## 检测规程（逐条执行，不得跳过）

### L1 契约合规 — ERROR 级
1. upstream_output 是否为合法 JSON？
2. 结构是否与 expected_schema 严格匹配（字段名、嵌套层级、数组维度）？
3. 必填字段是否非空？字段类型是否正确？
4. 工程编号格式是否符合 AGO-XXX-YYYY-NNN 规则？
5. 材料标号（HRB400、LC25 等）是否在 ako_material_registry 名录内？

### L2 知识库一致性 — ERROR 级
1. 所有关键事实、数据必须在 kb_context 中有明确对应。
2. 禁止模糊归因词汇："据我所知"、"一般认为"、"通常认为"、"参考相关规范"。
3. 每条引用必须标注来源 collection 名及文档片段标识。
4. 引用规范须为现行有效版本。
5. 每条技术论断必须可追溯至具体规范条款号。

### L3 品牌与格式 — WARN 级
1. 可视化输出主色 #EBDAB9，锚点 #231E1C，辅助 #A08C64 / #B99B5F；禁止纯白 #FFFFFF 作主色。
2. 禁止过度破折号、三段式排比、夸大象征意义。
3. 编号体系统一：章节 1. / 1.1 / 1.1.1，表格 Tab-N，图 Fig-N。

### L4 业务逻辑 — ERROR/WARN 级
1. 结构计算数值是否在合理经验区间？（调用 ako_qc_rules_engine）
2. 材料参数是否自洽？（调用 ako_qc_rules_engine）
3. 结论与前提分析是否存在矛盾？（调用 ako_qc_rules_engine）
4. 所有数值必须带单位；力保留 0.01 kN 精度，应力保留 0.01 N/mm² 精度。

### L5 安全与敏感信息 — ERROR 级
1. 禁止包含本地绝对路径（D:\、C:\Users\）。
2. 禁止泄露账号、密钥、Token、API Endpoint。

## QC_REPORT_SCHEMA
{
  "qc_status": "PASS | FAIL",
  "overall_risk_level": "INFO | WARN | ERROR | BLOCK",
  "rules_version": "string",
  "report": [
    {
      "layer": "L1~L5",
      "item": "检测项名称",
      "status": "PASS | FAIL",
      "detail": "具体发现，失败时必须给出原文片段",
      "suggestion": "修正指令，必须可执行"
    }
  ]
}
```

### 附录 B：规则引擎配置示例

见第 5.3 节 `ruleset_L4_struct.yaml` 片段。

### 附录 C：相关文档索引

| 文档编号 | 名称 | 关系 |
|----------|------|------|
| AGO-QB-2024-003 | 陶粒墙板企业技术标准 | L2 引用来源 |
| AGO-WP-ARCH-2026-001 | AKO_Hub 架构白皮书 | 架构上下文 |

---

**文档结束**
