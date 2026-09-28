"""DELTA-F5 — seam geometry: the publication conforms to the SOURCE geometry (P1).

Defect (measured, R3 run ``a94d76d9-8156-4ed2-a717-dd5fb2d733ad``): the chosen
profile renders at 640x368 (4+4 rows of pad over the 640x360 source) and the app
stitch published that 368-high file as the video's rendered result.  The QC
submit composition then compared source frames (360, 640) against render frames
(368, 640) and refused ``QC_EVIDENCE_MALFORMED`` (HTTP 422) — readiness stayed
``not_run`` and the S12 export returned 409 (evidence:
``tasks/MF-DEMO-E2E-R3/raw/qc_receipt.json`` + ``raw/export_receipt.json`` +
``FINDINGS.md`` §F5).

Fix (option a — conform before publication): the publication geometry IS the
source geometry.  When the decoded chunk bytes carry a different geometry, the
stitch strips the pad rows DECLARED by the run's model profile
(``app/media_workflows/model_profiles.json`` → ``pad: "centered (4+4 rows over
640x360)"``) from every decoded chunk frame before assembly.  The render graph
keeps its own 368-high geometry; nothing is hardcoded, and a declaration that
does not reconcile with the measured bytes refuses with a typed code.

Rows (binary; RED on the pre-fix tree, GREEN after the fix):
* 5.0 the committed media fixtures ARE the real run's artifacts — they hash to
  the shas recorded in the R3 evidence (source + three chunk outputs) and decode
  to the recorded geometry; the pad declaration is read from the REAL frozen
  profile registry through the same accessor the render path uses.
* 5.1 the stitch conforms: the publication decodes to 640x360 (== source),
  carries the conform block (declared rows 4+4, ``centered``), and is
  byte-identical to the deterministic re-encode of EXACTLY the declared center
  strips of the real chunk frames — no resampling, no hardcoded crop.
* 5.2 the PRE-fix publication (rebuilt by the pre-fix assembly rule and verified
  byte-identical to the R3 publication sha ``6de96ac7…``) still refuses QC with
  the exact measured message: the defect is reproduced, not papered over.
* 5.3 QC submit on the SAME data path (``compose_check_run_args``, scope
  ``full``) over the conformed publication: no geometry refusal, and
  ``trajectory_drift`` — the detector that produced the 422 — composes with real
  observed/reference series measured on the decoded publication.  The remaining
  refusals are the mask/scene-graph producers the R3 run never ran (typed
  ``QC_EVIDENCE_MISSING``), never a geometry refusal.
* 5.4 negatives: pad declarations that do not reconcile (rows / base geometry /
  self-inconsistent "centered"), an absent declaration and an unparseable
  declaration all refuse with their typed codes on the real bytes; the identity
  case (render already at the source geometry) needs no declaration.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.persistence import create_engine_for_path, create_session_factory
from app.services.qc_evidence import compose as qc_compose
from app.services.qc_evidence import measure as qc_measure
from app.services.qc_evidence import sources as qc_sources
from app.services.renderer_routes.composite import (
    canonical_frame_sha256,
    decode_rgb_frames,
    write_frames_mp4,
)
from app.workflow import qc_checks_handler as handler
from app.workflow import s10_full_apply_jobs as jobs

WT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "delta_f5"

WS = "default"
PROJECT = "proj-f5"
VIDEO = "vid-f5"
ROLE = "role-f5"
SEGMENT = "seg-f5"
ROUTE = "route-f5"
LOCK = "lock-f5"
PUB_ARTIFACT = "art-pub-f5"
SRC_ARTIFACT = "art-src-f5"

RUN_ID = "a94d76d9-8156-4ed2-a717-dd5fb2d733ad"
WAN_PROFILE = "wan_animate2_int8_pad640x368_cacheoff"
PAD_DECLARATION = "centered (4+4 rows over 640x360)"

#: The R3 run's recorded identities (tasks/MF-DEMO-E2E-R3/raw/**).
R3_SOURCE_SHA = "fc18e859599f8feeb730ee9018413ced4c183f90a15e20ccc162433c4666c8cc"
R3_SOURCE_BYTES = 629545
R3_BASE_PUBLICATION_SHA = "6de96ac723db87195f23f88397f5450dedaa52ef7aee4a53bd8817be013961f4"
R3_BASE_PUBLICATION_BYTES = 3766511
R3_CHUNKS: tuple[tuple[str, int, int, str, str, int], ...] = (
    (
        "sc-f67c96",
        0,
        119,
        "sc-f67c96_00001_.mp4",
        "2cbd7c8daf1283b0ce51f1b3fc836140a03b23491fbb21ae01a0e428a460698b",
        141610,
    ),
    (
        "sc-7154cb",
        120,
        239,
        "sc-7154cb_00001_.mp4",
        "4ea1335c56a95944e52957fdb5cc1f7124e5f699f2f5a2e089aedde3bbdad834",
        369220,
    ),
    (
        "sc-d7b9f0",
        240,
        359,
        "sc-d7b9f0_00001_.mp4",
        "cd2f9bffa571faec49f34e98ccabfd03306b74297c39f7497022c2e84d089d99",
        389879,
    ),
)
#: The pre-fix assembly rule: the publication is the plain encode of the RAW
#: chunk frames (the render geometry), source frames verbatim elsewhere.
PUBLISHED_RENDER_DIMS = (368, 640)
SOURCE_DIMS = (360, 640)


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _db(tmp_path: Path, name: str = "delta_f5.db") -> Any:
    cfg = Config(str(WT / "alembic.ini"))
    cfg.set_main_option("script_location", str(WT / "migrations"))
    db = tmp_path / name
    db.parent.mkdir(parents=True, exist_ok=True)
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    command.upgrade(cfg, "head")
    return create_session_factory(create_engine_for_path(db))


def _declaration() -> dict[str, Any]:
    """The run profile's OWN declaration, read through the production accessor.

    On the PRE-FIX tree that accessor does not exist at all: return ``{}`` so the
    base assembly rule runs and the geometry assertions below report the REAL
    mismatch (368 vs 360) instead of a missing-symbol error.
    """
    getter = getattr(jobs, "_publication_geometry_declaration", None)
    if getter is None:  # pragma: no cover - pre-fix tree only
        return {}
    return getter({"profile_id": WAN_PROFILE})


def _raw_chunk_frames() -> dict[str, list[np.ndarray]]:
    return {
        shot: decode_rgb_frames(FIXTURES / name) for shot, _s, _e, name, _h, _b in R3_CHUNKS
    }


def _pre_fix_publication_bytes() -> bytes:
    """Rebuild the PRE-fix publication from the real chunk frames (assembly rule)."""
    frames: list[np.ndarray] = []
    for _shot, _s, _e, name, _h, _b in R3_CHUNKS:
        frames.extend(decode_rgb_frames(FIXTURES / name))
    out = FIXTURES / "_tmp_pre_fix_publication.mp4"
    try:
        write_frames_mp4(frames, out, fps=30.0)
        return out.read_bytes()
    finally:
        out.unlink(missing_ok=True)


def _seed_chunks(sf: Any, managed: Path) -> list[dict[str, Any]]:
    """Real chunk bytes under the managed root + their artifact rows + sidecars."""
    chunks: list[dict[str, Any]] = []
    for shot, start, end, name, expected_sha, _bytes in R3_CHUNKS:
        rel = f"chunks/{shot}.mp4"
        target = managed / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((FIXTURES / name).read_bytes())
        assert _sha_file(target) == expected_sha
        artifact_id = f"art-{shot}"
        with sf() as s:
            s.execute(
                text(
                    "INSERT INTO artifact(id, workspace_id, kind, relative_path, state,"
                    " sha256, size_bytes, revision, created_at, updated_at) VALUES"
                    " (:id,:ws,'video',:rel,'ready',:sha,:size,1,"
                    " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": artifact_id,
                    "ws": WS,
                    "rel": rel,
                    "sha": expected_sha,
                    "size": target.stat().st_size,
                },
            )
            s.commit()
        frames = decode_rgb_frames(target)
        jobs._write_evidence_sidecar(
            managed,
            Path(rel),
            {
                "decoded_sha256": canonical_frame_sha256(frames),
                "decoded_frame_count": len(frames),
                "fps_num": 30,
                "fps_den": 1,
                "layer_id": "",
                "shot_id": shot,
                "route": "shot_group",
                "effective_adapter": "comfy_shot_engine",
            },
        )
        chunks.append(
            {
                "chunk_id": f"ck_{shot}",
                "shot_id": shot,
                "core_start_frame": start,
                "core_end_frame": end,
                "verified": True,
                "artifact_id": artifact_id,
                "content_hash": "a" * 64,
            }
        )
    return chunks


def _stitch(
    sf: Any, managed: Path, *, pad: Any, run_id: str = RUN_ID
) -> tuple[Path, str, int, dict[str, Any]]:
    """Run the REAL stitch over the real chunks + real source."""
    source = managed / "src/source_12s.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes((FIXTURES / "source_12s.mp4").read_bytes())
    with sf() as s:
        s.execute(
            text("INSERT OR IGNORE INTO workspace(id,name) VALUES (:w,'default')"),
            {"w": WS},
        )
        s.commit()
    manifest = {
        "source_media_rel": "src/source_12s.mp4",
        "source_media_sha256": _sha_file(source),
        "source_media_size_bytes": source.stat().st_size,
    }
    kwargs: dict[str, Any] = {
        "managed_root": managed,
        "run_id": run_id,
        "chunks": _seed_chunks(sf, managed),
        "session_factory": sf,
        "ws": WS,
        "fps_num": 30,
        "fps_den": 1,
        "authority": {"delta_f5": True},
        "manifest": manifest,
        "frame_count": 360,
    }
    try:
        return jobs._stitch_shot_chunks(**kwargs, pad=pad)
    except TypeError as exc:  # pragma: no cover - pre-fix tree only
        # On the PRE-FIX tree the stitch has no conform surface at all.  Run the
        # base assembly rule anyway so this file reports the REAL geometry
        # mismatch (368 vs 360) instead of a missing-symbol error.
        if "pad" not in str(exc):
            raise
        return jobs._stitch_shot_chunks(**kwargs)


def _seed_world(sf: Any, managed: Path, publication: Path, tag: str) -> None:
    """A real QC world: video item + source/publication artifacts + route chain."""
    pub_rel = f"{tag}/render/publication.mp4"
    src_rel = f"{tag}/src/source.mp4"
    (managed / pub_rel).parent.mkdir(parents=True, exist_ok=True)
    (managed / src_rel).parent.mkdir(parents=True, exist_ok=True)
    (managed / pub_rel).write_bytes(publication.read_bytes())
    (managed / src_rel).write_bytes((FIXTURES / "source_12s.mp4").read_bytes())
    with sf() as s:
        s.execute(text("INSERT OR IGNORE INTO workspace(id,name) VALUES (:w,'default')"), {"w": WS})
        s.execute(
            text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'F5')"),
            {"p": PROJECT, "w": WS},
        )
        for aid, rel in ((SRC_ARTIFACT, src_rel), (PUB_ARTIFACT, pub_rel)):
            s.execute(
                text(
                    "INSERT INTO artifact(id, workspace_id, kind, relative_path, state,"
                    " sha256, size_bytes, revision, created_at, updated_at) VALUES"
                    " (:id,:ws,'video',:rel,'ready',:sha,:size,1,"
                    " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": aid,
                    "ws": WS,
                    "rel": rel,
                    "sha": _sha_file(managed / rel),
                    "size": (managed / rel).stat().st_size,
                },
            )
        s.execute(
            text(
                "INSERT INTO artifact_owner(artifact_id, owner_type, owner_id, purpose)"
                " VALUES (:a,'video_item',:v,:purpose)"
            ),
            {"a": SRC_ARTIFACT, "v": VIDEO, "purpose": "source"},
        )
        s.execute(
            text(
                "INSERT INTO artifact_owner(artifact_id, owner_type, owner_id, purpose)"
                " VALUES (:a,'video_item',:v,:purpose)"
            ),
            {"a": PUB_ARTIFACT, "v": VIDEO, "purpose": "result"},
        )
        s.execute(
            text(
                "INSERT INTO video_item(id, project_id, title, position, source_artifact_id,"
                " width, height, fps_num, fps_den, duration_ms) VALUES"
                " (:v,:p,'12s 3-shot demo',0,:src,640,360,30,1,12000)"
            ),
            {"v": VIDEO, "p": PROJECT, "src": SRC_ARTIFACT},
        )
        s.execute(
            text(
                "INSERT INTO scene(id, video_item_id, position, start_frame, end_frame,"
                " start_time_ms, end_time_ms, status, revision, created_at, updated_at)"
                " VALUES ('sc-f5',:v,0,0,359,0,12000,'pending',1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"v": VIDEO},
        )
        s.execute(
            text(
                "INSERT INTO object_role(id, workspace_id, project_id, video_item_id,"
                " source_generation, name, kind, status, revision, created_at, updated_at)"
                " VALUES (:r,:w,:p,:v,'1','BOOK-P1','character','confirmed',1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"r": ROLE, "w": WS, "p": PROJECT, "v": VIDEO},
        )
        s.execute(
            text(
                "INSERT INTO structural_lock_manifest(id, workspace_id, project_id,"
                " video_item_id, source_generation, version, status, policy_version,"
                " manifest_hash, manifest_json, idempotency_key, revision,"
                " created_at, updated_at) VALUES (:i,:w,:p,:v,'1',1,'active',"
                " 'structural-thresholds-v1',:h,'{}','demo-lock-f5',1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"i": LOCK, "w": WS, "p": PROJECT, "v": VIDEO, "h": "f" * 64},
        )
        s.execute(
            text(
                "INSERT INTO occurrence_segment(id, logical_id, lineage_version, workspace_id,"
                " project_id, video_item_id, role_id, scene_id, name, kind, start_frame,"
                " end_frame, start_time_ms, end_time_ms, source_generation, prompt_json,"
                " segmentation_json, mask_artifact_id, confidence, confidence_source,"
                " reasons_json, visibility, z_order, revision, created_at, updated_at) VALUES"
                " (:i,:l,1,:w,:p,:v,:r,'sc-f5','BOOK-P1','character',0,359,0,12000,'1',"
                " :pj, :sg, NULL,1.0,'user','[]','visible',0,1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "i": SEGMENT,
                "l": "log-f5",
                "w": WS,
                "p": PROJECT,
                "v": VIDEO,
                "r": ROLE,
                "pj": '{"boxes":[{"h":0.4,"w":0.3,"x":0.05,"y":0.05}]}',
                "sg": '{"boxes":[{"h":0.3,"w":0.2,"x":0.1,"y":0.1}]}',
            },
        )
        s.execute(
            text(
                "INSERT INTO segment_render_route(id, workspace_id, project_id, video_item_id,"
                " occurrence_segment_id, structural_lock_manifest_id, route, anchor_x, anchor_y,"
                " start_frame, end_frame, algorithm, algorithm_version, confidence,"
                " confidence_source, provenance_json, reasons_json, idempotency_key, revision,"
                " created_at, updated_at) VALUES"
                " (:i,:w,:p,:v,:s,:m,'sprite_affine',0.5,0.5,0,359,'structural-lock-producer',"
                " '1',1.0,'derived','{}','[]','structural-lock-produce:f5',1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"i": ROUTE, "w": WS, "p": PROJECT, "v": VIDEO, "s": SEGMENT, "m": LOCK},
        )
        s.commit()


# ── 5.0 — the fixtures ARE the real run's artifacts ─────────────────────────


def test_delta_f5_0_fixtures_are_the_real_run_artifacts() -> None:
    assert _sha_file(FIXTURES / "source_12s.mp4") == R3_SOURCE_SHA
    assert (FIXTURES / "source_12s.mp4").stat().st_size == R3_SOURCE_BYTES
    for shot, _s, _e, name, sha, size in R3_CHUNKS:
        path = FIXTURES / name
        assert _sha_file(path) == sha, shot
        assert path.stat().st_size == size, shot
    # recorded geometry: source 640x360 / 120-frame chunks at 640x368
    source_frames = decode_rgb_frames(FIXTURES / "source_12s.mp4")
    assert len(source_frames) == 360
    assert source_frames[0].shape[:2] == SOURCE_DIMS
    for shot, _s, _e, name, _sha, _b in R3_CHUNKS:
        frames = decode_rgb_frames(FIXTURES / name)
        assert len(frames) == 120, shot
        assert frames[0].shape[:2] == PUBLISHED_RENDER_DIMS, shot
    # the declaration is read from the REAL frozen registry (same accessor as render)
    declaration = jobs._publication_geometry_declaration({"profile_id": WAN_PROFILE})
    assert declaration == {"pad": PAD_DECLARATION, "native_output_dims": [640, 368]}
    assert jobs._publication_geometry_declaration({"profile_id": "unknown-profile"}) == {}


# ── 5.1 — the stitch conforms the publication to the source geometry ────────


@pytest.fixture(scope="module")
def conformed(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One real stitch run (module scope: the 360-frame encode is expensive)."""
    tmp = tmp_path_factory.mktemp("delta_f5_conform")
    managed = tmp / "managed"
    managed.mkdir(parents=True, exist_ok=True)
    sf = _db(tmp)
    rel, sha, size, meta = _stitch(sf, managed, pad=_declaration())
    return {"path": managed / rel, "sha": sha, "size": size, "meta": meta, "tmp": tmp}


