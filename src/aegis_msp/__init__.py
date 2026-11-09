"""
AegisMSP: Autonomous Multi-Tenant Incident Triage, FinOps & SLA Remediation Agent
Built for the AWS MSP AI Hackathon (Amazon Bedrock AgentCore + Strands Agents SDK + CloudWatch/Quick).
"""

__version__ = "1.0.0"

from .bedrock_agentcore import (
    BedrockAgentCoreOrchestrator,
    MSPPolicyEnforcer,
    TenantContext,
    TenantSessionGuard,
)
from .strands_workflow import (
    IncidentEvent,
    RemediationOutcome,
    StrandsMSPWorkflow,
)

__all__ = [
    "BedrockAgentCoreOrchestrator",
    "MSPPolicyEnforcer",
    "TenantContext",
    "TenantSessionGuard",
    "IncidentEvent",
    "RemediationOutcome",
    "StrandsMSPWorkflow",
]
