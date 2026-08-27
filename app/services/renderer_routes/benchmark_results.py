"""Runtime benchmark-results loader for the adaptive route selection.

The adaptive pose-swap implementation MUST NOT hard-code measured outcomes:
route decisions are derived at runtime from the I03/I05 frozen benchmark
results JSON (schema_version=1, ``benchmark_results_seed<seed>.json``) or
from a fresh harness re-run.  This module is the single reader of that
document and exposes the smallest-passing route per risk class plus the
measured evidence needed by escalations.

Fail-closed rules:
- unknown schema_version / missing policy → BenchmarkResultsError;
- a fixture row whose threshold_evaluation is absent or malformed is never
  silently treated as passing;
- ``smallest_passing_route`` returns None (never another route) when no
  measured route passes the class.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

__all__ = [
    "BenchmarkResultsDocument",
    "BenchmarkResultsError",
    "load_benchmark_results",
]

#: Schemes this module knows how to read.  The original I03 harness froze
#: ``schema_version=1``; C2 emits v3 measured documents (typed freeze
#: components + per-row J1 pin + dict sample counts) and the I05-C2 route
#: decision pins their content SHA.  Bumping requires an explicit code
#: change here.
SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (1, 2, 3)

#: Canonical route ladder — mirrors ROUTE_PRIORITY (cheapest first).  Local
#: copy keeps this leaf import-free from the router (no cycles).
_ROUTE_LADDER: tuple[str, ...] = (
    "pose_swap",
    "sprite_affine",
    "mesh_warp",
    "part_rig",
    "controlled_redraw",
)


class BenchmarkResultsError(RuntimeError):
    """Raised when the benchmark-results document is unusable (fail closed)."""


class BenchmarkResultsDocument:
    """Typed view over one frozen benchmark-results JSON."""

    def __init__(self, path: Path, payload: dict[str, Any]) -> None:
        self._path = path
        self._payload = payload

    @property
    def path(self) -> Path:
        return self._path

    @property
    def schema_version(self) -> int:
        """Validated schema version of the underlying document."""
        return int(self._payload["schema_version"])

    @property
    def frozen_content_sha256(self) -> str:
        return str(self._payload["frozen_content_sha256"])

    @property
    def thresholds_policy(self) -> str | None:
        value = self._payload.get("thresholds_policy")
        return None if value is None else str(value)

    @property
    def routes(self) -> list[str]:
        routes = self._payload.get("routes")
        if not isinstance(routes, list) or not routes:
            raise BenchmarkResultsError(
                f"{self._path}: 'routes' must be a non-empty list"
            )
        out: list[str] = []
        for name in routes:
            if name not in _ROUTE_LADDER:
                raise BenchmarkResultsError(
                    f"{self._path}: unknown route {name!r} in results document"
                )
            out.append(str(name))
        return out

    def rows_for_class(self, risk_class: str) -> list[dict[str, Any]]:
        """Measured rows for one risk class; empty when never measured."""
        rows = self._payload.get("results")
        if not isinstance(rows, list):
            raise BenchmarkResultsError(
                f"{self._path}: 'results' must be a list"
            )
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise BenchmarkResultsError(
                    f"{self._path}: non-object result row"
                )
            if row.get("risk_class") == risk_class:
                out.append(row)
        return out

    def smallest_passing_route(self, risk_class: str) -> str | None:
        """Smallest route in the ladder whose measured evaluation PASSES.

        Returns None when nothing measured passes — callers decide policy
        (refuse / escalate with fresh evidence); this function NEVER returns
        a failing route as if it passed.
        """
        best: str | None = None
        best_rank = len(_ROUTE_LADDER)
        for row in self.rows_for_class(risk_class):
            evaluation = row.get("threshold_evaluation")
            if not isinstance(evaluation, dict):
                continue  # malformed row is not evidence of passing
            if evaluation.get("overall_pass") is not True:
                continue
            route = row.get("route")
            if route not in _ROUTE_LADDER:
                continue
            rank = _ROUTE_LADDER.index(route)
            if rank < best_rank:
                best, best_rank = str(route), rank
        return best

    def smallest_passing_or_raise(self, risk_class: str) -> str:
        route = self.smallest_passing_route(risk_class)
        if route is None:
            raise BenchmarkResultsError(
                f"no measured route passes risk class {risk_class!r} "
                f"in {self._path.name}"
            )
        return route

    def swap_capability_verified(self, risk_class: str, route: str) -> bool:
        """True only when a PASSING ``pose_state_capability`` check exists for
        (risk_class, route) — i.e. the document carries explicit measured
        evidence that this route handled annotated pose/expression swaps."""
        for row in self.rows_for_class(risk_class):
            if row.get("route") != route:
                continue
            evaluation = row.get("threshold_evaluation")
            if not isinstance(evaluation, dict):
                continue
            if evaluation.get("overall_pass") is not True:
                continue
            for check in evaluation.get("checks", []):
                if (
                    isinstance(check, dict)
                    and check.get("metric") == "pose_state_capability"
                    and check.get("pass") is True
                    and check.get("limit") == "required_when_swaps_annotated"
                ):
                    return True
        return False

    def zero_sample_classes(self) -> set[str]:
        """Risk classes claiming MEASURED_RENDERED_OUTPUT with a ZERO or
        missing sample count — never valid planning evidence (fail closed)."""
        out: set[str] = set()
        rows = self._payload.get("results")
        if not isinstance(rows, list):
            return out
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("measured_state") != "MEASURED_RENDERED_OUTPUT":
                continue
            raw_count = row.get("metrics_sample_count")
            if isinstance(raw_count, dict):
                # v3 shape: typed per-stream counts — measured when at least
                # one stream carries a positive sample.
                count = sum(
                    int(v) for v in raw_count.values() if isinstance(v, int)
                )
            else:
                try:
                    count = int(raw_count or 0)
                except (TypeError, ValueError):
                    count = 0
            if count <= 0:
                rc = row.get("risk_class")
                if isinstance(rc, str):
                    out.add(rc)
        return out

    def route_measured_passing(self, risk_class: str, route: str) -> bool:
        """True when (risk_class, route) was measured with overall_pass."""
        for row in self.rows_for_class(risk_class):
            if row.get("route") == str(route):
                evaluation = row.get("threshold_evaluation")
                if isinstance(evaluation, dict) and evaluation.get("overall_pass") is True:
                    return True
        return False

    def projection_for(
        self, risk_class: str, metric_name: str, route: str
    ) -> float | None:
        """Measured metric value for (risk_class, route) to use as the
        escalation candidate_metric_projection.  None when unmeasured."""
        for row in self.rows_for_class(risk_class):
            if row.get("route") != route:
                continue
            evaluation = row.get("threshold_evaluation")
            if not isinstance(evaluation, dict):
                continue
            for check in evaluation.get("checks", []):
                if (
                    isinstance(check, dict)
                    and check.get("metric") == metric_name
                    and isinstance(check.get("value"), (int, float))
                ):
                    return float(check["value"])
            metrics = row.get("metrics")
            if isinstance(metrics, dict):
                value = metrics.get(metric_name)
                if isinstance(value, (int, float)):
                    return float(value)
        return None


def load_benchmark_results(path: Path) -> BenchmarkResultsDocument:
    """Load + structurally validate one results document."""
    if not path.is_file():
        raise BenchmarkResultsError(f"benchmark results not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise BenchmarkResultsError(f"{path}: unreadable ({err})") from err
    if not isinstance(payload, dict):
        raise BenchmarkResultsError(f"{path}: top-level JSON must be an object")
    version = payload.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise BenchmarkResultsError(
            f"{path}: unsupported schema_version {version!r} "
            f"(supported: {list(SUPPORTED_SCHEMA_VERSIONS)})"
        )
    if not payload.get("frozen_content_sha256"):
        raise BenchmarkResultsError(f"{path}: missing frozen_content_sha256")
    doc = BenchmarkResultsDocument(path=path, payload=payload)
    if not doc.routes:  # validates the routes field eagerly (never empty here)
        raise BenchmarkResultsError(f"{path}: 'routes' must be a non-empty list")
    return doc


def rerun_harness(
    *,
    repo_root: Path,
    fixtures_dir: Path,
    out_dir: Path,
    routes: list[str] | None = None,
    seed: int = 20260823,
    timeout_s: float = 900.0,
    fixtures_filter: list[str] | None = None,
) -> Path:
    """Re-run the frozen I03 harness (read-only usage of its CLI) and return
    the freshly written results path.  Used when cached evidence is stale or
    a class needs a fresh measurement — never a silent substitute."""
    script = repo_root / "scripts" / "s09_renderer_benchmark.py"
    if not script.is_file():
        raise BenchmarkResultsError(f"harness script missing: {script}")
    cmd: list[str] = [
        sys.executable,
        str(script),
        "--routes",
        ",".join(routes if routes is not None else ["pose_swap", "sprite_affine"]),
        "--fixtures",
        str(fixtures_dir),
        "--out",
        str(out_dir),
        "--seed",
        str(seed),
    ]
    if fixtures_filter:
        cmd.extend(["--fixtures-filter", *fixtures_filter])
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout).strip().splitlines()
        raise BenchmarkResultsError(
            "harness re-run failed: " + (tail[-1] if tail else f"exit {completed.returncode}")
        )
    expected = out_dir / f"benchmark_results_seed{seed}.json"
    if not expected.is_file():
        raise BenchmarkResultsError(
            f"harness re-run produced no results at {expected}"
        )
    return expected