def test_delta_f5_1_stitch_conforms_publication_to_source_geometry(
    conformed: dict[str, Any],
) -> None:
    meta = conformed["meta"]
    assert meta["frame_count"] == 360
    assert meta["generated_frames"] == 360
    assert meta["publication_geometry"] == {"width": 640, "height": 360}
    assert meta["conform"] == {
        "schema": "mf-delta-f5/publication-conform@1",
        "applied": True,
        "mode": "centered",
        "pad_top": 4,
        "pad_bottom": 4,
        "render_dims": [640, 368],
        "source_dims": [640, 360],
        "declaration": PAD_DECLARATION,
    }
    # decoded geometry == the source geometry (this is the seam QC compares)
    frames = decode_rgb_frames(conformed["path"])
    assert len(frames) == 360
    assert frames[0].shape[:2] == SOURCE_DIMS
    # the publication is EXACTLY the deterministic re-encode of the declared
    # center strips of the real chunk frames — no resampling, no hardcoded crop
    strips: list[np.ndarray] = []
    for _shot, _s, _e, name, _sha, _b in R3_CHUNKS:
        strips.extend([frame[4:364] for frame in decode_rgb_frames(FIXTURES / name)])
    expect = conformed["tmp"] / "expected_strip.mp4"
    write_frames_mp4(strips, expect, fps=30.0)
    assert conformed["sha"] == _sha_file(expect)
    assert conformed["size"] == conformed["path"].stat().st_size
    # it is NOT the pre-fix (render-geometry) publication anymore
    assert conformed["sha"] != R3_BASE_PUBLICATION_SHA
    for row in meta["per_chunk_evidence"]:
        assert row["conform_applied"] is True
        assert row["decoded_sha256"] != row["publication_decoded_sha256"]


