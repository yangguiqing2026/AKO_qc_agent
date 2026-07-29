"""
ako_qc_rules_engine.py
======================
AKO_qc_agent L4 业务逻辑规则引擎

设计原则：
- 确定性代码执行，不依赖 LLM 模糊推理
- 同一输入，输出恒定
- 规则变更不修改 Prompt
- 计算过程可审计、可回放
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# ============================================================
# 数据结构
# ============================================================

@dataclass
class RuleViolation:
    """单条规则违反记录"""
    rule_id: str
    rule_name: str
    severity: str          # ERROR / WARN
    target_field: str
    value: Any
    message: str


@dataclass
class L4Report:
    """L4 层检测报告"""
    status: str = "PASS"                       # PASS / FAIL
    violations: List[RuleViolation] = field(default_factory=list)
    rules_version: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "rules_version": self.rules_version,
            "violations": [asdict(v) for v in self.violations],
        }


# ============================================================
# 规则引擎核心
# ============================================================

class AKOQCRulesEngine:
    """
    L4 业务逻辑规则引擎

    从 ako_qc_rules collection 加载 YAML 规则集，
    对上游 Agent 输出执行确定性数值校验。
    """

    def __init__(self, rules_dir: Optional[str] = None):
        if rules_dir is None:
            rules_dir = os.path.join(os.path.dirname(__file__), "ako_qc_rules")
        self.rules_dir = Path(rules_dir)
        self._rulesets: Dict[str, dict] = {}
        self._version_info: dict = {}
        self._material_registry: dict = {}
        self._load_version()

    # ---- 加载 ----

    def _load_version(self) -> None:
        """加载 version.json"""
        version_path = self.rules_dir / "version.json"
        if version_path.exists():
            with open(version_path, "r", encoding="utf-8") as f:
                self._version_info = json.load(f)

    def load_rules(self, ruleset_name: str, version: Optional[str] = None) -> dict:
        """
        从 collection 加载指定规则集

        Parameters
        ----------
        ruleset_name : str
            规则集名称，如 "L4_struct", "L4_material", "L4_logic"
        version : str, optional
            指定版本号（预留，当前加载最新文件）

        Returns
        -------
        dict
            解析后的规则集内容
        """
        if ruleset_name in self._rulesets:
            return self._rulesets[ruleset_name]

        # 从 version.json 获取文件名映射
        rulesets_map = self._version_info.get("rulesets", {})
        filename = rulesets_map.get(ruleset_name)
        if filename is None:
            raise FileNotFoundError(f"规则集 '{ruleset_name}' 未在 version.json 中注册")

        filepath = self.rules_dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"规则集文件不存在: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self._rulesets[ruleset_name] = data

        # 提取材料注册表（如果存在）
        if "material_registry" in data:
            self._material_registry.update(data["material_registry"])

        return data

    def load_all_rules(self) -> None:
        """加载所有已注册规则集"""
        for name in self._version_info.get("rulesets", {}):
            self.load_rules(name)

    @property
    def rules_version(self) -> str:
        return self._version_info.get("version", "unknown")

    # ---- 校验入口 ----

    def validate_struct(self, data: dict) -> L4Report:
        """
        结构计算校验

        Parameters
        ----------
        data : dict
            上游 Agent 输出中提取的结构计算相关字段

        Returns
        -------
        L4Report
        """
        ruleset = self.load_rules("L4_struct")
        report = L4Report(rules_version=self.rules_version)
        self._evaluate_rules(ruleset["rules"], data, report)
        if any(v.severity == "ERROR" for v in report.violations):
            report.status = "FAIL"
        return report

    def validate_material(self, data: dict) -> L4Report:
        """
        材料参数校验

        Parameters
        ----------
        data : dict
            上游 Agent 输出中提取的材料相关字段

        Returns
        -------
        L4Report
        """
        ruleset = self.load_rules("L4_material")
        report = L4Report(rules_version=self.rules_version)
        self._evaluate_rules(ruleset["rules"], data, report)
        # 材料匹配校验
        self._check_material_match(data, report)
        if any(v.severity == "ERROR" for v in report.violations):
            report.status = "FAIL"
        return report

    def validate_logic(self, data: dict) -> L4Report:
        """
        逻辑一致性校验

        Parameters
        ----------
        data : dict
            上游 Agent 输出，需包含 text_content 字段

        Returns
        -------
        L4Report
        """
        ruleset = self.load_rules("L4_logic")
        report = L4Report(rules_version=self.rules_version)
        self._evaluate_rules(ruleset["rules"], data, report)
        if any(v.severity == "ERROR" for v in report.violations):
            report.status = "FAIL"
        return report

    def validate_all(self, data: dict) -> L4Report:
        """
        执行全部 L4 校验，合并报告
        """
        merged = L4Report(rules_version=self.rules_version)

        for validator in [self.validate_struct, self.validate_material, self.validate_logic]:
            try:
                sub_report = validator(data)
                merged.violations.extend(sub_report.violations)
            except FileNotFoundError:
                # 规则集缺失时记录 WARN 但不阻断
                merged.violations.append(RuleViolation(
                    rule_id="L4-SYS",
                    rule_name="规则集加载",
                    severity="WARN",
                    target_field="rules_engine",
                    value=None,
                    message=f"规则集加载失败，跳过部分校验",
                ))

        if any(v.severity == "ERROR" for v in merged.violations):
            merged.status = "FAIL"
        return merged

    # ---- 规则求值 ----

    def _evaluate_rules(self, rules: list, data: dict, report: L4Report) -> None:
        """遍历规则列表，逐条求值"""
        for rule in rules:
            operator = rule.get("condition", {}).get("operator")
            target = rule.get("target_field", "")
            value = self._resolve_field(data, target)
            severity = rule.get("severity", "WARN")
            rule_id = rule.get("rule_id", "UNKNOWN")
            rule_name = rule.get("name", "")

            violated = False

            if operator == "less_than":
                ref = rule["condition"].get("reference_value")
                if value is not None and value < ref:
                    violated = True

            elif operator == "greater_than":
                ref = rule["condition"].get("reference_value")
                if value is not None and value > ref:
                    violated = True

            elif operator == "range":
                min_val = rule["condition"].get("min")
                max_val = rule["condition"].get("max")
                if value is not None and (value < min_val or value > max_val):
                    violated = True

            elif operator == "contradiction_check":
                violated = self._check_contradiction(rule, data)

            elif operator == "unit_required":
                violated = self._check_units(rule, data)

            elif operator == "precision_check":
                violated = False  # 预留，P1 阶段完善

            elif operator == "material_match":
                continue  # 由 _check_material_match 统一处理

            elif operator == "cross_check":
                violated = self._cross_check_material(rule, data)

            if violated:
                msg = rule.get("error_msg", f"规则 {rule_id} 未通过")
                msg = msg.replace("{value}", str(value))
                report.violations.append(RuleViolation(
                    rule_id=rule_id,
                    rule_name=rule_name,
                    severity=severity,
                    target_field=target,
                    value=value,
                    message=msg,
                ))

    # ---- 辅助方法 ----

    @staticmethod
    def _resolve_field(data: dict, field_path: str) -> Any:
        """支持点号分隔的嵌套字段解析"""
        keys = field_path.split(".")
        current = data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        return current

    def _check_material_match(self, data: dict, report: L4Report) -> None:
        """检查材料等级与注册表参数是否匹配"""
        # 混凝土匹配
        concrete_grade = data.get("concrete_grade")
        if concrete_grade and concrete_grade in self._material_registry.get("concrete", {}):
            expected = self._material_registry["concrete"][concrete_grade]
            actual_fc = data.get("concrete_compressive_strength")
            if actual_fc is not None and abs(actual_fc - expected["fc"]) > 0.01:
                report.violations.append(RuleViolation(
                    rule_id="L4-101",
                    rule_name="混凝土强度等级-参数自洽",
                    severity="ERROR",
                    target_field="concrete_grade",
                    value={"grade": concrete_grade, "fc_actual": actual_fc, "fc_expected": expected["fc"]},
                    message=f"混凝土等级 {concrete_grade} 的 fc 应为 {expected['fc']} N/mm²，实际为 {actual_fc} N/mm²",
                ))

        # 钢筋匹配
        steel_grade = data.get("steel_grade")
        if steel_grade and steel_grade in self._material_registry.get("steel", {}):
            expected = self._material_registry["steel"][steel_grade]
            actual_fy = data.get("steel_yield_strength")
            if actual_fy is not None and abs(actual_fy - expected["fy"]) > 0.01:
                report.violations.append(RuleViolation(
                    rule_id="L4-102",
                    rule_name="钢筋牌号-参数自洽",
                    severity="ERROR",
                    target_field="steel_grade",
                    value={"grade": steel_grade, "fy_actual": actual_fy, "fy_expected": expected["fy"]},
                    message=f"钢筋牌号 {steel_grade} 的 fy 应为 {expected['fy']} N/mm²，实际为 {actual_fy} N/mm²",
                ))

    @staticmethod
    def _check_contradiction(rule: dict, data: dict) -> bool:
        """检测文本中的逻辑矛盾"""
        text = data.get("text_content", "")
        if not text:
            return False

        pairs = rule.get("condition", {}).get("contradiction_pairs", [])
        for pair in pairs:
            has_positive = any(kw in text for kw in pair.get("keywords_positive", []))
            has_negative = any(kw in text for kw in pair.get("keywords_negative", []))
            if has_positive and has_negative:
                return True
        return False

    @staticmethod
    def _check_units(rule: dict, data: dict) -> bool:
        """检测数值是否缺少单位（仅检查 text_content 字段）"""
        text = data.get("text_content", "")
        if not text:
            return False

        required_units = rule.get("condition", {}).get("required_units", [])
        # 查找所有数字，检查后面是否紧跟单位
        for match in re.finditer(r"\d+\.?\d*", text):
            pos = match.end()
            following = text[pos:pos + 10].strip()
            has_unit = any(following.startswith(u) for u in required_units)
            # 跳过百分比、编号等非物理量数字
            if not has_unit:
                # 检查是否是编号类数字（如 AGO-QCC-2026-001 中的数字）
                before = text[max(0, match.start() - 5):match.start()]
                if re.search(r"[-/]$", before):
                    continue
                return True
        return False

    @staticmethod
    def _cross_check_material(rule: dict, data: dict) -> bool:
        """交叉检查材料等级与参数值"""
        pairs = rule.get("condition", {}).get("pairs", [])
        for grade_field, value_field in pairs:
            grade = data.get(grade_field)
            value = data.get(value_field)
            if grade and value and not isinstance(value, (int, float)):
                return True
        return False

    # ---- 报告导出 ----

    def export_report(self, report: L4Report) -> dict:
        """
        导出 L4 专项报告（JSON 格式）

        Returns
        -------
        dict
            结构化 L4 报告
        """
        return report.to_dict()


# ============================================================
# CLI 入口（调试用）
# ============================================================

if __name__ == "__main__":
    engine = AKOQCRulesEngine()
    engine.load_all_rules()

    # 测试用例
    test_data = {
        "reinforcement_ratio": 0.0015,        # 低于 0.002 → ERROR
        "concrete_compressive_strength": 11.9,
        "concrete_grade": "LC25",
        "steel_grade": "HRB400",
        "steel_yield_strength": 360,
        "crack_width": 0.25,
        "text_content": "不考虑地震作用，结构按非抗震设计。抗震构造措施按三级执行。",
    }

    report = engine.validate_all(test_data)
    print(json.dumps(engine.export_report(report), ensure_ascii=False, indent=2))
