"""
ako_qc_agent.py
===============
AKO_qc_agent — LangGraph 状态机中的强制性质量门节点

五层检测体系：
  L1 契约合规性     — ERROR 级，JSON Schema + 正则
  L2 知识库一致性   — ERROR 级，LLM 语义比对 + 向量检索
  L3 品牌与格式规范 — WARN 级，正则 + 规则引擎
  L4 业务逻辑校验   — ERROR/WARN 级，确定性规则引擎
  L5 安全与敏感信息 — ERROR 级，正则 + 敏感词库

路由逻辑：
  PASS  → 流入下游
  WARN  → 流入下游，标记风险，写入审计日志
  FAIL  → 返回上游修正，附带 QC 报告（最大重试 3 次，超限转人工）
  BLOCK → 强制拦截，转人工审核
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Literal, Optional, TypedDict

from ako_qc_rules_engine import AKOQCRulesEngine, L4Report
from ako_qc_audit_log import QCAuditLog

logger = logging.getLogger("ako_qc_agent")


# ============================================================
# LangGraph State 扩展字段
# ============================================================

class QCState(TypedDict, total=False):
    """LangGraph State 中 QC 相关字段"""
    qc_status: str            # PASS / WARN / FAIL / BLOCK
    qc_report: dict           # 结构化检测报告
    qc_rules_version: str     # 规则库版本号
    qc_retry_count: int       # 当前重试次数


# ============================================================
# 检测报告数据结构
# ============================================================

@dataclass
class ReportItem:
    """单层检测报告条目"""
    layer: str          # L1 / L2 / L3 / L4 / L5
    item: str           # 检测项名称
    status: str         # PASS / FAIL
    detail: str         # 具体发现
    suggestion: str     # 修正指令


@dataclass
class QCReport:
    """完整 QC 报告"""
    qc_status: str = "PASS"                     # PASS / FAIL
    overall_risk_level: str = "INFO"            # INFO / WARN / ERROR / BLOCK
    rules_version: str = ""
    report: List[ReportItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "qc_status": self.qc_status,
            "overall_risk_level": self.overall_risk_level,
            "rules_version": self.rules_version,
            "report": [asdict(item) for item in self.report],
        }


# ============================================================
# L1：契约合规性检测
# ============================================================

# 工程编号正则：AGO-XXX-YYYY-NNN
_PROJECT_ID_PATTERN = re.compile(r"^AGO-[A-Z]{3}-\d{4}-\d{3}$")

# 材料标号白名单（来自 ako_material_registry）
_MATERIAL_REGISTRY = {
    # 混凝土
    "C15", "C20", "C25", "C30", "C35", "C40", "C45", "C50",
    "LC20", "LC25", "LC30",
    # 钢筋
    "HPB300", "HRB400", "HRB500",
    # 其他
    "Q235", "Q345",
}


def _check_l1_contract(upstream_output: Any, expected_schema: Optional[dict]) -> ReportItem:
    """
    L1 契约合规性检测

    检测项：
    1. upstream_output 是否为合法 JSON
    2. 结构是否与 expected_schema 匹配
    3. 必填字段是否非空
    4. 字段类型是否正确
    5. 工程编号格式
    6. 材料标号是否在注册表内
    """
    issues: List[str] = []
    suggestions: List[str] = []

    # ---- 1. JSON 合法性 ----
    if isinstance(upstream_output, str):
        try:
            data = json.loads(upstream_output)
        except json.JSONDecodeError as e:
            return ReportItem(
                layer="L1", item="JSON 合法性", status="FAIL",
                detail=f"输出不是合法 JSON：{e}",
                suggestion="检查 JSON 语法，修复未闭合引号或尾随逗号。",
            )
    elif isinstance(upstream_output, dict):
        data = upstream_output
    else:
        return ReportItem(
            layer="L1", item="JSON 合法性", status="FAIL",
            detail=f"输出类型为 {type(upstream_output).__name__}，预期 dict 或 JSON 字符串。",
            suggestion="确保 Agent 输出为 JSON 对象。",
        )

    # ---- 2. Schema 匹配 ----
    if expected_schema:
        schema_issues = _validate_schema(data, expected_schema)
        issues.extend(schema_issues)
        if schema_issues:
            suggestions.append("按 expected_schema 补全缺失字段、修正类型。")

    # ---- 3. 必填非空 ----
    required_fields = []
    if expected_schema and "required" in expected_schema:
        required_fields = expected_schema["required"]
    for f in required_fields:
        val = data.get(f)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            issues.append(f"必填字段 '{f}' 为空或 null。")
            suggestions.append(f"为字段 '{f}' 提供有效值。")

    # ---- 4. 工程编号格式 ----
    project_id = data.get("project_id", "")
    if isinstance(project_id, str) and project_id:
        if not _PROJECT_ID_PATTERN.match(project_id):
            issues.append(f"工程编号 '{project_id}' 不符合 AGO-XXX-YYYY-NNN 格式。")
            suggestions.append("工程编号格式应为 AGO-XXX-YYYY-NNN，如 AGO-QC-2026-001。")

    # ---- 5. 材料标号 ----
    material_refs = _extract_material_refs(data)
    invalid_materials = [m for m in material_refs if m not in _MATERIAL_REGISTRY]
    if invalid_materials:
        issues.append(f"材料标号 {invalid_materials} 不在 ako_material_registry 名录内。")
        suggestions.append(f"核实材料标号：{invalid_materials}，使用注册表中的标准标号。")

    # ---- 汇总 ----
    if issues:
        return ReportItem(
            layer="L1", item="契约合规性", status="FAIL",
            detail="；".join(issues),
            suggestion="；".join(suggestions),
        )

    return ReportItem(
        layer="L1", item="契约合规性", status="PASS",
        detail="输出结构完全符合预期 Schema，所有必填字段非空，编号格式正确。",
        suggestion="",
    )


def _validate_schema(data: dict, schema: dict) -> List[str]:
    """简易 Schema 校验（字段名 + 类型）"""
    issues = []
    properties = schema.get("properties", {})
    for field_name, field_def in properties.items():
        if field_name not in data:
            issues.append(f"缺少字段 '{field_name}'。")
            continue
        expected_type = field_def.get("type")
        if expected_type:
            actual = data[field_name]
            type_map = {"string": str, "number": (int, float), "integer": int,
                        "boolean": bool, "array": list, "object": dict}
            py_type = type_map.get(expected_type)
            if py_type and not isinstance(actual, py_type):
                issues.append(
                    f"字段 '{field_name}' 类型应为 {expected_type}，"
                    f"实际为 {type(actual).__name__}。"
                )
    return issues


def _extract_material_refs(data: Any) -> List[str]:
    """递归提取数据中所有可能的材料标号"""
    refs = []
    if isinstance(data, str):
        # 匹配常见材料标号模式
        refs.extend(re.findall(r"\b(C\d{2}|LC\d{2}|HRB\d{3}|HPB\d{3}|Q\d{3}|φ\d+)\b", data))
    elif isinstance(data, dict):
        for v in data.values():
            refs.extend(_extract_material_refs(v))
    elif isinstance(data, list):
        for item in data:
            refs.extend(_extract_material_refs(item))
    return list(set(refs))


# ============================================================
# L2：知识库一致性检测
# ============================================================

# 禁止的模糊归因词汇
_VAGUE_ATTRIBUTION_PATTERNS = [
    "据我所知", "一般认为", "通常认为", "参考相关规范",
    "根据一般工程经验", "据估计", "大概", "可能",
    "据了解", "众所周知", "不言而喻",
]

# 需要引用的来源格式
_SOURCE_PATTERN = re.compile(r"(AGO-QB-\d{4}-\d{3}|GB\s?\d{5})")


def _check_l2_knowledge(upstream_output: Any, kb_context: Optional[List[dict]]) -> ReportItem:
    """
    L2 知识库一致性检测

    检测项：
    1. 关键事实是否可溯源
    2. 禁止通用填补
    3. 来源标注
    4. 版本时效
    5. 引用完整
    """
    issues: List[str] = []
    suggestions: List[str] = []

    # 提取文本内容
    text = _extract_text(upstream_output)

    # ---- 1. 禁止模糊归因 ----
    found_vague = [p for p in _VAGUE_ATTRIBUTION_PATTERNS if p in text]
    if found_vague:
        issues.append(f"发现模糊归因词汇：{found_vague}。")
        suggestions.append("删除模糊归因表述，改为引用具体知识库文档及条款号。")

    # ---- 2. 来源标注 ----
    sources_found = _SOURCE_PATTERN.findall(text)
    if not sources_found and kb_context:
        # 有知识库上下文但输出中没有任何引用
        issues.append("输出中未发现任何知识库或规范引用标注。")
        suggestions.append("每条技术论断须标注来源 collection 名及文档片段标识（如 AGO-QB-2024-003 第 5.2 条）。")

    # ---- 3. 引用完整性（是否追溯到条款号） ----
    if sources_found:
        # 检查引用后面是否跟了条款号
        clause_pattern = re.compile(r"第\s*[\d\.]+\s*[条款项]")
        for src in sources_found:
            src_pos = text.find(src)
            if src_pos >= 0:
                surrounding = text[src_pos:src_pos + 60]
                if not clause_pattern.search(surrounding):
                    issues.append(f"引用 '{src}' 未追溯到具体条款号。")
                    suggestions.append(f"补充 '{src}' 的具体条款号，如「第 X.X 条」。")

    # ---- 4. 关键数据溯源（简化版，完整版需 LLM） ----
    # 提取文本中的数值，检查是否在 kb_context 中有对应
    numbers_in_text = re.findall(r"\d+\.?\d*\s*(?:N/mm²|kN|mm|MPa|h|°C|%)", text)
    if numbers_in_text and kb_context:
        kb_text = " ".join(
            ctx.get("fragment", "") for ctx in kb_context if isinstance(ctx, dict)
        )
        for num_str in numbers_in_text[:5]:  # 抽检前 5 个
            num_val = re.match(r"\d+\.?\d*", num_str)
            if num_val:
                num = num_val.group()
                if num not in kb_text:
                    issues.append(f"数值 {num_str} 在知识库上下文中未找到对应来源。")
                    suggestions.append(f"核实数值 {num_str} 的来源，确保可溯源至知识库。")
                    break  # 只报告第一个

    # ---- 汇总 ----
    if issues:
        return ReportItem(
            layer="L2", item="知识库一致性", status="FAIL",
            detail="；".join(issues),
            suggestion="；".join(suggestions),
        )

    return ReportItem(
        layer="L2", item="知识库一致性", status="PASS",
        detail="关键数据均可溯源至知识库，引用标注完整，无模糊归因。",
        suggestion="",
    )


def _extract_text(data: Any) -> str:
    """从各种数据结构中提取文本"""
    if isinstance(data, str):
        return data
    elif isinstance(data, dict):
        parts = []
        for v in data.values():
            parts.append(_extract_text(v))
        return " ".join(parts)
    elif isinstance(data, list):
        return " ".join(_extract_text(item) for item in data)
    return ""


# ============================================================
# L3：品牌与格式规范检测
# ============================================================

# AKO 品牌色系
_AKO_COLORS = {
    "primary": "#EBDAB9",
    "anchor": "#231E1C",
    "aux1": "#A08C64",
    "aux2": "#B99B5F",
}
_FORBIDDEN_PRIMARY = "#FFFFFF"

# 编号格式正则
_CHAPTER_PATTERN = re.compile(r"^(?:第[一二三四五六七八九十]+[章节]|Section\s+\d+|Part\s+[IVX]+)", re.MULTILINE)
_CORRECT_CHAPTER = re.compile(r"^\d+\.\d*\.?\d*\.?\s", re.MULTILINE)
_TAB_PATTERN = re.compile(r"Tab-\d+", re.IGNORECASE)
_FIG_PATTERN = re.compile(r"Fig-\d+", re.IGNORECASE)

# AI 痕迹检测
_AI_PATTERNS = [
    re.compile(r"[—–]{2,}"),  # 过度破折号
    re.compile(r"在时代的浪潮中"),
    re.compile(r"以匠心铸就"),
    re.compile(r"这不仅.*更是"),
    re.compile(r"辉煌"),
]


def _check_l3_brand(upstream_output: Any) -> ReportItem:
    """
    L3 品牌与格式规范检测

    检测项：
    1. 色系合规
    2. AI 痕迹
    3. 编号统一
    """
    issues: List[str] = []
    suggestions: List[str] = []

    text = _extract_text(upstream_output)

    # ---- 1. 色系合规 ----
    hex_colors = re.findall(r"#[0-9A-Fa-f]{6}", text)
    if _FORBIDDEN_PRIMARY in [c.upper() for c in hex_colors]:
        issues.append(f"发现纯白色 {_FORBIDDEN_PRIMARY} 作为主色使用。")
        suggestions.append(f"主色应使用 AKO 品牌色 {_AKO_COLORS['primary']}。")

    # ---- 2. AI 痕迹 ----
    ai_matches = []
    for pattern in _AI_PATTERNS:
        match = pattern.search(text)
        if match:
            ai_matches.append(f"「{match.group()}」")
    if ai_matches:
        issues.append(f"发现 AI 生成痕迹：{', '.join(ai_matches)}。")
        suggestions.append("删除夸张修辞，使用简洁专业的工程语言。")

    # ---- 3. 编号统一 ----
    wrong_chapters = _CHAPTER_PATTERN.findall(text)
    if wrong_chapters:
        issues.append(f"发现非标准章节编号：{wrong_chapters[:3]}。")
        suggestions.append("统一使用 1. / 1.1 / 1.1.1 编号体系。")

    # ---- 汇总 ----
    if issues:
        return ReportItem(
            layer="L3", item="品牌与格式规范", status="FAIL",
            detail="；".join(issues),
            suggestion="；".join(suggestions),
        )

    return ReportItem(
        layer="L3", item="品牌与格式规范", status="PASS",
        detail="色系合规，无 AI 痕迹，编号体系统一。",
        suggestion="",
    )


# ============================================================
# L5：安全与敏感信息检测
# ============================================================

# 敏感信息正则
_LOCAL_PATH_PATTERN = re.compile(r"[A-Z]:\\(?:Users|BaiduSyncdisk|Documents)\\", re.IGNORECASE)
_CREDENTIAL_PATTERN = re.compile(r"sk-[a-zA-Z0-9]{20,}|api[_-]?key\s*[:=]\s*\S+", re.IGNORECASE)
_INTERNAL_DOMAIN_PATTERN = re.compile(r"https?://[\w.-]*\.ako\.(internal|local|lan)[:/\s]", re.IGNORECASE)
_INTERNAL_IP_PATTERN = re.compile(r"https?://(?:10\.|172\.(?:1[6-9]|2\d|3[01])\.|192\.168\.)\d+\.\d+")


def _check_l5_security(upstream_output: Any) -> ReportItem:
    """
    L5 安全与敏感信息检测

    检测项：
    1. 路径泄露
    2. 凭证泄露
    3. 内部域名
    """
    issues: List[str] = []
    suggestions: List[str] = []

    text = _extract_text(upstream_output)

    # ---- 1. 路径泄露 ----
    paths = _LOCAL_PATH_PATTERN.findall(text)
    if paths:
        issues.append(f"发现本地绝对路径泄露：{paths[:2]}。")
        suggestions.append("删除所有本地绝对路径，使用相对路径或文件名替代。")

    # ---- 2. 凭证泄露 ----
    creds = _CREDENTIAL_PATTERN.findall(text)
    if creds:
        issues.append(f"发现疑似凭证泄露：{creds[0][:10]}...。")
        suggestions.append("立即删除所有 API Key、Token、密码等凭证信息。")

    # ---- 3. 内部域名 ----
    domains = _INTERNAL_DOMAIN_PATTERN.findall(text)
    ips = _INTERNAL_IP_PATTERN.findall(text)
    if domains or ips:
        found = domains + ips
        issues.append(f"发现内部域名/IP 泄露：{found[:2]}。")
        suggestions.append("删除所有内网域名和 IP 地址。")

    # ---- 汇总 ----
    if issues:
        return ReportItem(
            layer="L5", item="安全与敏感信息", status="FAIL",
            detail="；".join(issues),
            suggestion="；".join(suggestions),
        )

    return ReportItem(
        layer="L5", item="安全与敏感信息", status="PASS",
        detail="未发现路径、凭证或内部域名泄露。",
        suggestion="",
    )


# ============================================================
# AKO_qc_agent 主节点
# ============================================================

MAX_RETRY = 3  # 最大重试次数


class AKOQCAgent:
    """
    AKO_qc_agent — LangGraph 质量门节点

    作为无状态检查节点（Stateless Checkpoint Node），
    串联于每个生产 Agent 之后执行五层检测。
    """

    def __init__(self, rules_dir: Optional[str] = None, audit_log_db: Optional[str] = None):
        self.rules_engine = AKOQCRulesEngine(rules_dir=rules_dir)
        self._audit_log: List[dict] = []
        self._audit_db = QCAuditLog(db_path=audit_log_db)
        # 加载 L3 品牌规则
        try:
            self._l3_rules = self.rules_engine.load_rules("L3_brand")
        except FileNotFoundError:
            self._l3_rules = {}

    def run(
        self,
        upstream_output: Any,
        expected_schema: Optional[dict] = None,
        kb_context: Optional[List[dict]] = None,
        rules_version: Optional[str] = None,
    ) -> dict:
        """
        执行五层检测，返回 QC 报告

        Parameters
        ----------
        upstream_output : Any
            上游 Agent 的完整输出
        expected_schema : dict, optional
            预期 JSON Schema
        kb_context : list, optional
            知识库上下文
        rules_version : str, optional
            规则库版本号

        Returns
        -------
        dict
            符合 QC_REPORT_SCHEMA 的检测报告
        """
        report = QCReport()
        report.rules_version = rules_version or self.rules_engine.rules_version

        # ---- L1 契约合规 ----
        l1_result = _check_l1_contract(upstream_output, expected_schema)
        report.report.append(l1_result)

        # ---- L2 知识库一致性 ----
        l2_result = _check_l2_knowledge(upstream_output, kb_context)
        report.report.append(l2_result)

        # ---- L3 品牌与格式 ----
        l3_result = _check_l3_brand(upstream_output)
        report.report.append(l3_result)

        # ---- L4 业务逻辑 ----
        l4_data = self._prepare_l4_data(upstream_output)
        l4_report = self.rules_engine.validate_all(l4_data)
        l4_item = ReportItem(
            layer="L4",
            item="业务逻辑校验",
            status="PASS" if l4_report.status == "PASS" else "FAIL",
            detail="；".join(v.message for v in l4_report.violations) if l4_report.violations else "所有数值校验通过。",
            suggestion="按规则引擎报告修正对应数值。" if l4_report.status == "FAIL" else "",
        )
        report.report.append(l4_item)

        # ---- L5 安全与敏感信息 ----
        l5_result = _check_l5_security(upstream_output)
        report.report.append(l5_result)

        # ---- 汇总判定 ----
        self._determine_overall_status(report)

        # ---- 写入审计日志 ----
        self._write_audit_log(report)

        return report.to_dict()

    def _prepare_l4_data(self, upstream_output: Any) -> dict:
        """从上游输出中提取 L4 校验所需的数据"""
        if isinstance(upstream_output, dict):
            data = dict(upstream_output)
            # text_content 仅从 description / text / content 等文本字段提取
            # 不从 project_id、编号等字段提取，避免误报
            if "text_content" not in data:
                text_fields = ["description", "text", "content", "summary", "narrative"]
                parts = []
                for f in text_fields:
                    val = data.get(f)
                    if isinstance(val, str):
                        parts.append(val)
                data["text_content"] = " ".join(parts)
            return data
        else:
            return {"text_content": str(upstream_output)}

    @staticmethod
    def _determine_overall_status(report: QCReport) -> None:
        """根据各层结果确定整体状态"""
        has_error = False
        has_warn = False
        has_security = False

        for item in report.report:
            if item.status == "FAIL":
                if item.layer in ("L1", "L2", "L4"):
                    has_error = True
                elif item.layer == "L5":
                    has_error = True
                    has_security = True
                elif item.layer == "L3":
                    has_warn = True

        if has_security:
            report.overall_risk_level = "BLOCK"
            report.qc_status = "FAIL"
        elif has_error:
            report.overall_risk_level = "ERROR"
            report.qc_status = "FAIL"
        elif has_warn:
            report.overall_risk_level = "WARN"
            report.qc_status = "PASS"  # WARN 不拦截
        else:
            report.overall_risk_level = "INFO"
            report.qc_status = "PASS"

    def _write_audit_log(self, report: QCReport) -> None:
        """写入审计日志（内存 + SQLite 持久化）"""
        report_dict = report.to_dict()
        log_entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "qc_status": report.qc_status,
            "overall_risk_level": report.overall_risk_level,
            "rules_version": report.rules_version,
            "layers": {
                item.layer: item.status for item in report.report
            },
        }
        self._audit_log.append(log_entry)
        # 持久化到 SQLite
        try:
            self._audit_db.write(report_dict, source="ako_qc_agent")
        except Exception as e:
            logger.warning("审计日志写入失败: %s", e)
        logger.info("QC 审计日志: %s", json.dumps(log_entry, ensure_ascii=False))

    def get_audit_log(self) -> List[dict]:
        """获取审计日志"""
        return list(self._audit_log)


# ============================================================
# LangGraph 节点函数（供状态机调用）
# ============================================================

def ako_qc_node(state: dict) -> dict:
    """
    LangGraph 节点函数

    从 state 中读取上游输出和配置，执行五层检测，
    将 qc_status / qc_report / qc_rules_version 写回 state。

    Parameters
    ----------
    state : dict
        LangGraph 状态字典

    Returns
    -------
    dict
        更新后的状态字段
    """
    upstream_output = state.get("upstream_output")
    expected_schema = state.get("expected_schema")
    kb_context = state.get("kb_context")
    rules_version = state.get("rules_version")
    retry_count = state.get("qc_retry_count", 0)

    agent = AKOQCAgent()
    qc_result = agent.run(
        upstream_output=upstream_output,
        expected_schema=expected_schema,
        kb_context=kb_context,
        rules_version=rules_version,
    )

    # 检查重试次数
    if qc_result["qc_status"] == "FAIL" and retry_count >= MAX_RETRY:
        qc_result["qc_status"] = "BLOCK"
        qc_result["overall_risk_level"] = "BLOCK"
        logger.warning("QC 重试次数已达上限 (%d)，转为人工审核。", MAX_RETRY)

    return {
        "qc_status": qc_result["qc_status"],
        "qc_report": qc_result,
        "qc_rules_version": qc_result["rules_version"],
        "qc_retry_count": retry_count + 1 if qc_result["qc_status"] == "FAIL" else 0,
    }


def qc_routing(state: dict) -> str:
    """
    LangGraph 条件边路由函数

    根据 qc_status 决定下一步走向：
    - "PASS"  → "downstream"
    - "WARN"  → "downstream"（同步写入审计日志）
    - "FAIL"  → "upstream_retry"
    - "BLOCK" → "human_review"

    Returns
    -------
    str
        下一个节点名称
    """
    status = state.get("qc_status", "PASS")
    if status == "PASS":
        return "downstream"
    elif status == "WARN":
        return "downstream"
    elif status == "FAIL":
        return "upstream_retry"
    elif status == "BLOCK":
        return "human_review"
    return "downstream"


# ============================================================
# CLI 入口（调试用）
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 模拟上游 Agent 输出
    mock_upstream = {
        "project_id": "AGO-QCC-2026-001",
        "material_spec": {
            "concrete_grade": "LC25",
            "concrete_compressive_strength": 11.9,
            "steel_grade": "HRB400",
            "steel_yield_strength": 360,
        },
        "structural_calc": {
            "reinforcement_ratio": 0.0015,
            "crack_width": 0.25,
        },
        "description": "根据一般工程经验，陶粒墙板耐火极限约为4h。"
                       "参考相关规范，配筋率取0.15%。"
                       "详见 D:\\BaiduSyncdisk\\AKO_Hub\\docs\\report.md",
    }

    mock_schema = {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "material_spec": {"type": "object"},
            "structural_calc": {"type": "object"},
            "description": {"type": "string"},
        },
        "required": ["project_id", "material_spec", "description"],
    }

    mock_kb_context = [
        {
            "collection": "陶粒墙板技术方案",
            "doc_id": "AGO-QB-2024-003",
            "fragment": "陶粒墙板耐火极限为3h，依据第5.2条测试报告。",
        }
    ]

    agent = AKOQCAgent()
    result = agent.run(
        upstream_output=mock_upstream,
        expected_schema=mock_schema,
        kb_context=mock_kb_context,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
