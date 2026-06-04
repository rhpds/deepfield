"""Converts RawSignal → NormalizedSignal with severity classification."""

from datetime import datetime, timezone

from app.domain.models import NormalizedSignal, RawSignal
from app.generators.signal_types import FAILURE_SIGNALS, HEALTHY_SIGNALS, WARNING_SIGNALS


SEVERITY_MAP = {
    "pod_running": "info",
    "pod_pending": "low",
    "pod_crashloop": "high",
    "pod_imagepullbackoff": "high",
    "route_ready": "info",
    "route_unhealthy": "high",
    "pvc_bound": "info",
    "pvc_pending": "medium",
    "node_ready": "info",
    "node_pressure": "critical",
    "namespace_quota_ok": "info",
    "namespace_quota_exceeded": "medium",
    "vm_running": "info",
    "vm_failed": "high",
    "kserve_ready": "info",
    "kserve_not_ready": "high",
    "kafka_lag_normal": "info",
    "kafka_lag_high": "medium",
    "launchpad_lab_active": "info",
    "launchpad_lab_failed": "high",
    "launchpad_lab_expired": "low",
    "stargate_stage_passed": "info",
    "stargate_stage_failed": "high",
    "stargate_run_completed": "info",
    # Real cluster signals discovered from live monitoring
    "vm_migration_failed": "high",
    "vm_migration_backoff": "medium",
    "failed_scheduling": "medium",
    "failed_get_metric": "medium",
    "invalid_configuration": "high",
    "backoff_limit_exceeded": "high",
    "job_failed": "high",
    "container_creating": "info",
    "pod_initializing": "info",
    # Event reasons that should escalate to macro (Gaudi 3)
    "event_backoff": "high",
    "event_crashloopbackoff": "high",
    "event_imagepullbackoff": "high",
    "event_errimagepull": "high",
    "event_unhealthy": "high",
    "event_backofflimitexceeded": "high",
    "event_invalidconfiguration": "high",
    "event_failedmigration": "high",
    "event_nodenotready": "critical",
    "event_evicted": "high",
    "event_failedscheduling": "medium",
    "event_failedcreate": "medium",
    "event_failed": "medium",
    "event_failedmount": "medium",
    "event_failedattachvolume": "medium",
    # Suppress patterns — these are info/noise
    "event_pulling": "info",
    "event_pulled": "info",
    "event_created": "info",
    "event_started": "info",
    "event_scheduled": "info",
    "event_successfulcreate": "info",
    "event_successfuldelete": "info",
    "event_normal": "info",
    "event_killing": "low",
    "event_preempting": "low",
    # AlertManager alerts
    "alert_critical": "critical",
    "alert_warning": "medium",
    "alert_info": "info",
    # Splunk alerts
    "splunk_critical_alert": "critical",
    "splunk_high_alert": "high",
    "splunk_medium_alert": "medium",
    "splunk_low_alert": "low",
    "splunk_info_alert": "info",
    "splunk_error_spike": "high",
    "splunk_slow_response": "medium",
    "splunk_anomaly": "medium",
}


def _extract_evidence(raw: RawSignal) -> dict:
    evidence = {"source": raw.source, "signal_type": raw.signal_type}
    if raw.raw_payload:
        for key in ("reason", "restartCount", "condition", "lag", "resource", "labId",
                     "message", "count", "image", "container", "app", "owner", "node",
                     "exit_code", "exit_reason", "exit_message",
                     "schedule_reason", "schedule_message", "phase",
                     "search_name", "search_query", "triggered_count", "description",
                     "alertname", "summary", "starts_at"):
            if key in raw.raw_payload:
                evidence[key] = raw.raw_payload[key]
    return evidence


def _classify_severity(signal_type: str) -> str:
    if signal_type in SEVERITY_MAP:
        return SEVERITY_MAP[signal_type]
    if signal_type.startswith("event_"):
        return "medium"
    return "low"


def _compute_confidence(signal_type: str) -> float:
    if signal_type in FAILURE_SIGNALS:
        return 0.95
    if signal_type in WARNING_SIGNALS:
        return 0.85
    return 0.99


def normalize_signal(raw: RawSignal) -> NormalizedSignal:
    severity = _classify_severity(raw.signal_type)
    return NormalizedSignal(
        signal_id=raw.signal_id,
        cluster_id=raw.cluster_id,
        namespace=raw.namespace,
        resource_kind=raw.resource_kind,
        resource_name=raw.resource_name,
        signal_type=raw.signal_type,
        severity=severity,
        confidence=_compute_confidence(raw.signal_type),
        deterministic=True,
        labels={"resource_kind": raw.resource_kind, "namespace": raw.namespace},
        evidence=_extract_evidence(raw),
        timestamp=raw.timestamp,
    )


def normalize_batch(signals: list[RawSignal]) -> list[NormalizedSignal]:
    return [normalize_signal(s) for s in signals]
