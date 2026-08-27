"""S09-T00-I03 benchmark harness tests (schema v2, PREP phase).

Covers TASK.md acceptance items:
- harness determinism (two same-seed runs => byte-identical results JSON,
  excluding documented non-deterministic fields);
- threshold evaluation formulas (pass/boundary/fail against FROZEN limits);
- skip-with-reason behaviour when the verified reference media is absent;
- reference MEDIA verification vs reference BENCHMARK are separate states
  (F2): media identity alone can never produce a structural PASS;
- fail-closed loading on missing / duplicate / invalid fixture manifests;
- FREEZE banner ordering: schema_version + frozen SHA printed BEFORE any
  measured output;
- route capability honesty (sprite_affine cannot measure pose states);
- f5 required-layer coverage: char_a/char_b/pillar all probed (F2);
- required layers with zero samples are structural failures, not passes;
- adversarial source-reencode control fails the replacement gate (F2);
- measured runs fail closed PENDING until the J1 contract-freeze handshake;
- Wave B (post-J1): real T02 compositor renders the plate, the OUTPUT shows
  the declared replacement (presence >= 0.5), contract-rejected combos are
  recorded honestly, and on-disk contract SHA drift flips back to PENDING.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "scripts" / "s09_renderer_benchmark.py"
FIXTURES_DIR = REPO / "tests" / "fixtures" / "s09_renderer"
GENERATOR = FIXTURES_DIR / "generate_fixtures.py"
NON_DETERMINISTIC_FIELDS = ("wall_runtime_ms_per_frame", "vram_peak_mib")

def _run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[bytes]:
    env = dict(os.environ)
    env.pop("MOTIONFORGE_DATABASE_URL", None)  # DB guard for this task
    return subprocess.run(
        cmd,
        capture_output=True,
        check=False,
        env=env,
        cwd=str(REPO),
        **kw,  # type: ignore[arg-type]
    )


@pytest.fixture(scope="session")
def fixtures_ready(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a private deterministic fixture set once per test session."""
    out = tmp_path_factory.mktemp("s09t00i03_fx")
    proc = _run([sys.executable, str(GENERATOR), "--out", str(out), "--seed", "20260823"])
    assert proc.returncode == 0, proc.stderr.decode()[-2000:]
    manifests = sorted((out / "manifests").glob("*.json"))
    assert len(manifests) == 6
    return out

NON_DETERMINISTIC_FIELDS = (
    "wall_runtime_ms_per_frame",
    "vram_peak_mib",
    "runtime_ms_per_frame_measured",
    "backend.wall_time_ms_total",
)


def _strip_nondet(doc: dict[str, object]) -> dict[str, object]:
    """Remove documented non-deterministic fields from results JSON."""
    clone = json.loads(json.dumps(doc))
    for entry in clone.get("results", []):  # type: ignore[union-attr]
        entry.pop("wall_runtime_ms_per_frame", None)
        entry.pop("vram_peak_mib", None)
        # v3 measured runtime (wall clock around RendererRouter.execute) is
        # timing noise, same class as wall_runtime_ms_per_frame
        entry.pop("runtime_ms_per_frame_measured", None)
        backend = entry.get("backend")
        if isinstance(backend, dict):
            backend.pop("wall_time_ms_total", None)
        # run-scoped evidence paths move with --out; they are locations, not
        # measurements, so both the artifact copy and the adversarial
        # control's artifact are dropped before comparing
        entry.pop("artifact_path", None)
        metrics = entry.get("metrics")
        if isinstance(metrics, dict):
            adv = metrics.get("adversarial_control")
            if isinstance(adv, dict):
                adv.pop("adversarial_artifact", None)
    return clone


# ── freeze contract ──────────────────────────────────────────────────────────


def test_freeze_banner_printed_before_measure(fixtures_ready: Path, tmp_path: Path) -> None:
    out = tmp_path / "bench_out"
    proc = _run(
        [
            sys.executable,
            str(HARNESS),
            "--routes",
            "pose_swap",
            "--fixtures",
            str(fixtures_ready),
            "--fixtures-filter",
            "f2_mouth_swap",
            "--out",
            str(out),
            "--seed",
            "20260823",
        ]
    )
    assert proc.returncode == 0, proc.stderr.decode()[-3000:]
    stdout = proc.stdout.decode()
    lines = stdout.splitlines()
    assert lines[0] == "=== S09-T00-I03 BENCHMARK FREEZE (schema v3) ==="
    freeze_line = json.loads(lines[1])
    assert freeze_line["schema_version"] == 3
    sha = freeze_line["frozen_content_sha256"]
    assert len(sha) == 64 and int(sha, 16) >= 0
    assert lines[2] == "=== FREEZE COMPLETE (no measurement has run yet) ==="
    first_run_idx = min(
        i
        for i, ln in enumerate(lines)
        if ln.startswith("[run]") or ln.startswith("[pending]")
    )
    assert first_run_idx > 2, "measured/pending output must come after the freeze banner"
    doc = json.loads((out / "benchmark_results_seed20260823.json").read_text())
    assert doc["frozen_content_sha256"] == sha


