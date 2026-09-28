"""MF-END-03 — public authored reference-artwork ingest: acceptance + negative controls.

Row map (binary):

* micro repro: the public route exists on the EXISTING durable-characters router
  with a multipart body (``file`` + ``reference_key`` + ``purpose``) and is
  reachable through the REAL app (OpenAPI path present, ``app/api/app.py``
  untouched); the reference-key validator accepts the frozen ``<view>@<role>``
  shape and refuses every malformed/unsafe form; a mask purpose is refused at
  the validator level too.
* acceptance (through the REAL app call path, ``TestClient``):
  authored RGBA PNG -> 201 with sha256/size/mime/width/height equal to the
  VERIFIED bytes; the managed file on disk is byte-identical to the upload; the
  ``Artifact`` row is ``ready`` with matching metadata; the asset is attached
  under the namespaced key and served by the existing content endpoint; an RGB
  payload whose channels are equal (grey-LOOKING artwork) is ADMITTED — the
  decision is the decoded colour representation + declared purpose, never the
  extension or the pixel appearance; repeat upload of the same key replaces in
  place (exactly one asset row for the key, new artifact, old artifact row
  preserved); JPEG bytes named ``.png`` are stored/served as the VERIFIED
  ``image/jpeg``; no response carries a filesystem path.
* negative controls: published version 409; missing and foreign-workspace
  version 404; truncated payload with valid PNG magic 415; empty payload 415;
  over-limit bytes 413; over-limit dimension 415; mode-L (PNG colour type 0,
  no alpha) mask payload 422 ``MASK_PAYLOAD_REFUSED`` with ZERO writes (no
  artifact row, no managed byte, no asset); declared mask purpose 422
  ``MASK_PURPOSE_REFUSED`` with zero writes; unsafe reference keys 422; hostile
  filename 422; failure AFTER the managed write (attach raises) rolls back:
  409 + zero new bytes + zero new rows + the previous asset untouched.

Everything here is a CI fixture: deterministic bytes generated in-process, the
per-test isolated SQLite database from ``tests/conftest.py``, and the FastAPI
``TestClient``.  No GPU, no network, no ffmpeg, no real product media — these
rows are engineering evidence, never product-demo evidence.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.api import deps
from app.api.routes import durable_characters
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.characters import CharacterRepository, PackVersionImmutableError
from app.persistence.models import CORE_POSE_SLOTS, Artifact, CharacterAsset
from app.workflow import character_reference_ingest as cri

REFERENCE_PATH = "/api/v2/characters/versions/{version_id}/reference-artwork"
REFERENCE_URL = "/api/v2/characters/versions/{version_id}/reference-artwork"
KEY = "front@character"


# ── helpers ───────────────────────────────────────────────────────────────────


def _session():
    service = deps._job_service
    assert service is not None
    return service.session_factory()


def _managed_root() -> Path:
    service = deps._job_service
    assert service is not None
    return Path(service.managed_root)


def _png_bytes(
    width: int = 256,
    height: int = 256,
    *,
    alpha: bool = True,
    rgba: tuple[int, int, int, int] = (120, 60, 200, 200),
) -> bytes:
    """Real PNG; RGBA (default, alpha 200 -> real transparency) or RGB."""
    if alpha:
        img = Image.new("RGBA", (width, height), rgba)
    else:
        img = Image.new("RGB", (width, height), rgba[:3])
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _grey_looking_rgb_png(width: int = 256, height: int = 256) -> bytes:
    """RGB payload whose channels are EQUAL (looks grey) but is colour-capable."""
    img = Image.new("RGB", (width, height), (90, 90, 90))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _mask_png_bytes(width: int = 256, height: int = 256) -> bytes:
    """Single-channel mask payload: PIL mode 'L' / PNG colour type 0, no alpha."""
    img = Image.new("L", (width, height), 255)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(width: int = 256, height: int = 256) -> bytes:
    img = Image.new("RGB", (width, height), (10, 200, 30))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _managed_files() -> dict[str, dict]:
    root = _managed_root()
    out: dict[str, dict] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            out[path.relative_to(root).as_posix()] = {
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
    return out


def _artifact_index() -> dict[str, dict]:
    with _session() as session:
        rows = session.scalars(select(Artifact)).all()
        return {
            row.id: {
                "kind": row.kind,
                "relative_path": row.relative_path,
                "state": row.state,
                "sha256": row.sha256,
                "size_bytes": row.size_bytes,
                "mime_type": row.mime_type,
                "width": row.width,
                "height": row.height,
                "workspace_id": row.workspace_id,
            }
            for row in rows
        }


def _asset_index() -> dict[str, dict]:
    with _session() as session:
        rows = session.scalars(select(CharacterAsset)).all()
        return {
            row.id: {
                "pose_slot": row.pose_slot,
                "artifact_id": row.artifact_id,
                "pack_version_id": row.pack_version_id,
                "workspace_id": row.workspace_id,
            }
            for row in rows
        }


def _create_character(client: TestClient, code: str) -> str:
    resp = client.post("/api/v2/characters", json={"name": f"Ref {code}", "code": code})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_version(client: TestClient, char_id: str) -> dict:
    resp = client.post(f"/api/v2/characters/{char_id}/versions")
    assert resp.status_code == 201, resp.text
    return resp.json()


def _write_managed(rel: str, data: bytes) -> Path:
    target = _managed_root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _attach_artifact(
    client: TestClient,
    ver_id: str,
    slot: str,
    *,
    data: bytes | None = None,
) -> dict:
    """Attach one REAL ready artifact to a slot (precondition builder)."""
    data = data if data is not None else _png_bytes()
    rel = f"characters/precondition/{ver_id}/{slot}.png"
    _write_managed(rel, data)
    with _session() as session:
        art = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="image",
            relative_path=rel,
            state="ready",
            size_bytes=len(data),
            mime_type="image/png",
            sha256=hashlib.sha256(data).hexdigest(),
        )
        session.add(art)
        session.commit()
        artifact_id = art.id
    resp = client.post(
        f"/api/v2/characters/versions/{ver_id}/assets",
        json={"pose_slot": slot, "artifact_id": artifact_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _publish(client: TestClient, char_id: str, ver: dict) -> dict:
    resp = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _upload(
    client: TestClient,
    version_id: str,
    data: bytes,
    *,
    key: str = KEY,
    purpose: str | None = None,
    filename: str = "artwork.png",
    content_type: str = "image/png",
    params: dict | None = None,
) -> object:
    form = {"reference_key": key}
    if purpose is not None:
        form["purpose"] = purpose
    return client.post(
        f"/api/v2/characters/versions/{version_id}/reference-artwork",
        data=form,
        files={"file": (filename, data, content_type)},
        params=params or {},
    )


def _version_assets(client: TestClient, char_id: str, ver_id: str) -> list[dict]:
    resp = client.get(f"/api/v2/characters/{char_id}/versions")
    assert resp.status_code == 200, resp.text
    version = next(v for v in resp.json() if v["id"] == ver_id)
    return version["assets"]


# ── micro repro ───────────────────────────────────────────────────────────────


def test_micro_public_route_present_with_multipart_body() -> None:
    from app.api.app import app

    spec = app.openapi()
    assert REFERENCE_PATH in spec["paths"], sorted(spec["paths"])
    post = spec["paths"][REFERENCE_PATH]["post"]
    assert "201" in post["responses"]
    body = post["requestBody"]["content"]["multipart/form-data"]["schema"]
    ref = body.get("$ref")
    props = (
        spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]["properties"]
        if ref
        else body["properties"]
    )
    assert {"file", "reference_key", "purpose"} <= set(props)
    # the handler lives on the EXISTING router module (app.py stays untouched)
    assert hasattr(durable_characters, "ingest_reference_artwork")


def test_micro_reference_key_grammar_accepts_frozen_shape() -> None:
    assert cri.validate_reference_key("front@character") == ("front", "character")
    assert cri.validate_reference_key("three_quarter@prop") == ("three_quarter", "prop")
    assert cri.validate_reference_key("walking@other") == ("walking", "other")


@pytest.mark.parametrize(
    "bad_key",
    [
        "",
        "front",
        "@character",
        "front@",
        "front@@character",
        "front@villain",
        "bogus@character",
        "..@character",
        "front@..",
        "../etc/passwd@character",
        "/absolute@character",
        "front @character",
        "front@char acter",
        "FRONT@character",
        "front@Character",
        "front@char/acter",
        "front@character.",
        "c" * 33 + "@character",
        "front@character" + "x" * 60,
    ],
)
def test_micro_reference_key_refuses_malformed_and_unsafe(bad_key: str) -> None:
    with pytest.raises(cri.ReferenceKeyRefusedError) as excinfo:
        cri.validate_reference_key(bad_key)
    assert excinfo.value.code == "REFERENCE_KEY_REFUSED"


def test_micro_mask_purpose_refused_at_validator() -> None:
    for mask_purpose in ("mask", "candidate_mask", "segmentation_mask", "matte"):
        with pytest.raises(cri.ReferencePurposeRefusedError) as excinfo:
            cri.validate_reference_purpose(mask_purpose)
        assert excinfo.value.code == "MASK_PURPOSE_REFUSED"
    assert cri.validate_reference_purpose("artwork") == "artwork"


# ── acceptance ────────────────────────────────────────────────────────────────


def test_acceptance_authored_rgba_upload_creates_real_managed_artifact(
    client: TestClient,
) -> None:
    char_id = _create_character(client, "ref_rgba")
    ver = _create_version(client, char_id)
    data = _png_bytes(rgba=(11, 22, 33, 200))

    resp = _upload(client, ver["id"], data)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["sha256"] == hashlib.sha256(data).hexdigest()
    assert body["size_bytes"] == len(data)
    assert body["mime_type"] == "image/png"
    assert (body["width"], body["height"]) == (256, 256)
    assert body["reference_key"] == KEY
    assert (body["view"], body["role"]) == ("front", "character")
    assert body["decoded_mode"] == "RGBA"
    assert body["colour_type"] == 6
    assert body["has_alpha"] is True
    assert body["purpose"] == "artwork"
    assert body["source_filename"] == "artwork.png"
    assert body["replaced_existing"] is False
    assert body["content_url"] == (
        f"/api/v2/characters/{char_id}/versions/{ver['id']}"
        f"/assets/{body['asset_id']}/content"
    )

    # the Artifact row is real, ready, and matches the verified bytes
    index = _artifact_index()
    art = index[body["artifact_id"]]
    assert art["state"] == "ready"
    assert art["kind"] == "image"
    assert art["sha256"] == body["sha256"]
    assert art["size_bytes"] == len(data)
    assert art["mime_type"] == "image/png"
    assert (art["width"], art["height"]) == (256, 256)

    # the managed file on disk is byte-identical to the upload
    on_disk = (_managed_root() / art["relative_path"]).read_bytes()
    assert on_disk == data
    assert hashlib.sha256(on_disk).hexdigest() == body["sha256"]

    # the asset is attached under the namespaced key (public listing route)
    assets = _version_assets(client, char_id, ver["id"])
    assert [a["pose_slot"] for a in assets] == [KEY]
    assert assets[0]["artifact_id"] == body["artifact_id"]

    # and the existing content endpoint serves the exact bytes
    content = client.get(body["content_url"])
    assert content.status_code == 200, content.text
    assert content.content == data
    assert content.headers["content-type"].startswith("image/png")


def test_acceptance_grey_looking_rgb_artwork_admitted_by_bytes_not_appearance(
    client: TestClient,
) -> None:
    char_id = _create_character(client, "ref_rgb_grey")
    ver = _create_version(client, char_id)
    data = _grey_looking_rgb_png()

    resp = _upload(client, ver["id"], data, key="side@character")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["decoded_mode"] == "RGB"
    assert body["colour_type"] == 2
    assert body["has_alpha"] is False
    assert body["sha256"] == hashlib.sha256(data).hexdigest()


def test_acceptance_repeat_same_key_replaces_without_duplication(
    client: TestClient,
) -> None:
    char_id = _create_character(client, "ref_repeat")
    ver = _create_version(client, char_id)
    first = _png_bytes(rgba=(1, 2, 3, 200))
    second = _png_bytes(rgba=(4, 5, 6, 210))

    first_resp = _upload(client, ver["id"], first)
    assert first_resp.status_code == 201, first_resp.text
    second_resp = _upload(client, ver["id"], second)
    assert second_resp.status_code == 201, second_resp.text
    assert second_resp.json()["replaced_existing"] is True
    assert second_resp.json()["artifact_id"] != first_resp.json()["artifact_id"]

    # exactly ONE asset row for the key, pointing at the NEW artifact
    assets = _version_assets(client, char_id, ver["id"])
    matching = [a for a in assets if a["pose_slot"] == KEY]
    assert len(matching) == 1
    assert matching[0]["artifact_id"] == second_resp.json()["artifact_id"]
    assert matching[0]["sha256"] == hashlib.sha256(second).hexdigest()

    # both artifact rows survive; both managed files are distinct and intact
    index = _artifact_index()
    assert index[first_resp.json()["artifact_id"]]["sha256"] == hashlib.sha256(first).hexdigest()
    assert index[second_resp.json()["artifact_id"]]["sha256"] == hashlib.sha256(second).hexdigest()
    first_path = index[first_resp.json()["artifact_id"]]["relative_path"]
    second_path = index[second_resp.json()["artifact_id"]]["relative_path"]
    assert first_path != second_path
    assert (_managed_root() / first_path).read_bytes() == first
    assert (_managed_root() / second_path).read_bytes() == second


def test_acceptance_verified_format_decides_mime_and_extension_not_filename(
    client: TestClient,
) -> None:
    char_id = _create_character(client, "ref_jpeg")
    ver = _create_version(client, char_id)
    data = _jpeg_bytes()

    resp = _upload(client, ver["id"], data, filename="artwork.png", content_type="image/png")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mime_type"] == "image/jpeg"
    assert body["decoded_mode"] == "RGB"
    art = _artifact_index()[body["artifact_id"]]
    assert art["mime_type"] == "image/jpeg"
    assert art["relative_path"].endswith(".jpg")

    content = client.get(body["content_url"])
    assert content.status_code == 200, content.text
    assert content.content == data
    assert content.headers["content-type"].startswith("image/jpeg")


def test_acceptance_response_never_carries_a_filesystem_path(
    client: TestClient,
) -> None:
    char_id = _create_character(client, "ref_nopath")
    ver = _create_version(client, char_id)
    resp = _upload(client, ver["id"], _png_bytes())
    assert resp.status_code == 201, resp.text
    raw = json.dumps(resp.json())
    assert str(_managed_root()) not in raw
    assert "relative_path" not in resp.json()
    assert "C:/" not in raw and "C:" + chr(92) not in raw


# ── negative controls ─────────────────────────────────────────────────────────


def test_negative_published_version_refused_409(client: TestClient) -> None:
    char_id = _create_character(client, "ref_published")
    ver = _create_version(client, char_id)
    for slot in CORE_POSE_SLOTS:
        _attach_artifact(client, ver["id"], slot)
    published = _publish(client, char_id, ver)
    assert published["status"] == "published"

    before = _artifact_index()
    resp = _upload(client, ver["id"], _png_bytes())
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "PACK_VERSION_IMMUTABLE"
    assert _artifact_index() == before, "refused upload must not create an artifact"


def test_negative_missing_and_foreign_version_404(client: TestClient) -> None:
    char_id = _create_character(client, "ref_foreign")
    ver = _create_version(client, char_id)
    _attach_artifact(client, ver["id"], "front")

    missing = _upload(client, str(uuid.uuid4()), _png_bytes())
    assert missing.status_code == 404, missing.text
    assert missing.json()["detail"]["code"] == "PACK_VERSION_NOT_FOUND"

    foreign = _upload(
        client, ver["id"], _png_bytes(), params={"workspace_id": "foreign_ws"}
    )
    assert foreign.status_code == 404, foreign.text
    assert foreign.json()["detail"]["code"] == "PACK_VERSION_NOT_FOUND"


def test_negative_truncated_payload_with_valid_magic_415(client: TestClient) -> None:
    char_id = _create_character(client, "ref_truncated")
    ver = _create_version(client, char_id)
    data = _png_bytes()[:40]  # valid PNG magic, truncated body
    assert data.startswith(b"\x89PNG")

    before_files = _managed_files()
    resp = _upload(client, ver["id"], data)
    assert resp.status_code == 415, resp.text
    assert resp.json()["detail"]["code"] == "REFERENCE_ARTWORK_UNREADABLE"
    assert _managed_files() == before_files


def test_negative_empty_payload_415(client: TestClient) -> None:
    char_id = _create_character(client, "ref_empty")
    ver = _create_version(client, char_id)
    resp = _upload(client, ver["id"], b"")
    assert resp.status_code == 415, resp.text
    assert resp.json()["detail"]["code"] == "REFERENCE_ARTWORK_UNREADABLE"


def test_negative_over_limit_bytes_413(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    char_id = _create_character(client, "ref_bigbytes")
    ver = _create_version(client, char_id)
    monkeypatch.setattr(
        durable_characters,
        "get_config",
        lambda: replace(deps._config, max_image_upload_bytes=1024),
    )
    resp = _upload(client, ver["id"], _png_bytes(512, 512))
    assert resp.status_code == 413, resp.text
    assert resp.json()["detail"]["code"] == "REFERENCE_ARTWORK_TOO_LARGE"


def test_negative_over_limit_dimension_415(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    char_id = _create_character(client, "ref_bigdims")
    ver = _create_version(client, char_id)
    monkeypatch.setattr(
        durable_characters,
        "get_config",
        lambda: replace(deps._config, max_image_dimension=64),
    )
    resp = _upload(client, ver["id"], _png_bytes(256, 256))
    assert resp.status_code == 415, resp.text
    assert resp.json()["detail"]["code"] == "REFERENCE_ARTWORK_UNREADABLE"


def test_negative_mode_l_mask_refused_with_zero_writes(client: TestClient) -> None:
    char_id = _create_character(client, "ref_mask")
    ver = _create_version(client, char_id)
    # a real, attached RGBA artwork for the same key must stay untouched
    attached = _attach_artifact(client, ver["id"], "three_quarter")
    before_files = _managed_files()
    before_artifacts = _artifact_index()
    before_assets = _asset_index()

    resp = _upload(client, ver["id"], _mask_png_bytes(), key=KEY)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "MASK_PAYLOAD_REFUSED"
    assert detail["details"]["decoded_mode"] == "L"
    assert detail["details"]["colour_type"] == 0
    assert detail["details"]["has_alpha"] is False

    # invariant: nothing was written, nothing was attached, nothing converted
    assert _managed_files() == before_files
    assert _artifact_index() == before_artifacts
    assert _asset_index() == before_assets
    assets = _version_assets(client, char_id, ver["id"])
    assert [a["pose_slot"] for a in assets] == ["three_quarter"]
    assert assets[0]["artifact_id"] == attached["artifact_id"]


def test_negative_mask_purpose_refused_with_zero_writes(client: TestClient) -> None:
    char_id = _create_character(client, "ref_maskpurpose")
    ver = _create_version(client, char_id)
    before_files = _managed_files()
    before_artifacts = _artifact_index()

    # valid RGBA bytes, but the DECLARED purpose is a mask -> refused
    resp = _upload(client, ver["id"], _png_bytes(), purpose="candidate_mask")
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "MASK_PURPOSE_REFUSED"
    assert _managed_files() == before_files
    assert _artifact_index() == before_artifacts


def test_negative_unknown_purpose_refused_422(client: TestClient) -> None:
    char_id = _create_character(client, "ref_badpurpose")
    ver = _create_version(client, char_id)
    resp = _upload(client, ver["id"], _png_bytes(), purpose="thumbnail")
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "INVALID_PURPOSE"


def test_negative_invalid_reference_key_through_route_422(client: TestClient) -> None:
    char_id = _create_character(client, "ref_badkey")
    ver = _create_version(client, char_id)
    before_files = _managed_files()
    before_artifacts = _artifact_index()

    for bad_key in ("front", "../evil@character", "front@villain"):
        resp = _upload(client, ver["id"], _png_bytes(), key=bad_key)
        assert resp.status_code == 422, (bad_key, resp.text)
        detail = resp.json().get("detail")
        assert (
            isinstance(detail, dict) and detail.get("code") == "REFERENCE_KEY_REFUSED"
        ), (bad_key, resp.text)

    # An EMPTY multipart value is transmitted as an absent field, so
    # FastAPI's own request validation answers 422 (measured; the typed
    # REFERENCE_KEY_REFUSED path is exercised by the non-empty bad keys
    # above and by the validator-level micro row).
    empty = _upload(client, ver["id"], _png_bytes(), key="")
    assert empty.status_code == 422, empty.text
    assert _managed_files() == before_files
    assert _artifact_index() == before_artifacts


def test_negative_hostile_filename_refused_422(client: TestClient) -> None:
    char_id = _create_character(client, "ref_hostile")
    ver = _create_version(client, char_id)
    for hostile in ("../evil.png", ".." + chr(92) + "evil.png", "/etc/passwd.png"):
        resp = _upload(client, ver["id"], _png_bytes(), filename=hostile)
        assert resp.status_code == 422, (hostile, resp.text)
        assert resp.json()["detail"]["code"] == "REFERENCE_FILENAME_REFUSED"


def test_negative_rollback_when_attach_fails_after_managed_write(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    char_id = _create_character(client, "ref_rollback")
    ver = _create_version(client, char_id)
    first = _upload(client, ver["id"], _png_bytes(rgba=(7, 8, 9, 200)))
    assert first.status_code == 201, first.text

    before_files = _managed_files()
    before_artifacts = _artifact_index()
    before_assets = _asset_index()

    def _boom(self, *args, **kwargs):
        raise PackVersionImmutableError("forced attach failure (MF-END-03 rollback row)")

    monkeypatch.setattr(CharacterRepository, "attach_asset", _boom)

    resp = _upload(client, ver["id"], _png_bytes(rgba=(5, 4, 3, 200)), key="side@character")
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "PACK_VERSION_IMMUTABLE"

    # the managed write is rolled back: no orphan bytes, no orphan rows
    assert _managed_files() == before_files, "failed ingest left managed bytes behind"
    assert _artifact_index() == before_artifacts, "failed ingest left an artifact row"
    assert _asset_index() == before_assets, "failed ingest changed the asset rows"

    # the previously attached artwork is still exactly the one served
    assets = _version_assets(client, char_id, ver["id"])
    assert [(a["pose_slot"], a["artifact_id"]) for a in assets] == [
        (KEY, first.json()["artifact_id"])
    ]
    content = client.get(first.json()["content_url"])
    assert content.status_code == 200, content.text
