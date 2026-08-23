"""Focused S08-H02 security tests (+ C1 correction round).

Exercises the real FastAPI app through the conftest ``client`` fixture
(never a bare TestClient).  C1 acceptance coverage:

- A: server-owned upload filename; project.json / reserved names immutable,
      case-insensitive; client filename is metadata only; traversal/backslash
      filenames never escape.
- B: REAL ffprobe validation (fake ftyp + zeros => 415; valid MP4 => ok
      stored under a server-owned name).
- C: image fully decoded (truncated with valid magic => 415); dimension and
      total-pixel caps; correct extension + Content-Type per verified format.
- D: staging/publish temps cleaned on all error paths; metadata-update
      failure rolls file(s) + state back; existing replacement never destroyed.
- E: traversal identifiers rejected before any join; replacement GET cannot
      read a file outside the project root; delete never removes outside root;
      absolute / ``..`` asset paths rejected by replacement-settings.
- F: trusted/untrusted origin + happy paths (previous round) still pass.
"""

from __future__ import annotations

import dataclasses
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.security import (
    InvalidPathIdentifierError,
    validate_path_identifier,
)
from app.schemas import ReplacementConfig, ReplacementMode
from app.services.media_validation import (
    MediaValidationError,
    probe_image,
    sniff_video_container,
)

TRUSTED = "http://trusted.example"
UNTRUSTED = "http://evil.example"


# ── real-media helpers (no fake video data) ─────────────────────────────────


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _make_mp4(path: Path) -> Path:
    """A real, ffprobe-decodable MP4 via ffmpeg (never fake bytes)."""
    if not _ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe not available")
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        shutil.which("ffmpeg") or "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", "color=c=black:duration=0.3:size=64x64:rate=10",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "30",
        "-pix_fmt", "yuv420p",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return path


@pytest.fixture(scope="module")
def real_mp4_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _make_mp4(tmp_path_factory.mktemp("h02c1") / "real-video.mp4")


def _png_bytes(width: int = 16, height: int = 16, value: int = 128) -> bytes:
    ok, enc = cv2.imencode(
        ".png", np.full((height, width, 3), value, dtype=np.uint8)
    )
    assert ok
    return enc.tobytes()


def _jpeg_bytes(width: int = 16, height: int = 16, value: int = 128) -> bytes:
    ok, enc = cv2.imencode(
        ".jpg", np.full((height, width, 3), value, dtype=np.uint8)
    )
    assert ok
    return enc.tobytes()


def _webp_bytes(width: int = 16, height: int = 16, value: int = 128) -> bytes:
    ok, enc = cv2.imencode(
        ".webp", np.full((height, width, 3), value, dtype=np.uint8)
    )
    assert ok
    return enc.tobytes()


# ── helper utilities ─────────────────────────────────────────────────────────


def _set_origins(monkeypatch: pytest.MonkeyPatch, *origins: str) -> None:
    cfg = dataclasses.replace(deps._config, cors_origins=tuple(origins))
    monkeypatch.setattr(deps, "_config", cfg)


def _set_upload_limit(
    monkeypatch: pytest.MonkeyPatch, limit: int, *, image: bool = False
) -> None:
    field = "max_image_upload_bytes" if image else "max_upload_bytes"
    cfg = dataclasses.replace(deps._config, **{field: limit})
    monkeypatch.setattr(deps, "_config", cfg)


def _set_image_caps(
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_dimension: int | None = None,
    max_pixels: int | None = None,
) -> None:
    kwargs: dict[str, object] = {}
    if max_dimension is not None:
        kwargs["max_image_dimension"] = max_dimension
    if max_pixels is not None:
        kwargs["max_image_pixels"] = max_pixels
    cfg = dataclasses.replace(deps._config, **kwargs)
    monkeypatch.setattr(deps, "_config", cfg)


def _create_project(client: TestClient, name: str = "H02-Project") -> str:
    resp = client.post("/api/projects", json={"name": name})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["project_id"])


def _project_dir(project_id: str) -> Path:
    return Path(deps._config.project_root) / "projects" / project_id


def _create_object(client: TestClient, project_id: str) -> str:
    """Create a tracked object (with a frame on disk like the productive path)."""
    proj_root = Path(deps._config.project_root)
    frame_dir = proj_root / "projects" / project_id / "frames" / "scene_0"
    frame_dir.mkdir(parents=True, exist_ok=True)
    frame = np.full((200, 200, 3), 255, dtype=np.uint8)
    frame[50:150, 50:150] = (0, 0, 0)
    assert cv2.imwrite(str(frame_dir / "frame_000000.png"), frame)

    payload = {
        "name": "Vật thể #1",
        "selection": {
            "mode": "bounding_box",
            "frame_index": 0,
            "x": 60,
            "y": 60,
            "width": 80,
            "height": 80,
        },
        "scene_id": 0,
    }
    resp = client.post(f"/api/projects/{project_id}/objects", json=payload)
    assert resp.status_code == 201, resp.text
    return str(resp.json()["object_id"])


def _staging_leftovers(project_id: str) -> list[Path]:
    proj_dir = _project_dir(project_id)
    if not proj_dir.is_dir():
        return []
    return sorted(
        p
        for p in proj_dir.rglob("*")
        if ".staging" in p.name or ".replacement-publish-" in p.name
    )


def _upload_video(client: TestClient, project_id: str, filename: str, content: bytes):
    return client.post(
        f"/api/projects/{project_id}/video",
        files={"file": (filename, content, "video/mp4")},
    )


# ── AC1/AC2 — allowlist config, no wildcard, no credentials ─────────────────


def test_config_allowlist_never_wildcard_no_credentials() -> None:
    cfg = deps.get_config()
    assert "*" not in cfg.cors_origins
    assert cfg.cors_allow_credentials is False


def test_validate_path_identifier_accepts_real_ids() -> None:
    assert validate_path_identifier("ab12cd34ef56") == "ab12cd34ef56"
    assert validate_path_identifier("a-b_c.d") == "a-b_c.d"


def test_validate_path_identifier_rejects_traversal() -> None:
    for bad in ("..", "../etc", "..\\..\\etc", "a/b", "a\\b", ".", "", "ab\x00cd"):
        with pytest.raises(InvalidPathIdentifierError):
            validate_path_identifier(bad)
    with pytest.raises(InvalidPathIdentifierError):
        validate_path_identifier("x" * 201)


# ── AC3 — untrusted / null origin state-changing => 403, zero side effect ───


