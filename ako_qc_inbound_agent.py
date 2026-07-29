"""
ako_qc_inbound_agent.py
========================
AKO_qc_inbound_agent — 外部接口回传数据反向检测节点

P2 阶段交付物。当外部系统向 AKO_Hub 回传数据时，
该节点作为入口侧质量门，防止外部污染数据进入系统。

检测维度：
  1. 契约合规 — 回传数据是否符合预定义 Schema
  2. 数据完整性 — 必填字段是否存在、类型是否正确
  3. 数值合理性 — 关键数值是否在合理区间
  4. 安全扫描 — 是否携带恶意内容、注入攻击
  5. 来源可信度 — 回传来源是否在白名单内
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set

from ako_qc_rules_engine import AKOQCRulesEngine
from ako_qc_audit_log import QCAuditLog

logger = logging.getLogger("ako_qc_inbound")


# ============================================================
# 数据结构
# ============================================================

@dataclass
class InboundReportItem:
    """单条检测项"""
    layer: str          # IB-1 ~ IB-5
    item: str
    status: str         # PASS / FAIL
    detail: str
    suggestion: str


@dataclass
class InboundQCReport:
    """ inbound QC 报告 """
    qc_status: str = "PASS"             # PASS / FAIL / BLOCK
    overall_risk_level: str = "INFO"    # INFO / WARN / ERROR / BLOCK
    source: str = ""
    report: List[InboundReportItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "qc_status": self.qc_status,
            "overall_risk_level": self.overall_risk_level,
            "source": self.source,
            "report": [asdict(item) for item in self.report],
        }


# ============================================================
# 来源白名单
# ============================================================

_DEFAULT_TRUSTED_SOURCES: Set[str] = {
    "ako_hub_internal",
    "partner_api_v1",
    "partner_api_v2",
    "gov_portal",
    "certified_lab",
}


# ============================================================
# IB-1：契约合规检测
# ============================================================

def _check_ib1_contract(inbound_data: Any, expected_schema: Optional[dict]) -> InboundReportItem:
    """检测回传数据是否符合预定义 Schema"""
    issues: List[str] = []

    if isinstance(inbound_data, str):
        try:
            data = json.loads(inbound_data)
        except json.JSONDecodeError as e:
            return InboundReportItem(
                layer="IB-1", item="JSON 合法性", status="FAIL",
                detail=f"回传数据不是合法 JSON：{e}",
                suggestion="要求外部接口返回合法 JSON 格式数据。",
            )
    elif isinstance(inbound_data, dict):
        data = inbound_data
    else:
        return InboundReportItem(
            layer="IB-1", item="数据类型", status="FAIL",
            detail=f"回传数据类型为 {type(inbound_data).__name__}，预期 dict 或 JSON 字符串。",
            suggestion="要求外部接口返回 JSON 对象。",
        )

    if expected_schema:
        properties = expected_schema.get("properties", {})
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
                    issues.append(f"字段 '{field_name}' 类型应为 {expected_type}，实际为 {type(actual).__name__}。")

        required = expected_schema.get("required", [])
        for f in required:
            val = data.get(f)
            if val is None or (isinstance(val, str) and val.strip() == ""):
                issues.append(f"必填字段 '{f}' 为空。")

    if issues:
        return InboundReportItem(
            layer="IB-1", item="契约合规", status="FAIL",
            detail="；".join(issues),
            suggestion="要求外部接口按预定义 Schema 补全字段、修正类型。",
        )

    return InboundReportItem(
        layer="IB-1", item="契约合规", status="PASS",
        detail="回传数据结构符合预期 Schema。",
        suggestion="",
    )


# ============================================================
# IB-2：数据完整性检测
# ============================================================

def _check_ib2_integrity(inbound_data: dict) -> InboundReportItem:
    """检测关键字段是否缺失或异常"""
    issues: List[str] = []

    # 检查是否有空值集中出现（可能表示数据未填充）
    if isinstance(inbound_data, dict):
        null_count = 0
        total_count = 0
        for key, val in inbound_data.items():
            total_count += 1
            if val is None or (isinstance(val, str) and val.strip() == ""):
                null_count += 1

        if total_count > 0 and null_count / total_count > 0.5:
            issues.append(f"空值比例过高：{null_count}/{total_count}（{null_count*100//total_count}%）。")

    if issues:
        return InboundReportItem(
            layer="IB-2", item="数据完整性", status="FAIL",
            detail="；".join(issues),
            suggestion="外部接口可能未正确填充数据，要求补全。",
        )

    return InboundReportItem(
        layer="IB-2", item="数据完整性", status="PASS",
        detail="数据完整性检查通过，空值比例正常。",
        suggestion="",
    )


# ============================================================
# IB-3：数值合理性检测
# ============================================================

def _check_ib3_numerical(inbound_data: dict, rules_engine: AKOQCRulesEngine) -> InboundReportItem:
    """对回传数据中的数值执行 L4 规则引擎校验"""
    issues: List[str] = []

    # 复用 L4 规则引擎进行数值校验
    try:
        l4_report = rules_engine.validate_all(inbound_data)
        for v in l4_report.violations:
            if v.severity == "ERROR":
                issues.append(f"[{v.rule_id}] {v.message}")
    except Exception as e:
        logger.warning("IB-3 规则引擎校验异常: %s", e)

    if issues:
        return InboundReportItem(
            layer="IB-3", item="数值合理性", status="FAIL",
            detail="；".join(issues),
            suggestion="回传数据中存在超出合理区间的数值，要求外部接口核实。",
        )

    return InboundReportItem(
        layer="IB-3", item="数值合理性", status="PASS",
        detail="数值合理性校验通过。",
        suggestion="",
    )


# ============================================================
# IB-4：安全扫描
# ============================================================

# 注入攻击模式
_INJECTION_PATTERNS = [
    re.compile(r"<script[^>]*>", re.IGNORECASE),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"on\w+\s*=", re.IGNORECASE),
    re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE),
    re.compile(r"\bUNION\s+SELECT\b", re.IGNORECASE),
    re.compile(r";\s*--"),
]


def _check_ib4_security(inbound_data: Any) -> InboundReportItem:
    """安全扫描：检测注入攻击和恶意内容"""
    issues: List[str] = []

    text = json.dumps(inbound_data, ensure_ascii=False) if not isinstance(inbound_data, str) else inbound_data

    # 注入攻击检测
    for pattern in _INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            issues.append(f"发现疑似注入攻击：「{match.group()[:30]}...」。")

    # 异常大体积检测（防止 DoS）
    if len(text) > 10_000_000:  # 10MB
        issues.append(f"回传数据体积异常：{len(text) / 1024 / 1024:.1f} MB。")

    if issues:
        return InboundReportItem(
            layer="IB-4", item="安全扫描", status="FAIL",
            detail="；".join(issues),
            suggestion="拦截该回传数据，排查外部接口安全性。",
        )

    return InboundReportItem(
        layer="IB-4", item="安全扫描", status="PASS",
        detail="安全扫描通过，未发现注入攻击或恶意内容。",
        suggestion="",
    )


# ============================================================
# IB-5：来源可信度检测
# ============================================================

def _check_ib5_source(source: str, trusted_sources: Set[str]) -> InboundReportItem:
    """检测回传来源是否在白名单内"""
    if source not in trusted_sources:
        return InboundReportItem(
            layer="IB-5", item="来源可信度", status="FAIL",
            detail=f"回传来源 '{source}' 不在可信来源白名单内。",
            suggestion=f"将 '{source}' 加入白名单，或拒绝该回传数据。",
        )

    return InboundReportItem(
        layer="IB-5", item="来源可信度", status="PASS",
        detail=f"来源 '{source}' 在可信白名单内。",
        suggestion="",
    )


# ============================================================
# AKO_qc_inbound_agent 主节点
# ============================================================

class AKOQCInboundAgent:
    """
    AKO_qc_inbound_agent — 外部数据反向检测节点

    在外部接口回传数据进入 AKO_Hub 时执行质量门检测，
    防止外部污染数据进入系统。
    """

    def __init__(
        self,
        rules_dir: Optional[str] = None,
        audit_log_db: Optional[str] = None,
        trusted_sources: Optional[Set[str]] = None,
    ):
        self.rules_engine = AKOQCRulesEngine(rules_dir=rules_dir)
        self._audit_db = QCAuditLog(db_path=audit_log_db)
        self.trusted_sources = trusted_sources or _DEFAULT_TRUSTED_SOURCES
        self._audit_log: List[dict] = []

    def run(
        self,
        inbound_data: Any,
        source: str = "",
        expected_schema: Optional[dict] = None,
    ) -> dict:
        """
        执行 inbound 五维检测

        Parameters
        ----------
        inbound_data : Any
            外部接口回传的原始数据
        source : str
            回传来源标识
        expected_schema : dict, optional
            预期 JSON Schema

        Returns
        -------
        dict
            inbound QC 报告
        """
        report = InboundQCReport(source=source)

        # IB-1 契约合规
        report.report.append(_check_ib1_contract(inbound_data, expected_schema))

        # IB-2 数据完整性
        data = inbound_data if isinstance(inbound_data, dict) else {}
        report.report.append(_check_ib2_integrity(data))

        # IB-3 数值合理性
        report.report.append(_check_ib3_numerical(data, self.rules_engine))

        # IB-4 安全扫描
        report.report.append(_check_ib4_security(inbound_data))

        # IB-5 来源可信度
        report.report.append(_check_ib5_source(source, self.trusted_sources))

        # 汇总判定
        self._determine_status(report)

        # 写入审计日志
        self._write_audit_log(report)

        return report.to_dict()

    @staticmethod
    def _determine_status(report: InboundQCReport) -> None:
        """汇总判定"""
        has_fail = False
        has_security = False
        has_untrusted = False

        for item in report.report:
            if item.status == "FAIL":
                has_fail = True
                if item.layer == "IB-4":
                    has_security = True
                if item.layer == "IB-5":
                    has_untrusted = True

        if has_security or has_untrusted:
            report.qc_status = "BLOCK"
            report.overall_risk_level = "BLOCK"
        elif has_fail:
            report.qc_status = "FAIL"
            report.overall_risk_level = "ERROR"
        else:
            report.qc_status = "PASS"
            report.overall_risk_level = "INFO"

    def _write_audit_log(self, report: InboundQCReport) -> None:
        """写入审计日志"""
        report_dict = report.to_dict()
        log_entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "type": "inbound",
            "source": report.source,
            "qc_status": report.qc_status,
            "overall_risk_level": report.overall_risk_level,
            "layers": {item.layer: item.status for item in report.report},
        }
        self._audit_log.append(log_entry)
        try:
            self._audit_db.write(report_dict, source=f"inbound:{report.source}")
        except Exception as e:
            logger.warning("Inbound 审计日志写入失败: %s", e)
        logger.info("Inbound QC 审计日志: %s", json.dumps(log_entry, ensure_ascii=False))

    def add_trusted_source(self, source: str) -> None:
        """动态添加可信来源"""
        self.trusted_sources.add(source)

    def get_audit_log(self) -> List[dict]:
        """获取审计日志"""
        return list(self._audit_log)


# ============================================================
# LangGraph 节点函数
# ============================================================

def ako_qc_inbound_node(state: dict) -> dict:
    """
    LangGraph 节点函数（inbound 侧）

    从 state 中读取外部回传数据，执行反向检测，
    将 qc_status / qc_report 写回 state。
    """
    inbound_data = state.get("inbound_data")
    source = state.get("inbound_source", "")
    expected_schema = state.get("inbound_expected_schema")

    agent = AKOQCInboundAgent()
    result = agent.run(
        inbound_data=inbound_data,
        source=source,
        expected_schema=expected_schema,
    )

    return {
        "qc_status": result["qc_status"],
        "qc_report": result,
    }


def inbound_routing(state: dict) -> str:
    """
    Inbound 侧路由函数

    - PASS → 进入 AKO_Hub 内部处理
    - FAIL → 拒绝并记录
    - BLOCK → 强制拦截，告警
    """
    status = state.get("qc_status", "PASS")
    if status == "PASS":
        return "process_inbound"
    elif status == "FAIL":
        return "reject_inbound"
    elif status == "BLOCK":
        return "alert_inbound"
    return "process_inbound"


# ============================================================
# CLI 入口（调试用）
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 模拟正常回传数据
    normal_data = {
        "project_id": "AGO-QCC-2026-001",
        "material_spec": {
            "concrete_grade": "LC25",
            "concrete_compressive_strength": 11.9,
        },
        "test_results": {
            "fire_resistance": 3.5,
            "load_capacity": 150.0,
        },
    }

    # 模拟恶意回传数据
    malicious_data = {
        "project_id": "AGO-QCC-2026-001",
        "description": "<script>alert('xss')</script>; DROP TABLE users; --",
        "data": None,
    }

    agent = AKOQCInboundAgent()

    print("=== 正常数据检测 ===")
    result1 = agent.run(normal_data, source="partner_api_v1")
    print(json.dumps(result1, ensure_ascii=False, indent=2))

    print("\n=== 恶意数据检测 ===")
    result2 = agent.run(malicious_data, source="unknown_source")
    print(json.dumps(result2, ensure_ascii=False, indent=2))
