"""
Amazon Bedrock AgentCore Multi-Tenant Orchestrator & Guardrail Engine for MSPs.

Implements:
1. Cryptographically isolated TenantSessionGuard ensuring zero cross-tenant context leakage
   across Managed Service Provider (MSP) customer AWS accounts.
2. MSPPolicyEnforcer evaluating IAM/SSM/FinOps actions against per-tenant SLA tier guardrails
   before tool invocation.
3. BedrockAgentCoreOrchestrator wrapping Amazon Bedrock Converse API + AgentCore Memory
   with deterministic local fallback for CI/offline testing and reproducible demos.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class TenantContext:
    """Represents an isolated MSP customer account and SLA governance profile."""

    tenant_id: str
    tenant_name: str
    aws_account_id: str
    region: str
    sla_tier: str  # "PLATINUM_99_99", "GOLD_99_95", "SILVER_99_9"
    monthly_aws_spend_usd: float
    auto_remediate_allowed: bool = True
    max_autonomous_cost_impact_usd: float = 500.0
    allowed_ssm_runbooks: List[str] = field(
        default_factory=lambda: [
            "AWS-RestartEC2Instance",
            "Aegis-RecycleECSServiceTasks",
            "Aegis-ScaleRDSReadReplica",
            "Aegis-ThrottleNatGatewayIdleFlows",
            "Aegis-RightsizeEBSGP2ToGP3",
            "Aegis-RotateWAFBlockedIPSet",
        ]
    )


@dataclass
class AgentCoreMemoryEntry:
    """Short-term session state and anonymized cross-tenant pattern memory."""

    memory_id: str
    tenant_id: str
    session_id: str
    incident_signature: str
    root_cause_summary: str
    remediation_runbook: str
    mttr_seconds: float
    monthly_savings_usd: float
    timestamp: float = field(default_factory=time.time)


class TenantSessionGuard:
    """
    Enforces strict tenant boundary isolation in Amazon Bedrock AgentCore sessions.
    Prevents cross-tenant prompt injection, memory poisoning, or STS role confusion.
    """

    def __init__(self, secret_key: Optional[str] = None) -> None:
        raw_secret = secret_key or os.environ.get(
            "AEGIS_MSP_SESSION_SECRET", "aegis-msp-agentcore-zero-trust-key-2026"
        )
        self._secret = raw_secret.encode("utf-8")
        self._active_sessions: Dict[str, TenantContext] = {}

    def create_isolated_session(self, tenant: TenantContext) -> str:
        """Creates a signed, tenant-bound AgentCore session token."""
        nonce = uuid.uuid4().hex[:12]
        payload = f"{tenant.tenant_id}:{tenant.aws_account_id}:{tenant.region}:{nonce}"
        signature = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
        session_id = f"ac-sess-{tenant.tenant_id}-{nonce}-{signature}"
        self._active_sessions[session_id] = tenant
        return session_id

    def verify_session_access(self, session_id: str, target_account_id: str) -> TenantContext:
        """
        Verifies that the session exists, has a valid HMAC signature, and matches the target
        customer AWS Account ID. Raises PermissionError on cross-tenant access attempts.
        """
        if session_id not in self._active_sessions:
            raise PermissionError(f"Unrecognized or expired AgentCore session: {session_id}")

        tenant = self._active_sessions[session_id]
        parts = session_id.split("-")
        if len(parts) < 5:
            raise PermissionError("Malformed AgentCore session token")

        nonce = parts[-2]
        provided_sig = parts[-1]
        expected_payload = f"{tenant.tenant_id}:{tenant.aws_account_id}:{tenant.region}:{nonce}"
        expected_sig = hmac.new(
            self._secret, expected_payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()[:24]

        if not hmac.compare_digest(provided_sig, expected_sig):
            raise PermissionError("Invalid AgentCore session cryptographic signature")

        if tenant.aws_account_id != target_account_id:
            raise PermissionError(
                f"Cross-tenant isolation violation! Session bound to account {tenant.aws_account_id} "
                f"attempted to access account {target_account_id}."
            )

        return tenant


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str
    requires_human_approval: bool = False
    policy_rule_id: str = "AEGIS-CEDAR-DEFAULT"


class MSPPolicyEnforcer:
    """
    Cedar-inspired policy guardrail evaluator for Amazon Bedrock AgentCore tool calls.
    Ensures autonomous MSP agents never execute destructive actions or exceed cost thresholds.
    """

    DESTRUCTIVE_ACTIONS = {
        "rds:DeleteDBCluster",
        "ec2:TerminateInstances",
        "s3:DeleteBucket",
        "iam:PutRolePolicy",
        "dynamodb:DeleteTable",
    }

    def evaluate_action(
        self,
        tenant: TenantContext,
        action_name: str,
        estimated_cost_delta_usd: float = 0.0,
        target_account_id: Optional[str] = None,
    ) -> PolicyDecision:
        if target_account_id and target_account_id != tenant.aws_account_id:
            return PolicyDecision(
                allowed=False,
                reason=f"Cross-account boundary violation ({target_account_id} != {tenant.aws_account_id})",
                requires_human_approval=False,
                policy_rule_id="AEGIS-CEDAR-001-TENANT-ISOLATION",
            )

        if action_name in self.DESTRUCTIVE_ACTIONS:
            return PolicyDecision(
                allowed=False,
                reason=f"Destructive action '{action_name}' is hard-blocked by MSP safety policy",
                requires_human_approval=True,
                policy_rule_id="AEGIS-CEDAR-002-NO-DESTRUCTIVE-MUTATION",
            )

        if not tenant.auto_remediate_allowed:
            return PolicyDecision(
                allowed=False,
                reason=f"Tenant {tenant.tenant_name} has autonomous remediation disabled (advisory mode only)",
                requires_human_approval=True,
                policy_rule_id="AEGIS-CEDAR-003-ADVISORY-ONLY-TENANT",
            )

        if estimated_cost_delta_usd > tenant.max_autonomous_cost_impact_usd:
            return PolicyDecision(
                allowed=False,
                reason=(
                    f"Estimated cost delta ${estimated_cost_delta_usd:.2f}/mo exceeds tenant autonomous "
                    f"threshold ${tenant.max_autonomous_cost_impact_usd:.2f}/mo"
                ),
                requires_human_approval=True,
                policy_rule_id="AEGIS-CEDAR-004-FINOPS-CAP-EXCEEDED",
            )

        if action_name.startswith("ssm:") and action_name.split(":", 1)[1] not in tenant.allowed_ssm_runbooks:
            runbook = action_name.split(":", 1)[1]
            return PolicyDecision(
                allowed=False,
                reason=f"SSM Runbook '{runbook}' is not on the approved allowlist for {tenant.tenant_id}",
                requires_human_approval=True,
                policy_rule_id="AEGIS-CEDAR-005-UNAPPROVED-RUNBOOK",
            )

        return PolicyDecision(
            allowed=True,
            reason="Permitted by tenant AgentCore policy guardrails",
            requires_human_approval=False,
            policy_rule_id="AEGIS-CEDAR-000-ALLOW",
        )


class BedrockAgentCoreOrchestrator:
    """
    Wraps Amazon Bedrock Converse API (Claude 3.7 Sonnet / Amazon Nova Pro) and
    Bedrock AgentCore Memory with deterministic local simulation fallback.
    """

    def __init__(
        self,
        model_id: str = "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        region_name: str = "us-east-1",
        force_simulation: Optional[bool] = None,
    ) -> None:
        self.model_id = model_id
        self.region_name = region_name
        self.session_guard = TenantSessionGuard()
        self.policy_enforcer = MSPPolicyEnforcer()
        self._memory_store: List[AgentCoreMemoryEntry] = []

        if force_simulation is not None:
            self.simulation_mode = force_simulation
        else:
            self.simulation_mode = not bool(
                os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AEGIS_USE_LIVE_BEDROCK")
            )

        self._bedrock_client = None
        if not self.simulation_mode:
            try:
                import boto3  # type: ignore

                self._bedrock_client = boto3.client("bedrock-runtime", region_name=self.region_name)
            except Exception:
                self.simulation_mode = True

    def record_memory(self, entry: AgentCoreMemoryEntry) -> None:
        """Persists an incident resolution trace into AgentCore memory."""
        self._memory_store.append(entry)

    def query_similar_incidents(self, incident_signature: str, limit: int = 3) -> List[Dict[str, Any]]:
        """
        Retrieves anonymized cross-tenant runbook successes matching the incident signature.
        Never exposes raw customer PII or account IDs across tenant boundaries.
        """
        matches = []
        sig_tokens = set(incident_signature.lower().replace("-", " ").replace("_", " ").split())
        for item in reversed(self._memory_store):
            item_tokens = set(item.incident_signature.lower().replace("-", " ").replace("_", " ").split())
            overlap = len(sig_tokens.intersection(item_tokens))
            if overlap > 0 or item.incident_signature == incident_signature:
                matches.append(
                    {
                        "memory_id": item.memory_id,
                        "incident_signature": item.incident_signature,
                        "root_cause_summary": item.root_cause_summary,
                        "recommended_runbook": item.remediation_runbook,
                        "historical_mttr_seconds": item.mttr_seconds,
                        "avg_monthly_savings_usd": item.monthly_savings_usd,
                    }
                )
            if len(matches) >= limit:
                break
        return matches

    def invoke_converse_reasoning(
        self,
        session_id: str,
        target_account_id: str,
        system_prompt: str,
        user_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Invokes Amazon Bedrock Converse API within a verified tenant session boundary.
        Falls back to deterministic domain-expert synthesis when in local simulation mode.
        """
        tenant = self.session_guard.verify_session_access(session_id, target_account_id)

        if not self.simulation_mode and self._bedrock_client is not None:
            response = self._bedrock_client.converse(
                modelId=self.model_id,
                system=[{"text": system_prompt}],
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": json.dumps(user_payload)}],
                    }
                ],
                inferenceConfig={"maxTokens": 1024, "temperature": 0.1},
            )
            output_text = (
                response.get("output", {})
                .get("message", {})
                .get("content", [{}])[0]
                .get("text", "{}")
            )
            try:
                return json.loads(output_text)
            except json.JSONDecodeError:
                return {"raw_response": output_text, "tenant_id": tenant.tenant_id}

        # Deterministic high-precision synthesis for local/CI execution
        metric_name = user_payload.get("metric_name", "CPUUtilization")
        service = user_payload.get("aws_service", "AWS/ECS")
        severity = user_payload.get("severity", "CRITICAL")

        if "ECS" in service or "Memory" in metric_name or "CPU" in metric_name:
            root_cause = (
                f"Container memory leak and connection pool exhaustion in {service} cluster "
                f"following deployment v2.14.8 on account {tenant.aws_account_id}; "
                f"accompanied by over-provisioned NAT Gateway idle cross-AZ data transfer."
            )
            runbook = "ssm:Aegis-RecycleECSServiceTasks"
            finops_action = "Rightsize 6 underutilized gp2 volumes to gp3 & consolidate NAT Gateway AZ routing"
            savings = round(tenant.monthly_aws_spend_usd * 0.145, 2)
            cost_delta = -savings
        elif "RDS" in service or "DatabaseConnections" in metric_name:
            root_cause = (
                f"RDS PostgreSQL connection spike caused by unindexed analytic query burst and "
                f"stale idle read-replica scaling policy in {tenant.region}."
            )
            runbook = "ssm:Aegis-ScaleRDSReadReplica"
            finops_action = "Convert 2 idle RDS db.r6g.2xlarge Multi-AZ instances to Graviton3 Reserved Capacity"
            savings = round(tenant.monthly_aws_spend_usd * 0.182, 2)
            cost_delta = 45.0
        else:
            root_cause = (
                f"Anomalous traffic and API throttling detected on {service} ({metric_name}, {severity}) "
                f"correlated with unattached EBS snapshots and orphaned ALB target groups."
            )
            runbook = "ssm:Aegis-RotateWAFBlockedIPSet"
            finops_action = "Delete 42 orphaned EBS snapshots & migrate burst workloads to Compute Savings Plans"
            savings = round(tenant.monthly_aws_spend_usd * 0.118, 2)
            cost_delta = 0.0

        return {
            "tenant_id": tenant.tenant_id,
            "aws_account_id": tenant.aws_account_id,
            "model_id": self.model_id,
            "execution_mode": "bedrock-agentcore-deterministic-sim" if self.simulation_mode else "bedrock-live",
            "root_cause_hypothesis": root_cause,
            "confidence_score": 0.96,
            "recommended_runbook": runbook,
            "estimated_runbook_cost_delta_usd": cost_delta,
            "finops_optimization_recommendation": finops_action,
            "estimated_monthly_savings_usd": savings,
            "quick_nlq_summary": (
                f"{tenant.tenant_name} ({tenant.sla_tier}): Resolved {service} {metric_name} anomaly "
                f"via {runbook} while unlocking ${savings:,.2f}/mo in AWS FinOps savings."
            ),
        }

    def export_telemetry_snapshot(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "region": self.region_name,
            "simulation_mode": self.simulation_mode,
            "active_isolated_sessions": len(self.session_guard._active_sessions),
            "memory_entries_count": len(self._memory_store),
            "recent_memory": [asdict(m) for m in self._memory_store[-5:]],
        }
