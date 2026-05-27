"""Multi-cluster collector — scans multiple OpenShift clusters and merges signals."""

import logging
from typing import List, Tuple

from app.domain.models import ClusterRef, RawSignal
from app.collectors.openshift import OpenShiftCollector

logger = logging.getLogger(__name__)


class MultiClusterCollector:
    def __init__(self, cluster_configs: List[dict]):
        self.collectors = []
        for cfg in cluster_configs:
            self.collectors.append(OpenShiftCollector(
                cluster_name=cfg["name"],
                api_url=cfg["api_url"],
                token=cfg.get("token", ""),
                include_namespaces=cfg.get("include_namespaces"),
                exclude_namespaces=cfg.get("exclude_namespaces"),
            ))

    def collect(self) -> Tuple[List[ClusterRef], List[RawSignal]]:
        all_clusters = []
        all_signals = []
        for collector in self.collectors:
            try:
                clusters, signals = collector.collect()
                all_clusters.extend(clusters)
                all_signals.extend(signals)
            except Exception as e:
                logger.warning("Failed to collect from %s: %s", collector.cluster_name, e)
        return all_clusters, all_signals
