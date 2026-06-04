"""Suppresses known-noisy infrastructure components that generate millions of
errors without actual impact (coredns, kube-controller-manager, virt-controller, etc.)."""

from typing import List

from app.domain.models import FilterDecision, NormalizedSignal

name = "InfraNoiseAgent"

NOISY_SOURCES = {
    "coredns", "kube-controller-manager", "kube-apiserver", "virt-controller",
    "node-exporter", "catalog-operator", "virt-handler", "cdi-deployment",
    "prometheus", "endpoint",
}

NOISY_NAMESPACES = {
    "openshift-dns", "openshift-monitoring", "openshift-operator-lifecycle-manager",
    "openshift-marketplace", "openshift-image-registry",
}


def filter(signals: List[NormalizedSignal], **kwargs) -> List[FilterDecision]:
    decisions = []
    for s in signals:
        if s.severity in ("info", "low"):
            continue
        resource = s.resource_name.lower()
        evidence = s.evidence or {}
        container = str(evidence.get("container", evidence.get("app", ""))).lower()
        source_comp = container or resource

        if any(noisy in source_comp for noisy in NOISY_SOURCES):
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="suppress",
                reason_code="known_noisy_component",
                evidence={"component": source_comp, "namespace": s.namespace},
            ))
        elif s.namespace in NOISY_NAMESPACES and s.severity == "medium":
            decisions.append(FilterDecision(
                signal_id=s.signal_id, filter_name=name, outcome="suppress",
                reason_code="noisy_platform_namespace",
                evidence={"namespace": s.namespace},
            ))
    return decisions
