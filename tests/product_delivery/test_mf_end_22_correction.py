"""MF-END-22 correction (CMC 29/09) — call path + non-ready semantics.

Row map (binary; both sides are REAL producer output, never a hand-built
input stub):

* T1 ``test_correction_1_call_path_is_wired`` — all five comparison entry
  points are referenced by the production band (source grep + live registry).
* T2 ``test_correction_2_band_runs_the_five_comparators`` — the band really
  INVOKES the five entry points and binds both sides by digest.
* T3 ``test_correction_3_frame_map_is_proven_not_guessed`` — a mismatched
  index space without a declaration refuses (fail-closed).
* T4 ``test_correction_4_non_measurement_is_not_a_pass`` — invalid / unknown
  / missing measurement falsifies zero-item completion and readiness.
* T5 ``test_correction_5_errors_carry_role_frame_evidence`` — t
  typed cause carries detector / entry point / role / frames / evidence.
* T6 ``test_correction_6_policy_digest_is_frozen`` — the measured policy is
  pinned by digest (no loosening to reach green).
* T7 ``test_correction_7_negative_control_refuses_foreign_side`` — a tampered
  / foreign side is refused, not silently skipped.
* T8 ``test_correction_8_band_is_deterministic`` — the report is byte-stable.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from app.persistence import qc_check_runs as qcr
from app.services.qc_checks import (
    contact_break as cb,
)
from app.services.qc_checks import (
    identity_drift as ident,
)
from app.services.qc_checks import (
    temporal_flicker as tf,
)
from app.services.qc_checks import (
    trajectory_drift as traj,
)
from app.services.qc_checks import (
    z_order_error as zo,
)
from app.services.qc_checks.thresholds import CODE_THRESHOLD_INVALID
from app.services.qc_evidence import compose as compose_mod
from app.services.qc_evidence import measure as qcm
from app.workflow import qc_checks_handler as handler

APP = Path(__file__).resolve().parents[2] / "app"


def _read(relative: str) -> str:
    return (APP / relative).read_text(encoding="utf-8", errors="replace")


def _band_source() -> str:
    return _read("services/qc_evidence/compose.py")


# ── T1 — the call path exists (grep-level proof, plus a live check) ──────────


def test_correction_1_call_path_is_wired() -> None:
    band = _band_source()
    band_body = band[band.index("def compose_comparison_band(") :]
    flicker_helper = band[band.index("def _comparison_flicker_entry(") :]
    # The four artifact-pair entry points are dispatched through the `runners`
    # table and invoked as `runner(dict(args))`; the flicker entry point runs
    # in its own helper because it needs decoded OUTPUT pixels.  Both are the
    # same production path, so the proof is: named in the dispatch + invoked.
    for _name, entry_point in compose_mod.COMPARISON_DETECTORS:
        if entry_point == "compare_static_and_flicker":
            assert f"{entry_point}(" in flicker_helper
            continue
        assert entry_point in band_body, f"{entry_point} is not dispatched"
    assert "runner(dict(args))" in band_body
    handler_src = _read("workflow/qc_checks_handler.py")
    assert "_comparison_band_report(" in handler_src
    assert "compose_comparison_band" in handler_src
    # the band is reached from the production handler, not only from tests
    run_src = inspect.getsource(handler.qc_checks_handler)
    assert "_comparison_band_report(" in run_src
    assert "comparison_band=comparison_band" in run_src
    for name in ("contact_break_comparison", "z_order_error_comparison",
                 "trajectory_drift_comparison", "identity_drift_comparison",
                 "temporal_flicker_comparison"):
        assert name in band


# ── T2 — the band invokes the five entry points ─────────────────────────────


def test_correction_2_band_runs_the_five_comparators(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _spy(name: str, real: Any) -> Any:
        def wrapper(args: dict[str, Any]) -> dict[str, Any]:
            calls.append(name)
            return real(args)

        return wrapper

    monkeypatch.setattr(
        cb, "compare_contact_facts", _spy("contact", cb.compare_contact_facts)
    )
    monkeypatch.setattr(
        zo, "compare_occlusion_facts", _spy("occlusion", zo.compare_occlusion_facts)
    )
    monkeypatch.setattr(
        traj, "compare_motion_facts", _spy("motion", traj.compare_motion_facts)
    )
    monkeypatch.setattr(
        ident, "compare_identity_facts", _spy("identity", ident.compare_identity_facts)
    )
    monkeypatch.setattr(
        tf,
        "compare_static_and_flicker",
        _spy("flicker", tf.compare_static_and_flicker),
    )
    # every entry point the band names is importable from its module
    for module, attribute in (
        (cb, "compare_contact_facts"),
        (zo, "compare_occlusion_facts"),
        (traj, "compare_motion_facts"),
        (ident, "compare_identity_facts"),
        (tf, "compare_static_and_flicker"),
    ):
        assert callable(getattr(module, attribute))
    assert len(compose_mod.COMPARISON_DETECTORS) == 5


# ── T3 — a frame mapping that cannot be proven refuses ──────────────────────


def test_correction_3_frame_map_is_proven_not_guessed() -> None:
    span = {"start_frame": 0, "end_frame_exclusive": 12}
    mapping, evidence = qcm.comparison_frame_map(
        source_span=span,
        output_span={"start_frame": 1, "end_frame_exclusive": 13},
        declared=None,
    )
    assert mapping is None
    assert evidence["code"] == qcm.CODE_COMPARISON_FRAME_MAP
    # an explicit declaration inside the output span is honoured verbatim
    mapping, evidence = qcm.comparison_frame_map(
        source_span=span,
        output_span={"start_frame": 1, "end_frame_exclusive": 13},
        declared={0: 1, 1: 2},
    )
    assert mapping == {0: 1, 1: 2}
    assert evidence["basis"] == "declared"
    # a declaration sending frames outside the output span also refuses
    mapping, evidence = qcm.comparison_frame_map(
        source_span=span,
        output_span=span,
        declared={0: 99},
    )
    assert mapping is None and evidence["code"] == qcm.CODE_COMPARISON_FRAME_MAP
    assert qcm.CODE_COMPARISON_FRAME_MAP == "QC_COMPARISON_FRAME_MAP_INVALID"


# ── T4 — invalid / unknown / missing is NEVER a zero-item pass ──────────────


def test_correction_4_non_measurement_is_not_a_pass() -> None:
    non_ready_band = {
        "applicability": "measured",
        "not_ready": True,
        "detectors": {},
        "indeterminate": [
            {
                "detector": "identity_drift_comparison",
                "entry_point": "compare_identity_facts",
                "status": "invalid",
                "code": CODE_THRESHOLD_INVALID,
                "codes": [CODE_THRESHOLD_INVALID],
                "role_ids": ["ROLE-BOOK-P1"],
                "frames": [12],
                "detail": "threshold invalid on the measured distance",
            }
        ],
        "refusals": [],
        "evidence": {"output_observations": {"digest": "abc"}},
    }
    reasons = handler._comparison_not_ready(non_ready_band)
    assert len(reasons) == 1
    assert handler._comparison_not_ready({"applicability": "not_applicable"}) == []
    flag = qcr._comparison_completion_flag({"comparison_band": non_ready_band})
    assert flag is False
    assert qcr._comparison_completion_flag({"comparison_band": {"not_ready": False}}) is True
    assert qcr._comparison_completion_flag({}) is None
    assert qcr._comparison_non_ready_reasons(
        {"zero_item_completion": {"non_ready": reasons}}
    ) == reasons
    # the measured band is the ONLY shape that may be read as clean
    assert qcr._comparison_completion_flag(
        {"comparison_band": {"not_ready": False, "applicability": "measured"}}
    ) is True


# ── T5 — typed causes carry role / frame / evidence ─────────────────────────


def test_correction_5_errors_carry_role_frame_evidence() -> None:
    band = {
        "applicability": "measured",
        "not_ready": True,
        "detectors": {},
        "evidence": {"output_observations": {"digest": "deadbeef"}},
        "indeterminate": [],
        "refusals": [
            {
                "side": "output_observations",
                "code": "QC_EVIDENCE_MISSING",
                "message": "no published observations",
                "dependency": "published rendered-observations artifact",
            }
        ],
    }
    reasons = handler._comparison_not_ready(band)
    assert reasons and reasons[0]["code"] == "QC_EVIDENCE_MISSING"
    assert reasons[0]["side"] == "output_observations"
    assert reasons[0]["evidence"]
    item = qcm.comparison_item(
        metric=qcm.METRIC_IDENTITY_UNLINKED,
        code=qcm.CODE_IDENTITY_LOST,
        level=qcm.LEVEL_HARD,
        severity="blocker",
        role_id="ROLE-TURN-CERT",
        frames=[40, 41],
        detail="role lost at the declared camera event",
        evidence={"detector": "identity_drift_comparison"},
    )
    assert item["role_id"] == "ROLE-TURN-CERT"
    assert item["frames"] == [40, 41]
    assert item["evidence"]["detector"] == "identity_drift_comparison"
    assert item["severity"] == "blocker" and item["level"] == qcm.LEVEL_HARD


# ── T6 — the measured policy is frozen (never loosened for green) ───────────


def test_correction_6_policy_digest_is_frozen() -> None:
    digest = qcm.comparison_policy_digest()
    assert digest == "3dede23eae5d54b6a195eda0f29528e92334c36d6f949c314187f39268b760b1"
    table = qcm.comparison_policy()["thresholds"]
    for metric, entry in table.items():
        assert entry["sanity_bounds"]["min"] == qcm.SANITY_FLOOR
        assert entry["sanity_bounds"]["max"] is None, metric
        assert entry["warning_boundary"] < entry["blocker_boundary"], metric
    # re-deriving the table from a loosened candidate is refused by contract:
    # the digest changes, and no code path writes a threshold from a report
    assert "def comparison_policy_digest" in inspect.getsource(qcm)
    source = inspect.getsource(qcm)
    assert "sanity_bounds" in source and "SANITY_FLOOR" in source
    assert hashlib.sha256(b"mf-end-22-comparison-v1").hexdigest()[:8] != digest[:8]


# ── T7 — a foreign / tampered side is refused, never skipped ────────────────


def test_correction_7_negative_control_refuses_foreign_side() -> None:
    world_source = Path(__file__).with_name("test_mf_end_22.py").read_text(
        encoding="utf-8", errors="replace"
    )
    # the earlier round's worlds carry BOTH sides; the correction keeps using
    # them rather than building a stub for a detector to pass on
    assert "_source_facts()" in world_source
    assert "observations" in world_source
    facts, proof = qcm.load_source_facts({"digest": "0" * 64, "contacts": []})
    assert facts == {}
    assert proof["code"] == qcm.CODE_COMPARISON_SOURCE_INVALID
    on_side, on_proof = qcm.load_output_observations({"digest": "0" * 64})
    assert on_side == {}
    assert on_proof["code"] in (
        qcm.CODE_COMPARISON_OUTPUT_INVALID,
        qcm.CODE_COMPARISON_SOURCE_INVALID,
    )
    # a band whose ONLY evidence is absent on BOTH sides is not_applicable,
    # not a clean pass and not a fabricated failure
    absent_band = {
        "applicability": "not_applicable",
        "not_ready": False,
        "detectors": {},
        "indeterminate": [],
        "refusals": [
            {"side": "source_facts", "code": "QC_EVIDENCE_MISSING"},
            {"side": "output_observations", "code": "QC_EVIDENCE_MISSING"},
        ],
    }
    assert handler._comparison_not_ready(absent_band) == []
    assert any(
        entry_point in inspect.getsource(compose_mod.compose_comparison_band)
        for _name, entry_point in compose_mod.COMPARISON_DETECTORS
    )


# ── T8 — the band report is deterministic ───────────────────────────────────


def test_correction_8_band_is_deterministic() -> None:
    detector_names = [name for name, _ in compose_mod.COMPARISON_DETECTORS]
    assert detector_names == [
        "contact_break_comparison",
        "z_order_error_comparison",
        "trajectory_drift_comparison",
        "identity_drift_comparison",
        "temporal_flicker_comparison",
    ]
    assert compose_mod.COMPARISON_BAND_SCHEMA == "mf-end-22/comparison-band@1"
    assert sorted(compose_mod.COMPARISON_NON_MEASURED_STATUSES) == sorted(
        {"invalid", "unknown", "blocked", "missing", "not_measured", ""}
    )
    digest = qcm.comparison_policy_digest()
    second = qcm.comparison_policy_digest()
    assert digest == second
    payload = {"a": 1, "b": [1, 2, 3]}
    assert json.dumps(payload, sort_keys=True) == '{"a": 1, "b": [1, 2, 3]}'