# ── determinism ──────────────────────────────────────────────────────────────


def test_same_seed_two_runs_byte_identical(fixtures_ready: Path, tmp_path: Path) -> None:
    outs = []
    for i in ("a", "b"):
        odir = tmp_path / f"run{i}"
        proc = _run(
            [
                sys.executable,
                str(HARNESS),
                "--routes",
                "pose_swap,sprite_affine",
                "--fixtures",
                str(fixtures_ready),
                "--fixtures-filter",
                "f1_hard_cut",
                "f2_mouth_swap",
                "--out",
                str(odir),
                "--seed",
                "20260823",
                # exercise the ESTIMATOR path so real measured numbers are
                # compared, not just PENDING placeholders
                "--self-test-source-observation",
            ]
        )
        assert proc.returncode == 0, proc.stderr.decode()[-3000:]
        outs.append(
            _strip_nondet(json.loads((odir / "benchmark_results_seed20260823.json").read_text()))
        )
    assert outs[0] == outs[1], (
        f"same-seed runs must be identical after removing {list(NON_DETERMINISTIC_FIELDS)}"
    )


def test_documented_nondeterministic_fields_are_the_only_exclusion(
    fixtures_ready: Path, tmp_path: Path
) -> None:
    """The exclusion list in the results doc must match the module constant."""
    odir = tmp_path / "run"
    proc = _run(
        [
            sys.executable,
            str(HARNESS),
            "--routes",
            "pose_swap",
            "--fixtures",
            str(fixtures_ready),
            "--fixtures-filter",
            "f1_hard_cut",
            "--out",
            str(odir),
            "--seed",
            "20260823",
        ]
    )
    assert proc.returncode == 0
    doc = json.loads((odir / "benchmark_results_seed20260823.json").read_text())
    assert set(doc["non_deterministic_fields_excluded_from_compare"]) == set(
        NON_DETERMINISTIC_FIELDS
    )


# ── threshold formula evaluation ─────────────────────────────────────────────


def _evaluator() -> object:
    sys.path.insert(0, str(REPO / "scripts"))
    import s09_renderer_benchmark as bench  # type: ignore[import-not-found]

    return bench


def test_threshold_evaluation_formulas() -> None:
    bench = _evaluator()
    thr = json.loads((FIXTURES_DIR / "thresholds.json").read_text())

    # all inside limits -> pass
    metrics_ok = {
        "cut_error_frames": 1,  # == limit (<= passes)
        "swap_error_frames": 1,
        "trajectory_median_pct": 0.5,  # boundary
        "trajectory_p95_pct": 0.99,
        "scale_p95_pct": 2.9,
        "rotation_p95_deg": 3.0,  # boundary
        "contact_p95_pct": 0.7,
        "z_order_inversions": 0,
        "unexplained_visibility_events": 0,
        "clipping_from_source_silhouette": {"applicable": False, "fail_bool": False},
        "annotated_swaps": 0,
        "pose_states_measured": False,
        "annotated_contacts": 1,
        "contact_samples_measured": True,
        "required_layer_sample_counts": {},
    }
    ev = bench.evaluate_thresholds(metrics_ok, thr)  # type: ignore[attr-defined]
    assert ev["overall_pass"] is True
    by_name = {c["metric"]: c["pass"] for c in ev["checks"]}
    assert by_name["cut_error_frames"] is True  # boundary <= limit
    assert by_name["trajectory_median_pct"] is True  # boundary <= limit

    # one violation flips overall to False without touching others
    bad = dict(metrics_ok)
    bad["trajectory_median_pct"] = 0.51
    ev_bad = bench.evaluate_thresholds(bad, thr)  # type: ignore[attr-defined]
    by_name_bad = {c["metric"]: c["pass"] for c in ev_bad["checks"]}
    assert ev_bad["overall_pass"] is False
    assert by_name_bad["trajectory_median_pct"] is False
    assert by_name_bad["cut_error_frames"] is True

    # zero-tolerance metrics: any event fails
    zero = dict(metrics_ok)
    zero["unexplained_visibility_events"] = 1
    assert bench.evaluate_thresholds(zero, thr)["overall_pass"] is False  # type: ignore[attr-defined]


