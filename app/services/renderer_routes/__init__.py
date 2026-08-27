"""S09-T02 adaptive renderer route implementations.

Public surface of the adaptive route package:

- :mod:`composite` — the deterministic CPU compositor (pose-swap schedule +
  sprite-affine keyframes) shared by the wired adapters;
- :class:`PoseSwapAdaptiveAdapter` — pose_swap backend with MEASURED
  pose-state-capability evidence over the real composite pipeline;
- :class:`OptimizedSpriteAffineAdapter` — sprite_affine backend tuned from
  the measured baseline (identity segments skip the filter graph);
- :func:`select_route` / ``BenchmarkResultsDocument`` — runtime adaptive
  selection from the frozen benchmark results JSON (never hard-coded);
- :func:`measure_pose_state_capability` — the measured swap verifier.

Import note: ``app.adapters.renderer.pose_swap_adapter`` imports THIS
package's ``composite`` module; this package's ``adaptive_pose_swap``
imports that adapter back.  To avoid a circular import, this ``__init__``
does NOT import ``adaptive_pose_swap`` eagerly — use the lazy accessors
below (attribute access on the package).
"""

from typing import TYPE_CHECKING

from app.services.renderer_routes import composite
from app.services.renderer_routes.benchmark_results import (
    BenchmarkResultsDocument,
    BenchmarkResultsError,
    load_benchmark_results,
    rerun_harness,
)
from app.services.renderer_routes.composite import (
    canonical_frame_sha256,
    composite_pose_swap_frames,
    composite_sprite_affine_frames,
    decode_rgb_frames,
    write_frames_mp4,
)

if TYPE_CHECKING:
    # Static-only re-exports matching the lazy accessors below.  Mypy reads
    # this branch so static consumers (e.g. app/workflow/s09_demo_jobs.py)
    # see real callables/classes instead of ``object`` from ``__getattr__``;
    # runtime keeps using PEP 562 to break the adapter ⇄ package cycle.
    from app.services.renderer_routes.adaptive_pose_swap import (
        AdaptiveRouteDecision,
        OptimizedSpriteAffineAdapter,
        PoseSwapAdaptiveAdapter,
        load_pose_templates_rgba,
        measure_pose_state_capability,
        select_route,
    )

__all__ = [
    "AdaptiveRouteDecision",
    "BenchmarkResultsDocument",
    "BenchmarkResultsError",
    "OptimizedSpriteAffineAdapter",
    "PoseSwapAdaptiveAdapter",
    "canonical_frame_sha256",
    "composite",
    "composite_pose_swap_frames",
    "composite_sprite_affine_frames",
    "decode_rgb_frames",
    "load_benchmark_results",
    "load_pose_templates_rgba",
    "measure_pose_state_capability",
    "rerun_harness",
    "select_route",
    "write_frames_mp4",
]


def __getattr__(name: str) -> object:  # PEP 562 lazy re-export
    """Lazy re-exports to break the adapter ⇄ package import cycle."""
    if name in (
        "AdaptiveRouteDecision",
        "OptimizedSpriteAffineAdapter",
        "PoseSwapAdaptiveAdapter",
        "load_pose_templates_rgba",
        "measure_pose_state_capability",
        "select_route",
    ):
        from app.services.renderer_routes import adaptive_pose_swap as _mod

        return getattr(_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
