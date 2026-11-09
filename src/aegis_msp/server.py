"""
AegisMSP Multi-Tenant Command Center HTTP Server & CLI Runner.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from .strands_workflow import build_default_msp_fleet


def execute_fleet_simulation() -> Dict[str, Any]:
    workflow, events = build_default_msp_fleet()
    outcomes = [asdict(workflow.run_triage_workflow(ev)) for ev in events]
    quick_summary = workflow.answer_quick_nlq(
        "How much FinOps cost savings and MTTR improvement did AegisMSP deliver across tenants?"
    )
    return {
        "outcomes": outcomes,
        "metrics": quick_summary["metrics"],
        "quick_default": quick_summary,
        "agentcore_telemetry": workflow.orchestrator.export_telemetry_snapshot(),
        "_workflow": workflow,
        "_events": events,
    }


class AegisMSPRequestHandler(BaseHTTPRequestHandler):
    fleet_state: Dict[str, Any] = {}

    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            html_path = Path(__file__).parent / "dashboard.html"
            content = html_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if parsed.path == "/api/fleet-status":
            state = self.fleet_state
            self._send_json(
                {
                    "outcomes": state["outcomes"],
                    "metrics": state["metrics"],
                    "quick_default": state["quick_default"],
                    "agentcore_telemetry": state["agentcore_telemetry"],
                }
            )
            return

        if parsed.path == "/api/quick-nlq":
            qs = parse_qs(parsed.query)
            question = qs.get("q", ["Fleet summary"])[0]
            wf = self.fleet_state["_workflow"]
            self._send_json(wf.answer_quick_nlq(question))
            return

        self._send_json({"error": "Not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/run-triage":
            AegisMSPRequestHandler.fleet_state = execute_fleet_simulation()
            self._send_json({"status": "re-executed", "metrics": self.fleet_state["metrics"]})
            return
        self._send_json({"error": "Not found"}, status=404)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="AegisMSP Multi-Tenant Command Center")
    parser.add_argument("--port", type=int, default=8090, help="HTTP port for dashboard")
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Execute multi-tenant triage workflow once and print telemetry report",
    )
    args = parser.parse_args()

    state = execute_fleet_simulation()
    if args.run_once:
        report = {
            "metrics": state["metrics"],
            "quick_executive_insight": state["quick_default"]["answer"],
            "agentcore_telemetry": state["agentcore_telemetry"],
            "outcomes": [
                {
                    "tenant_id": o["tenant_id"],
                    "tenant_name": o["tenant_name"],
                    "service": o["incident_event"]["aws_service"],
                    "executed_runbook": o["executed_runbook"],
                    "remediation_status": o["remediation_status"],
                    "autonomous_mttr_seconds": o["autonomous_mttr_seconds"],
                    "estimated_monthly_savings_usd": o["estimated_monthly_savings_usd"],
                }
                for o in state["outcomes"]
            ],
        }
        print(json.dumps(report, indent=2))
        return

    AegisMSPRequestHandler.fleet_state = state
    server = HTTPServer(("127.0.0.1", args.port), AegisMSPRequestHandler)
    print(f"AegisMSP Command Center listening on http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