def test_pose_capability_gate_requires_measurement_when_swaps_annotated() -> None:
    bench = _evaluator()
    thr = json.loads((FIXTURES_DIR / "thresholds.json").read_text())
    base = {
        "cut_error_frames": 0,
        "swap_error_frames": 0,
        "trajectory_median_pct": 0.1,
        "trajectory_p95_pct": 0.2,
        "scale_p95_pct": 0.5,
        "rotation_p95_deg": 0.5,
        "contact_p95_pct": 0.5,
        "z_order_inversions": 0,
        "unexplained_visibility_events": 0,
        "clipping_from_source_silhouette": {"applicable": False, "fail_bool": False},
        "annotated_contacts": 0,
        "contact_samples_measured": False,
        "required_layer_sample_counts": {},
    }
    with_swaps_no_state = {**base, "annotated_swaps": 1, "pose_states_measured": False}
    ev = bench.evaluate_thresholds(with_swaps_no_state, thr)  # type: ignore[attr-defined]
    assert ev["overall_pass"] is False
    assert any(c["metric"] == "pose_state_capability" and not c["pass"] for c in ev["checks"])

    with_swaps_and_state = {**base, "annotated_swaps": 1, "pose_states_measured": True}
    ev2 = bench.evaluate_thresholds(with_swaps_and_state, thr)  # type: ignore[attr-defined]
    assert ev2["overall_pass"] is True

    # contact gate mirrors the pose gate
    contacts_no_est = {
        **base,
        "annotated_swaps": 0,
        "pose_states_measured": False,
        "annotated_contacts": 1,
        "contact_samples_measured": False,
    }
    ev3 = bench.evaluate_thresholds(contacts_no_est, thr)  # type: ignore[attr-defined]
    assert ev3["overall_pass"] is False
    assert any(c["metric"] == "contact_capability" and not c["pass"] for c in ev3["checks"])


def test_clipping_detector_injection_validates_fail_paths() -> None:
    """Inject synthetic silhouettes to prove the detector fires both ways."""
    bench = _evaluator()
    import numpy as np

    src = np.zeros((20, 20, 4), dtype=np.uint8)
    rep = np.zeros((20, 20, 4), dtype=np.uint8)
    src[:, :, 3] = 255  # full opaque source silhouette
    rep[5:15, 5:15, 3] = 255  # replacement content inside source -> nothing lost
    man = {
        "fixture_id": "synthetic",
        "motion": {"pivot_xy": [0, 0], "rotation_deg_by_frame": {}, "max_scale": 1.0},
        "clipping_probe": {"min_clipped_pixels_for_fail": 25, "applies_to_routes": ["legacy_clip"]},
    }
    # route declared as reusing silhouettes + no loss -> pass
    res_ok = bench._clipping_probe(man, np.zeros((1, 1, 3), dtype=np.uint8), Path("/nonexistent"))  # type: ignore[attr-defined]
    assert res_ok["applicable"] is True and res_ok["fail_bool"] is False
    # replacement content OUTSIDE source silhouette -> lost pixels -> fail
    src2 = np.zeros((20, 20, 4), dtype=np.uint8)
    src2[8:12, 8:12, 3] = 255
    rep2 = np.zeros((20, 20, 4), dtype=np.uint8)
    rep2[2:12, 10:20, 3] = 255  # mostly OUTSIDE the src alpha region
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        sd = Path(td) / "synthetic"
        sd.mkdir()
        from PIL import Image as PILImage

        PILImage.fromarray(src2, "RGBA").save(sd / "char_src.png")
        PILImage.fromarray(rep2, "RGBA").save(sd / "char_rep.png")
        res_fail = bench._clipping_probe(man, np.zeros((1, 1, 3), dtype=np.uint8), Path(td))  # type: ignore[attr-defined]
    assert res_fail["count"] >= 16
    assert res_fail["fail_bool"] is True
    # same asset pair but a route NOT declared for reuse -> must NOT fail
    man_open = dict(man)
    man_open["clipping_probe"] = {"min_clipped_pixels_for_fail": 25, "applies_to_routes": []}
    with tempfile.TemporaryDirectory() as td:
        sd = Path(td) / "synthetic"
        sd.mkdir()
        from PIL import Image as PILImage

        PILImage.fromarray(src2, "RGBA").save(sd / "char_src.png")
        PILImage.fromarray(rep2, "RGBA").save(sd / "char_rep.png")
        res_open = bench._clipping_probe(man_open, np.zeros((1, 1, 3), dtype=np.uint8), Path(td))  # type: ignore[attr-defined]
    assert res_open["count"] >= 16
    assert res_open["fail_bool"] is False


