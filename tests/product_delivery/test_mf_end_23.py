"""MF-END-23 — QC readiness gắn output thật + export gate: acceptance + negatives.

Row map (binary; every row is built on a REAL temp database with REAL bytes in
a temp managed root — nothing is mocked at the code level):

* micro repro (23.0): the additive surface exists — ``mf-end-23/output-binding@1``,
  ``mf-end-23/evidence-binding@1``, ``mf-end-23/export-gate@1`` — the LEGACY
  fingerprint formula is still computable and differs from the output-bound one
  (proving the change is additive, not a silent redefinition);
* 23.1: the composer reads the producer artifacts of the RIGHT publication and
  validates freshness/ownership/timebase: a sealed MF-END-21 payload bound to
  the CURRENT render is accepted with its binding; a payload bound to a
  different render / source / timebase REFUSES (typed stale); tampered bytes
  REFUSE; a video without a published observation carries a TYPED visibility
  block (never a blanket "no evidence");
* 23.2: the export gate runs the registered band: a completed run whose
  detector set/revisions do not match the registered band BLOCKS; missing
  output-observation evidence BLOCKS; a completed AUDIO-only run never
  produces readiness or an export ``ready`` (the authority + gate both refuse);
* 23.3: a render change or a cast change invalidates the completed run
  (readiness ``not_run``, gate ``not_run``); a finding maps to the SHOT that
  contains its frame window and is REFUSED (never guessed) when no shot does;
  the stale-evidence check gains the render anchor;
* 23.4: the OLD readiness authority is untouched (``compute_project_readiness``
  keeps its contract; the frozen policy identity is unchanged) — the export
  gate is a NEW additive contract consumed on top of it.

Disclosure (no green-by-fabrication): the durable RUN rows that replay a
completed full-band check-run are seeded as Job/JobAttempt rows because
composing the eight visual detectors for real needs the whole S08 evidence
chain (covered by ``tests/product_p1/qc_evidence`` and MF-END-21/22); every
IDENTITY in those rows (evidence fingerprint, scope fingerprint, detector
revisions, evidence binding, policy hashes) is computed by the REAL production
functions, and every consumer under test reads them through its real code
path.  The publishable observation payload is built by the REAL
``rendered_observations`` builder; the media bytes are labeled CI fixtures.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.persistence import create_engine_for_path, create_session_factory
from app.persistence import readiness as rd
from app.persistence.qc_items import QCItemRepository
from app.services import qc_correction_bridge as bridge
from app.services import rendered_observations as ro
from app.services import source_role_tracks as srt
from app.services.qc_evidence import compose as qc_compose
from app.services.qc_evidence import sources as qc_sources
from app.workflow import qc_checks_handler as handler

WT = Path(__file__).resolve().parents[2]

WS = "ws-mf23"
PROJECT = "p-mf23"
VIDEO = "v-mf23"
GEN = "1"
W, H, FRAMES = 64, 48, 12
FPS = "30/1"
ROLE = "r-mf23"
PERSON_LEVEL = 200
BG_LEVEL = 20


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


#: The managed root every world in a test writes into (set by the autouse
#: fixture below and published through the application's public accessor, the
#: same way every production component resolves it).
_MANAGED: dict[str, Path] = {}
_WORLD_SEQ = iter(range(1000))


@pytest.fixture(autouse=True)
def _isolated_managed_root(monkeypatch: Any, tmp_path: Path) -> Path:
    root = tmp_path / "managed"
    root.mkdir(parents=True, exist_ok=True)
    _MANAGED["root"] = root
    monkeypatch.setattr("app.api.deps.get_managed_root", lambda: root)
    return root


def _db(tmp_path: Path, name: str = "mf23.db") -> Any:
    cfg = Config(str(WT / "alembic.ini"))
    cfg.set_main_option("script_location", str(WT / "migrations"))
    db = tmp_path / name
    db.parent.mkdir(parents=True, exist_ok=True)
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    command.upgrade(cfg, "head")
    return create_session_factory(create_engine_for_path(db))


class _LevelSource:
    """Deterministic CI output-mask engine (level match, bounded)."""

    engine_id = "mf23_level"
    provenance = srt.PROVENANCE_FIXTURE
    probe: dict[str, Any] | None = None
    candidates: dict[str, str] = {}
    inference_ran = False

    def __init__(self, level: int = PERSON_LEVEL) -> None:
        self.level = int(level)
        self.params = {"rule": "mf23_level", "tolerance": 2}

    def sample(self, frame_index: int, seed: Any, frame: Any) -> Any:
        array = np.asarray(frame)
        if array.ndim == 3:
            array = array[:, :, 0]
        target = np.abs(array.astype(np.int64) - self.level) <= 2
        if not target.any():
            return srt.MaskSample(mask=None, method="mf23:absent", present=False)
        return srt.MaskSample(mask=target.astype(np.uint8) * 255, method="mf23:level")


def _frames(start: int = 0) -> dict[int, np.ndarray]:
    frames: dict[int, np.ndarray] = {}
    for index in range(FRAMES):
        canvas = np.full((H, W), BG_LEVEL, dtype=np.uint8)
        x = 4 + ((start + index) % (W - 20))
        canvas[10:26, x : x + 14] = PERSON_LEVEL
        frames[index] = canvas
    return frames


def _ro_payload(
    *,
    render_sha: str,
    source_sha: str,
    fps: str = FPS,
    output_role: str = "owned_result_artifact",
    artifact_id: str = "art-render",
    source_artifact_id: str = "art-source",
) -> dict[str, Any]:
    """The REAL sealed MF-END-21 payload bound to the given render/source."""
    output = ro.RenderedOutput(
        artifact_id=artifact_id,
        sha256=render_sha,
        size_bytes=1234,
        relative_path="render/out.mp4",
        role=output_role,
        width=W,
        height=H,
        frame_count=FRAMES,
        source_artifact_id=source_artifact_id,
        source_sha256=source_sha,
        producer="ci_render",
        facts={},
    )
    segments = [
        ro.RenderedSegment(
            segment_id="seg-r1",
            role_id=ROLE,
            kind=srt.ROLE_KIND_PERSON,
            start_frame=0,
            end_frame=FRAMES,
            window=(0, 0, W, H),
        )
    ]
    artifact = ro.build_rendered_observations(
        output=output,
        frames=_frames(),
        segments=segments,
        engine=_LevelSource(),
        fps_rational=fps,
        production=False,
    )
    return artifact.to_payload()


def _write_artifact(
    session: Any,
    managed: Path,
    *,
    artifact_id: str,
    rel: str,
    data: bytes,
    kind: str,
    purposes: tuple[tuple[str, str, str], ...],
    sha_override: str | None = None,
) -> str:
    """Write REAL bytes under the managed root + the artifact/owner rows."""
    path = managed / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    sha = sha_override or _sha(data)
    session.execute(
        text(
            "INSERT INTO artifact(id, workspace_id, kind, relative_path, state, "
            "sha256, size_bytes, revision, created_at, updated_at) VALUES"
            " (:id, :ws, :kind, :rel, 'ready', :sha, :size, 1, "
            " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "id": artifact_id,
            "ws": WS,
            "kind": kind,
            "rel": rel,
            "sha": sha,
            "size": len(data),
        },
    )
    for owner_type, owner_id, purpose in purposes:
        session.execute(
            text(
                "INSERT INTO artifact_owner(artifact_id, owner_type, owner_id, "
                "purpose) VALUES (:a, :t, :o, :p)"
            ),
            {"a": artifact_id, "t": owner_type, "o": owner_id, "p": purpose},
        )
    return sha


def _seed_world(
    tmp_path: Path,
    *,
    with_observations: bool = True,
    observations_for_other_render: bool = False,
    observations_fps: str = FPS,
    observations_tampered: bool = False,
    with_run: bool = True,
    with_publication: bool = True,
    with_shots: bool = True,
) -> dict[str, Any]:
    """One CI world: real rows, real bytes, real sealed observations."""
    sf = _db(tmp_path)
    tag = f"w{next(_WORLD_SEQ):02d}"
    managed = _MANAGED.get("root") or (tmp_path / "managed")
    managed.mkdir(parents=True, exist_ok=True)
    source_bytes = b"MF23-CI-SOURCE" + b"\x00" * 64
    render_bytes = b"MF23-CI-RENDER-v1" + b"\x00" * 64
    with sf() as s:
        s.execute(
            text("INSERT OR IGNORE INTO workspace(id,name) VALUES (:w,'default')"),
            {"w": WS},
        )
        s.execute(
            text(
                "INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'Proj')"
            ),
            {"p": PROJECT, "w": WS},
        )
        source_sha = _write_artifact(
            s,
            managed,
            artifact_id="art-source",
            rel=f"{tag}/source/src.mp4",
            data=source_bytes,
            kind="video",
            purposes=(("video_item", VIDEO, "source"),),
        )
        render_sha = _write_artifact(
            s,
            managed,
            artifact_id="art-render",
            rel=f"{tag}/render/out.mp4",
            data=render_bytes,
            kind="video",
            purposes=(("video_item", VIDEO, "result"),),
        )
        s.execute(
            text(
                "INSERT INTO video_item(id, project_id, title, position, "
                "source_artifact_id, width, height, fps_num, fps_den, "
                "duration_ms) VALUES (:v, :p, 'Vid', 0, 'art-source', :wd, "
                ":ht, 30, 1, 400)"
            ),
            {"v": VIDEO, "p": PROJECT, "wd": W, "ht": H},
        )
        # cast mapping (FK-complete: character + published pack version + role)
        s.execute(
            text(
                "INSERT INTO character(id, workspace_id, name, code) VALUES"
                " ('ch-mf23', :w, 'hero', 'hero-mf23')"
            ),
            {"w": WS},
        )
        s.execute(
            text(
                "INSERT INTO character_pack_version(id, character_id, workspace_id, "
                "version, status) VALUES ('pv-mf23', 'ch-mf23', :w, 1, 'published')"
            ),
            {"w": WS},
        )
        s.execute(
            text(
                "INSERT INTO object_role(id, workspace_id, project_id, video_item_id, "
                "source_generation, name, kind, status) VALUES"
                " (:r, :w, :p, :v, '1', 'role-r1', 'character', 'confirmed')"
            ),
            {"r": ROLE, "w": WS, "p": PROJECT, "v": VIDEO},
        )
        # shot inventory chain: reskin_config -> apply_checkpoint -> run -> chunks
        if with_run:
            s.execute(
                text(
                    "INSERT INTO reskin_config(id, workspace_id, project_id, "
                    "object_role_id, character_id, pack_version_id, params_json, "
                    "revision) VALUES ('rc-mf23', :w, :p, :r, 'ch-mf23', 'pv-mf23', "
                    "'{}', 1)"
                ),
                {"w": WS, "p": PROJECT, "r": ROLE},
            )
            s.execute(
                text(
                    "INSERT INTO apply_checkpoint(id, workspace_id, project_id, "
                    "reskin_config_id, reskin_config_revision, pack_version_ids_json, "
                    "loop_hashes_json, timebase_fingerprint, snapshot_json, "
                    "checkpoint_hash, revision, created_at, updated_at) VALUES "
                    "('cp-mf23', :w, :p, 'rc-mf23', 1, '[]', '[]', '30/1', '{}', "
                    ":h, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"w": WS, "p": PROJECT, "h": "c" * 64},
            )
            s.execute(
                text(
                    "INSERT INTO s10_full_apply_run(id, workspace_id, project_id, "
                    "video_item_id, apply_checkpoint_id, apply_checkpoint_hash, "
                    "apply_checkpoint_revision, plan_id, plan_hash, status, "
                    "frame_count, fps_num, fps_den, chunk_config_json, attempt, "
                    "revision, created_at, updated_at) VALUES"
                    " ('run-mf23', :w, :p, :v, 'cp-mf23', :h, 1, :pid, :ph, "
                    "'completed', 12, 30, 1, '{}', 1, 1, CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP)"
                ),
                {
                    "w": WS,
                    "p": PROJECT,
                    "v": VIDEO,
                    "h": "c" * 64,
                    "pid": "d" * 64,
                    "ph": "e" * 64,
                },
            )
            for index, (shot_id, c_start, c_end) in enumerate(
                (("shot-a", 0, 5), ("shot-b", 6, 11))
            ) if with_shots else ():
                s.execute(
                    text(
                        "INSERT INTO s10_full_apply_chunk(id, workspace_id, run_id, "
                        "chunk_index, order_index, shot_id, layer_id, core_start_frame, "
                        "core_end_frame, overlap_before, overlap_after, content_hash, "
                        "state, attempt, verified, revision, created_at, updated_at) "
                        "VALUES (:id, :w, 'run-mf23', :idx, :idx, :shot, :lid, "
                        ":cs, :ce, 0, 0, :ch, 'completed', 1, 1, 1, "
                        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {
                        "id": f"chunk-{index}",
                        "w": WS,
                        "idx": index,
                        "shot": shot_id,
                        "lid": f"layer-{index}",
                        "cs": c_start,
                        "ce": c_end,
                        "ch": f"{index + 1:064x}"[:64],
                    },
                )
            s.execute(
                text(
                    "INSERT INTO project_cast_mapping(id, workspace_id, project_id, "
                    "object_role_id, character_id, pack_version_id, revision, "
                    "created_at, updated_at) VALUES ('pcm-mf23', :w, :p, :r, "
                    "'ch-mf23', 'pv-mf23', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"w": WS, "p": PROJECT, "r": ROLE},
            )
        if with_publication and with_run:
            s.execute(
                text(
                    "INSERT INTO s10_full_apply_publication(id, workspace_id, run_id, "
                    "artifact_id, content_hash, frame_count, frame_metadata_json, "
                    "checkpoint_id, checkpoint_hash, checkpoint_revision, state, "
                    "created_at, updated_at) VALUES ('pub-mf23', :w, 'run-mf23', "
                    "'art-render', :ch, 12, '{\"frame_count\": 12}', 'cp-mf23', :hh, "
                    "1, 'completed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"w": WS, "ch": "f" * 64, "hh": "c" * 64},
            )
        observations = None
        if with_observations:
            bound_render_sha = "9" * 64 if observations_for_other_render else render_sha
            observations = _ro_payload(
                render_sha=bound_render_sha,
                source_sha=source_sha,
                fps=observations_fps,
            )
            obs_bytes = json.dumps(observations, sort_keys=True).encode("utf-8")
            if observations_tampered:
                # bytes on disk diverge from the recorded sha → TAMPERED
                obs_bytes = obs_bytes + b" "
            _write_artifact(
                s,
                managed,
                artifact_id="art-observations",
                rel=f"{tag}/observations/mf23.json",
                data=obs_bytes,
                kind="document",
                purposes=(("video_item", VIDEO, "rendered_observations"),),
                sha_override=None if not observations_tampered else _sha(
                    obs_bytes[:-1]
                ),
            )
        s.commit()
    return {
        "sf": sf,
        "managed": managed,
        "source_sha": source_sha,
        "render_sha": render_sha,
        "observations": observations,
    }


def _render_row(sf: Any) -> dict[str, Any] | None:
    with sf() as s:
        return qc_compose.render_row(
            s, workspace_id=WS, project_id=PROJECT, video_item_id=VIDEO
        )


def _binding(sf: Any) -> dict[str, Any]:
    with sf() as s:
        return handler.output_evidence_binding(
            s, workspace_id=WS, project_id=PROJECT, video_item_id=VIDEO
        )


def _seed_full_run(
    sf: Any,
    *,
    completion_override: dict[str, Any] | None = None,
    manifest_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Seed a completed FULL-scope check-run whose every identity is real."""
    band = list(handler.SCOPE_BANDS[handler.SCOPE_FULL])
    handler.ensure_full_band_registered()
    with sf() as s:
        from app.persistence.jobs import JobRepository

        fp = handler.evidence_fingerprint(
            s, workspace_id=WS, video_item_id=VIDEO, generation=GEN, project_id=PROJECT
        )
        binding = handler.output_evidence_binding(
            s, workspace_id=WS, project_id=PROJECT, video_item_id=VIDEO
        )
        policy = handler.policy_bundle()
        scope_fp = handler.scope_fingerprint(handler.SCOPE_FULL)
        source_fp = handler.source_artifact_fingerprint(s, video_item_id=VIDEO)
        manifest = {
            "schema_version": handler.RUN_QC_SCHEMA_VERSION,
            "workspace_id": WS,
            "project_id": PROJECT,
            "video_item_id": VIDEO,
            "scope": handler.SCOPE_FULL,
            "scope_fingerprint": scope_fp,
            "evidence_fingerprint": fp,
            "evidence_binding": binding,
            "policy_id": policy["policy_id"],
            "policy_content_hash": policy["policy_content_hash"],
            "source_generation": GEN,
            "source_artifact_id": source_fp["source_artifact_id"],
            "source_sha256": source_fp["source_sha256"],
            "deadline_sec": 300.0,
            "capture_cap_bytes": 65536,
            "detector_args": {name: {"workspace_id": WS} for name in band},
        }
        if manifest_override:
            manifest.update(manifest_override)
        job = JobRepository(s).create_job(
            workspace_id=WS,
            job_type=handler.JOB_TYPE_RUN_QC_CHECKS,
            owner_type="video_item",
            owner_id=VIDEO,
            input_manifest=manifest,
            idempotency_key=f"MF23-FULL:{VIDEO}:{fp}",
            input_generation=GEN,
            steps=handler.run_qc_checks_steps(),
            actor="api",
        )
        completion: dict[str, Any] = {
            "schema_version": handler.RUN_QC_SCHEMA_VERSION,
            "job_type": handler.JOB_TYPE_RUN_QC_CHECKS,
            "completed": True,
            "run_id": f"run-{job.id}",
            "policy_id": policy["policy_id"],
            "policy_content_hash": policy["policy_content_hash"],
            "source_generation": GEN,
            "source_artifact_id": source_fp["source_artifact_id"],
            "source_artifact_fingerprint": source_fp["source_sha256"],
            "evidence_fingerprint": fp,
            "scope": handler.SCOPE_FULL,
            "scope_fingerprint": scope_fp,
            "detectors": band,
            "detector_revisions": handler.detector_revisions(band),
            "evidence_binding": binding,
            "summary": {
                "checks_requested": len(band),
                "checks_run": len(band),
                "checks_skipped": 0,
                "created": 0,
                "reused": 0,
                "resolved_after_recheck": 0,
                "reopened_stale": 0,
                "not_applicable": 0,
                "errors": 0,
                "cancelled": False,
                "deadline_exceeded": False,
                "per_detector": {},
            },
            "zero_item_completion": {
                "evidence": True,
                "qc_items_created": 0,
                "issues_found": 0,
                "checks_run": len(band),
                "not_applicable": 0,
            },
        }
        if completion_override:
            completion.update(completion_override)
        s.commit()
        return {"job_id": job.id, "manifest": manifest, "completion": completion}


