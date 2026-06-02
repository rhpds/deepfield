"""Rubric history — tracks EDD evaluation scores over time for trend detection."""

import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("deepfield.rubric_history")

_instance: Optional["RubricHistory"] = None


class RubricHistory:
    def __init__(self, max_per_cluster: int = 100):
        self._history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_per_cluster))

    def record(self, cluster_id: str, evaluation: dict,
               source: str = "manual", source_id: str = ""):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overall": evaluation.get("overall", "unknown"),
            "rubrics": {
                name: rubric.get("score", "unknown")
                for name, rubric in evaluation.get("rubrics", {}).items()
            },
            "source": source,
            "source_id": source_id,
        }
        self._history[cluster_id].append(entry)

        try:
            from app.db import enqueue_write
            enqueue_write("rubric_evaluations", {
                "cluster_id": cluster_id,
                "overall_score": entry["overall"],
                "rubric_scores": entry["rubrics"],
                "source": source,
                "source_id": source_id,
            })
        except Exception:
            pass

    def get_history(self, cluster_id: str, limit: int = 20) -> list:
        entries = list(self._history.get(cluster_id, []))
        return entries[-limit:]

    def get_trend(self, cluster_id: str) -> dict:
        entries = list(self._history.get(cluster_id, []))
        if len(entries) < 4:
            return {"overall": "insufficient_data", "rubrics": {}}

        recent = entries[-3:]
        prior = entries[-6:-3] if len(entries) >= 6 else entries[:3]

        rubric_names = set()
        for e in recent + prior:
            rubric_names.update(e.get("rubrics", {}).keys())

        score_rank = {"healthy": 2, "warning": 1, "failing": 0, "unknown": -1}
        trends = {}
        for name in rubric_names:
            recent_avg = sum(score_rank.get(e.get("rubrics", {}).get(name, "unknown"), -1) for e in recent) / len(recent)
            prior_avg = sum(score_rank.get(e.get("rubrics", {}).get(name, "unknown"), -1) for e in prior) / len(prior)
            if recent_avg > prior_avg + 0.3:
                trends[name] = "improving"
            elif recent_avg < prior_avg - 0.3:
                trends[name] = "degrading"
            else:
                trends[name] = "stable"

        recent_overall = sum(score_rank.get(e.get("overall", "unknown"), -1) for e in recent) / len(recent)
        prior_overall = sum(score_rank.get(e.get("overall", "unknown"), -1) for e in prior) / len(prior)
        if recent_overall > prior_overall + 0.3:
            overall_trend = "improving"
        elif recent_overall < prior_overall - 0.3:
            overall_trend = "degrading"
        else:
            overall_trend = "stable"

        return {"overall": overall_trend, "rubrics": trends}


def get_rubric_history() -> RubricHistory:
    global _instance
    if _instance is None:
        _instance = RubricHistory()
    return _instance