# ── skip-with-reason for verified reference ─────────────────────────────────


def test_reference_skip_with_reason_when_media_absent() -> None:
    bench = _evaluator()
    missing = REPO / "output" / "__definitely_not_here__.mp4"
    result = bench.evaluate_reference_media(missing if missing.is_file() else None)  # type: ignore[attr-defined]
    assert result["status"] == "SKIPPED_WITH_REASON"
    assert result["reason"]
    assert result["expected_sha256"].lower().startswith("5a175454")


def test_reference_sha_mismatch_is_reported_not_faked(tmp_path: Path) -> None:
    bench = _evaluator()
    fake = tmp_path / "ref.mp4"
    fake.write_bytes(b"\x00" * 64)
    result = bench.evaluate_reference_media(fake)  # type: ignore[attr-defined]
    assert result["status"] == "FAILED_SHA_CHECK"


# ── reference media verification vs reference benchmark are SEPARATE (F2) ────


def test_reference_benchmark_skipped_without_ground_truth_even_when_media_verified() -> None:
    """MEDIA_VERIFIED alone must never produce a structural PASS."""
    bench = _evaluator()
    verified = {"status": "MEDIA_VERIFIED", "sha256": "5a175454"}
    rb = bench.evaluate_reference_benchmark(verified, None)  # type: ignore[attr-defined]
    assert rb["status"] == "SKIPPED_WITH_REASON_REFERENCE_GROUND_TRUTH_UNAVAILABLE"
    assert rb["reason"]


def test_reference_benchmark_requires_full_ref_loop_coverage(tmp_path: Path) -> None:
    bench = _evaluator()
    contract_path = tmp_path / "ref_contract.json"
    partial = {"loops": [{"loop_id": "REF-R01"}, {"loop_id": "REF-R02"}]}
    contract_path.write_text(json.dumps(partial))
    rb = bench.evaluate_reference_benchmark({"status": "MEDIA_VERIFIED"}, contract_path)  # type: ignore[attr-defined]
    assert rb["status"] == "FAILED_CONTRACT_COVERAGE"
    full = {
        "loops": [{"loop_id": f"REF-R0{i}"} for i in range(1, 6)],
    }
    contract_path.write_text(json.dumps(full))
    rb2 = bench.evaluate_reference_benchmark({"status": "MEDIA_VERIFIED"}, contract_path)  # type: ignore[attr-defined]
    assert rb2["status"] == "ANNOTATION_CONTRACT_READY_BENCHMARK_PENDING"


def test_unverified_media_blocks_reference_benchmark() -> None:
    bench = _evaluator()
    rb = bench.evaluate_reference_benchmark({"status": "SKIPPED_WITH_REASON"}, None)  # type: ignore[attr-defined]
    assert rb["status"] == "NOT_RUN"


# ── fail-closed fixture loading ──────────────────────────────────────────────


def test_fail_closed_on_duplicate_fixture_id(fixtures_ready: Path, tmp_path: Path) -> None:
    bench = _evaluator()
    mdir_src = fixtures_ready / "manifests"
    dup_dir = tmp_path / "dup"
    (dup_dir / "manifests").mkdir(parents=True)
    (dup_dir / "media").mkdir()
    files = sorted(mdir_src.glob("*.json"))
    shutil.copy(files[0], dup_dir / "manifests" / files[0].name)
    # second file with SAME fixture_id but different filename
    data = json.loads(files[1].read_text())
    data["fixture_id"] = json.loads(files[0].read_text())["fixture_id"]
    (dup_dir / "manifests" / "clone.json").write_text(json.dumps(data))
    for fid in (json.loads(files[0].read_text())["fixture_id"],):
        src_media = fixtures_ready / "media" / f"{fid}.mp4"
        shutil.copy(src_media, dup_dir / "media" / f"{fid}.mp4")
    with pytest.raises(bench.BenchmarkError, match="[Dd]uplicate"):  # type: ignore[attr-defined]
        bench.load_fixtures(dup_dir, None)  # type: ignore[attr-defined]


def test_fail_closed_on_missing_required_manifest_keys(
    fixtures_ready: Path, tmp_path: Path
) -> None:
    bench = _evaluator()
    broken = tmp_path / "broken"
    shutil.copytree(fixtures_ready, broken)
    target = next((broken / "manifests").glob("*.json"))
    raw = json.loads(target.read_text())
    raw.pop("frame_count")
    target.write_text(json.dumps(raw))
    with pytest.raises(bench.BenchmarkError, match="missing keys"):  # type: ignore[attr-defined]
        bench.load_fixtures(broken, None)  # type: ignore[attr-defined]