# ── 5.2 — the pre-fix publication still refuses QC (defect reproduced) ──────


def test_delta_f5_2_pre_fix_publication_refuses_qc_geometry(
    tmp_path: Path, monkeypatch: Any
) -> None:
    base_bytes = _pre_fix_publication_bytes()
    # the rebuilt pre-fix publication IS the R3 publication, byte for byte
    assert hashlib.sha256(base_bytes).hexdigest() == R3_BASE_PUBLICATION_SHA
    assert len(base_bytes) == R3_BASE_PUBLICATION_BYTES

    managed = tmp_path / "managed"
    managed.mkdir(parents=True, exist_ok=True)
    publication = managed / "base_publication.mp4"
    publication.write_bytes(base_bytes)
    sf = _db(tmp_path, "delta_f5_base.db")
    _seed_world(sf, managed, publication, "base")
    monkeypatch.setattr("app.api.deps.get_managed_root", lambda: managed)

    with sf() as s, pytest.raises(handler.QcCheckRunSubmitError) as exc:
        handler.compose_check_run_args(
            s, workspace_id=WS, project_id=PROJECT, video_item_id=VIDEO, scope="full"
        )
    assert exc.value.code == handler.QC_RUN_EVIDENCE_UNAVAILABLE
    message = str(exc.value)
    assert "QC_EVIDENCE_MALFORMED" in message
    assert "source frame (360, 640) and render frame (368, 640) have different geometry" in message
    failed = (exc.value.details or {}).get("failed_detectors") or {}
    assert failed["trajectory_drift"]["code"] == "QC_EVIDENCE_MALFORMED"