def test_untrusted_origin_state_changing_403_zero_side_effect(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_origins(monkeypatch, TRUSTED)
    resp = client.post(
        "/api/projects",
        json={"name": "Evil Project"},
        headers={"Origin": UNTRUSTED},
    )
    assert resp.status_code == 403
    listing = client.get("/api/projects")
    assert listing.status_code == 200
    assert listing.json() == []


def test_origin_null_state_changing_403(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_origins(monkeypatch, TRUSTED)
    resp = client.post(
        "/api/projects",
        json={"name": "Null Origin Project"},
        headers={"Origin": "null"},
    )
    assert resp.status_code == 403
    assert client.get("/api/projects").json() == []


def test_untrusted_origin_put_patch_delete_403(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_origins(monkeypatch, TRUSTED)
    project_id = _create_project(client)
    for method in ("post", "put", "patch", "delete"):
        kwargs: dict[str, object] = {"headers": {"Origin": UNTRUSTED}}
        if method != "delete":
            kwargs["json"] = {"name": "x"}
        resp = getattr(client, method)(
            f"/api/projects/{project_id}", **kwargs,
        )
        assert resp.status_code == 403, method


# ── AC4/AC5 — trusted origins work; no-Origin local contract works ──────────


def test_trusted_origin_works_and_gets_acao(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_origins(monkeypatch, TRUSTED)
    resp = client.post(
        "/api/projects",
        json={"name": "Trusted Project"},
        headers={"Origin": TRUSTED},
    )
    assert resp.status_code == 201, resp.text
    assert resp.headers.get("access-control-allow-origin") == TRUSTED
    assert "access-control-allow-credentials" not in resp.headers


def test_no_origin_local_contract_works(client: TestClient) -> None:
    project_id = _create_project(client)
    assert project_id
    resp = client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 200


# ── AC6 — preflight handling ────────────────────────────────────────────────


def test_untrusted_preflight_403_no_acao(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_origins(monkeypatch, TRUSTED)
    resp = client.options(
        "/api/projects",
        headers={
            "Origin": UNTRUSTED,
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code == 403
    assert "access-control-allow-origin" not in resp.headers


def test_trusted_preflight_gets_acao_no_credentials(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_origins(monkeypatch, TRUSTED)
    resp = client.options(
        "/api/projects",
        headers={
            "Origin": TRUSTED,
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == TRUSTED
    assert "access-control-allow-credentials" not in resp.headers


# ── A + B + D — video upload: server-owned name, real probe, cleanup ────────


def test_valid_video_upload_ok_server_owned_name(
    client: TestClient, real_mp4_file: Path,
) -> None:
    project_id = _create_project(client)
    content = real_mp4_file.read_bytes()
    resp = _upload_video(client, project_id, "mymovie.mp4", content)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    # A: the stored name is SERVER-OWNED; the client name is metadata only.
    stored_name = body["filename"]
    assert stored_name.startswith("source_") and stored_name.endswith(".mp4")
    assert body["original_filename"] == "mymovie.mp4"
    proj_dir = _project_dir(project_id)
    stored = proj_dir / stored_name
    assert stored.is_file()
    assert stored.read_bytes() == content
    assert not (proj_dir / "mymovie.mp4").exists()
    assert _staging_leftovers(project_id) == []


def test_fake_ftyp_only_rejected_415_no_state_change(
    client: TestClient,
) -> None:
    project_id = _create_project(client)
    before = (_project_dir(project_id) / "project.json").read_bytes()
    resp = _upload_video(
        client, project_id, "clip.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2mp41" + b"\x00" * 256,
    )
    assert resp.status_code == 415
    # B: probe failure => no file created, no project state change.
    assert (_project_dir(project_id) / "project.json").read_bytes() == before
    assert _staging_leftovers(project_id) == []
    proj_dir = _project_dir(project_id)
    assert not list(proj_dir.glob("source_*.mp4"))


def test_malformed_video_rejected_415_and_cleaned(
    client: TestClient,
) -> None:
    project_id = _create_project(client)
    resp = _upload_video(client, project_id, "clip.mp4", b"\x00" * 200)
    assert resp.status_code == 415
    assert _staging_leftovers(project_id) == []


def test_oversized_video_rejected_413_and_cleaned(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = _create_project(client)
    _set_upload_limit(monkeypatch, 128, image=False)
    payload = b"\x00" * 64 + b"ftyp" + b"\x00" * 512  # 576 bytes > 128 limit
    resp = _upload_video(client, project_id, "big.mp4", payload)
    assert resp.status_code == 413
    assert _staging_leftovers(project_id) == []


# ── A — hostile filenames can never touch project.json / reserved names ─────


def test_filename_project_json_does_not_overwrite(
    client: TestClient, real_mp4_file: Path,
) -> None:
    project_id = _create_project(client)
    proj_json = _project_dir(project_id) / "project.json"
    before = proj_json.read_bytes()
    content = real_mp4_file.read_bytes()
    resp = _upload_video(client, project_id, "project.json", content)
    assert resp.status_code == 422, resp.text
    # Repro closed: project.json byte-identical and GET project still works.
    assert proj_json.read_bytes() == before
    get = client.get(f"/api/projects/{project_id}")
    assert get.status_code == 200
    # No source file published, no staging/publish temp orphan.
    assert _staging_leftovers(project_id) == []
    assert not list(_project_dir(project_id).glob("source_*.mp4"))


def test_reserved_names_case_insensitive_never_overwrite(
    client: TestClient, real_mp4_file: Path,
) -> None:
    project_id = _create_project(client)
    proj_json = _project_dir(project_id) / "project.json"
    before = proj_json.read_bytes()
    content = real_mp4_file.read_bytes()
    proj_dir = _project_dir(project_id)
    for hostile in ("PROJECT.JSON", "Project.Json", "project.JsOn", "objects"):
        resp = _upload_video(client, project_id, hostile, content)
        assert resp.status_code == 422, (hostile, resp.text)
        assert proj_json.read_bytes() == before
    # Only the legitimate project.json exists (no hostile-named file is ever
    # created — Windows globbing is case-insensitive so ``glob("PROJECT.JSON")``
    # would match project.json itself; count real entries instead).
    created = sorted(p.name for p in proj_dir.iterdir())
    assert created == ["project.json"], created
    assert _staging_leftovers(project_id) == []


def test_filename_traversal_and_backslash_never_escape(
    client: TestClient, real_mp4_file: Path,
) -> None:
    project_id = _create_project(client)
    proj_json = _project_dir(project_id) / "project.json"
    before = proj_json.read_bytes()
    content = real_mp4_file.read_bytes()
    proj_root = Path(deps._config.project_root)
    for hostile in (
        "..\\..\\..\\evil.mp4",
        "..%2F..%2Fevil.mp4",
        "..\\evil.mp4",
        "x/..\\y.mp4",
    ):
        resp = _upload_video(client, project_id, hostile, content)
        assert resp.status_code == 422, (hostile, resp.text)
        assert proj_json.read_bytes() == before
    # No server-owned file was published by the rejected uploads.
    assert _staging_leftovers(project_id) == []
    assert not list(_project_dir(project_id).glob("source_*.mp4"))
    # Nothing escaped the project root.
    assert not (proj_root / "evil.mp4").exists()
    assert not (proj_root.parent / "evil.mp4").exists()

    # A drive-qualified filename may be reduced to its basename by the
    # multipart framework BEFORE our guard sees it; either way it must never
    # escape the project root and storage must be server-owned.
    resp = _upload_video(client, project_id, "C:\\Windows\\evil.mp4", content)
    assert resp.status_code in (200, 422), resp.text
    if resp.status_code == 200:
        assert resp.json()["filename"].startswith("source_")
        assert resp.json()["original_filename"] == "evil.mp4"
        assert _staging_leftovers(project_id) == []
    assert not (proj_root.parent / "evil.mp4").exists()
    assert not (Path("C:/Windows") / "evil.mp4").exists()


# ── C — image validation: full decode, truncation, caps, canonical type ─────


def test_truncated_png_jpeg_webp_with_valid_magic_rejected_415(
    client: TestClient,
) -> None:
    project_id = _create_project(client)
    object_id = _create_object(client, project_id)
    for data in (_png_bytes(64, 64), _jpeg_bytes(64, 64), _webp_bytes(64, 64)):
        truncated = data[: max(1, len(data) // 2)]
        assert truncated.startswith(
            (b"\x89PNG", b"\xff\xd8\xff", b"RIFF")
        )
        resp = client.post(
            f"/api/projects/{project_id}/objects/{object_id}/replacement",
            files={"file": ("broken.png", truncated, "image/png")},
        )
        assert resp.status_code == 415, len(truncated)
    assert _staging_leftovers(project_id) == []
    obj_dir = _project_dir(project_id) / "objects" / object_id
    assert not list(obj_dir.glob("replacement.*"))


def test_valid_images_served_with_correct_bytes_and_mime(
    client: TestClient,
) -> None:
    project_id = _create_project(client)
    object_id = _create_object(client, project_id)
    expectations = [
        (_png_bytes(24, 24), "image/png", "replacement.png"),
        (_jpeg_bytes(24, 24), "image/jpeg", "replacement.jpg"),
        (_webp_bytes(24, 24), "image/webp", "replacement.webp"),
    ]
    for data, mime, expected_name in expectations:
        resp = client.post(
            f"/api/projects/{project_id}/objects/{object_id}/replacement",
            files={"file": (f"x.{expected_name.rsplit('.', 1)[1]}", data, mime)},
        )
        assert resp.status_code == 200, resp.text
        rel = resp.json()["asset_path"]
        assert rel.endswith(expected_name), rel  # canonical extension
        img = client.get(
            f"/api/projects/{project_id}/objects/{object_id}/replacement-image"
        )
        assert img.status_code == 200
        assert img.headers["content-type"] == mime
        assert img.content == data  # byte-exact round trip
        assert _staging_leftovers(project_id) == []


def test_oversized_dimensions_rejected_415(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = _create_project(client)
    object_id = _create_object(client, project_id)
    _set_image_caps(monkeypatch, max_dimension=16)
    resp = client.post(
        f"/api/projects/{project_id}/objects/{object_id}/replacement",
        files={"file": ("big.png", _png_bytes(300, 300), "image/png")},
    )
    assert resp.status_code == 415
    assert _staging_leftovers(project_id) == []


def test_oversized_total_pixels_rejected_415(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = _create_project(client)
    object_id = _create_object(client, project_id)
    # side < max_dimension, but 300x300 = 90000 px > 1000 px cap.
    _set_image_caps(monkeypatch, max_dimension=4096, max_pixels=1000)
    resp = client.post(
        f"/api/projects/{project_id}/objects/{object_id}/replacement",
        files={"file": ("tall.png", _png_bytes(300, 300), "image/png")},
    )
    assert resp.status_code == 415
    assert _staging_leftovers(project_id) == []


# ── A/C — malformed + oversize replacement (byte limit + bomb) ──────────────


def test_oversized_replacement_image_byte_limit_413(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = _create_project(client)
    object_id = _create_object(client, project_id)
    _set_upload_limit(monkeypatch, 64, image=True)
    resp = client.post(
        f"/api/projects/{project_id}/objects/{object_id}/replacement",
        files={"file": ("big.png", _png_bytes() * 8, "image/png")},
    )
    assert resp.status_code == 413
    assert _staging_leftovers(project_id) == []


def test_decompression_bomb_image_rejected_415(
    client: TestClient,
) -> None:
    project_id = _create_project(client)
    object_id = _create_object(client, project_id)
    sig = b"\x89PNG\r\n\x1a\n"
    header = b"IHDR" + struct.pack(">II", 99999, 99999) + b"\x08\x02\x00\x00\x00"
    ihdr = struct.pack(">I", 13) + header + struct.pack(
        ">I", zlib.crc32(header) & 0xFFFFFFFF
    )
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", 0)
    resp = client.post(
        f"/api/projects/{project_id}/objects/{object_id}/replacement",
        files={"file": ("giant.png", sig + ihdr + iend, "image/png")},
    )
    assert resp.status_code == 415
    assert _staging_leftovers(project_id) == []


def test_malformed_replacement_image_rejected_415_and_cleaned(
    client: TestClient,
) -> None:
    project_id = _create_project(client)
    object_id = _create_object(client, project_id)
    resp = client.post(
        f"/api/projects/{project_id}/objects/{object_id}/replacement",
        files={"file": ("char.png", b"this is not an image at all", "image/png")},
    )
    assert resp.status_code == 415
    assert _staging_leftovers(project_id) == []
    obj_dir = _project_dir(project_id) / "objects" / object_id
    assert not (obj_dir / "replacement.png").exists()


def test_replacement_upload_valid_png_ok_and_served(
    client: TestClient,
) -> None:
    project_id = _create_project(client)
    object_id = _create_object(client, project_id)
    png = _png_bytes()
    resp = client.post(
        f"/api/projects/{project_id}/objects/{object_id}/replacement",
        files={"file": ("char.png", png, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["asset_path"] == f"objects/{object_id}/replacement.png"
    assert _staging_leftovers(project_id) == []

    img = client.get(f"/api/projects/{project_id}/objects/{object_id}/replacement-image")
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png"
    assert img.content == png


# ── D — atomicity: rollback and publish-temp cleanup on injected failure ────


def test_metadata_update_failure_rolls_back_file_and_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = _create_project(client)
    object_id = _create_object(client, project_id)
    first = _png_bytes(24, 24, value=10)
    up = client.post(
        f"/api/projects/{project_id}/objects/{object_id}/replacement",
        files={"file": ("a.png", first, "image/png")},
    )
    assert up.status_code == 200, up.text
    first_rel = up.json()["asset_path"]

    # Inject a metadata-update failure AFTER the file is atomically published.
    from app.api import deps as api_deps

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated metadata write failure")

    monkeypatch.setattr(api_deps._project_wf, "update_object", _boom)

    second = _png_bytes(24, 24, value=200)
    resp = client.post(
        f"/api/projects/{project_id}/objects/{object_id}/replacement",
        files={"file": ("b.png", second, "image/png")},
    )
    assert resp.status_code == 500
    # D: existing valid replacement still served (rollback restored old bytes).
    img = client.get(f"/api/projects/{project_id}/objects/{object_id}/replacement-image")
    assert img.status_code == 200
    assert img.content == first
    assert _staging_leftovers(project_id) == []
    # Project state unchanged: metadata still points at the ORIGINAL file.
    meta = client.get(f"/api/projects/{project_id}/objects/{object_id}").json()
    assert meta["replacement_image"] == first_rel


def test_publish_temp_cleanup_on_injected_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = _create_project(client)
    object_id = _create_object(client, project_id)
    import app.api.routes.projects as project_routes

    def _failing_copy2(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated publish failure")

    monkeypatch.setattr(project_routes.shutil, "copy2", _failing_copy2)
    resp = client.post(
        f"/api/projects/{project_id}/objects/{object_id}/replacement",
        files={"file": ("x.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 500
    # D: every staging/publish temp removed on the failure path; no partial file.
    assert _staging_leftovers(project_id) == []
    obj_dir = _project_dir(project_id) / "objects" / object_id
    assert not list(obj_dir.glob("replacement.*"))


def test_video_metadata_update_failure_rolls_back_file_and_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, real_mp4_file: Path,
) -> None:
    """S08-H02-C1-recovery: a set_video failure AFTER the new source is
    atomically published must remove the just-published source file (no
    orphan), keep the previous project.json byte-identical and keep the
    previous valid source present and SELECTED."""
    project_id = _create_project(client)
    proj_dir = _project_dir(project_id)
    proj_json = proj_dir / "project.json"
    content = real_mp4_file.read_bytes()

    # Establish a previous valid source.
    first = _upload_video(client, project_id, "first.mp4", content)
    assert first.status_code == 200, first.text
    first_name = first.json()["filename"]
    prev_src_bytes = (proj_dir / first_name).read_bytes()
    before = proj_json.read_bytes()

    # Inject a set_video failure AFTER the new source file is published.
    from app.api import deps as api_deps

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated source-metadata write failure")

    monkeypatch.setattr(api_deps._project_wf, "set_video", _boom)

    resp = _upload_video(client, project_id, "second.mp4", content)
    assert resp.status_code == 500
    # The newly published source is REMOVED (no orphan) — only the previous
    # source file remains.
    assert _staging_leftovers(project_id) == []
    remaining = sorted(p.name for p in proj_dir.glob("source_*.mp4"))
    assert remaining == [first_name], remaining
    # Previous project.json bytes/state preserved (byte-identical).
    assert proj_json.read_bytes() == before
    # Previous valid source stays present and its bytes are intact.
    assert (proj_dir / first_name).exists()
    assert (proj_dir / first_name).read_bytes() == prev_src_bytes
    # GET project returns 200 with the PREVIOUS source selected.
    get = client.get(f"/api/projects/{project_id}")
    assert get.status_code == 200
    assert get.json()["source_video"].endswith(first_name)


# ── E — replacement settings + serve containment ────────────────────────────


def test_replacement_settings_reject_absolute_and_dotdot_asset_path(
    client: TestClient,
) -> None:
    project_id = _create_project(client)
    object_id = _create_object(client, project_id)
    for bad in ("/etc/passwd", "C:\\Windows\\system32", "../objects/x.png", "C:/x"):
        resp = client.patch(
            f"/api/projects/{project_id}/objects/{object_id}/replacement-settings",
            json={"replacement_config": {"mode": "static_asset", "assetPath": bad}},
        )
        assert resp.status_code == 422, bad


def test_replacement_get_cannot_read_sentinel_outside_project_root(
    client: TestClient, tmp_path: Path,
) -> None:
    project_id = _create_project(client)
    object_id = _create_object(client, project_id)
    sentinel = tmp_path / "secret.txt"
    sentinel.write_text("SECRET", encoding="utf-8")

    # Plant an absolute asset_path pointing OUTSIDE the project root.
    from app.api import deps as api_deps

    api_deps._project_wf.update_object(
        project_id,
        object_id,
        replacement_config=ReplacementConfig(
            mode=ReplacementMode.STATIC_ASSET,
            assetPath=str(sentinel),
        ),
    )
    resp = client.get(
        f"/api/projects/{project_id}/objects/{object_id}/replacement-image"
    )
    # E: never served — the file outside the managed root is unreachable.
    assert resp.status_code in (403, 404)
    assert "SECRET" not in resp.text
    assert sentinel.read_text(encoding="utf-8") == "SECRET"


def test_delete_traversal_does_not_delete_outside_projects_root(
    client: TestClient, tmp_path: Path,
) -> None:
    sentinel = tmp_path / "irreplaceable.txt"
    sentinel.write_text("KEEP", encoding="utf-8")
    resp = client.delete("/api/projects/a..b")
    assert resp.status_code in (403, 404, 422)
    assert sentinel.read_text(encoding="utf-8") == "KEEP"
    assert sentinel.exists()


# ── E — traversal identifiers → 4xx before any join ─────────────────────────


def test_traversal_project_identifier_upload_rejected(
    client: TestClient,
) -> None:
    resp = _upload_video(client, "a..b", "clip.mp4", _png_bytes())
    assert resp.status_code == 422


def test_traversal_identifiers_replacement_rejected(
    client: TestClient,
) -> None:
    resp = client.post(
        "/api/projects/a..b/objects/c..d/replacement",
        files={"file": ("char.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 422
    proj_root = Path(deps._config.project_root)
    assert not (proj_root / "escape").exists()
    assert not (proj_root / "projects" / "a..b").exists()


# ── AC11 — probe dimension/pixel caps (unit-level) ──────────────────────────


def test_probe_image_rejects_oversized_dimensions() -> None:
    with pytest.raises(MediaValidationError):
        probe_image(_png_bytes(32, 32), max_dimension=16)


def test_probe_image_rejects_oversized_total_pixels() -> None:
    with pytest.raises(MediaValidationError):
        probe_image(_png_bytes(300, 300), max_dimension=4096, max_pixels=1000)


def test_probe_image_rejects_non_image_bytes() -> None:
    with pytest.raises(MediaValidationError):
        probe_image(b"\x00" * 64)
    with pytest.raises(MediaValidationError):
        probe_image(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64)


def test_sniff_video_container_recognizes_real_containers() -> None:
    assert sniff_video_container(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64) == "video/mp4"
    assert sniff_video_container(b"\x1a\x45\xdf\xa3" + b"\x00" * 16) == "video/webm"
    assert sniff_video_container(b"\x00" * 100) is None
    assert sniff_video_container(b"") is None


# ── S08-H02-C2 — preset path containment + video_probe bounded output ───────


def _presets_dir(project_id: str) -> Path:
    return _project_dir(project_id) / "presets"


def test_preset_save_traversal_names_cannot_overwrite_project_json(
    client: TestClient,
) -> None:
    project_id = _create_project(client)
    proj_json = _project_dir(project_id) / "project.json"
    before = proj_json.read_bytes()
    for hostile in (
        "..\\project",
        "../project",
        "..\\..\\..\\project",
        "../../../overwrite",
    ):
        resp = client.post(
            f"/api/projects/{project_id}/presets/save",
            json={"name": hostile},
        )
        assert resp.status_code == 422, hostile
        assert proj_json.read_bytes() == before
    assert _staging_leftovers(project_id) == []


def test_preset_save_hostile_names_rejected_422(
    client: TestClient,
) -> None:
    project_id = _create_project(client)
    proj_json = _project_dir(project_id) / "project.json"
    before = proj_json.read_bytes()
    for hostile in (
        "/absolute.json",
        "C:\\overwrite",
        "C:/overwrite.json",
        "a/b",
        "a\\b",
        ".",
        "..",
        "....",
        "a\x00b",
        "",
    ):
        resp = client.post(
            f"/api/projects/{project_id}/presets/save",
            json={"name": hostile},
        )
        assert resp.status_code == 422, repr(hostile)
        assert proj_json.read_bytes() == before


def test_preset_save_reserved_slug_rejected_422(
    client: TestClient,
) -> None:
    project_id = _create_project(client)
    proj_json = _project_dir(project_id) / "project.json"
    before = proj_json.read_bytes()
    # slug "project.json" collides with the project's own manifest (case-insensitive).
    for hostile in ("project", "PROJECT", "Project"):
        resp = client.post(
            f"/api/projects/{project_id}/presets/save",
            json={"name": hostile},
        )
        assert resp.status_code == 422, hostile
        assert proj_json.read_bytes() == before


def test_preset_save_isolated_sentinel_byte_identical(
    client: TestClient, tmp_path: Path,
) -> None:
    project_id = _create_project(client)
    sentinel = tmp_path / "channels.json"
    sentinel_bytes = b'{"isolated": true, "protected": "yes"}'
    sentinel.write_bytes(sentinel_bytes)
    proj_json = _project_dir(project_id) / "project.json"
    proj_before = proj_json.read_bytes()
    for hostile in ("..\\..\\..\\channels.json", "..../channels.json", "C:\\channels.json"):
        resp = client.post(
            f"/api/projects/{project_id}/presets/save",
            json={"name": hostile},
        )
        assert resp.status_code == 422, hostile
        assert proj_json.read_bytes() == proj_before
    assert sentinel.read_bytes() == sentinel_bytes  # no file appears outside presets
    assert not list(_project_dir(project_id).rglob("channels.json"))


def test_preset_apply_traversal_cannot_load_project_json_or_sentinel(
    client: TestClient,
) -> None:
    project_id = _create_project(client)
    proj_dir = _project_dir(project_id)
    sentinel = proj_dir / "sentinel.json"
    sentinel.write_text("SECRET-PRESET", encoding="utf-8")
    proj_json_bytes = (proj_dir / "project.json").read_bytes()
    for hostile in (
        "..\\project.json",
        "a..b.json",
        "..%5C..%5Cproject.json",
        "sub%2Fx.json",
        "C%3A%5Cproject.json",
        "x.txt",
        "....json",
    ):
        resp = client.post(
            f"/api/projects/{project_id}/presets/{hostile}/apply",
        )
        assert resp.status_code in (404, 422), hostile
        assert resp.status_code != 500, hostile
        assert "SECRET-PRESET" not in resp.text
    # `..%2F..%2Fproject.json` may be collapsed client-side to 404; still safe.
    resp = client.post(
        f"/api/projects/{project_id}/presets/..%2F..%2Fproject.json/apply",
    )
    assert resp.status_code in (404, 422)
    assert "SECRET-PRESET" not in resp.text
    assert sentinel.read_text(encoding="utf-8") == "SECRET-PRESET"
    assert (proj_dir / "project.json").read_bytes() == proj_json_bytes
    # No new file appears outside the presets dir.
    outside = [p for p in proj_dir.iterdir() if p.name not in ("project.json", "presets")]
    assert outside == [sentinel], [p.name for p in outside]


def test_preset_apply_symlink_escape_rejected(
    client: TestClient,
) -> None:
    import os

    project_id = _create_project(client)
    proj_dir = _project_dir(project_id)
    presets_dir = _presets_dir(project_id)
    presets_dir.mkdir(parents=True, exist_ok=True)
    outside = proj_dir / "outside-target.json"
    outside.write_text('{"name": "OUTSIDE"}', encoding="utf-8")
    link = presets_dir / "evil.json"
    try:
        os.symlink(str(outside), str(link))
    except OSError:
        pytest.skip("symlink creation not permitted on this host")
    resp = client.post(f"/api/projects/{project_id}/presets/evil.json/apply")
    # resolved path escapes presets → rejected (symlink-safe resolution).
    assert resp.status_code == 422
    assert "outside the presets directory" in resp.text


def test_preset_apply_missing_preset_404(client: TestClient) -> None:
    project_id = _create_project(client)
    resp = client.post(f"/api/projects/{project_id}/presets/nope.json/apply")
    assert resp.status_code == 404


def test_preset_valid_save_list_apply_succeeds(client: TestClient) -> None:
    project_id = _create_project(client)
    resp = client.post(
        f"/api/projects/{project_id}/presets/save",
        json={"name": "My Preset", "description": "desc"},
    )
    assert resp.status_code == 200, resp.text
    saved_path = resp.json()["path"]
    # strict slug file name, display name preserved in the JSON.
    filename = Path(saved_path).name
    assert filename == "my_preset.json", filename
    preset_json = _presets_dir(project_id) / "my_preset.json"
    assert preset_json.is_file()
    import json as _json

    stored = _json.loads(preset_json.read_text(encoding="utf-8"))
    assert stored["name"] == "My Preset"

    listed = client.get(f"/api/projects/{project_id}/presets")
    assert listed.status_code == 200
    assert any(item["filename"] == "my_preset.json" for item in listed.json())

    applied = client.post(f"/api/projects/{project_id}/presets/my_preset.json/apply")
    assert applied.status_code == 200, applied.text
    assert applied.json()["ok"] is True


def test_preset_rejected_requests_never_500(client: TestClient) -> None:
    project_id = _create_project(client)
    proj_json = _project_dir(project_id) / "project.json"
    before = proj_json.read_bytes()
    for save_name in ("..\\x", "/x", "C:\\x", "a/b", "....", "project"):
        resp = client.post(
            f"/api/projects/{project_id}/presets/save",
            json={"name": save_name},
        )
        assert resp.status_code in (404, 422), save_name
        assert resp.status_code != 500
    for apply_name in ("..\\project.json", "a..b.json", "x.txt", "..%5Cproject.json"):
        resp = client.post(f"/api/projects/{project_id}/presets/{apply_name}/apply")
        assert resp.status_code in (404, 422), apply_name
        assert resp.status_code != 500
    assert proj_json.read_bytes() == before
    assert _staging_leftovers(project_id) == []


def test_video_probe_oversized_output_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from app.services import video_probe
    from app.services.video_probe import ProbeOutputTooLargeError, probe_video

    assert issubclass(ProbeOutputTooLargeError, RuntimeError)

    probe_file = tmp_path / "dummy.mp4"
    probe_file.write_bytes(b"\x00")

    def _oversize(*_args: object, **_kwargs: object) -> tuple[int, str, str]:
        raise ProbeOutputTooLargeError("simulated output ceiling exceeded")

    monkeypatch.setattr(video_probe, "_run_ffprobe", _oversize)
    with pytest.raises(ProbeOutputTooLargeError):
        probe_video(probe_file)


def test_video_probe_malformed_output_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from app.services import video_probe
    from app.services.video_probe import probe_video

    probe_file = tmp_path / "dummy.mp4"
    probe_file.write_bytes(b"\x00")

    def _malformed(*_args: object, **_kwargs: object) -> tuple[int, str, str]:
        return 0, "this is not json", ""

    monkeypatch.setattr(video_probe, "_run_ffprobe", _malformed)
    with pytest.raises(RuntimeError):
        probe_video(probe_file)


def test_video_probe_stream_ceiling_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from app.services import video_probe
    from app.services.video_probe import probe_video

    probe_file = tmp_path / "dummy.mp4"
    probe_file.write_bytes(b"\x00")
    fake_streams = [
        {"codec_type": "video", "codec_name": "h264", "width": 64, "height": 64,
         "r_frame_rate": "10/1", "nb_frames": "3"}
        for _ in range(10)
    ]
    payload = {"streams": fake_streams, "format": {"duration": "0.3", "size": "100"}}

    def _many_streams(*_a: object, **_k: object) -> tuple[int, str, str]:
        import json as _json

        return 0, _json.dumps(payload), ""

    monkeypatch.setattr(video_probe, "_run_ffprobe", _many_streams)
    with pytest.raises(RuntimeError):
        probe_video(probe_file)


def test_video_upload_probe_failure_does_not_publish(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, real_mp4_file: Path,
) -> None:
    from app.services import video_probe
    from app.services.video_probe import ProbeOutputTooLargeError

    project_id = _create_project(client)
    proj_json = _project_dir(project_id) / "project.json"
    before = proj_json.read_bytes()

    def _oversize(*_args: object, **_kwargs: object) -> tuple[int, str, str]:
        raise ProbeOutputTooLargeError("simulated output ceiling exceeded")

    monkeypatch.setattr(video_probe, "_run_ffprobe", _oversize)
    resp = _upload_video(client, project_id, "clip.mp4", real_mp4_file.read_bytes())
    # Fail closed: 415, nothing published, project state unchanged.
    assert resp.status_code == 415, resp.text
    assert not list(_project_dir(project_id).glob("source_*.mp4"))
    assert proj_json.read_bytes() == before
    assert _staging_leftovers(project_id) == []


# ── S08-H02-C3 — probe deadline concurrent drain + preset root junction + collision ──


def _make_presets_dir_link(link: Path, target: Path) -> bool:
    """Create *link* as a directory symlink or an NTFS junction to *target*.

    Returns True on success; False (-> pytest.skip) when the host refuses
    symlink/junction creation.
    """
    import os
    import subprocess as _sp

    if link.exists():
        if link.is_symlink() or link.is_junction():
            link.unlink()
        else:
            link.rmdir()  # only a leftover empty scaffolding dir on a fresh project
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return True
    except OSError:
        pass
    try:
        _sp.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (OSError, _sp.CalledProcessError):
        return False


def test_video_probe_deadline_enforced_real_child() -> None:
    """A child sleeping far past the deadline MUST fail in under 1 second.

    REAL subprocess (python -c child), not a monkeypatch: the previous
    implementation blocked on a sequential readline and let a 0.2s timeout
    actually take 3.016s.  The main thread owns the deadline now, so the raise
    lands around 0.2s.
    """
    import sys
    import time

    from app.services import video_probe

    t0 = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        video_probe._run_ffprobe(
            [sys.executable, "-c", "import time; time.sleep(3)"],
            timeout=0.2,
        )
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, f"deadline not enforced: {elapsed:.3f}s"


def test_video_probe_stderr_then_stdout_no_deadlock() -> None:
    """A child fills stderr (pipe-filling volume) BEFORE writing stdout.

    Concurrent drain means the parent never blocks on a full stderr pipe while
    waiting on stdout — both streams come back intact.
    """
    import sys
    import time

    from app.services import video_probe

    child = (
        "import sys"
        ";d=b'x'*65536"
        ";sys.stderr.buffer.write(d);sys.stderr.buffer.flush()"
        ";print('done', end='');sys.stdout.flush()"
    )
    t0 = time.monotonic()
    rc, out, err = video_probe._run_ffprobe(
        [sys.executable, "-c", child], timeout=15
    )
    elapsed = time.monotonic() - t0
    assert rc == 0, f"rc={rc} err head={err[:200]!r}"
    assert out == "done", repr(out)
    assert len(err) == 65536, len(err)
    assert elapsed < 15.0, f"deadlock/bound issue: {elapsed:.3f}s"


def test_video_probe_over_cap_line_without_newline_fails_closed() -> None:
    """An over-ceiling burst with NO newline fails within bounded time.

    REAL subprocess writes >1 MiB of 'x' in a single newline-less stream then
    sleeps ~30s — the combined cap must trip (and kill the child) well under
    that, proving the cap does not depend on line termination.
    """
    import sys
    import time

    from app.services import video_probe
    from app.services.video_probe import (
        PROBE_MAX_OUTPUT_BYTES,
        ProbeOutputTooLargeError,
    )

    n = PROBE_MAX_OUTPUT_BYTES + 200_000
    child = (
        "import sys"
        f";sys.stdout.buffer.write(b'x'*{n})"
        ";sys.stdout.buffer.flush()"
        ";import time;time.sleep(30)"
    )
    t0 = time.monotonic()
    with pytest.raises(ProbeOutputTooLargeError):
        video_probe._run_ffprobe([sys.executable, "-c", child], timeout=10)
    elapsed = time.monotonic() - t0
    assert elapsed < 5.0, f"over-cap failure not bounded: {elapsed:.3f}s"


def test_video_probe_combined_streams_cap_fails_closed() -> None:
    """The ceiling is COMBINED: neither stream alone exceeds it, the SUM does."""
    import sys
    import time

    from app.services import video_probe
    from app.services.video_probe import (
        PROBE_MAX_OUTPUT_BYTES,
        ProbeOutputTooLargeError,
    )

    half = PROBE_MAX_OUTPUT_BYTES // 2 + 100_000
    child = (
        "import sys"
        f";sys.stdout.buffer.write(b'a'*{half});sys.stdout.buffer.flush()"
        f";sys.stderr.buffer.write(b'b'*{half});sys.stderr.buffer.flush()"
        ";import time;time.sleep(30)"
    )
    t0 = time.monotonic()
    with pytest.raises(ProbeOutputTooLargeError):
        video_probe._run_ffprobe([sys.executable, "-c", child], timeout=10)
    elapsed = time.monotonic() - t0
    assert elapsed < 5.0, f"combined cap not bounded: {elapsed:.3f}s"


def test_preset_root_directory_link_outside_rejected_422(
    client: TestClient, tmp_path: Path,
) -> None:
    """<project>/presets as a DIRECTORY symlink/junction pointing OUTSIDE the
    project makes SAVE and APPLY return stable 422 with zero side effects.

    The resolver anchors BOTH the unresolved and resolved presets root to the
    validated project dir, so a relocated root can never be written or read.
    """
    project_id = _create_project(client)
    proj_dir = _project_dir(project_id)
    presets_dir = _presets_dir(project_id)
    outside = tmp_path / "outside-presets-root"
    outside.mkdir(parents=True, exist_ok=True)
    sentinel = outside / "owned.json"
    sentinel.write_text('{"name": "OUTSIDE-OWNED"}', encoding="utf-8")
    proj_json = proj_dir / "project.json"
    proj_before = proj_json.read_bytes()

    if not _make_presets_dir_link(presets_dir, outside):
        pytest.skip("host cannot create directory symlink/junction")

    # SAVE -> 422; nothing written inside the project or on the outside target.
    resp = client.post(
        f"/api/projects/{project_id}/presets/save",
        json={"name": "Safe Name"},
    )
    assert resp.status_code == 422, resp.text
    assert "outside the project" in resp.text
    assert sentinel.read_bytes() == b'{"name": "OUTSIDE-OWNED"}'
    outside_entries = {p.name for p in outside.iterdir()}
    assert outside_entries == {"owned.json"}, outside_entries
    assert proj_json.read_bytes() == proj_before

    # APPLY -> 422 even though a preset exists on the outside target; its
    # content is never read/served.
    resp2 = client.post(f"/api/projects/{project_id}/presets/owned.json/apply")
    assert resp2.status_code == 422, resp2.text
    assert "outside the project" in resp2.text
    assert "OUTSIDE-OWNED" not in resp2.text
    assert sentinel.read_bytes() == b'{"name": "OUTSIDE-OWNED"}'
    assert proj_json.read_bytes() == proj_before
    assert _staging_leftovers(project_id) == []


def test_preset_collision_distinct_names_same_slug_not_overwritten(
    client: TestClient,
) -> None:
    """A! and A? both slugify to 'a' — the second must NOT overwrite the first.

    Server-owned unique filenames: a.json then a-2.json; the first preset stays
    byte-identical; both are listed and apply normally.
    """
    import json as _json

    project_id = _create_project(client)
    r1 = client.post(
        f"/api/projects/{project_id}/presets/save", json={"name": "A!"}
    )
    assert r1.status_code == 200, r1.text
    p1 = Path(r1.json()["path"])
    assert p1.name == "a.json", p1.name
    a_before = p1.read_bytes()

    r2 = client.post(
        f"/api/projects/{project_id}/presets/save", json={"name": "A?"}
    )
    assert r2.status_code == 200, r2.text
    p2 = Path(r2.json()["path"])
    assert p2.name == "a-2.json", p2.name
    assert p2.exists()
    # First preset untouched (byte-identical) and the second keeps its own name.
    assert p1.read_bytes() == a_before
    stored2 = _json.loads(p2.read_text(encoding="utf-8"))
    assert stored2["name"] == "A?"

    listed = client.get(f"/api/projects/{project_id}/presets")
    assert listed.status_code == 200
    names = {item["filename"] for item in listed.json()}
    assert names == {"a.json", "a-2.json"}, names

    # Both presets still apply normally.
    for fname in ("a.json", "a-2.json"):
        applied = client.post(
            f"/api/projects/{project_id}/presets/{fname}/apply"
        )
        assert applied.status_code == 200, applied.text


def test_preset_same_name_resave_updates_in_place(client: TestClient) -> None:
    """Re-saving the SAME display name updates its own file (no new file)."""
    project_id = _create_project(client)
    r1 = client.post(
        f"/api/projects/{project_id}/presets/save", json={"name": "My Preset"}
    )
    assert r1.status_code == 200, r1.text
    p1 = Path(r1.json()["path"])
    assert p1.name == "my_preset.json", p1.name
    before = p1.read_bytes()

    r2 = client.post(
        f"/api/projects/{project_id}/presets/save",
        json={"name": "My Preset", "description": "v2"},
    )
    assert r2.status_code == 200, r2.text
    p2 = Path(r2.json()["path"])
    assert p2 == p1, (p1, p2)  # same file, in-place update
    assert p2.read_bytes() != before  # content updated, not clobbered


# ── S08-H02-C4 — atomic preset reservation (Finding 1) ──────────────────────


def _c4_concurrent_save(project_dir: Path, names: tuple[str, str]):
    """Two threads + barrier saving *names* into a fresh project dir.

    REAL concurrency (barrier release), service-level — exactly reproduces the
    Codex two-save race A!/A? becoming a.json + a-2.json.  Returns
    ``(results, errors)`` where results maps display name -> reserved path.
    """
    import threading as _threading

    from app.workflow.preset_service import (
        PresetService,
        ProjectPreset,
        unique_preset_output_path,
    )

    presets_dir = project_dir / "presets"
    results: dict[str, Path] = {}
    errors: list[BaseException] = []
    lock = _threading.Lock()
    barrier = _threading.Barrier(2)

    def _save(name: str) -> None:
        preset = ProjectPreset(name=name, description="c4-concurrent")
        try:
            barrier.wait()
            path = unique_preset_output_path(presets_dir, project_dir, name)
            PresetService().save_preset(preset, path)
            with lock:
                results[name] = path
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    threads = [
        _threading.Thread(target=_save, args=(names[0],)),
        _threading.Thread(target=_save, args=(names[1],)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results, errors


def test_c4_preset_concurrent_distinct_names_two_files(tmp_path: Path) -> None:
    """A! and A? saved CONCURRENTLY never collide.

    REAL two-thread + barrier test (S08-H02-C4 Finding 1): distinct display
    names that slugify identically MUST yield two DISTINCT durable, valid JSON
    preset files — no silent overwrite, no partial file.
    """
    import json as _json

    project_dir = tmp_path / "proj"
    presets_dir = project_dir / "presets"
    results, errors = _c4_concurrent_save(project_dir, ("A!", "A?"))
    assert errors == [], [repr(e) for e in errors]
    assert sorted(results) == ["A!", "A?"], sorted(results)

    # Both responses successful -> two DISTINCT files.
    paths = list(results.values())
    assert len(paths) == 2
    assert len({p.resolve() for p in paths}) == 2, "must be two distinct files"

    # Both JSON documents valid and retain the correct display names.
    for name, path in results.items():
        data = _json.loads(path.read_text(encoding="utf-8"))
        assert data["name"] == name
        assert data["description"] == "c4-concurrent"

    # Exactly the two expected files — no partial/empty residue, no extras.
    files = sorted(p.name for p in presets_dir.glob("*.json"))
    assert len(files) == 2, files
    assert {p.name for p in paths} == set(files)


def test_c4_preset_concurrent_distinct_names_deterministic(
    tmp_path: Path,
) -> None:
    """Run the A!/A? two-thread collision 5x — always exactly two distinct
    files, never an overwrite: the O_EXCL reservation is deterministic."""
    for iteration in range(5):
        project_dir = tmp_path / f"proj-{iteration}"
        results, errors = _c4_concurrent_save(project_dir, ("A!", "A?"))
        assert errors == [], (iteration, [repr(e) for e in errors])
        assert sorted(results) == ["A!", "A?"], iteration
        paths = [p.resolve() for p in results.values()]
        assert len(set(paths)) == 2, iteration
        assert len(list(project_dir.rglob("*.json"))) == 2, iteration


# ── S08-H02-C4 — exact BYTE cap over multibyte UTF-8 (Finding 2) ────────────


def test_c4_probe_byte_cap_multibyte_utf8_over_1mib_raises() -> None:
    """>1 MiB of MULTIBYTE UTF-8 output MUST raise ProbeOutputTooLargeError.

    The old text-mode pipe counted DECODED CHARACTERS, so 700_000 ``é``
    characters (1.4 MB of UTF-8 bytes) slipped past the 1 MiB cap.  The
    binary byte count (Finding 2) enforces the true byte ceiling.
    """
    import sys
    import time

    from app.services import video_probe

    # Child generates 'é' * 700000 (=1 400 000 UTF-8 bytes) with ASCII-only
    # argv (the \u00e9 escape is decoded by the child itself).
    script = (
        "import sys;"
        "s = '\\u00e9' * 700000;"
        "sys.stdout.buffer.write(s.encode('utf-8'));"
        "sys.stdout.flush()"
    )
    t0 = time.monotonic()
    with pytest.raises(video_probe.ProbeOutputTooLargeError):
        video_probe._run_ffprobe([sys.executable, "-c", script], timeout=10.0)
    assert time.monotonic() - t0 < 5.0


def test_c4_probe_byte_cap_multibyte_utf8_under_cap_decodes() -> None:
    """Multibyte UTF-8 UNDER the cap decodes losslessly (decode-after-bytes)."""
    import sys

    from app.services import video_probe

    text = "\u00e9" * 1000  # 2,000 UTF-8 bytes — well under the 1 MiB cap
    script = (
        "import sys;"
        "s = '\\u00e9' * 1000;"
        "sys.stdout.buffer.write(s.encode('utf-8'));"
        "sys.stdout.flush()"
    )
    rc, out, err = video_probe._run_ffprobe(
        [sys.executable, "-c", script], timeout=10.0
    )
    assert rc == 0, err[:200]
    assert out == text
    assert err == ""


# ── S08-H02-C4 — remaining deadline budget (Finding 3) ──────────────────────


def test_c4_probe_deadline_budget_finishes_in_tight_window() -> None:
    """After reader EOF the reap uses only the REMAINING budget.

    REAL subprocess: child sleeps ~0.18s, closes stdout+stderr, then keeps
    sleeping.  Old code then granted a SECOND full ``timeout`` window
    (proc.wait(timeout=0.2) -> ~0.407s total).  New code reaps with
    max(0, deadline - monotonic()); a 0.2s probe must finish under 0.30s.
    """
    import sys
    import time

    from app.services import video_probe

    script = (
        "import sys, time;"
        "time.sleep(0.18);"
        "sys.stdout.close(); sys.stderr.close();"
        "time.sleep(2.0)"
    )
    t0 = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        video_probe._run_ffprobe([sys.executable, "-c", script], timeout=0.2)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.30, f"deadline budget exceeded: {elapsed:.3f}s"


def test_c4_probe_deadline_remaining_budget_not_second_window() -> None:
    """Reader EOF early + child keeps running -> total ~= the deadline, never
    deadline + one more full timeout (distinguishes the C4 fix from the old
    double-grant without depending on interpreter startup timing)."""
    import sys
    import time

    from app.services import video_probe

    script = (
        "import sys, time;"
        "sys.stdout.buffer.write(b'x'); sys.stdout.flush();"
        "sys.stdout.close(); sys.stderr.close();"
        "time.sleep(30)"
    )
    t0 = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        video_probe._run_ffprobe([sys.executable, "-c", script], timeout=0.4)
    elapsed = time.monotonic() - t0
    # Old bug: EOF at ~0.1s then a SECOND full 0.4s wait -> ~0.5s total.
    # Fix: remaining-budget reap ends ~0.4s (the deadline), kill+reap thereafter.
    assert elapsed < 0.48, f"reap granted a second window: {elapsed:.3f}s"


# ── S08-H02-C5 — atomic combined pipe cap (Finding 1) ───────────────────────


def test_c5_capture_state_atomic_boundary_overshoot_one_chunk() -> None:
    """Deterministic worst-case at the cap boundary: stdout and stderr each
    hold one reader chunk.  The atomic accept() retains at most the pre-cap
    bytes (combined overshoot <= one 8192-byte reader chunk), sets abort
    exactly once, and rejects every later chunk — retained output never grows
    after abort.
    """
    from app.services.video_probe import _CaptureState

    cap = 10000  # < 2 * 8192: a second reader chunk at the boundary must trip
    state = _CaptureState(cap)
    # Reader A (stdout) chunk at the boundary is accepted and retained.
    assert state.accept(8192) is True
    # Reader B (stderr) chunk AT THE SAME boundary pushes past the cap -> the
    # atomic decision rejects it (discarded, never appended) and sets abort
    # exactly once.
    assert state.accept(8192) is False
    assert state.abort.is_set()
    # Retained bytes never exceed the cap -> overshoot <= 0 <= one reader chunk.
    retained = state.count
    assert retained <= cap
    assert (retained - cap) <= 8192
    # No further chunk is counted or appended after abort (sibling must stop).
    before = state.count
    assert state.accept(1) is False
    assert state.accept(8192) is False
    assert state.count == before


def test_c5_capture_state_two_reader_barrier_worst_case() -> None:
    """Two readers each hold a chunk at the cap boundary and race via a
    barrier.  Under EVERY interleaving at most ONE chunk is retained, the
    combined count never exceeds cap, and abort is set exactly once."""
    import threading as _threading

    from app.services.video_probe import _CaptureState

    chunk = 8192
    for _ in range(300):
        state = _CaptureState(chunk + 100)  # exactly one chunk fits
        barrier = _threading.Barrier(2)
        results: list[bool] = []
        lock = _threading.Lock()

        def race(
            _state=state,
            _barrier=barrier,
            _lock=lock,
            _results=results,
            _chunk=chunk,
        ) -> None:
            _barrier.wait()
            keep = _state.accept(_chunk)
            with _lock:
                _results.append(keep)

        ts = [_threading.Thread(target=race) for _ in range(2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert state.abort.is_set()
        assert len(results) == 2
        assert sum(results) <= 1, "worst-case overshoot must be <= 1 chunk"
        assert state.count <= chunk + 100
        assert (state.count - (chunk + 100)) <= chunk


def test_c5_pipe_reader_no_append_after_abort() -> None:
    """A reader that starts AFTER abort must read nothing and append nothing."""
    import io

    from app.services.video_probe import _CaptureState, _PipeReader

    state = _CaptureState(8192)
    reader = _PipeReader(state, io.BytesIO(b"x" * 5000), "stdout")
    state.abort.set()  # abort BEFORE any read
    reader.run()
    assert reader.chunks == []
    assert state.count == 0


def test_c5_combined_pipe_cap_simultaneous_streams_bounded() -> None:
    """REAL subprocess floods stdout AND stderr SIMULTANEOUSLY (two writer
    threads) above the combined cap -> ProbeOutputTooLargeError; no deadlock;
    bounded time."""
    import sys
    import time

    from app.services import video_probe
    from app.services.video_probe import (
        PROBE_MAX_OUTPUT_BYTES,
        ProbeOutputTooLargeError,
    )

    half = PROBE_MAX_OUTPUT_BYTES // 2 + 300_000
    child = (
        "import sys, threading, time\n"
        f"n={half}\n"
        "def w(s):\n"
        "    s.buffer.write(b'z'*n); s.buffer.flush(); time.sleep(30)\n"
        "threading.Thread(target=w, args=(sys.stdout,)).start()\n"
        "threading.Thread(target=w, args=(sys.stderr,)).start()\n"
        "time.sleep(60)\n"
    )
    t0 = time.monotonic()
    with pytest.raises(ProbeOutputTooLargeError):
        video_probe._run_ffprobe([sys.executable, "-c", child], timeout=10)
    elapsed = time.monotonic() - t0
    assert elapsed < 5.0, f"combined cap not bounded: {elapsed:.3f}s"


# ── S08-H02-C5 — cleanup deadline budgets (Finding 2) ───────────────────────


def test_c5_deadline_tight_window_after_readers_eof() -> None:
    """Child closes pipes near deadline then keeps running: timeout=0.2s must
    finish in a tight bound (<0.30s) — the reap never gets a second window and
    the cleanup never gets a fixed timeout."""
    import sys
    import time

    from app.services import video_probe

    child = (
        "import sys, time;"
        "time.sleep(0.18);"
        "sys.stdout.close(); sys.stderr.close();"
        "time.sleep(2.0)"
    )
    t0 = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        video_probe._run_ffprobe([sys.executable, "-c", child], timeout=0.2)
    assert time.monotonic() - t0 < 0.30


def test_c5_timeout_cleanup_no_fixed_5s_window() -> None:
    """A child that sleeps far past the deadline without closing its pipes:
    kill, reap and BOTH reader joins use only the remaining budget — the
    caller is never held by a fixed ~5s cleanup window (total stays < 1s)."""
    import sys
    import time

    from app.services import video_probe

    child = "import time; time.sleep(60)"  # no output, never closes pipes
    t0 = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        video_probe._run_ffprobe([sys.executable, "-c", child], timeout=0.3)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, f"cleanup left a fixed window: {elapsed:.3f}s"


def test_c5_kill_proc_reaps_child_within_budget() -> None:
    """Direct _kill_proc unit test: after kill, the child PID is reaped using
    only the remaining deadline budget (non-blocking poll when exhausted)."""
    import contextlib
    import sys
    import time

    from app.services import video_probe

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 0.2
    t0 = time.monotonic()
    video_probe._kill_proc(proc, deadline)
    elapsed = time.monotonic() - t0
    assert proc.poll() is not None, "child PID must be reaped"
    assert elapsed < 1.0, f"kill/reap not bounded: {elapsed:.3f}s"
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            with contextlib.suppress(Exception):
                stream.close()


def test_c5_no_output_and_dual_pipe_children_no_deadlock() -> None:
    """Regression: an exiting no-output child and a dual-pipe child both
    complete without deadlock or an orphaned process."""
    import sys
    import time

    from app.services import video_probe

    # No-output child that exits immediately.
    t0 = time.monotonic()
    rc, out, err = video_probe._run_ffprobe(
        [sys.executable, "-c", "import sys; sys.exit(0)"], timeout=10
    )
    assert rc == 0
    assert out == "" and err == ""
    assert time.monotonic() - t0 < 10

    # Child that writes to BOTH pipes then exits normally.
    rc2, out2, err2 = video_probe._run_ffprobe(
        [sys.executable, "-c",
         "import sys;"
         "sys.stdout.buffer.write(b'A'*2000); sys.stdout.flush();"
         "sys.stderr.buffer.write(b'B'*2000); sys.stderr.flush()"],
        timeout=10,
    )
    assert rc2 == 0
    assert out2 == "A" * 2000
    assert err2 == "B" * 2000