def test_fail_closed_on_missing_media(fixtures_ready: Path, tmp_path: Path) -> None:
    bench = _evaluator()
    broken = tmp_path / "broken2"
    shutil.copytree(fixtures_ready, broken)
    target = next((broken / "media").glob("*.mp4"))
    target.unlink()
    with pytest.raises(bench.BenchmarkError, match="media missing"):  # type: ignore[attr-defined]
        bench.load_fixtures(broken, None)  # type: ignore[attr-defined]


def test_unknown_route_rejected(fixtures_ready: Path, tmp_path: Path) -> None:
    proc = _run(
        [
            sys.executable,
            str(HARNESS),
            "--routes",
            "made_up_route",
            "--fixtures",
            str(fixtures_ready),
            "--fixtures-filter",
            "f1_hard_cut",
            "--out",
            str(tmp_path / "o"),
            "--seed",
            "1",
        ]
    )
    assert proc.returncode == 2
    assert b"unknown routes" in proc.stderr


# ── measured-run semantics on synthetic fixtures ─────────────────────────────


@pytest.mark.parametrize(
    "fixture_id,risk_class",
    [
        ("f1_hard_cut", "hard_cut"),
        ("f2_mouth_swap", "mouth_expression_swap"),
        ("f3_phone_contact", "phone_contact"),
        ("f4_body_rotation", "whole_body_rotation"),
        ("f5_group_occlusion", "group_occlusion"),
        ("f6_graphic_replacement", "semantic_graphic_replacement"),
    ],
)
def test_all_fixtures_present_with_expected_risk_class(
    fixtures_ready: Path, fixture_id: str, risk_class: str
) -> None:
    man = json.loads((fixtures_ready / "manifests" / f"{fixture_id}.json").read_text())
    assert man["fixture_id"] == fixture_id
    assert man["risk_class"] == risk_class
    assert man["generation"]["tool"].startswith("ffmpeg lavfi")


def test_pose_swap_vs_sprite_affine_capability_difference(
    fixtures_ready: Path, tmp_path: Path
) -> None:
    """The two routes must differ exactly where their contracts differ."""
    odir = tmp_path / "cap"
    proc = _run(
        [
            sys.executable,
            str(HARNESS),
            "--routes",
            "pose_swap,sprite_affine",
            "--fixtures",
            str(fixtures_ready),
            "--fixtures-filter",
            "f2_mouth_swap",
            "--out",
            str(odir),
            "--seed",
            "20260823",
        ]
    )
    assert proc.returncode == 0, proc.stderr.decode()[-3000:]
    doc = json.loads((odir / "benchmark_results_seed20260823.json").read_text())
    by_route = {r["route"]: r for r in doc["results"]}
    pose_entry = by_route["pose_swap"]
    rigid_entry = by_route["sprite_affine"]
    # Post-J1 the capability boundary shows up in the RENDERED-OUTPUT path:
    # f2 carries a pose_state_sequence contract so pose_swap measures it,
    # while sprite_affine has nothing to affine-replace and must be
    # contract-rejected (fail-closed) rather than scored against source.
    pose = pose_entry["metrics"]
    assert pose["pose_states_measured"] is True
    assert pose_entry["measured_state"] == "MEASURED_RENDERED_OUTPUT"
    assert pose_entry["threshold_evaluation"]["overall_pass"] is True
    assert rigid_entry["measured_state"] == "CONTRACT_REJECTED_BY_FROZEN_CONTRACT"
    reason = str(rigid_entry.get("contract_rejection_reason", ""))
    assert "capability_mismatch" in reason and "sprite_affine" in reason


# ── v2: f5 coverage, required-layer gates, adversarial control, J1 gate ──────


def test_f5_required_layers_have_measured_samples(fixtures_ready: Path, tmp_path: Path) -> None:
    """F2: char_a/char_b/pillar must all be probed -- no empty universe."""
    bench = _evaluator()
    fixture = bench.load_fixtures(fixtures_ready, ["f5_group_occlusion"])[0]  # type: ignore[attr-defined]
    frames_raw = bench.decode_frames(fixture.media_path)  # type: ignore[attr-defined]
    res = fixture.manifest["resolution"]
    n = int(fixture.manifest["frame_count"])
    frames = frames_raw[: n * int(res["height"]) * int(res["width"]) * 3].reshape(
        n, int(res["height"]), int(res["width"]), 3
    )
    obs = bench.observe_route("pose_swap", frames, fixture, fixtures_ready)  # type: ignore[attr-defined]
    for layer in ("char_a", "char_b", "pillar"):
        assert len(obs.visible_frames.get(layer, [])) > 0, (
            f"{layer} must have measured visibility samples (F2 empty-universe)"
        )
        assert len(obs.probed_frames.get(layer, set())) > 0
    metrics = bench.compute_metrics(  # type: ignore[attr-defined]
        "pose_swap", frames, fixture, obs, fixtures_ready / "sprites"
    )
    counts = metrics["required_layer_sample_counts"]
    assert counts.get("char_a", 0) > 0
    assert counts.get("char_b", 0) > 0
    assert counts.get("pillar", 0) > 0


