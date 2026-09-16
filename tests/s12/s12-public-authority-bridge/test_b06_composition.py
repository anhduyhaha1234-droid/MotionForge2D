"""B06 — worker composition + frozen-format per-layer evidence (D2 node IDs).

`_stitch_verified_chunks` composes ALL visible/occluded layers (never
dedup-to-first-artifact); real decoded regions/pixels prove both objects;
missing artifact/evidence fails closed with zero publication; frame count /
rational FPS preserved (no doubled timeline); voice policy unchanged (silent
engineering source — no fabricated audio).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import text

from conftest import (
    WS,
    authorized_manifest,
    build_graph,
    make_env,
    render_authority_for,
    submit_full_apply,
)

DBOX = {"x": 16.0, "y": 12.0, "w": 80.0, "h": 60.0}
DBOX2 = {"x": 56.0, "y": 20.0, "w": 60.0, "h": 48.0}


def _run_full(env, seed) -> str:
    resp = submit_full_apply(env, seed)
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    assert env.svc._worker.run_once() == 1
    return run_id


def _pub_rel(env, run_id: str) -> str:
    with env.factory() as s:
        row = s.execute(
            text(
                "SELECT a.relative_path FROM s10_full_apply_publication p "
                "JOIN artifact a ON a.id = p.artifact_id "
                "WHERE p.run_id=:r AND p.workspace_id=:w AND p.state='completed'"
            ),
            {"r": run_id, "w": WS},
        ).scalar()
    assert row, "completed publication required"
    return str(row)


def _sidecar(env, run_id: str) -> dict:
    rel = _pub_rel(env, run_id)
    ev = env.managed_root / (rel + ".evidence.json")
    assert ev.is_file(), f"sidecar missing: {ev}"
    return json.loads(ev.read_text(encoding="utf-8"))


def _two_layer_graph(env, monkeypatch):
    return build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        segments=[
            {"role": "r1", "start": 0, "end": 119, "box": DBOX, "z_order": 0},
            {"role": "r2", "start": 0, "end": 119, "box": DBOX2, "z_order": 1},
        ],
    )


def test_b06_stitch_composes_all_visible_layers_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.renderer_routes.composite import decode_rgb_frames

    env = make_env(tmp_path, monkeypatch)
    seed = _two_layer_graph(env, monkeypatch)
    run_id = _run_full(env, seed)
    out = decode_rgb_frames(env.managed_root / _pub_rel(env, run_id))
    src = decode_rgb_frames(env.managed_root / seed["source_rel"])
    assert len(out) == 120
    sidecar = _sidecar(env, run_id)
    per_layer = sidecar["per_layer_evidence"]
    assert len({r["layer_id"] for r in per_layer}) == 2
    # real decoded regions differ from the source region for BOTH layers
    for row in per_layer:
        if row["range"][0] != 0 or row["range"][1] != 47:
            continue
        f = 10
        x0, y0, x1, y1 = row["region_px"]
        src_crop = src[f][y0:y1, x0:x1].astype(int)
        out_crop = out[f][y0:y1, x0:x1].astype(int)
        assert float(np.abs(out_crop - src_crop).mean()) > 2.0, (
            f"layer {row['layer_id']} region not composed into final frames"
        )


def test_b06_per_layer_decoded_evidence_contribution_frozen_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = _two_layer_graph(env, monkeypatch)
    run_id = _run_full(env, seed)
    sidecar = _sidecar(env, run_id)
    rows = sidecar["per_layer_evidence"]
    assert rows
    required = {
        "shot_id",
        "range",
        "layer_id",
        "role_id",
        "route",
        "visibility",
        "z_order",
        "artifact_sha256",
        "artifact_size_bytes",
        "region_norm",
        "region_px",
        "sampled_frames",
        "region_crop_sha256_before",
        "region_crop_sha256_after",
        "final_crop_sha256",
        "changed_pixel_count",
        "changed_ratio",
        "threshold",
        "verdict",
    }
    for row in rows:
        assert required <= set(row), f"row missing fields: {required - set(row)}"
        assert row["threshold"] == 0.01
        assert row["verdict"] == "contributed"
        assert len(row["artifact_sha256"]) == 64
        assert row["region_crop_sha256_before"] != row["region_crop_sha256_after"]
        assert row["final_crop_sha256"]
        x0, y0, x1, y1 = row["region_px"]
        area = (x1 - x0) * (y1 - y0)
        expected_ratio = row["changed_pixel_count"] / float(area * len(row["sampled_frames"]))
        assert abs(row["changed_ratio"] - expected_ratio) < 1e-9
        assert row["visibility"] in ("visible", "occluded")
        assert row["sampled_frames"] == [row["range"][0]] or row["sampled_frames"] == row["range"]


def test_b06_no_dedup_first_layer_only_distinct_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = _two_layer_graph(env, monkeypatch)
    run_id = _run_full(env, seed)
    rows = _sidecar(env, run_id)["per_layer_evidence"]
    # the no-dedup proof: co-active units carry DISTINCT artifacts and each
    # unit's own before/after delta (first-layer-only dedup would show one
    # artifact and a no_delta second row)
    covering = [r for r in rows if r["range"][0] <= 10 <= r["range"][1]]
    assert len(covering) >= 2
    shas = [r["artifact_sha256"] for r in covering]
    assert len(set(shas)) == len(shas)
    for row in covering:
        assert row["region_crop_sha256_before"] != row["region_crop_sha256_after"]


def test_b06_occluded_layer_composed_before_occluder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        segments=[
            {
                "role": "r1",
                "start": 0,
                "end": 119,
                "box": DBOX,
                "z_order": 0,
                "visibility": "occluded",
            },
            {"role": "r2", "start": 0, "end": 119, "box": DBOX2, "z_order": 1},
        ],
    )
    run_id = _run_full(env, seed)
    rows = _sidecar(env, run_id)["per_layer_evidence"]
    occluded = [r for r in rows if r["visibility"] == "occluded"]
    assert occluded, "occluded layer must appear in evidence"
    for row in occluded:
        assert row["verdict"] == "contributed"  # its own step changed pixels
        # then legally overpainted by the later (higher-z) layer:
        assert row["final_crop_sha256"] != row["region_crop_sha256_after"], (
            "occluded layer's crop must document the overpaint result"
        )
    visible = [r for r in rows if r["visibility"] == "visible"]
    assert visible and all(r["verdict"] == "contributed" for r in visible)


def test_b06_missing_artifact_or_evidence_fails_closed_no_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.workflow.s10_full_apply_jobs as mod

    env = make_env(tmp_path, monkeypatch)
    seed = _two_layer_graph(env, monkeypatch)
    run_id = _run_full(env, seed)

    # direct stitch with REAL artifacts: baseline recompute succeeds…
    chunks = mod._list_chunks(env.factory, WS, run_id)
    assert chunks
    mod._stitch_verified_chunks(
        managed_root=env.managed_root,
        run_id=run_id,
        chunks=chunks,
        session_factory=env.factory,
        ws=WS,
        fps_num=30,
        fps_den=1,
        authority=render_authority_for(seed),
        manifest=authorized_manifest(seed),
        frame_count=120,
    )
    # …missing artifact (nulled id) fails closed…
    broken = [dict(c) for c in chunks]
    broken[0]["artifact_id"] = None
    with pytest.raises(mod.S10FullApplyJobError) as err1:
        mod._stitch_verified_chunks(
            managed_root=env.managed_root,
            run_id=run_id,
            chunks=broken,
            session_factory=env.factory,
            ws=WS,
            fps_num=30,
            fps_den=1,
            authority=render_authority_for(seed),
            manifest=authorized_manifest(seed),
            frame_count=120,
        )
    assert "STITCH_LAYER_ARTIFACT_MISSING" in str(err1.value)
    # …a dropped unit (missing range coverage) fails closed too.
    with pytest.raises(mod.S10FullApplyJobError) as err2:
        mod._stitch_verified_chunks(
            managed_root=env.managed_root,
            run_id=run_id,
            chunks=[dict(c) for c in chunks[1:]],
            session_factory=env.factory,
            ws=WS,
            fps_num=30,
            fps_den=1,
            authority=render_authority_for(seed),
            manifest=authorized_manifest(seed),
            frame_count=120,
        )
    assert "STITCH_LAYER_ARTIFACT_MISSING" in str(err2.value)

    # end-to-end fail-closed flow: a stitch failure leaves NO publication.
    env2 = make_env(tmp_path / "flow", monkeypatch)
    seed2 = _two_layer_graph(env2, monkeypatch)
    resp = submit_full_apply(env2, seed2)
    assert resp.status_code == 202, resp.text
    run2 = resp.json()["run_id"]

    def _boom(**_kwargs):
        raise mod.S10FullApplyJobError("STITCH_LAYER_EVIDENCE_MISSING: simulated no_delta")

    monkeypatch.setattr(mod, "_stitch_verified_chunks", _boom)
    assert env2.svc._worker.run_once() == 1
    with env2.factory() as s:
        status = s.execute(
            text("SELECT status FROM s10_full_apply_run WHERE id=:r"), {"r": run2}
        ).scalar()
        pubs = s.execute(
            text("SELECT COUNT(*) FROM s10_full_apply_publication WHERE run_id=:r"),
            {"r": run2},
        ).scalar()
    assert status == "failed"
    assert int(pubs) == 0


def test_b06_frame_count_rational_fps_preserved_no_double_timeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.renderer_routes.composite import decode_rgb_frames

    env = make_env(tmp_path, monkeypatch)
    seed = _two_layer_graph(env, monkeypatch)
    run_id = _run_full(env, seed)
    sidecar = _sidecar(env, run_id)
    assert sidecar["decoded_frame_count"] == 120
    assert (sidecar["fps_num"], sidecar["fps_den"]) == (30, 1)
    with env.factory() as s:
        meta = json.loads(
            s.execute(
                text(
                    "SELECT frame_metadata_json FROM s10_full_apply_publication "
                    "WHERE run_id=:r AND workspace_id=:w"
                ),
                {"r": run_id, "w": WS},
            ).scalar()
        )
        row = s.execute(
            text("SELECT frame_count FROM s10_full_apply_run WHERE id=:r"), {"r": run_id}
        ).scalar()
    assert int(meta.get("frame_count") or 0) == 120
    assert int(row) == 120
    assert "per_layer_evidence" not in meta  # sidecar carries it; row stays lean
    out = decode_rgb_frames(env.managed_root / _pub_rel(env, run_id))
    src = decode_rgb_frames(env.managed_root / seed["source_rel"])
    assert len(out) == 120  # NOT 240 — no doubled timeline
    # frame order preserved: frame means follow the source ramp frame-for-frame
    for frame_index in (0, 60, 119):
        got = float(out[frame_index].astype(int).mean())
        want = float(src[frame_index].astype(int).mean())
        assert abs(got - want) < 25.0, (
            f"frame order changed at {frame_index}: out={got} src={want}"
        )
    m0 = float(out[0].astype(int).mean())
    m60 = float(out[60].astype(int).mean())
    # distinct frames (a doubled/shuffled/duplicated timeline collapses this)
    assert abs(m0 - m60) > 20.0


def test_b06_voice_policy_unchanged_and_audio_gap_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = _two_layer_graph(env, monkeypatch)
    run_id = _run_full(env, seed)
    ffprobe = shutil.which("ffprobe")
    assert ffprobe, "ffprobe required for the audio-policy probe"
    out_path = env.managed_root / _pub_rel(env, run_id)
    src_path = env.managed_root / seed["source_rel"]

    def _streams(path: Path) -> list[dict]:
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        return list(json.loads(proc.stdout or "{}").get("streams") or [])

    src_audio = [s for s in _streams(src_path) if s.get("codec_type") == "audio"]
    out_audio = [s for s in _streams(out_path) if s.get("codec_type") == "audio"]
    # engineering fixture is silent (no audio track to preserve) — the bridge
    # must not FABRICATE one, and must not alter any audio policy.
    assert src_audio == []
    assert out_audio == []
    with env.factory() as s:
        audio_artifacts = int(
            s.execute(
                text(
                    "SELECT COUNT(*) FROM artifact WHERE workspace_id=:w AND kind='audio'"
                ),
                {"w": WS},
            ).scalar()
            or 0
        )
        meta = json.loads(
            s.execute(
                text(
                    "SELECT frame_metadata_json FROM s10_full_apply_publication "
                    "WHERE run_id=:r AND workspace_id=:w"
                ),
                {"r": run_id, "w": WS},
            ).scalar()
        )
    assert audio_artifacts == 0
    assert not any("audio" in str(k).lower() for k in meta)
    sidecar = _sidecar(env, run_id)
    assert not any("audio" in str(k).lower() for k in sidecar)
