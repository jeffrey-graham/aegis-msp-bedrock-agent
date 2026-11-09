# AegisMSP: Autonomous Multi-Tenant Incident Triage, FinOps & SLA Remediation Agent

**Built for the AWS MSP AI Hackathon ($64,000 Prize Pool across 16 Winners)**  
**Target Tracks:**
- **Main Track 1:** Autonomous Incident Operations & Service Reliability
- **Main Track 2:** Cloud FinOps & Customer Resource Optimization
- **Special Category Prizes ($2,000 each):**
  - *Best Use of Amazon Bedrock AgentCore* (Cryptographic Session Isolation, AgentCore Memory, Cedar Policy Guardrails)
  - *Best Use of Strands Agents SDK* (5-Node Multi-Agent Triage, Remediation & FinOps Graph)
  - *Best Use of Amazon Quick / CloudWatch* (Real-Time CloudWatch Alarm Correlation + Executive NLQ Insights)

---

## Architecture Overview

![AegisMSP Architecture](assets/architecture.png)

Managed Service Providers (MSPs) operate hundreds of isolated customer AWS accounts simultaneously under strict Platinum/Gold SLAs. **AegisMSP** eliminates L1/L2 alert fatigue and cloud waste through a 5-stage **Strands Agents SDK** pipeline governed by **Amazon Bedrock AgentCore**:

1. **`AlertIngestorAgent`**: Normalizes CloudWatch Alarms, EventBridge notifications, and AWS Cost Anomaly signals while matching against anonymized cross-tenant AgentCore memory signatures.
2. **`RootCauseAnalyzerAgent`**: Invokes Amazon Bedrock Converse API (`us.anthropic.claude-3-7-sonnet-20250219-v1:0`) inside a cryptographically isolated `TenantSessionGuard` session, correlating X-Ray traces and CloudWatch Logs Insights.
3. **`RunbookExecutorAgent`**: Evaluates proposed AWS Systems Manager (`ssm:StartAutomationExecution`) runbooks against 5 Cedar-compatible safety policies (`MSPPolicyEnforcer`) before autonomous execution.
4. **`FinOpsRightsizerAgent`**: Quantifies idle EBS `gp2`->`gp3` upgrades, Graviton3 RDS rightsizing, and NAT Gateway consolidation opportunities.
5. **`SLARiskScorerAgent`**: Computes SLA error-budget burn rate, MTTR reduction, and powers an **Amazon Quick (QuickSight Q)** natural-language query interface for MSP leadership.

---

## Quick Start

### 1. Run the Unit & Guardrail Verification Suite
```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

### 2. Run the Multi-Tenant Fleet Triage CLI Simulation
```bash
PYTHONPATH=src python3 -m aegis_msp.server --run-once
```

### 3. Launch the Live Interactive MSP Command Center Web UI
```bash
PYTHONPATH=src python3 -m aegis_msp.server --port 8090
# Open http://127.0.0.1:8090 in your browser
```

### 4. Regenerate 1080p Architecture Diagram & Demo Video
```bash
python3 scripts/generate_demo_video.py
```
This outputs `assets/architecture.png` and `assets/aegis_msp_demo.mp4`.
