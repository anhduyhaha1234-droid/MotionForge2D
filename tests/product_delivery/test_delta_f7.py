"""DELTA-F7 — Export sản phẩm mang AUDIO GỐC (publication là video-only).

Row map (binary; every row runs REAL code over REAL temp databases, REAL
managed roots and the REAL MF-DEMO-E2E-R4 run artifacts — nothing is mocked
at the code level):

* F7.0 — the fixtures ARE the real R4 run artifacts (sha256 + size +
  measured streams): the 12s source (AAC 48k stereo), the publication
  ``075133f3…`` (video-only, a:0), the attach receipt (202 → completed);
* F7.1 (RED-on-base repro) — the R4 data path over the REAL T03C export
  world: publication artifact → the real video-only publication, the
  VideoItem source artifact → the real source, the attached original-audio
  artifact → the real attach output (S11 remux engine, STREAM_COPY).  The
  submit must resolve the manifest audio to the ATTACHED artifact
  (``original_audio_attach``) with the publication probe recorded absent.
  On the base commit this row observes ``audio_source=None`` — the defect;
* F7.2 — without an attach artifact the resolution falls back to the
  VideoItem's CURRENT source artifact (mode ``source_artifact``) — the
  canonical first audio stream, measured;
* F7.3 (honest negative) — a source that GENUINELY has no audio: the
  resolution returns None with ``mode="absent"`` and the measured fallback
  attempts, and the export master stays silently video-only (a:0) — no
  fabricated audio anywhere;
* F7.4 (ACCEPTANCE) — the app's export path (route submit → durable job →
  real runner/stitch/ffmpeg → REAL output validation) produces an MP4 that
  carries the ORIGINAL audio (AAC 48k stereo) with the full frame count and
  reopens decodable; the publication stays video-only;
* F7.5 — regression/precedence: a publication that DOES carry audio keeps
  the legacy resolution (mode ``source_remux``, path == publication) even
  when source/attach artifacts exist;
* F7.6 — the retry leg resolves the same fallback: a cancelled
  predecessor's successor manifest carries the attached original audio.

Disclosures (no green-by-fabrication): the export world is the REAL
S12-T03C harness (``tests/s12/s12-lc3-retry`` — durable JobService +
seeded S10 authority + structural lock), re-used read-only; the only
substituted boundary is the frozen QC readiness aggregate (Decision F)
that the harness itself substitutes.  F7.1/F7.2/F7.5 run over the REAL R4
fixtures (publication ``075133f3…``, source ``fc18e859…``); the full-path
rows (F7.3/F7.4/F7.6) need a publication matching the harness run pins
(fps/frames), so they use a generated harness-shaped VIDEO-ONLY publication
— the identical defect mechanism at the run's own timeline — with a
harness-shaped source carrying AAC 48k stereo audio.  The attach artifact
is REGENERATED with the REAL S11 remux engine over that source; over the
REAL R4 source fixture it is byte-deterministic and matches the R4 attach
job's artifact (sha256 4d0d3611…, 629508 B measured on the R4 runtime DB
row).  The output validator's approved-audio reference is the manifest's
server-resolved ``audio_source`` (DELTA-F7; ``publication.py`` is a
disclosed protected change — see REPORT).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

from app.services import original_audio_remux as remux
from app.workflow import s12_export_jobs as jobs

WT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "delta_f7"


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: REAL S12-T03C worker harness (read-only reuse, S12-LC3 lane).
_RETRY = _load_module(
    "f7_retry_harness",
    WT / "tests" / "s12" / "s12-lc3-retry" / "test_s12_t03c_c1_closure.py",
)
route = _RETRY.route
WS = _RETRY.WS
PROJECT = f"p-{WS}"
VIDEO = f"v-{WS}"
FPS = _RETRY.FPS
FRAMES = _RETRY.FRAMES
CHK_HASH = _RETRY.CHK_HASH

# ── The REAL MF-DEMO-E2E-R4 artifacts (recorded from the R4 runtime) ────────

R4_SOURCE_SHA = "fc18e859599f8feeb730ee9018413ced4c183f90a15e20ccc162433c4666c8cc"
R4_SOURCE_BYTES = 629545
R4_PUBLICATION_SHA = (
    "075133f3d2d6918d7cff3a036d7234ce64e154b06b09fe8dbc4b1b04ff9fa269"
)
R4_PUBLICATION_BYTES = 3840735
R4_RECEIPT_SHA = "ecf59c93628200841a672d0c47a3c5d7be5e6df2c798540c994abfa09fd0fab2"
R4_ATTACH_JOB_ID = "3a1dbde3-27df-4ce3-b2bd-61bfb0ce2101"


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not on PATH (real-media rows need the real binary)")
    return ffmpeg


def _probe(path: Path) -> Any:
    return remux.probe_original_audio(path)


def _world(tmp_path: Path) -> SimpleNamespace:
    """One fresh REAL T03C world (per test; two engines disposed on exit)."""
    fixture = getattr(_RETRY.env, "__wrapped__", _RETRY.env)
    root = tmp_path / "retry"
    root.mkdir(parents=True, exist_ok=True)
    factory, svc, manifest_id, auth, _dirs, managed = next(fixture(root))
    return SimpleNamespace(
        factory=factory,
        svc=svc,
        manifest_id=manifest_id,
        auth=auth,
        managed=managed,
    )


def _make_clip(
    path: Path,
    *,
    audio: bool,
    seconds: float,
    rate: int,
    size: str = "320x180",
    sample_rate: int = 44100,
) -> Path:
    """Real CFR H.264 clip; optional REAL AAC stereo audio (the proof shape)."""
    cmd = [
        _ffmpeg(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={size}:rate={rate}:duration={seconds}",
    ]
    if audio:
        cmd += [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate={sample_rate}:duration={seconds}",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-ar",
            str(sample_rate),
            "-shortest",
        ]
    else:
        cmd += ["-an"]
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
    assert path.is_file() and path.stat().st_size > 0
    return path


def _seed_r4_path(
    world: SimpleNamespace,
    *,
    attach: bool = True,
    source: str = "r4",
    publication: str = "r4",
) -> SimpleNamespace:
    """Seed the R4 data path into the REAL world.

    ``publication``: ``"r4"`` — the real R4 video-only publication fixture;
    ``"harness"`` — a generated harness-shaped VIDEO-ONLY publication (the
    same defect mechanism at the run's own fps/frames); ``"with_audio"`` —
    a generated publication that DOES carry audio (precedence regression).
    ``source``: ``"r4"`` — the real R4 source; ``"small"`` — a harness-shaped
    source carrying the original audio (AAC 48k stereo — the R4 source's
    measured shape); ``"silent"`` — a source that genuinely has no audio
    stream.  Returns the placed paths.
    """
    managed = world.managed
    pub_rel = f"apply/{world.auth['artifact_id']}.mp4"
    pub_dest = managed / pub_rel
    pub_dest.parent.mkdir(parents=True, exist_ok=True)
    if publication == "r4":
        shutil.copyfile(FIXTURES / "publication.mp4", pub_dest)
        pub_sha = R4_PUBLICATION_SHA
    elif publication == "harness":
        _make_clip(pub_dest, audio=False, seconds=FRAMES / FPS, rate=FPS)
        pub_sha = _sha_file(pub_dest)
    else:
        _make_clip(pub_dest, audio=True, seconds=FRAMES / FPS, rate=FPS)
        pub_sha = _sha_file(pub_dest)

    src_rel = "sources/source_12s.mp4"
    src_dest = managed / src_rel
    src_dest.parent.mkdir(parents=True, exist_ok=True)
    if source == "r4":
        shutil.copyfile(FIXTURES / "source_12s.mp4", src_dest)
        src_sha = R4_SOURCE_SHA
        src_bytes = R4_SOURCE_BYTES
    elif source == "small":
        # Harness-shaped source carrying the ORIGINAL audio (AAC 48k stereo —
        # the R4 source's measured shape) for the full-path rows.
        _make_clip(
            src_dest,
            audio=True,
            seconds=FRAMES / FPS,
            rate=FPS,
            size="640x360",
            sample_rate=48000,
        )
        src_sha = _sha_file(src_dest)
        src_bytes = src_dest.stat().st_size
    else:
        # A source that GENUINELY has no audio (a:0) — the honest-negative row.
        _make_clip(
            src_dest, audio=False, seconds=FRAMES / FPS, rate=FPS, size="640x360"
        )
        src_sha = _sha_file(src_dest)
        src_bytes = src_dest.stat().st_size

    with world.factory() as session:
        session.execute(
            text(
                "UPDATE artifact SET relative_path=:rel, sha256=:sha WHERE id=:aid"
            ),
            {"rel": pub_rel, "sha": pub_sha, "aid": world.auth["artifact_id"]},
        )
        session.execute(
            text(
                "INSERT INTO artifact(id,workspace_id,kind,relative_path,state,"
                "sha256,size_bytes,revision) VALUES "
                "(:a,:w,'video',:rel,'ready',:sha,:n,1)"
            ),
            {
                "a": "art-f7-src",
                "w": WS,
                "rel": src_rel,
                "sha": src_sha,
                "n": src_bytes,
            },
        )
        session.execute(
            text("UPDATE video_item SET source_artifact_id=:a WHERE id=:v"),
            {"a": "art-f7-src", "v": VIDEO},
        )
        session.execute(
            text(
                "INSERT INTO artifact_owner(artifact_id,owner_type,owner_id,purpose)"
                " VALUES ('art-f7-src','video_item',:v,'source')"
            ),
            {"v": VIDEO},
        )
        session.commit()

    attach_rel: str | None = None
    attach_dest: Path | None = None
    if attach:
        # The REAL S11 remux engine publishes the attach output (STREAM_COPY
        # of the canonical first audio stream) — same bytes as R4's attach.
        engine_dir = managed / f"artifacts/{WS}/audio/job-f7-attach/attach"
        result = remux.remux_original_audio(src_dest, engine_dir)
        assert result.status == remux.STATUS_STREAM_COPY, result.status
        assert result.output_path is not None and result.output_sha256
        attach_dest = Path(result.output_path)
        attach_rel = str(attach_dest.relative_to(managed)).replace("\\", "/")
        with world.factory() as session:
            session.execute(
                text(
                    "INSERT INTO artifact(id,workspace_id,kind,relative_path,state,"
                    "sha256,size_bytes,revision) VALUES "
                    "('art-f7-attach',:w,'audio',:rel,'ready',:sha,:n,1)"
                ),
                {
                    "w": WS,
                    "rel": attach_rel,
                    "sha": result.output_sha256,
                    "n": result.output_size_bytes,
                },
            )
            session.execute(
                text(
                    "INSERT INTO artifact_owner(artifact_id,owner_type,owner_id,"
                    "purpose) VALUES ('art-f7-attach','video_item',:v,"
                    "'original_audio')"
                ),
                {"v": VIDEO},
            )
            session.commit()

    return SimpleNamespace(
        publication=pub_dest,
        source=src_dest,
        attach_dest=attach_dest,
        attach_rel=attach_rel,
    )


def _ready_boundary(mp: pytest.MonkeyPatch) -> None:
    """Decision F boundary: the frozen QC readiness aggregate, WITH the video.

    Production readiness needs a completed CURRENT FULL QC band run — a
    T03G/T04A-lane fixture this lane does not own; the export submit and
    publish legs consume the SAME aggregate.  Only its verdict (and the
    video list the publish leg iterates) is substituted — every other step
    stays REAL (the identical substitution the MF-END-26 delivery made).
    """
    mp.setattr(
        "app.persistence.readiness.compute_project_readiness",
        lambda session, **kw: SimpleNamespace(
            status="ready", videos=[SimpleNamespace(video_item_id=VIDEO)]
        ),
    )
    mp.setattr(
        "app.services.s12_export.publication._check_run_readiness",
        lambda session, **kw: "ready",
    )


@contextmanager
def _submitted(world: SimpleNamespace) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """Submit the export through the REAL route and yield (out, manifest)."""
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(route, "get_job_service", lambda: world.svc)
        mp.setattr(route, "get_managed_root", lambda: world.managed)
        mp.setattr("app.api.deps.get_managed_root", lambda: world.managed)
        _ready_boundary(mp)
        body = _RETRY._authority_body(world.factory, world.auth, world.manifest_id)
        with world.factory() as session:
            out = route.submit_export(
                route.S12ExportSubmitRequest(**body), session, workspace_id=WS
            )
            session.commit()
        yield out, _manifest_of(world, out["job_id"])
    finally:
        mp.undo()


def _manifest_of(world: SimpleNamespace, job_id: str) -> dict[str, Any]:
    from app.persistence.models import Job as JobRow

    with world.factory() as session:
        row = session.get(JobRow, job_id)
        assert row is not None
        return json.loads(row.input_manifest_json)


def _run_handler(world: SimpleNamespace, manifest: dict[str, Any]) -> dict[str, Any]:
    ctx = SimpleNamespace(
        worker_id="worker-f7",
        session_factory=world.factory,
        input_manifest=manifest,
    )
    return _RETRY._s12_export_handler(ctx)


def _ffprobe_frames(path: Path) -> int:
    ffprobe = shutil.which("ffprobe")
    assert ffprobe, "ffprobe required"
    out = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    return int(json.loads(out.stdout)["streams"][0]["nb_read_frames"])


# ── F7.0 — the fixtures ARE the real R4 run artifacts ───────────────────────


def test_delta_f7_0_fixtures_are_the_real_r4_run_artifacts() -> None:
    source = FIXTURES / "source_12s.mp4"
    publication = FIXTURES / "publication.mp4"
    receipt = json.loads((FIXTURES / "audio_receipt.json").read_text("utf-8"))
    assert _sha_file(source) == R4_SOURCE_SHA
    assert source.stat().st_size == R4_SOURCE_BYTES
    assert _sha_file(publication) == R4_PUBLICATION_SHA
    assert publication.stat().st_size == R4_PUBLICATION_BYTES
    assert _sha_file(FIXTURES / "audio_receipt.json") == R4_RECEIPT_SHA
    # the real R4 attach receipt: 202 → completed (the audio was attached).
    assert receipt["status"] == 202
    assert receipt["job_id"] == R4_ATTACH_JOB_ID
    assert receipt["final_state"] == "completed"
    # measured shapes: source carries AAC 48k stereo; publication is a:0.
    src_probe = _probe(source)
    assert src_probe.present is True
    assert src_probe.codec == "aac"
    assert src_probe.sample_rate == 48000 and src_probe.channels == 2
    pub_probe = _probe(publication)
    assert pub_probe.present is False
    assert "no audio stream" in str(pub_probe.detail)


# ── F7.1 — RED-on-base repro: the R4 path resolves the attached audio ───────


def test_delta_f7_1_export_resolves_attached_original_audio(tmp_path: Path) -> None:
    """The defect repro: on base the manifest audio is None (publication a:0)."""
    world = _world(tmp_path)
    placed = _seed_r4_path(world)
    assert placed.attach_dest is not None
    with _submitted(world) as (out, manifest):
        assert out["job_id"]
        # NOT the publication — the R4 defect was probing exactly that file.
        assert str(placed.publication) != str(placed.attach_dest)
        assert manifest["audio_source"] == str(placed.attach_dest)
        provenance = manifest["audio_provenance"]
        assert provenance["mode"] == jobs.AUDIO_FALLBACK_MODE_ATTACH
        assert provenance["artifact_id"] == "art-f7-attach"
        assert provenance["codec"] == "aac"
        assert provenance["sample_rate"] == 48000
        assert provenance["channels"] == 2
        # the publication probe itself is recorded, honestly absent
        assert provenance["publication_probe"]["mode"] == "absent"
        assert (
            provenance["publication_probe"]["source"]
            == "completed_publication_artifact"
        )


# ── F7.2 — fallback to the VideoItem's current source artifact ──────────────


def test_delta_f7_2_falls_back_to_video_item_source_artifact(tmp_path: Path) -> None:
    world = _world(tmp_path)
    placed = _seed_r4_path(world, attach=False)
    with _submitted(world) as (out, manifest):
        assert out["job_id"]
        assert manifest["audio_source"] == str(placed.source)
        provenance = manifest["audio_provenance"]
        assert provenance["mode"] == jobs.AUDIO_FALLBACK_MODE_SOURCE
        assert provenance["codec"] == "aac"
        assert provenance["sample_rate"] == 48000
        assert provenance["channels"] == 2
        assert provenance["publication_probe"]["mode"] == "absent"


# ── F7.3 — honest negative: a source that genuinely has no audio ────────────


def test_delta_f7_3_honest_absent_when_source_has_no_audio(tmp_path: Path) -> None:
    """No fabricated audio: absent everywhere ⇒ None + measured attempts."""
    world = _world(tmp_path)
    _seed_r4_path(world, attach=False, source="silent", publication="harness")
    with _submitted(world) as (out, manifest):
        assert manifest["audio_source"] is None
        provenance = manifest["audio_provenance"]
        assert provenance["mode"] == "absent"
        attempts = provenance["fallbacks"]
        assert attempts, "the fallback candidates must be measured, not assumed"
        source_attempt = [a for a in attempts if a["mode"] == "source_artifact"]
        assert source_attempt, attempts
        assert source_attempt[0]["outcome"] == "absent"
        assert "no audio stream" in str(source_attempt[0]["detail"])
        # the export still runs — honestly silent (video-only), nothing faked.
        result = _run_handler(world, manifest)
        assert result["status"] == "completed", result
        final = Path(out["output_path"])
        assert final.is_file() and final.stat().st_size > 0
        assert _probe(final).present is False
        assert _ffprobe_frames(final) == FRAMES


# ── F7.4 — ACCEPTANCE: the export master carries the ORIGINAL audio ─────────


def test_delta_f7_4_export_end_to_end_carries_original_audio(tmp_path: Path) -> None:
    """submit → durable job → real runner/stitch → master with original audio."""
    _ffmpeg()
    world = _world(tmp_path)
    placed = _seed_r4_path(world, source="small", publication="harness")
    with _submitted(world) as (out, manifest):
        assert manifest["audio_source"] == str(placed.attach_dest)
        result = _run_handler(world, manifest)
        assert result["status"] == "completed", result
        with world.factory() as session:
            run = _RETRY.S12ExportRepository(session).get_run(out["run_id"])
        assert run.status == "completed"
        final = Path(out["output_path"])
        assert final.is_file() and final.stat().st_size > 0
        probe = _probe(final)
        assert probe.present is True, "exported MP4 must carry the original audio"
        assert probe.codec == "aac"
        assert probe.sample_rate == 48000 and probe.channels == 2
        assert _ffprobe_frames(final) == FRAMES
        dec = subprocess.run(
            [
                _ffmpeg(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(final),
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert dec.returncode == 0, dec.stderr
        assert dec.stderr.strip() == "", dec.stderr


# ── F7.5 — regression: a publication WITH audio keeps the legacy path ───────


def test_delta_f7_5_publication_with_audio_keeps_legacy_resolution(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    placed = _seed_r4_path(world, publication="with_audio")
    with _submitted(world) as (out, manifest):
        assert out["job_id"]
        # precedence: the publication probe wins even with attach/source present
        assert manifest["audio_source"] == str(placed.publication)
        provenance = manifest["audio_provenance"]
        assert provenance["mode"] == "source_remux"
        assert provenance["source"] == "completed_publication_artifact"


# ── F7.6 — the retry leg resolves the same fallback ─────────────────────────


def test_delta_f7_6_retry_leg_resolves_the_fallback(tmp_path: Path) -> None:
    world = _world(tmp_path)
    placed = _seed_r4_path(world, source="small", publication="harness")
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(route, "get_job_service", lambda: world.svc)
        mp.setattr(route, "get_managed_root", lambda: world.managed)
        mp.setattr("app.api.deps.get_managed_root", lambda: world.managed)
        _ready_boundary(mp)
        body = _RETRY._authority_body(world.factory, world.auth, world.manifest_id)
        # Direct route calls: the Query(...) defaults only materialise under
        # HTTP, so every optional parameter is passed explicitly.
        with world.factory() as session:
            out = route.submit_export(
                route.S12ExportSubmitRequest(**body), session, workspace_id=WS
            )
            session.commit()
        with world.factory() as session:
            cancel_out = route.cancel_export(
                out["run_id"], session, workspace_id=WS, project_id=None
            )
            session.commit()
        assert cancel_out["cancelled"] is True
        with world.factory() as session:
            retry_out = route.retry_export(
                out["run_id"],
                session,
                workspace_id=WS,
                project_id=None,
                client_id=None,
            )
            session.commit()
        assert retry_out["run_id"] != out["run_id"]
        successor = _manifest_of(world, retry_out["job_id"])
        assert successor["audio_source"] == str(placed.attach_dest)
        assert (
            successor["audio_provenance"]["mode"]
            == jobs.AUDIO_FALLBACK_MODE_ATTACH
        )
        assert successor["predecessor_run_id"] == out["run_id"]
    finally:
        mp.undo()
