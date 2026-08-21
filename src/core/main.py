# ============================================
# Author: AKO_studio
# Agent: AKO_qc_agent
# Entry Point
# ============================================

import argparse
import json
import logging
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from ako_qc_agent import AKOQCAgent  # noqa: E402


class HealthHandler(BaseHTTPRequestHandler):
    """最小健康检查端点，响应 /health。"""

    def do_GET(self):
        if self.path == "/health":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def setup_logging(level="INFO"):
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(str(log_dir / "AKO_qc_agent.log"), encoding="utf-8"),
        ],
    )


def main():
    parser = argparse.ArgumentParser(description="AKO_qc_agent 质量门入口")
    parser.add_argument(
        "--config",
        default="config/AKO_qc_agent_config.yaml",
        help="配置文件路径",
    )
    parser.add_argument(
        "--input",
        default=None,
        help="待检上游输出 JSON 文件路径（缺省时运行内置自检示例）",
    )
    parser.add_argument(
        "--output",
        default="qc_report.json",
        help="QC 报告输出路径",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="启动健康检查 HTTP 服务（/health）而非单次检测",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5001,
        help="健康检查服务端口（默认 5001）",
    )
    args = parser.parse_args()

    setup_logging(args.log_level)
    logger = logging.getLogger("AKO_qc_agent")
    logger.info("AKO_qc_agent 启动中...")
    logger.info("Config: %s", args.config)

    if args.serve:
        server = HTTPServer(("0.0.0.0", args.port), HealthHandler)
        logger.info("健康检查服务已启动: http://0.0.0.0:%s/health", args.port)
        server.serve_forever()
        return

    agent = AKOQCAgent()

    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            upstream = json.load(f)
        result = agent.run(upstream_output=upstream)
    else:
        logger.info("未提供 --input，运行内置自检示例...")
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
        }
        result = agent.run(upstream_output=mock_upstream)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info("QC 报告已写入: %s", args.output)
    logger.info("总体状态: %s (%s)", result["qc_status"], result["overall_risk_level"])


if __name__ == "__main__":
    main()