def _record_full_run(sf: Any, seeded: dict[str, Any]) -> None:
    """Mark the seeded full job completed with its REAL completion block."""
    with sf() as s:
        s.execute(
            text(
                "UPDATE job SET state='completed', attempt=1, progress=100, "
                "started_at=CURRENT_TIMESTAMP, finished_at=CURRENT_TIMESTAMP "
                "WHERE id=:id"
            ),
            {"id": seeded["job_id"]},
        )
        step_id = s.scalar(
            text("SELECT id FROM job_step WHERE job_id=:id LIMIT 1"),
            {"id": seeded["job_id"]},
        )
        s.execute(
            text(
                "INSERT INTO job_attempt(id, job_id, step_id, step_code, attempt, "
                "worker_id, fence_token, result_json, error_json, started_at, "
                "finished_at) VALUES (:id, :job, :step, :code, 1, 'mf23-worker', "
                ":tok, :result, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "id": f"attempt-{seeded['job_id']}",
                "job": seeded["job_id"],
                "step": step_id,
                "code": handler.RUN_QC_STEP_CODE,
                "tok": "t" * 32,
                "result": json.dumps(seeded["completion"], sort_keys=True),
            },
        )
        s.commit()


def _gate(sf: Any) -> rd.ExportGateRecord:
    with sf() as s:
        return rd.compute_export_gate(s, workspace_id=WS, project_id=PROJECT)