# ── 5.3 — QC submit composes on the conformed publication (same data path) ──


def test_delta_f5_3_qc_submit_composes_on_the_conformed_publication(
    conformed: dict[str, Any], tmp_path: Path, monkeypatch: Any
) -> None:
    managed = tmp_path / "managed"
    managed.mkdir(parents=True, exist_ok=True)
    publication = managed / "conformed_publication.mp4"
    publication.write_bytes(conformed["path"].read_bytes())
    assert _sha_file(publication) == conformed["sha"]
    sf = _db(tmp_path, "delta_f5_conformed.db")
    _seed_world(sf, managed, publication, "fixed")
    monkeypatch.setattr("app.api.deps.get_managed_root", lambda: managed)

    # the exact geometry pair QC compares, through the REAL decode path
    src_frames = qc_measure.decode_video_frames(
        managed / "fixed/src/source.mp4", [0, 10, 40, 80, 119], detector="trajectory_drift"
    )
    ren_frames = qc_measure.decode_video_frames(
        managed / "fixed/render/publication.mp4", [0, 10, 40, 80, 119], detector="trajectory_drift"
    )
    assert sorted(src_frames) == sorted(ren_frames) == [0, 10, 40, 80, 119]
    for index in sorted(src_frames):
        source_matrix = np.asarray(src_frames[index], dtype=np.float64)
        render_matrix = np.asarray(ren_frames[index], dtype=np.float64)
        assert source_matrix.shape == render_matrix.shape == SOURCE_DIMS
        measured = qc_measure.changed_centroid_x(src_frames[index], ren_frames[index])
        assert measured is not None and 0.0 <= measured <= 640.0

    with sf() as s:
        scope = qc_sources.load_scope(
            s, workspace_id=WS, project_id=PROJECT, video_item_id=VIDEO
        )
        ctx = qc_compose._Context(session=s, managed_root=managed, scope=scope)
        args = qc_compose._BUILDERS["trajectory_drift"](ctx)
        assert len(args["observed_x"]) == len(args["reference_x"]) == 16
        assert args["frame_start"] == 0
        observation = args["render_observation"]
        assert observation["render_role"] == "owned_result_artifact"
        assert observation["artifact"]["artifact_id"] == PUB_ARTIFACT
        assert observation["artifact"]["sha256"] == conformed["sha"]
        assert observation["artifact"]["bytes_reverified"] is True
        provenance = args["evidence_provenance"]["families"]["artifact"]
        assert provenance["render"]["sha256"] == conformed["sha"]

        with pytest.raises(handler.QcCheckRunSubmitError) as exc:
            handler.compose_check_run_args(
                s, workspace_id=WS, project_id=PROJECT, video_item_id=VIDEO, scope="full"
            )
    message = str(exc.value)
    assert exc.value.code == handler.QC_RUN_EVIDENCE_UNAVAILABLE
    assert "different geometry" not in message
    assert "QC_EVIDENCE_MALFORMED" not in message
    failed = (exc.value.details or {}).get("failed_detectors") or {}
    assert "trajectory_drift" not in failed
    assert "cut_drift" not in failed
    assert "temporal_flicker" not in failed
    # the remaining refusals are the producers the R3 run never ran (masks /
    # scene graph), never the geometry seam
    assert set(failed) == {
        "contact_break",
        "z_order_error",
        "silhouette_clipping",
        "identity_drift",
        "edge_halo",
    }
    assert {row["code"] for row in failed.values()} == {"QC_EVIDENCE_MISSING"}


