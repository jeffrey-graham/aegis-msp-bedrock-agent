"""
Unit & Integration Test Suite for AegisMSP (AWS MSP AI Hackathon).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aegis_msp.bedrock_agentcore import (  # noqa: E402
    MSPPolicyEnforcer,
    TenantContext,
    TenantSessionGuard,
)
from aegis_msp.server import execute_fleet_simulation  # noqa: E402
from aegis_msp.strands_workflow import build_default_msp_fleet  # noqa: E402


class TestAegisMSP(unittest.TestCase):
    def setUp(self) -> None:
        self.tenant_a = TenantContext(
            tenant_id="tenant-alpha",
            tenant_name="Alpha Bank",
            aws_account_id="111122223333",
            region="us-east-1",
            sla_tier="PLATINUM_99_99",
            monthly_aws_spend_usd=50000.0,
            auto_remediate_allowed=True,
            max_autonomous_cost_impact_usd=500.0,
        )
        self.tenant_b = TenantContext(
            tenant_id="tenant-beta",
            tenant_name="Beta Health",
            aws_account_id="999988887777",
            region="us-west-2",
            sla_tier="GOLD_99_95",
            monthly_aws_spend_usd=25000.0,
            auto_remediate_allowed=False,
            max_autonomous_cost_impact_usd=200.0,
        )

    def test_tenant_session_isolation_and_hmac_verification(self) -> None:
        guard = TenantSessionGuard(secret_key="unit-test-secret-key")
        sess_a = guard.create_isolated_session(self.tenant_a)

        verified = guard.verify_session_access(sess_a, "111122223333")
        self.assertEqual(verified.tenant_id, "tenant-alpha")

        # Cross-tenant account access attempt must raise PermissionError
        with self.assertRaises(PermissionError):
            guard.verify_session_access(sess_a, "999988887777")

        # Tampered signature must raise PermissionError
        tampered = sess_a[:-4] + "ffff"
        guard._active_sessions[tampered] = self.tenant_a
        with self.assertRaises(PermissionError):
            guard.verify_session_access(tampered, "111122223333")

    def test_msp_policy_enforcer_cedar_guardrails(self) -> None:
        enforcer = MSPPolicyEnforcer()

        # 1. Valid allowlisted SSM runbook within cost cap
        ok_decision = enforcer.evaluate_action(
            self.tenant_a,
            action_name="ssm:Aegis-RecycleECSServiceTasks",
            estimated_cost_delta_usd=0.0,
            target_account_id="111122223333",
        )
        self.assertTrue(ok_decision.allowed)
        self.assertEqual(ok_decision.policy_rule_id, "AEGIS-CEDAR-000-ALLOW")

        # 2. Destructive mutation blocked
        destruct_decision = enforcer.evaluate_action(
            self.tenant_a,
            action_name="rds:DeleteDBCluster",
            estimated_cost_delta_usd=0.0,
        )
        self.assertFalse(destruct_decision.allowed)
        self.assertTrue(destruct_decision.requires_human_approval)
        self.assertEqual(destruct_decision.policy_rule_id, "AEGIS-CEDAR-002-NO-DESTRUCTIVE-MUTATION")

        # 3. Cost cap exceeded blocked
        cost_decision = enforcer.evaluate_action(
            self.tenant_a,
            action_name="ssm:Aegis-ScaleRDSReadReplica",
            estimated_cost_delta_usd=1200.0,
        )
        self.assertFalse(cost_decision.allowed)
        self.assertEqual(cost_decision.policy_rule_id, "AEGIS-CEDAR-004-FINOPS-CAP-EXCEEDED")

        # 4. Advisory-only tenant gated for CAB approval
        advisory_decision = enforcer.evaluate_action(
            self.tenant_b,
            action_name="ssm:Aegis-RecycleECSServiceTasks",
            estimated_cost_delta_usd=0.0,
        )
        self.assertFalse(advisory_decision.allowed)
        self.assertTrue(advisory_decision.requires_human_approval)
        self.assertEqual(advisory_decision.policy_rule_id, "AEGIS-CEDAR-003-ADVISORY-ONLY-TENANT")

    def test_strands_5_agent_workflow_and_quick_nlq(self) -> None:
        workflow, events = build_default_msp_fleet()
        outcomes = [workflow.run_triage_workflow(ev) for ev in events]

        self.assertEqual(len(outcomes), 4)
        # First 3 tenants have autonomous remediation enabled; 4th is advisory-only
        self.assertEqual(outcomes[0].remediation_status, "AUTONOMOUSLY_RESOLVED")
        self.assertEqual(outcomes[1].remediation_status, "AUTONOMOUSLY_RESOLVED")
        self.assertEqual(outcomes[2].remediation_status, "AUTONOMOUSLY_RESOLVED")
        self.assertEqual(outcomes[3].remediation_status, "ESCALATED_FOR_APPROVAL")

        # Verify all 5 Strands agent traces ran for each incident
        for o in outcomes:
            self.assertEqual(len(o.agent_traces), 5)
            self.assertGreater(o.estimated_monthly_savings_usd, 1000.0)
            self.assertGreater(o.mttr_reduction_pct, 80.0)

        # Verify AgentCore cross-tenant anonymized memory lookup works
        matches = workflow.orchestrator.query_similar_incidents("AWS/ECS:MemoryUtilization:CRITICAL")
        self.assertGreaterEqual(len(matches), 1)

        # Verify Amazon Quick NLQ responder
        finops_nlq = workflow.answer_quick_nlq("How much FinOps cost savings did we unlock?")
        self.assertIn("FinOps optimizations", finops_nlq["answer"])
        self.assertGreater(finops_nlq["metrics"]["total_annual_savings_usd"], 150000.0)

    def test_server_fleet_simulation_export(self) -> None:
        state = execute_fleet_simulation()
        self.assertEqual(state["metrics"]["managed_tenants"], 4)
        self.assertEqual(state["metrics"]["autonomously_resolved"], 3)
        self.assertEqual(state["agentcore_telemetry"]["memory_entries_count"], 4)

    def test_static_github_pages_fallback_snapshot_present(self) -> None:
        root_html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        dash_html = (Path(__file__).resolve().parents[1] / "src/aegis_msp/dashboard.html").read_text(encoding="utf-8")
        self.assertEqual(root_html, dash_html)
        self.assertIn("STATIC_FLEET_SNAPSHOT", root_html)
        self.assertIn("IS_LOCAL_PYTHON_SERVER", root_html)
        self.assertIn("Apex Clearing FinServ", root_html)


if __name__ == "__main__":
    unittest.main()
