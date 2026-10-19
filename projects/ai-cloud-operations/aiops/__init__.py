"""aiops: deterministic log-anomaly detection with guardrailed, human-approved remediation.

Pipeline stages (see README.md for the full write-up):

  Inputs      logs, deploy events, alerts
  Analyze     anomaly detection (rolling baseline / z-score), correlation
              by time window + service
  Summarize   template summary always; optional, budgeted LLM summary
  Act         allow-listed remediation proposal, human approval required,
              append-only audit trail

The analysis process never holds credentials capable of executing anything;
it can only produce a Proposal object for a human to approve or reject.
"""

from __future__ import annotations

__version__ = "0.1.0"