# ── 5.4 — declaration negatives refuse typed (on the real bytes) ────────────


@pytest.mark.parametrize(
    ("declaration", "code"),
    (
        (
            {"pad": "centered (4+5 rows over 640x360)", "native_output_dims": [640, 368]},
            "STITCH_CONFORM_PAD_MISMATCH",
        ),
        (
            {"pad": "centered (4+4 rows over 640x368)", "native_output_dims": [640, 368]},
            "STITCH_CONFORM_PAD_MISMATCH",
        ),
        (
            {"pad": "centered (3+5 rows over 640x360)", "native_output_dims": [640, 368]},
            "STITCH_CONFORM_PAD_MISMATCH",
        ),
        (
            {"pad": "centered (4+4 rows over 640x360)", "native_output_dims": [640, 376]},
            "STITCH_CONFORM_PAD_MISMATCH",
        ),
        (
            {"pad": "bottom-anchored (0+8 rows)", "native_output_dims": [640, 368]},
            "STITCH_CONFORM_DECLARATION_INVALID",
        ),
        ({}, "STITCH_CONFORM_DECLARATION_MISSING"),
        ({"pad": None, "native_output_dims": [640, 368]}, "STITCH_CONFORM_DECLARATION_MISSING"),
    ),
)
def test_delta_f5_4_bad_declarations_refuse_typed(
    declaration: dict[str, Any], code: str
) -> None:
    with pytest.raises(jobs.S10FullApplyJobError) as exc:
        jobs._publication_conform(
            source_shape=SOURCE_DIMS,
            render_shape=PUBLISHED_RENDER_DIMS,
            declaration=declaration,
        )
    assert code in str(exc.value)
    # identity case: render already at the source geometry needs no declaration
    identity = jobs._publication_conform(
        source_shape=SOURCE_DIMS, render_shape=SOURCE_DIMS, declaration={}
    )
    assert identity["applied"] is False
    assert identity["mode"] == "identity"


def test_delta_f5_4_stitch_refuses_a_declaration_that_does_not_reconcile(
    tmp_path: Path,
) -> None:
    managed = tmp_path / "managed"
    managed.mkdir(parents=True, exist_ok=True)
    sf = _db(tmp_path, "delta_f5_negative.db")
    with pytest.raises(jobs.S10FullApplyJobError) as exc:
        _stitch(
            sf,
            managed,
            pad={"pad": "centered (4+5 rows over 640x360)", "native_output_dims": [640, 368]},
        )
    assert "STITCH_CONFORM_PAD_MISMATCH" in str(exc.value)
    # fail closed BEFORE any publication bytes exist
    assert not (managed / f"s10_full_apply/{RUN_ID}/stitch_shot_chunks.mp4").exists()