def _readiness(sf: Any) -> Any:
    with sf() as s:
        return rd.compute_project_readiness(s, workspace_id=WS, project_id=PROJECT)


# ── 23.0 — micro repro: the additive surface ────────────────────────────────


def test_mf23_0_additive_surface_and_legacy_formula(tmp_path: Path) -> None:
    world = _seed_world(tmp_path)
    sf = world["sf"]
    assert qc_compose.OUTPUT_BINDING_SCHEMA == "mf-end-23/output-binding@1"
    assert handler.EVIDENCE_BINDING_SCHEMA == "mf-end-23/evidence-binding@1"
    assert rd.EXPORT_GATE_SCHEMA == "mf-end-23/export-gate@1"
    with sf() as s:
        legacy = handler.legacy_evidence_fingerprint(
            s, workspace_id=WS, video_item_id=VIDEO, generation=GEN
        )
        source = handler.source_artifact_fingerprint(s, video_item_id=VIDEO)
        manual = hashlib.sha256(
            json.dumps(
                {
                    "source_artifact_id": source["source_artifact_id"],
                    "source_sha256": source["source_sha256"],
                    "source_generation": GEN,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        bound = handler.evidence_fingerprint(
            s, workspace_id=WS, video_item_id=VIDEO, generation=GEN, project_id=PROJECT
        )
    assert legacy == manual, "the legacy formula must stay computable bit-for-bit"
    assert bound != legacy, "the output-bound identity must cover more than source"


# ── 23.1 — producer artifacts of the RIGHT publication ──────────────────────


def test_mf23_1_render_row_prefers_publication_then_owned(tmp_path: Path) -> None:
    # (1) completed publication → the publication artifact is the current render
    world_pub = _seed_world(tmp_path / "pub", with_publication=True)
    published = _render_row(world_pub["sf"])
    assert published is not None
    assert published["role"] == "publication"
    assert published["publication"]["publication_id"] == "pub-mf23"
    assert published["publication"]["checkpoint_hash"] == "c" * 64
    assert published["publication"]["frame_count"] == FRAMES
    assert published["artifact"]["artifact_id"] == "art-render"
    assert published["artifact"]["sha256"] == world_pub["render_sha"]
    assert published["unusable"] is None

    # (2) no full-apply run at all → newest render-side artifact owned by video
    world_owned = _seed_world(tmp_path / "owned", with_run=False)
    owned = _render_row(world_owned["sf"])
    assert owned is not None
    assert owned["role"] == "owned_result_artifact"
    assert owned["artifact"]["artifact_id"] == "art-render"
    assert owned["artifact"]["sha256"] == world_owned["render_sha"]
    assert owned["artifact"]["owner_purposes"] == ["result"]
    assert owned["unusable"] is None

    # (3) completed run WITHOUT a completed publication → unusable (the
    # composer refuses the same state as stale; never a silent fallback)
    world_bare = _seed_world(tmp_path / "bare", with_publication=False)
    bare = _render_row(world_bare["sf"])
    assert bare is not None
    assert bare["unusable"] == "completed_run_without_publication"


def test_mf23_1_output_evidence_status_valid_and_typed_refusals(
    tmp_path: Path,
) -> None:
    world = _seed_world(tmp_path)
    sf = world["sf"]
    with sf() as s:
        status = qc_compose.output_evidence_status(
            s,
            managed_root=world["managed"],
            workspace_id=WS,
            project_id=PROJECT,
            video_item_id=VIDEO,
        )
    assert status["state"] == "valid", status.get("detail")
    assert status["checked"]["sealed"]["output"]["sha256"] == world["render_sha"]
    assert status["checked"]["sealed"]["fps_rational"] == FPS

    # observations bound to a DIFFERENT render → stale (never silently fresh)
    stale_world = _seed_world(
        tmp_path / "stale", observations_for_other_render=True
    )
    with stale_world["sf"]() as s:
        stale = qc_compose.output_evidence_status(
            s,
            managed_root=stale_world["managed"],
            workspace_id=WS,
            project_id=PROJECT,
            video_item_id=VIDEO,
        )
    assert stale["state"] == "stale"
    assert stale["code"] == "OUTPUT_STATUS_RENDER_CHANGED"

    # a different timebase is not admissible for this video's canonical fps
    fps_world = _seed_world(tmp_path / "fps", observations_fps="24/1")
    with fps_world["sf"]() as s:
        bad_fps = qc_compose.output_evidence_status(
            s,
            managed_root=fps_world["managed"],
            workspace_id=WS,
            project_id=PROJECT,
            video_item_id=VIDEO,
        )
    assert bad_fps["state"] == "stale"
    assert bad_fps["code"] == "OUTPUT_STATUS_TIMEBASE_CHANGED"

    # bytes on disk divergence → tampered
    tampered_world = _seed_world(tmp_path / "tampered", observations_tampered=True)
    with tampered_world["sf"]() as s:
        tampered = qc_compose.output_evidence_status(
            s,
            managed_root=tampered_world["managed"],
            workspace_id=WS,
            project_id=PROJECT,
            video_item_id=VIDEO,
        )
    assert tampered["state"] == "tampered"

    # no published observations → TYPED missing (producer + persistence named)
    missing_world = _seed_world(tmp_path / "missing", with_observations=False)
    with missing_world["sf"]() as s:
        missing = qc_compose.output_evidence_status(
            s,
            managed_root=missing_world["managed"],
            workspace_id=WS,
            project_id=PROJECT,
            video_item_id=VIDEO,
        )
    assert missing["state"] == "missing"
    assert missing["code"] == "QC_EVIDENCE_MISSING"
    assert "MF-END-21" in missing["detail"] or "rendered-observations" in (
        missing["detail"]
    )


def test_mf23_1_composer_reads_and_binds_the_right_publication(
    tmp_path: Path,
) -> None:
    world = _seed_world(tmp_path)
    sf = world["sf"]
    with sf() as s:
        scope = qc_sources.load_scope(
            s, workspace_id=WS, project_id=PROJECT, video_item_id=VIDEO
        )
        ctx = qc_compose._Context(  # noqa: SLF001 - the band's own context
            session=s, managed_root=world["managed"], scope=scope
        )
        evidence, role, meta = ctx.render("trajectory_drift")
        payload, binding, visibility = qc_compose.compose_output_observations(
            ctx,
            "trajectory_drift",
            render_evidence=evidence,
            render_role=role,
            render_meta=meta,
        )
    assert visibility is None and payload is not None and binding is not None
    assert binding["schema"] == qc_compose.OUTPUT_BINDING_SCHEMA
    assert binding["sealed"]["output"]["sha256"] == world["render_sha"]
    assert binding["sealed"]["digest"] == payload["digest"]
    assert binding["render"]["artifact_id"] == "art-render"
    assert binding["validation"] == {
        "ownership": "video_item_scoped",
        "freshness": "render_sha_match",
        "timebase": FPS,
        "bytes_reverified": True,
    }
    assert binding["artifact"]["bytes_reverified"] is True

    # missing producer → a TYPED visibility block, not a blanket refusal
    missing_world = _seed_world(tmp_path / "missing2", with_observations=False)
    with missing_world["sf"]() as s:
        scope = qc_sources.load_scope(
            s, workspace_id=WS, project_id=PROJECT, video_item_id=VIDEO
        )
        ctx = qc_compose._Context(  # noqa: SLF001
            session=s, managed_root=missing_world["managed"], scope=scope
        )
        evidence, role, meta = ctx.render("trajectory_drift")
        payload, binding, visibility = qc_compose.compose_output_observations(
            ctx,
            "trajectory_drift",
            render_evidence=evidence,
            render_role=role,
            render_meta=meta,
        )
    assert payload is None and binding is None and visibility is not None
    assert visibility["state"] == "missing"
    assert visibility["producer"].startswith("MF-END-21")
    assert "rendered_observations" in visibility["persistence"]

    # observations bound to another render REFUSE (typed stale), never skip
    stale_world = _seed_world(tmp_path / "stale2", observations_for_other_render=True)
    with stale_world["sf"]() as s:
        scope = qc_sources.load_scope(
            s, workspace_id=WS, project_id=PROJECT, video_item_id=VIDEO
        )
        ctx = qc_compose._Context(  # noqa: SLF001
            session=s, managed_root=stale_world["managed"], scope=scope
        )
        evidence, role, meta = ctx.render("trajectory_drift")
        with pytest.raises(Exception) as raised:
            qc_compose.compose_output_observations(
                ctx,
                "trajectory_drift",
                render_evidence=evidence,
                render_role=role,
                render_meta=meta,
            )
    assert "QC_EVIDENCE_STALE" in str(getattr(raised.value, "code", raised.value))


# ── 23.2 — registered checks; audio-only never authoritative ────────────────


def test_mf23_2_audio_only_run_never_produces_export(tmp_path: Path) -> None:
    world = _seed_world(tmp_path)
    sf = world["sf"]
    handler.ensure_full_band_registered()
    with sf() as s:
        from app.persistence.jobs import JobRepository

        band = list(handler.SCOPE_BANDS[handler.SCOPE_AUDIO])
        fp = handler.evidence_fingerprint(
            s, workspace_id=WS, video_item_id=VIDEO, generation=GEN, project_id=PROJECT
        )
        job = JobRepository(s).create_job(
            workspace_id=WS,
            job_type=handler.JOB_TYPE_RUN_QC_CHECKS,
            owner_type="video_item",
            owner_id=VIDEO,
            input_manifest={
                "schema_version": handler.RUN_QC_SCHEMA_VERSION,
                "workspace_id": WS,
                "project_id": PROJECT,
                "video_item_id": VIDEO,
                "scope": handler.SCOPE_AUDIO,
                "scope_fingerprint": handler.scope_fingerprint(handler.SCOPE_AUDIO),
                "evidence_fingerprint": fp,
                "policy_id": handler.policy_bundle()["policy_id"],
                "policy_content_hash": handler.policy_bundle()["policy_content_hash"],
                "source_generation": GEN,
                "detector_args": {name: {} for name in band},
            },
            idempotency_key=f"MF23-AUDIO:{VIDEO}:{fp}",
            input_generation=GEN,
            steps=handler.run_qc_checks_steps(),
            actor="api",
        )
        s.execute(
            text(
                "UPDATE job SET state='completed', attempt=1, progress=100, "
                "started_at=CURRENT_TIMESTAMP, finished_at=CURRENT_TIMESTAMP "
                "WHERE id=:id"
            ),
            {"id": job.id},
        )
        step_id = s.scalar(
            text("SELECT id FROM job_step WHERE job_id=:id LIMIT 1"), {"id": job.id}
        )
        s.execute(
            text(
                "INSERT INTO job_attempt(id, job_id, step_id, step_code, attempt, "
                "worker_id, fence_token, result_json, error_json, started_at, "
                "finished_at) VALUES ('attempt-audio', :job, :step, :code, 1, "
                "'mf23-worker', :tok, :result, NULL, CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP)"
            ),
            {
                "job": job.id,
                "step": step_id,
                "code": handler.RUN_QC_STEP_CODE,
                "tok": "t" * 32,
                "result": json.dumps(
                    {
                        "schema_version": handler.RUN_QC_SCHEMA_VERSION,
                        "job_type": handler.JOB_TYPE_RUN_QC_CHECKS,
                        "completed": True,
                        "scope": handler.SCOPE_AUDIO,
                        "scope_fingerprint": handler.scope_fingerprint(
                            handler.SCOPE_AUDIO
                        ),
                        "evidence_fingerprint": fp,
                        "zero_item_completion": {"evidence": True},
                    }
                ),
            },
        )
        s.commit()
    readiness = _readiness(sf)
    gate = _gate(sf)
    assert readiness.status == rd.READINESS_NOT_RUN
    assert gate.status == rd.EXPORT_NOT_RUN
    assert any(
        b.code == rd.EXPORT_BLOCKED_READINESS for b in gate.blockers
    ), gate.blockers


def test_mf23_2_gate_ready_when_full_run_and_output_evidence_valid(
    tmp_path: Path,
) -> None:
    world = _seed_world(tmp_path)
    sf = world["sf"]
    seeded = _seed_full_run(sf)
    _record_full_run(sf, seeded)
    readiness = _readiness(sf)
    assert readiness.status == rd.READINESS_READY, readiness
    gate = _gate(sf)
    assert gate.status == rd.EXPORT_READY, gate.to_dict()
    record = gate.videos[0]
    assert record.binding_state == "current"
    assert record.output_state == "valid"
    assert sorted(gate.visibility["registered_band"]) == sorted(
        handler.SCOPE_BANDS[handler.SCOPE_FULL]
    )


def test_mf23_2_gate_blocks_band_drift_and_missing_evidence(tmp_path: Path) -> None:
    # (a) unknown detector in the completion → blocked (never a pass)
    world = _seed_world(tmp_path / "band")
    sf = world["sf"]
    seeded = _seed_full_run(
        sf,
        completion_override={
            "detectors": [*handler.SCOPE_BANDS[handler.SCOPE_FULL], "ghost_detector"],
            "detector_revisions": {
                **handler.detector_revisions(handler.SCOPE_BANDS[handler.SCOPE_FULL]),
                "ghost_detector": "9.9.9",
            },
        },
    )
    _record_full_run(sf, seeded)
    gate = _gate(sf)
    codes = {b.code for b in gate.blockers}
    assert gate.status == rd.EXPORT_NOT_RUN  # authority refuses the coverage
    assert rd.EXPORT_BLOCKED_READINESS in codes

    # (b) missing output-observation evidence → blocked with the typed code
    world2 = _seed_world(tmp_path / "noobs", with_observations=False)
    sf2 = world2["sf"]
    seeded2 = _seed_full_run(sf2)
    _record_full_run(sf2, seeded2)
    gate2 = _gate(sf2)
    assert gate2.status == rd.EXPORT_BLOCKED, gate2.to_dict()
    blocking = {b.code for b in gate2.blockers}
    assert rd.EXPORT_BLOCKED_OUTPUT_EVIDENCE in blocking
    assert gate2.videos[0].output_state == "missing"

    # (c) tampered observation bytes → blocked
    world3 = _seed_world(tmp_path / "tamper", observations_tampered=True)
    sf3 = world3["sf"]
    seeded3 = _seed_full_run(sf3)
    _record_full_run(sf3, seeded3)
    gate3 = _gate(sf3)
    assert gate3.videos[0].output_state == "tampered"
    assert rd.EXPORT_BLOCKED_OUTPUT_EVIDENCE in {b.code for b in gate3.blockers}


def test_mf23_2_gate_blocks_binding_tamper(tmp_path: Path) -> None:
    world = _seed_world(tmp_path)
    sf = world["sf"]
    seeded = _seed_full_run(
        sf, manifest_override={"evidence_binding": {"digest": "0" * 64}}
    )
    _record_full_run(sf, seeded)
    gate = _gate(sf)
    assert gate.status == rd.EXPORT_BLOCKED, gate.to_dict()
    assert rd.EXPORT_BLOCKED_STALE_SOURCE in {b.code for b in gate.blockers}
    assert gate.videos[0].binding_state == "source"


# ── 23.3 — render/cast invalidation + finding → shot ────────────────────────


def test_mf23_3_render_change_invalidates_readiness_and_export(
    tmp_path: Path,
) -> None:
    world = _seed_world(tmp_path, with_run=False)
    sf = world["sf"]
    seeded = _seed_full_run(sf)
    _record_full_run(sf, seeded)
    assert _readiness(sf).status == rd.READINESS_READY
    # a NEWER render artifact appears (a re-render / new checkpoint)
    with sf() as s:
        _write_artifact(
            s,
            world["managed"],
            artifact_id="art-render-2",
            rel="render/out_v2.mp4",
            data=b"MF23-CI-RENDER-v2" + b"\x00" * 64,
            kind="video",
            purposes=(("video_item", VIDEO, "result"),),
        )
        s.commit()
    readiness_after = _readiness(sf)
    gate_after = _gate(sf)
    assert readiness_after.status == rd.READINESS_NOT_RUN, readiness_after
    assert gate_after.status == rd.EXPORT_NOT_RUN
    codes = {b.code for b in gate_after.blockers}
    assert rd.EXPORT_BLOCKED_READINESS in codes


def test_mf23_3_cast_change_invalidates_readiness(tmp_path: Path) -> None:
    world = _seed_world(tmp_path)
    sf = world["sf"]
    seeded = _seed_full_run(sf)
    _record_full_run(sf, seeded)
    assert _readiness(sf).status == rd.READINESS_READY
    with sf() as s:
        s.execute(
            text(
                "INSERT INTO character_pack_version(id, character_id, workspace_id, "
                "version, status) VALUES ('pv-mf23b', 'ch-mf23', :w, 2, 'published')"
            ),
            {"w": WS},
        )
        s.execute(
            text(
                "UPDATE project_cast_mapping SET pack_version_id='pv-mf23b', "
                "revision=2 WHERE id='pcm-mf23'"
            )
        )
        s.commit()
    readiness_after = _readiness(sf)
    assert readiness_after.status == rd.READINESS_NOT_RUN
    gate_after = _gate(sf)
    assert gate_after.status == rd.EXPORT_NOT_RUN


def test_mf23_3_shot_intent_maps_finding_to_the_right_shot(tmp_path: Path) -> None:
    world = _seed_world(tmp_path)
    sf = world["sf"]
    with sf() as s:
        repo = QCItemRepository(s)
        item = repo.create(
            workspace_id=WS,
            project_id=PROJECT,
            video_item_id=VIDEO,
            layer_ref_type="segment",
            layer_ref_id="seg-r1",
            reason_code="trajectory_drift",
            evidence_window_key="trajectory_drift:segment:seg-r1:w07-09",
            evidence={
                "frame_start": 7,
                "frame_end": 9,
                "window": {"start_frame": 7, "end_frame_exclusive": 10},
                "object_role_id": ROLE,
            },
            severity="blocker",
            category="trajectory_drift",
            detector="trajectory_drift",
            detector_revision="1.0.0",
            confidence=0.9,
            confidence_source="detector",
            checkpoint_ref="s11-qc-evidence",
        )
        s.commit()
        intent = bridge.shot_correction_intent(s, item, workspace_id=WS)
    assert [shot["shot_id"] for shot in intent.shots] == ["shot-b"]
    assert intent.shots[0]["core_start_frame"] == 6
    assert intent.window == {"start_frame": 7, "end_frame": 9}
    assert intent.render_artifact_id == "art-render"
    assert intent.render_sha256 == world["render_sha"]
    assert intent.to_dict()["kind"] == "shot_correction"

    # a window outside every shot is REFUSED (never routed to a guess)
    with sf() as s:
        outside = QCItemRepository(s).create(
            workspace_id=WS,
            project_id=PROJECT,
            video_item_id=VIDEO,
            layer_ref_type="segment",
            layer_ref_id="seg-r1",
            reason_code="trajectory_drift",
            evidence_window_key="trajectory_drift:segment:seg-r1:w40-44",
            evidence={"frame_start": 40, "frame_end": 44},
            severity="blocker",
            category="trajectory_drift",
            detector="trajectory_drift",
            detector_revision="1.0.0",
            confidence=0.9,
            confidence_source="detector",
            checkpoint_ref="s11-qc-evidence",
        )
        s.commit()
        with pytest.raises(bridge.QcCorrectionBridgeError) as raised:
            bridge.shot_correction_intent(s, outside, workspace_id=WS)
    assert raised.value.code == "CORRECTION_SHOT_UNRESOLVED"

    # no structured window at all → REFUSED (no guessing from free text)
    with sf() as s:
        blind = QCItemRepository(s).create(
            workspace_id=WS,
            project_id=PROJECT,
            video_item_id=VIDEO,
            layer_ref_type="video_item",
            layer_ref_id=VIDEO,
            reason_code="trajectory_drift",
            evidence_window_key="trajectory_drift:video_item:w-none",
            evidence={"note": "no anchors"},
            severity="warning",
            category="trajectory_drift",
            detector="trajectory_drift",
            detector_revision="1.0.0",
            confidence=0.5,
            confidence_source="detector",
            checkpoint_ref="s11-qc-evidence",
        )
        s.commit()
        with pytest.raises(bridge.QcCorrectionBridgeError):
            bridge.shot_correction_intent(s, blind, workspace_id=WS)


def test_mf23_3_render_anchor_in_stale_evidence(tmp_path: Path) -> None:
    world = _seed_world(tmp_path, with_run=False)
    sf = world["sf"]
    with sf() as s:
        item = QCItemRepository(s).create(
            workspace_id=WS,
            project_id=PROJECT,
            video_item_id=VIDEO,
            layer_ref_type="segment",
            layer_ref_id="seg-r1",
            reason_code="trajectory_drift",
            evidence_window_key="trajectory_drift:segment:seg-r1:w0-2",
            evidence={
                "frame_start": 0,
                "frame_end": 2,
                "render_artifact_id": "art-render",
                "render_sha256": world["render_sha"],
            },
            severity="warning",
            category="trajectory_drift",
            detector="trajectory_drift",
            detector_revision="1.0.0",
            confidence=0.5,
            confidence_source="detector",
            checkpoint_ref="s11-qc-evidence",
        )
        s.commit()
        fresh = bridge.check_stale_evidence(s, item, workspace_id=WS)
    assert fresh.stale is False

    with sf() as s:
        _write_artifact(
            s,
            world["managed"],
            artifact_id="art-render-3",
            rel="render/out_v3.mp4",
            data=b"MF23-CI-RENDER-v3" + b"\x00" * 64,
            kind="video",
            purposes=(("video_item", VIDEO, "result"),),
        )
        s.commit()
        stale = bridge.check_stale_evidence(s, item, workspace_id=WS)
    assert stale.stale is True
    assert stale.anchor == "render_changed"


# ── 23.4 — the old authority is untouched; measured transport rule ──────────


def test_mf23_4_old_authority_contract_unchanged(tmp_path: Path) -> None:
    world = _seed_world(tmp_path)
    sf = world["sf"]
    readiness = _readiness(sf)
    # same shape/verbs as before MF-END-23 (Decision F aggregate untouched)
    assert readiness.status == rd.READINESS_NOT_RUN
    assert readiness.policy_version == rd.POLICY_ID
    assert readiness.content_hash
    assert [v.video_item_id for v in readiness.videos] == [VIDEO]
    assert readiness.videos[0].run_state == "never_run"
    policy = handler.policy_bundle()
    assert readiness.policy_version == policy["policy_id"]
    assert readiness.content_hash == policy["policy_content_hash"]


def test_mf23_4_transport_rule_is_the_measured_one() -> None:
    import subprocess

    args = {f"k{index:05d}": "v" * 8 for index in range(500)}
    escaped = qc_compose._argv_transport_bytes(args)  # noqa: SLF001
    raw = len(qc_compose._runner_argv_json(args))  # noqa: SLF001
    assert escaped == len(
        subprocess.list2cmdline([qc_compose._runner_argv_json(args)])  # noqa: SLF001
    )
    assert escaped > raw, "every quote costs an escape character on this host"
    assert (
        qc_compose.ARGV_RUNNER_COMMANDLINE_OVERHEAD_BYTES
        + qc_compose.ARGV_CEILING_SPAWN_OK_BYTES
    ) > qc_compose.ARGV_CEILING_WINERROR_206_BYTES
