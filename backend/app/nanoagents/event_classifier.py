"""Event classifier nano-agent — maps raw Kubernetes events to signal types.

These rules are deterministic. New rules can be added from YAML config
or promoted from LLM classifications after validation.
"""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "EventClassifierAgent"

# Deterministic event reason → classification rules
# Format: event_reason → (reclassified_signal_type, outcome, severity_hint)
EVENT_RULES = {
    "event_backoff": ("pod_crashloop", "escalate", "high"),
    "event_crashloopbackoff": ("pod_crashloop", "escalate", "high"),
    "event_failed": ("pod_pending", "keep", "medium"),
    "event_failedcreate": ("pod_pending", "keep", "medium"),
    "event_failedscheduling": ("failed_scheduling", "keep", "medium"),
    "event_imagepullbackoff": ("pod_imagepullbackoff", "escalate", "high"),
    "event_errimagepull": ("pod_imagepullbackoff", "escalate", "high"),
    "event_unhealthy": ("route_unhealthy", "escalate", "high"),
    "event_failedmount": ("pvc_pending", "escalate", "medium"),
    "event_failedattachvolume": ("pvc_pending", "escalate", "medium"),
    "event_nodenotready": ("node_pressure", "escalate", "critical"),
    "event_backofflimitexceeded": ("backoff_limit_exceeded", "escalate", "high"),
    "event_failedgetresourcemetric": ("failed_get_metric", "keep", "medium"),
    "event_invalidconfiguration": ("invalid_configuration", "escalate", "high"),
    "event_failedmigration": ("vm_migration_failed", "escalate", "high"),
    "event_migrationtargetpodunschedulable": ("vm_migration_failed", "escalate", "high"),
    "event_migrationbackoff": ("vm_migration_backoff", "keep", "medium"),
    "event_killing": ("pod_pending", "keep", "low"),
    "event_preempting": ("pod_pending", "keep", "low"),
    "event_evicted": ("pod_crashloop", "escalate", "high"),
}

# Patterns that should be suppressed (known transients)
SUPPRESS_PATTERNS = {
    "event_pulling",
    "event_pulled",
    "event_created",
    "event_started",
    "event_scheduled",
    "event_successfulcreate",
    "event_successfuldelete",
    "event_normal",
    "event_unknown",
}


def filter(signals: List[NormalizedSignal]) -> List[FilterDecision]:
    decisions = []
    for s in signals:
        if not s.signal_type.startswith("event_"):
            continue

        if s.signal_type in SUPPRESS_PATTERNS:
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="suppress",
                reason_code="known_transient_event",
                evidence={"original_type": s.signal_type},
            ))
            continue

        rule = EVENT_RULES.get(s.signal_type)
        if rule:
            classified_type, outcome, severity = rule
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome=outcome,
                reason_code=f"classified:{classified_type}",
                evidence={
                    "original_type": s.signal_type,
                    "classified_as": classified_type,
                    "severity_hint": severity,
                    "rule_source": "deterministic",
                },
            ))
        else:
            # Unknown event type — keep for potential LLM classification
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="keep",
                reason_code="unclassified_event",
                evidence={
                    "original_type": s.signal_type,
                    "needs_llm_classification": True,
                },
            ))

    return decisions
