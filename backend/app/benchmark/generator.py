"""Deterministic benchmark workload generator."""

import random
from typing import List, Optional
from uuid import uuid5, NAMESPACE_DNS

from app.domain.models import BenchmarkRequest
from app.benchmark.profiles import BenchmarkProfile, TASK_PROMPTS, get_profile


class BenchmarkWorkloadGenerator:
    def __init__(self, profile: str, seed: int = 42, models: Optional[List[str]] = None):
        self.profile: BenchmarkProfile = get_profile(profile)
        self.seed = seed
        self.rng = random.Random(seed)
        self.models = models or self.profile.models

    def _deterministic_uuid(self, *parts):
        key = ":".join(str(p) for p in parts)
        return uuid5(NAMESPACE_DNS, f"deepfield:bench:{self.seed}:{key}")

    def generate(self, benchmark_run_id=None) -> list[BenchmarkRequest]:
        if benchmark_run_id is None:
            benchmark_run_id = self._deterministic_uuid("run")

        requests = []
        idx = 0
        for model in self.models:
            for _ in range(self.profile.requests_per_model):
                task_type = self.rng.choice(self.profile.task_types)
                prompts = TASK_PROMPTS.get(task_type, TASK_PROMPTS["general_summary"])
                prompt = self.rng.choice(prompts)
                input_tokens_est = max(1, len(prompt.split()) * 2)

                requests.append(
                    BenchmarkRequest(
                        request_id=self._deterministic_uuid("req", idx),
                        benchmark_run_id=benchmark_run_id,
                        workload_profile=self.profile.name,
                        task_type=task_type,
                        prompt=prompt,
                        input_tokens_estimate=input_tokens_est,
                        expected_output_tokens=self.profile.max_output_tokens,
                        model_preference=model,
                    )
                )
                idx += 1

        return requests

    def generate_for_concurrency_level(self, concurrency: int, benchmark_run_id=None) -> list[BenchmarkRequest]:
        reqs = self.generate(benchmark_run_id)
        for req in reqs:
            req.metadata = {**req.metadata, "concurrency_level": concurrency}
        return reqs