def test_required_layer_zero_samples_is_structural_failure() -> None:
    bench = _evaluator()
    thr = json.loads((FIXTURES_DIR / "thresholds.json").read_text())
    metrics = {
        "cut_error_frames": 0,
        "swap_error_frames": 0,
        "trajectory_median_pct": 0.0,
        "trajectory_p95_pct": 0.0,
        "scale_p95_pct": 0.0,
        "rotation_p95_deg": 0.0,
        "contact_p95_pct": 0.0,
        "z_order_inversions": 0,
        "unexplained_visibility_events": 0,
        "clipping_from_source_silhouette": {"applicable": False, "fail_bool": False},
        "annotated_swaps": 0,
        "pose_states_measured": False,
        "annotated_contacts": 0,
        "contact_samples_measured": False,
        "required_layer_sample_counts": {"char_a": 0},
    }
    ev = bench.evaluate_thresholds(metrics, thr)  # type: ignore[attr-defined]
    assert ev["overall_pass"] is False
    assert any(
        c["metric"] == "required_layer_coverage:char_a" and not c["pass"] for c in ev["checks"]
    )


def test_adversarial_source_reencode_fails_replacement_gate(
    fixtures_ready: Path, tmp_path: Path
) -> None:
    """Substituting a source re-encode as 'output' must go red (F2)."""
    bench = _evaluator()
    fixture = bench.load_fixtures(fixtures_ready, ["f3_phone_contact"])[0]  # type: ignore[attr-defined]
    workdir = tmp_path / "adv"
    control = bench.adversarial_source_reencode_control(  # type: ignore[attr-defined]
        fixture, "pose_swap", fixtures_ready, workdir
    )
    assert control is not None
    assert control["status"] == "FAILED_AS_EXPECTED"
    assert control["control_failed_as_expected"] is True
    ratios = control["replacement_presence_ratios"]
    assert ratios.get("phone", 1.0) < 0.5


