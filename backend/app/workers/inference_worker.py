"""Kafka consumer: findings → LLM inference → inference results."""

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.workers.base import KafkaWorker

logger = logging.getLogger("deepfield.workers.inference")


class InferenceWorker(KafkaWorker):
    topic = "deepfield-findings"
    group_id = "deepfield-inference"

    def __init__(self, client=None, store=None):
        super().__init__()
        self._client = client
        self._store = store

    def process(self, message: dict) -> None:
        from app.domain.models import CandidateFinding
        from app.routing.signal_router import create_reasoning_tasks
        from app.inference.router import resolve_model
        from app.agents.prompts import load_prompt

        finding = CandidateFinding(
            finding_id=message.get("finding_id", str(uuid4())),
            finding_type=message.get("finding_type", ""),
            severity=message.get("severity", "medium"),
            summary=message.get("summary", ""),
            namespaces=message.get("namespaces", []),
            clusters=[UUID(c) if len(c) == 36 else uuid4() for c in message.get("clusters", [])],
            signal_ids=[UUID(s) if len(str(s)) == 36 else uuid4() for s in message.get("signal_ids", [])],
            signal_count=message.get("signal_count", 0),
            evidence=message.get("evidence", {}),
        )

        tasks = create_reasoning_tasks([finding])
        if not tasks or not self._client:
            return

        for task in tasks[:4]:
            model = resolve_model(task)
            prompt_name = _TASK_TO_PROMPT.get(task.task_type, "rca")
            prompt_config = load_prompt(prompt_name)
            max_tokens = prompt_config.get("max_tokens", 800)

            resp = self._client.infer(model=model, prompt=task.prompt, max_tokens=max_tokens)
            tier = "micro" if "cpu" in model or "granite" in model else "macro"

            inference_dict = {
                "model": model,
                "tier": tier,
                "task_type": task.task_type,
                "prompt": task.prompt,
                "output": resp.output or "" if resp.status == "success" else "",
                "error": resp.error or "" if resp.status != "success" else "",
                "latency_ms": round(resp.latency_ms, 1),
                "tokens_in": resp.tokens_in if resp.status == "success" else 0,
                "tokens_out": resp.tokens_out if resp.status == "success" else 0,
                "severity": task.context.get("severity", ""),
                "finding_type": task.context.get("finding_type", ""),
                "namespace": (task.context.get("namespaces") or [""])[0],
                "clusters": task.context.get("clusters", []),
            }

            if self._store:
                self._store.add_inference(inference_dict)

            if resp.status == "success" and resp.output:
                self._feed_incident(task, model, resp.output)

            try:
                from app.integrations.kafka_publisher import publish_to_kafka
                publish_to_kafka("deepfield-inferences", inference_dict,
                                 key=str(task.finding_id))
            except Exception:
                pass

    def _feed_incident(self, task, model: str, output: str):
        """Route inference results to incident manager — same logic as streaming session."""
        try:
            import json as _json
            import re
            from app.api.incidents import get_manager
            mgr = get_manager()

            ns = (task.context.get("namespaces") or [""])[0]
            cluster = (task.context.get("clusters") or ["infra01"])[0]
            if not ns:
                return

            if task.task_type in ("root_cause_analysis", "cross_cluster_correlation"):
                all_signals = task.context.get("signals", [])
                signal_count = task.context.get("signal_count", len(all_signals))

                mgr.process_signal(
                    namespace=ns, cluster_id=cluster,
                    signal_type=task.context.get("finding_type", "namespace_correlation"),
                    severity=task.context.get("severity", "high"),
                    signal_id=str(task.task_id)[:8],
                    resource_name=f"{signal_count} correlated signals",
                )

                for sig in all_signals:
                    if isinstance(sig, dict):
                        mgr.process_signal(
                            namespace=ns, cluster_id=cluster,
                            signal_type=sig.get("signal_type", "unknown"),
                            severity=sig.get("severity", "medium"),
                            signal_id=sig.get("signal_id", str(hash(str(sig)))[:8]),
                            resource_name=sig.get("resource_name", ""),
                        )

                mgr.add_inference(namespace=ns, cluster_id=cluster,
                                  task_type="root_cause_analysis", model=model, output=output)

                parsed = None
                try:
                    cleaned = re.sub(r'<think>.*?</think>', '', output, flags=re.DOTALL)
                    cleaned = cleaned.replace('```json', '').replace('```', '').strip()
                    start = cleaned.find("{")
                    if start >= 0:
                        json_str = cleaned[start:]
                        try:
                            parsed = _json.loads(json_str)
                        except _json.JSONDecodeError:
                            opens = json_str.count("{") - json_str.count("}")
                            json_str += "}" * max(opens, 0)
                            json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
                            parsed = _json.loads(json_str)
                except (ValueError, _json.JSONDecodeError):
                    pass

                if parsed:
                    if parsed.get("category"):
                        mgr.add_classification(
                            namespace=ns, cluster_id=cluster,
                            failure_class=str(parsed["category"]),
                            confidence=float(parsed.get("confidence", 0.7)),
                            model=model,
                        )
                    rem = parsed.get("remediation", {})
                    if isinstance(rem, dict):
                        for step in rem.get("steps", []):
                            mgr.add_remediation_option(
                                namespace=ns, cluster_id=cluster,
                                action=step, risk=str(rem.get("risk", "medium")), source="rca",
                            )
                        for cmd in rem.get("commands", []):
                            mgr.add_remediation_option(
                                namespace=ns, cluster_id=cluster,
                                action=f"Run: {cmd}", command=cmd,
                                risk=str(rem.get("risk", "low")), source="rca",
                            )

            elif task.task_type == "classify_signal" and output:
                try:
                    parsed = _json.loads(output.strip().strip("`").strip())
                    if parsed.get("failure_class"):
                        mgr.add_classification(
                            namespace=ns, cluster_id=cluster,
                            failure_class=parsed["failure_class"],
                            confidence=float(parsed.get("confidence", 0.5)),
                            model=model,
                        )
                except (ValueError, _json.JSONDecodeError, AttributeError):
                    pass

            elif task.task_type == "suggest_remediation" and output:
                try:
                    parsed = _json.loads(output.strip().strip("`").strip())
                    if parsed.get("fix"):
                        mgr.add_remediation_option(
                            namespace=ns, cluster_id=cluster,
                            action=parsed["fix"],
                            command=parsed.get("command"),
                            risk=str(parsed.get("risk", "medium")),
                            source="micro",
                        )
                except (ValueError, _json.JSONDecodeError, AttributeError):
                    pass

            elif task.task_type == "explain_signal":
                mgr.add_inference(namespace=ns, cluster_id=cluster,
                                  task_type="explain_signal", model=model, output=output)

            try:
                from app.integrations.kafka_publisher import publish_incident_event
                inc_state = mgr._find_open(ns, cluster)
                if inc_state:
                    publish_incident_event({
                        "id": inc_state.get("id", ""),
                        "namespace": ns,
                        "cluster_id": cluster,
                        "status": inc_state.get("status", "open"),
                        "severity": inc_state.get("severity", ""),
                        "task_type": task.task_type,
                        "model": model,
                        "signal_count": inc_state.get("signal_count", 0),
                    })
            except Exception:
                pass

        except Exception as e:
            logger.debug("Incident feed error: %s", e)


_TASK_TO_PROMPT = {
    "root_cause_analysis": "rca",
    "summarize_finding": "triage",
    "cross_cluster_correlation": "correlation",
    "fleet_summary": "rca",
    "incident_analysis": "incident",
    "classify_signal": "classify_signal",
    "correlate_findings": "correlate_findings",
    "suggest_remediation": "suggest_remediation",
    "explain_signal": "explain_signal",
    "filter_noise": "filter_noise",
}
