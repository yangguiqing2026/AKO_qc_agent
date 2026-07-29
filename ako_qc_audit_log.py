"""
ako_qc_audit_log.py
====================
AKO_qc_agent 审计日志持久化模块

使用 SQLite 存储 qc_audit_log，支持：
- 写入检测报告
- 按时间/状态/层级查询
- 导出统计摘要
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional


_DEFAULT_DB_PATH = "qc_audit_log.db"


class QCAuditLog:
    """
    QC 审计日志持久化

    将每次 QC 检测报告写入 SQLite，支持查询与统计。
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(Path(__file__).parent / _DEFAULT_DB_PATH)
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库表"""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS qc_audit_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT    NOT NULL,
                    source      TEXT,
                    qc_status   TEXT    NOT NULL,
                    risk_level  TEXT    NOT NULL,
                    rules_ver   TEXT,
                    layer_l1    TEXT,
                    layer_l2    TEXT,
                    layer_l3    TEXT,
                    layer_l4    TEXT,
                    layer_l5    TEXT,
                    report_json TEXT    NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp ON qc_audit_log(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON qc_audit_log(qc_status)
            """)

    @contextmanager
    def _connect(self):
        """数据库连接上下文管理器"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def write(self, report: dict, source: str = "") -> int:
        """
        写入一条审计日志

        Parameters
        ----------
        report : dict
            完整的 QC 报告（符合 QC_REPORT_SCHEMA）
        source : str
            来源标识（如 Agent 名称）

        Returns
        -------
        int
            插入记录的 ID
        """
        layers = {}
        for item in report.get("report", []):
            layers[item["layer"]] = item["status"]

        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO qc_audit_log
                   (timestamp, source, qc_status, risk_level, rules_ver,
                    layer_l1, layer_l2, layer_l3, layer_l4, layer_l5, report_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    time.strftime("%Y-%m-%dT%H:%M:%S"),
                    source,
                    report.get("qc_status", "UNKNOWN"),
                    report.get("overall_risk_level", "UNKNOWN"),
                    report.get("rules_version", ""),
                    layers.get("L1", ""),
                    layers.get("L2", ""),
                    layers.get("L3", ""),
                    layers.get("L4", ""),
                    layers.get("L5", ""),
                    json.dumps(report, ensure_ascii=False),
                ),
            )
            return cursor.lastrowid

    def query(
        self,
        qc_status: Optional[str] = None,
        source: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        """
        查询审计日志

        Parameters
        ----------
        qc_status : str, optional
            按状态过滤：PASS / FAIL / BLOCK
        source : str, optional
            按来源过滤
        since : str, optional
            起始时间（ISO 格式）
        limit : int
            返回条数上限

        Returns
        -------
        list[dict]
        """
        conditions = []
        params: list = []

        if qc_status:
            conditions.append("qc_status = ?")
            params.append(qc_status)
        if source:
            conditions.append("source = ?")
            params.append(source)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM qc_audit_log WHERE {where} ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def summary(self) -> dict:
        """
        统计摘要

        Returns
        -------
        dict
            包含总数、各状态计数、各层通过率
        """
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM qc_audit_log").fetchone()[0]

            status_counts = {}
            for row in conn.execute(
                "SELECT qc_status, COUNT(*) as cnt FROM qc_audit_log GROUP BY qc_status"
            ):
                status_counts[row[0]] = row[1]

            layer_stats = {}
            for layer in ["L1", "L2", "L3", "L4", "L5"]:
                col = f"layer_{layer.lower()}"
                row = conn.execute(
                    f"SELECT COUNT(*) FROM qc_audit_log WHERE {col} = 'PASS'"
                ).fetchone()
                pass_count = row[0] if row else 0
                layer_stats[layer] = {
                    "pass": pass_count,
                    "fail": total - pass_count if total > 0 else 0,
                    "pass_rate": round(pass_count / total * 100, 1) if total > 0 else 0,
                }

            return {
                "total": total,
                "status_counts": status_counts,
                "layer_stats": layer_stats,
            }

    def clear(self) -> None:
        """清空审计日志（调试用）"""
        with self._connect() as conn:
            conn.execute("DELETE FROM qc_audit_log")


# ============================================================
# CLI 入口（调试用）
# ============================================================

if __name__ == "__main__":
    log = QCAuditLog()

    # 写入测试
    mock_report = {
        "qc_status": "FAIL",
        "overall_risk_level": "ERROR",
        "rules_version": "1.1.0",
        "report": [
            {"layer": "L1", "item": "契约合规", "status": "PASS", "detail": "", "suggestion": ""},
            {"layer": "L2", "item": "知识库一致性", "status": "FAIL", "detail": "模糊归因", "suggestion": "修正"},
            {"layer": "L3", "item": "品牌格式", "status": "PASS", "detail": "", "suggestion": ""},
            {"layer": "L4", "item": "业务逻辑", "status": "PASS", "detail": "", "suggestion": ""},
            {"layer": "L5", "item": "安全信息", "status": "PASS", "detail": "", "suggestion": ""},
        ],
    }
    row_id = log.write(mock_report, source="test_agent")
    print(f"写入成功，ID: {row_id}")

    # 查询测试
    results = log.query(limit=5)
    print(f"查询结果: {len(results)} 条")

    # 统计测试
    stats = log.summary()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