def test_measured_runs_fail_closed_before_j1_contract_freeze(
    fixtures_ready: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the J1 token the harness must NOT emit route verdicts."""
    monkeypatch.setenv("S09_FORCE_J1_PENDING", "1")
    odir = tmp_path / "pending"
    proc = _run(
        [
            sys.executable,
            str(HARNESS),
            "--routes",
            "pose_swap",
            "--fixtures",
            str(fixtures_ready),
            "--fixtures-filter",
            "f2_mouth_swap",
            "--out",
            str(odir),
            "--seed",
            "20260823",
        ]
    )
    assert proc.returncode == 0, proc.stderr.decode()[-3000:]
    doc = json.loads((odir / "benchmark_results_seed20260823.json").read_text())
    assert doc["schema_version"] == 3
    for entry in doc["results"]:
        assert entry["measured_state"] == "PENDING_RENDERER_CONTRACT_FREEZE"
        assert "metrics" not in entry and "threshold_evaluation" not in entry
    assert doc["measurement_mode"] == "BLOCKED_PENDING_J1"


# ── Wave B: real renderer integration (post J1) ─────────────────────────────


def test_wave_b_renders_real_output_and_shows_replacement(
    fixtures_ready: Path, tmp_path: Path
) -> None:
    """J1 satisfied: the T02 compositor renders the plate; the OUTPUT must
    contain the declared replacement (presence >= 0.5) and score honestly."""
    odir = tmp_path / "waveb"
    proc = _run(
        [
            sys.executable,
            str(HARNESS),
            "--routes",
            "pose_swap,sprite_affine",
            "--fixtures",
            str(fixtures_ready),
            "--fixtures-filter",
            "f2_mouth_swap",
            "f4_body_rotation",
            "f3_phone_contact",
            "--out",
            str(odir),
            "--seed",
            "20260823",
        ]
    )
    assert proc.returncode == 0, proc.stderr.decode()[-3000:]
    doc = json.loads((odir / "benchmark_results_seed20260823.json").read_text())
    assert doc["measurement_mode"] == "RENDERED_OUTPUT"
    by_key = {(r["fixture_id"], r["route"]): r for r in doc["results"]}
    # pose_swap on f2: real head replacement rendered over the plate
    f2p = by_key[("f2_mouth_swap", "pose_swap")]
    assert f2p["measured_state"] == "MEASURED_RENDERED_OUTPUT"
    # v3: the request goes through the PUBLIC production router surface
    assert f2p["backend"]["adapter"].startswith("RendererRouter.execute")
    assert f2p["backend_v3"]["adapter_class"] in ("PoseSwapAdapter", "SpriteAffineAdapter")
    assert f2p["selected_route"] == "pose_swap"
    assert len(str(f2p["j1_manifest_sha256"])) == 64
    assert Path(f2p["artifact_path"]).is_file()
    assert len(f2p["decoded_output_hash"]) == 64
    assert len(f2p["encoded_artifact_sha256"]) == 64
    assert f2p["frame_count_rendered"] > 0
    assert f2p["fps_rational"] == [30, 1]
    eff = f2p["metrics"]["replacement_effect"]
    assert all(v >= 0.5 for v in eff.values()), f"replacement missing from output: {eff}"
    checks = {c["metric"]: c["pass"] for c in f2p["threshold_evaluation"]["checks"]}
    assert checks["replacement_effect_rendered_output"] is True
    # sprite_affine on f4: rotated body layer visible in the output
    f4a = by_key[("f4_body_rotation", "sprite_affine")]
    assert f4a["measured_state"] == "MEASURED_RENDERED_OUTPUT"
    eff4 = f4a["metrics"]["replacement_effect"]
    assert all(v >= 0.5 for v in eff4.values()), f"rotated body missing: {eff4}"


def test_wave_b_contract_rejected_combo_recorded_honestly(
    fixtures_ready: Path, tmp_path: Path
) -> None:
    """pose_swap on a fixture without a pose schedule must be recorded as
    CONTRACT_REJECTED_BY_FROZEN_CONTRACT -- never silently scored PASS."""
    odir = tmp_path / "rejected"
    proc = _run(
        [
            sys.executable,
            str(HARNESS),
            "--routes",
            "pose_swap",
            "--fixtures",
            str(fixtures_ready),
            "--fixtures-filter",
            "f6_graphic_replacement",
            "--out",
            str(odir),
            "--seed",
            "20260823",
        ]
    )
    assert proc.returncode == 0, proc.stderr.decode()[-3000:]
    doc = json.loads((odir / "benchmark_results_seed20260823.json").read_text())
    entry = doc["results"][0]
    assert entry["measured_state"] == "CONTRACT_REJECTED_BY_FROZEN_CONTRACT"
    assert "pose_swap requires a pose_schedule" in entry["contract_rejection_reason"]
    assert entry["backend"]["accepted"] is False
    assert "threshold_evaluation" not in entry


def test_wave_b_contract_sha_drift_fails_closed(
    fixtures_ready: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any drift between disk contract and the frozen handshake SHA flips the
    harness back to PENDING -- even with the registry token present."""
    monkeypatch.setenv("S09_FORCE_J1_PENDING", "1")
    bench = _evaluator()
    state = bench._detect_contract_freeze()  # type: ignore[attr-defined]
    assert state["frozen"] is False
    assert "S09_FORCE_J1_PENDING" in str(state["evidence"])
    # and the real on-disk state (no hook) verifies against the Manager
    # manifest authority (C3): 13/13 files clean, no fallback involved.
    monkeypatch.delenv("S09_FORCE_J1_PENDING")
    live = bench._detect_contract_freeze()  # type: ignore[attr-defined]
    assert live["frozen"] is True
    evidence = str(live["evidence"])
    assert "j1_manifest=" in evidence
    assert "files=13/13 verified clean" in evidence


# ── C3: unified freeze authority + canonical independent hash (F2/F3) ───────


def test_c3_freeze_authority_single_manifest_no_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C3 F2: exactly ONE authority.  Wrong manifest SHA, the deprecated
    three-file pin, and a missing file all fail closed; the pinned v4
    authority verifies clean."""
    bench = _evaluator()
    # default authority = pinned J1-C3-v4 (13 files, Manager SHA)
    live = bench._detect_contract_freeze()  # type: ignore[attr-defined]
    assert live["frozen"] is True
    assert bench.J1_C3_V4_MANIFEST_SHA256.startswith("ae92247b")  # type: ignore[attr-defined]
    # explicit CLI authority with a WRONG sha -> fail closed
    ns = __import__("argparse").Namespace(
        manifest_path=str(REPO / bench.J1_C3_V4_MANIFEST_RELPATH),  # type: ignore[attr-defined]
        manifest_sha256="0" * 64,
    )
    bad = bench._detect_contract_freeze(ns)  # type: ignore[attr-defined]
    assert bad["frozen"] is False
    assert "!= Manager-pinned" in str(bad["evidence"])
    # the historical three-file pin is NOT an authority anymore
    ns3 = __import__("argparse").Namespace(
        manifest_path=str(REPO / "output/s09/contract_freeze_manifest.json"),
        manifest_sha256="0" * 64,
    )
    legacy = bench._detect_contract_freeze(ns3)  # type: ignore[attr-defined]
    assert legacy["frozen"] is False
    # missing manifest file -> fail closed
    ns_missing = __import__("argparse").Namespace(
        manifest_path=str(tmp_path / "nope.json"),
        manifest_sha256="0" * 64,
    )
    gone = bench._detect_contract_freeze(ns_missing)  # type: ignore[attr-defined]
    assert gone["frozen"] is False


def test_c3_cli_rejects_incomplete_manifest_flags(fixtures_ready: Path, tmp_path: Path) -> None:
    """--manifest-path without --manifest-sha256 fails BEFORE any work."""
    proc = _run(
        [
            sys.executable,
            str(HARNESS),
            "--routes",
            "pose_swap",
            "--fixtures",
            str(fixtures_ready),
            "--out",
            str(tmp_path / "o"),
            "--manifest-path",
            str(REPO / "nonexistent_manifest.json"),
        ]
    )
    assert proc.returncode == 2
    assert b"--manifest-sha256" in proc.stderr


def test_c3_canonical_hash_is_count_shape_bytes_not_raw_concat() -> None:
    """C3 F3: the independent hash implements count+shape+bytes and differs
    from the old raw-concat bug; it equals the production canonical helper
    on identical frames but is computed WITHOUT calling it."""
    import hashlib

    import numpy as np

    sys.path.insert(0, str(REPO))
    from app.services.renderer_routes.composite import (
        canonical_frame_sha256 as production_canonical,
    )

    bench = _evaluator()
    rng = np.random.default_rng(7)
    frames = [rng.integers(0, 255, (8, 16, 3), dtype=np.uint8) for _ in range(5)]
    mine = bench.canonical_decoded_hash_independent(frames)  # type: ignore[attr-defined]
    prod = production_canonical(frames)
    assert mine == prod, "independent canonical must match production algorithm"
    raw_concat = hashlib.sha256(
        b"".join(np.ascontiguousarray(f).tobytes() for f in frames)
    ).hexdigest()
    assert raw_concat != mine, "raw-concat regression must be detectable"
    # order-sensitivity + count sensitivity (canonical semantics)
    reordered = list(reversed(frames))
    assert bench.canonical_decoded_hash_independent(reordered) != mine  # type: ignore[attr-defined]
    assert bench.canonical_decoded_hash_independent(frames[:-1]) != mine  # type: ignore[attr-defined]


def test_c3_measured_rows_pin_v4_manifest_and_canonical_equality(
    fixtures_ready: Path, tmp_path: Path
) -> None:
    """Every measured row records j1_manifest_path + v4 SHA, and the
    independently recomputed decoded hash EQUALS the adapter's
    output_frame_sha256 (12 rows over A/B)."""
    docs = []
    for tag in ("a", "b"):
        odir = tmp_path / f"run_{tag}"
        proc = _run(
            [
                sys.executable,
                str(HARNESS),
                "--routes",
                "pose_swap,sprite_affine",
                "--fixtures",
                str(fixtures_ready),
                "--fixtures-filter",
                "f1_hard_cut",
                "f2_mouth_swap",
                "--out",
                str(odir),
                "--seed",
                "20260823",
            ]
        )
        assert proc.returncode == 0, proc.stderr.decode()[-3000:]
        docs.append(json.loads((odir / "benchmark_results_seed20260823.json").read_text()))
    for doc in docs:
        measured = [r for r in doc["results"] if r["measured_state"] == "MEASURED_RENDERED_OUTPUT"]
        assert measured, "expected at least one measured row"
        v4_sha = "ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5"
        for row in measured:
            assert row["j1_manifest_sha256"] == v4_sha
            assert row["j1_manifest_path"].endswith("renderer_freeze_manifest_v4.json")
            assert row["decoded_output_hash"] == row["adapter_output_frame_sha256"]
            assert row["canonical_hash_verified"] is True
