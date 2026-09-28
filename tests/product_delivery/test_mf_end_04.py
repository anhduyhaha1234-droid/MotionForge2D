"""MF-END-04 — publish + validation against the reference manifest: acceptance + negative controls.

Row map (binary):

* micro repro: the validator exposes the branch API (``PackContractBranch`` /
  ``parse_reference_manifest`` / ``reference_pack_completeness``) and the
  legacy default path is byte-for-byte behaviour-preserved; the frozen
  manifest shape (``manifest_version`` 1, ``pack_contract``, reference keys
  ``<view>@<role>``, per-requirement ``alpha``) parses, and every broken
  shape (bad version, wrong contract, empty/invalid/duplicate requirements,
  unknown capability, sha mismatch) fails closed with a distinct message;
  completeness and validation validity are separate answers and are never
  derived from one another.
* acceptance (through the REAL app call path — repository + TestClient on
  the MF-END-03 ingest route and the publish route): a reference pack whose
  frozen manifest requirements are all attached publishes; the publish
  snapshot freezes ``pack_contract_version`` + ``requirement_manifest_sha256``
  + the exact per-key artifact hashes; an opaque RGB reference publishes when
  its requirement declares ``alpha: false`` (D2-01: the legacy unconditional
  alpha gate is NOT applied to the reference branch); ``CORE_POSE_SLOTS`` is
  never demanded; a pack can be ``complete`` while its validation status is
  ``invalid`` (and is then not publishable) — the two are reported
  separately and neither is conflated with the other; validation never
  mutates the row (status/revision/validation_json unchanged).
* negative controls: missing required key names the EXACT view/key and never
  the word "pose"; alpha missing where the requirement demands transparency;
  manifest sha mismatch; duplicate reference keys (declaration and stored);
  non-independent pixels do not satisfy the capability floor; unknown
  capability / unsupported manifest version / empty requirements refused at
  declaration; a mask (mode ``L``) never satisfies a reference requirement;
  reference-asset integrity failures (file missing on disk, size/checksum,
  resolution); declaration refused on non-draft versions (published /
  archived) and twice (write-once); mutation after publish refused (attach
  through the route 409, tampered manifest re-publish refused through the
  route).
* legacy regression: the six-slot contract is unchanged — same completeness
  message, unconditional transparency policy, and the legacy publish
  snapshot (``core_slots`` / ``asset_count``) carries no reference fields;
  the legacy reader DTO stays exactly the six-slot record (no branch
  attributes leak into ``PackVersionRecord``).

Everything here is a CI fixture: deterministic bytes generated in-process,
the per-test isolated SQLite database from ``tests/conftest.py``, and the
FastAPI ``TestClient``.  No GPU, no network, no ffmpeg, no real product
media — these rows are engineering evidence, never product-demo evidence.
"""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.characters import (
    CharacterRepository,
    PackVersionConflictError,
    PackVersionImmutableError,
    PublishValidationFailedError,
)
from app.persistence.models import (
    CORE_POSE_SLOTS,
    PACK_CONTRACT_VERSION_LEGACY,
    PACK_CONTRACT_VERSION_REFERENCE,
    CharacterPackVersion,
)
from app.workflow.character_validator import (
    REFERENCE_MANIFEST_VERSIONS_SUPPORTED,
    PackContractBranch,
    ReferenceManifest,
    parse_reference_manifest,
    reference_pack_completeness,
    validate_character_pack,
)

SYMBOL = "reference_pack_v1"
FRONT = "front@character"
SIDE = "side@character"
BACK = "back@character"


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
    mode: str = "RGBA",
    alpha: int = 200,
    gray: int = 120,
) -> bytes:
    """Deterministic PNG: RGBA with real transparency, RGB, or mode-L mask."""
    if mode == "RGBA":
        img = Image.new("RGBA", (width, height), (gray, 60, 200, alpha))
    elif mode == "RGB":
        img = Image.new("RGB", (width, height), (gray, 60, 200))
    elif mode == "L":
        img = Image.new("L", (width, height), gray)
    else:  # pragma: no cover - guard
        raise ValueError(mode)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _manifest(requirements, capabilities=None, version: int = 1) -> dict:
    payload: dict = {
        "manifest_version": version,
        "pack_contract": SYMBOL,
        "requirements": list(requirements),
    }
    if capabilities is not None:
        payload["capabilities"] = list(capabilities)
    return payload


def _requirement(key: str, alpha: bool) -> dict:
    return {"key": key, "alpha": alpha}


def _create_character(client: TestClient, code: str) -> str:
    resp = client.post("/api/v2/characters", json={"name": f"Ref {code}", "code": code})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_version(client: TestClient, char_id: str) -> dict:
    resp = client.post(f"/api/v2/characters/{char_id}/versions")
    assert resp.status_code == 201, resp.text
    return resp.json()


def _declare(ver_id: str, manifest) -> str:
    """Declare the reference manifest through the repository; return its
    stored sha256 (hex)."""
    with _session() as session:
        repo = CharacterRepository(session)
        repo.declare_reference_manifest(ver_id, DEFAULT_WORKSPACE_ID, manifest)
        session.commit()
    return _manifest_row(ver_id)["requirement_manifest_sha256"]


def _declare_expecting_refusal(ver_id: str, manifest, exc_type):
    with _session() as session:
        repo = CharacterRepository(session)
        with pytest.raises(exc_type) as excinfo:
            repo.declare_reference_manifest(ver_id, DEFAULT_WORKSPACE_ID, manifest)
        session.rollback()
    return excinfo.value


def _manifest_row(ver_id: str) -> dict:
    with _session() as session:
        row = session.get(CharacterPackVersion, ver_id)
        assert row is not None
        return {
            "pack_contract_version": row.pack_contract_version,
            "requirement_manifest_json": row.requirement_manifest_json,
            "requirement_manifest_sha256": row.requirement_manifest_sha256,
            "status": row.status,
            "revision": row.revision,
            "validation_json": row.validation_json,
        }


def _tamper_manifest(ver_id: str, *, text=None, sha=None) -> None:
    with _session() as session:
        row = session.get(CharacterPackVersion, ver_id)
        assert row is not None
        if text is not None:
            row.requirement_manifest_json = text
        if sha is not None:
            row.requirement_manifest_sha256 = sha
        session.commit()


def _write_managed(rel: str, data: bytes) -> Path:
    target = _managed_root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _upload(
    client: TestClient,
    version_id: str,
    data: bytes,
    *,
    key: str = FRONT,
    filename: str = "artwork.png",
):
    """Upload authored artwork through the REAL MF-END-03 ingest route."""
    return client.post(
        f"/api/v2/characters/versions/{version_id}/reference-artwork",
        data={"reference_key": key},
        files={"file": (filename, data, "image/png")},
    )


def _attach_artifact(
    client: TestClient,
    ver_id: str,
    slot: str,
    *,
    data: bytes | None = None,
) -> dict:
    """Attach one REAL ready artifact to a key through the assets route
    (precondition builder for artifact-level negatives)."""
    from app.persistence.models import Artifact

    data = data if data is not None else _png_bytes(gray=170)
    rel = f"characters/mf_end_04/{ver_id}/{slot.replace('@', '_')}.png"
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


def _validation(client: TestClient, ver_id: str) -> dict:
    resp = client.get(f"/api/v2/characters/versions/{ver_id}/validation")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _publish_attempt(client: TestClient, ver_id: str, revision: int):
    return client.post(
        f"/api/v2/characters/versions/{ver_id}/publish",
        json={"revision": revision},
    )


def _publish(client: TestClient, ver_id: str, revision: int) -> dict:
    resp = _publish_attempt(client, ver_id, revision)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _no_pose_wording(*payloads) -> None:
    """The reference branch must never demand six poses by wording."""
    for payload in payloads:
        blob = json.dumps(payload).lower()
        assert "pose" not in blob, blob


# ── micro repro ───────────────────────────────────────────────────────────────


def test_micro_validator_exposes_branch_api() -> None:
    assert REFERENCE_MANIFEST_VERSIONS_SUPPORTED == (1,)
    branch = PackContractBranch(pack_contract_version=PACK_CONTRACT_VERSION_LEGACY)
    assert branch.requirement_manifest_json is None
    assert branch.requirement_manifest_sha256 is None
    # the legacy default is still reachable with no branch argument at all:
    # an empty pack refuses with the LEGACY message (dispatch default).
    empty_version = _bare_record()
    errors = validate_character_pack(empty_version)
    assert errors and errors[0].startswith("Missing required core pose slots")


def _bare_record():
    """A PackVersionRecord with no assets — dispatch/legacy unit probe."""
    from datetime import UTC, datetime

    from app.persistence.characters import PackVersionRecord

    now = datetime.now(UTC)
    return PackVersionRecord(
        id="probe",
        character_id="probe",
        workspace_id=DEFAULT_WORKSPACE_ID,
        version=1,
        status="draft",
        validation_json=None,
        published_at=None,
        revision=1,
        created_at=now,
        updated_at=now,
        archived_at=None,
        assets=[],
    )


def test_micro_parse_accepts_frozen_shape_and_alpha_defaults() -> None:
    text = json.dumps(
        _manifest(
            [
                _requirement(FRONT, True),
                _requirement(SIDE, False),
                BACK,  # bare string -> alpha required (conservative default)
            ],
            capabilities=["image_edit_multi_reference"],
        ),
        sort_keys=True,
    )
    parsed = parse_reference_manifest(
        PackContractBranch(
            pack_contract_version=PACK_CONTRACT_VERSION_REFERENCE,
            requirement_manifest_json=text,
            requirement_manifest_sha256=hashlib.sha256(text.encode()).hexdigest(),
        )
    )
    assert parsed.errors == []
    assert parsed.manifest_version == 1
    assert parsed.capabilities == ("image_edit_multi_reference",)
    by_key = {req.key: req for req in parsed.requirements}
    assert by_key[FRONT].view == "front" and by_key[FRONT].role == "character"
    assert by_key[FRONT].alpha_required is True
    assert by_key[SIDE].alpha_required is False
    assert by_key[BACK].alpha_required is True  # bare key default
    # completeness and validity are separate answers
    complete, missing = reference_pack_completeness(_bare_record(), parsed)
    assert complete is False and missing == [FRONT, SIDE, BACK]


@pytest.mark.parametrize(
    "case, mutate, fragment",
    [
        ("sha-mismatch", "sha", "Reference manifest SHA-256 mismatch"),
        ("bad-json", "json", "Reference manifest is not valid JSON"),
        ("not-object", "json-list", "must be a JSON object"),
        ("bad-version", "version2", "Unsupported reference manifest version 2"),
        ("bad-contract", "contract", "does not match the version branch"),
        ("empty-requirements", "empty", "requirements must be a non-empty list"),
        ("invalid-key", "badkey", "Reference requirement key 'front@villain' is invalid"),
        ("duplicate-key", "dup", "Duplicate reference requirement key"),
        ("unknown-capability", "cap", "claims unknown engine capability"),
        ("bad-entry", "intent", "unsupported type"),
        ("bad-alpha", "alpha", "must be {'key': str, 'alpha': bool}"),
    ],
)
def test_micro_parse_refuses_broken_manifest_shapes(case, mutate, fragment) -> None:
    manifest = _manifest([_requirement(FRONT, True), _requirement(SIDE, False)])
    text = json.dumps(manifest, sort_keys=True)
    if mutate == "json":
        text = "{not json"
    elif mutate == "json-list":
        text = "[1, 2]"
    elif mutate == "version2":
        text = json.dumps(_manifest([FRONT], version=2), sort_keys=True)
    elif mutate == "contract":
        payload = _manifest([FRONT])
        payload["pack_contract"] = "legacy_six_slot_2d"
        text = json.dumps(payload, sort_keys=True)
    elif mutate == "empty":
        text = json.dumps(_manifest([]), sort_keys=True)
    elif mutate == "badkey":
        text = json.dumps(_manifest(["front@villain"]), sort_keys=True)
    elif mutate == "dup":
        text = json.dumps(_manifest([FRONT, FRONT]), sort_keys=True)
    elif mutate == "cap":
        text = json.dumps(
            _manifest([FRONT], capabilities=["fast_and_furious"]), sort_keys=True
        )
    elif mutate == "intent":
        text = json.dumps(_manifest([42]), sort_keys=True)
    elif mutate == "alpha":
        text = json.dumps(_manifest([{"key": FRONT, "alpha": "yes"}]), sort_keys=True)
    # every case except the explicit sha-mismatch one stores a CONSISTENT hash
    # over the (possibly tampered) text, so only the targeted check can fire.
    sha = (
        "0" * 64
        if mutate == "sha"
        else hashlib.sha256(text.encode()).hexdigest()
    )
    parsed = parse_reference_manifest(
        PackContractBranch(
            pack_contract_version=PACK_CONTRACT_VERSION_REFERENCE,
            requirement_manifest_json=text,
            requirement_manifest_sha256=sha,
        )
    )
    assert parsed.errors, case
    assert any(fragment in err for err in parsed.errors), (case, parsed.errors)
    # a broken manifest is never complete and never carries a parsed set
    complete, missing = reference_pack_completeness(_bare_record(), parsed)
    assert complete is False and missing == []


def test_micro_manifest_error_completeness_is_not_validity() -> None:
    broken = ReferenceManifest(
        manifest_version=None, capabilities=(), requirements=(), errors=["boom"]
    )
    assert reference_pack_completeness(_bare_record(), broken) == (False, [])


# ── acceptance: the real call path ────────────────────────────────────────────


def test_acceptance_reference_pack_publishes_and_freezes_snapshot(client: TestClient) -> None:
    char = _create_character(client, "ref-accept")
    ver = _create_version(client, char)
    manifest = _manifest(
        [_requirement(FRONT, True), _requirement(SIDE, True), _requirement(BACK, True)],
        capabilities=["image_edit_multi_reference"],
    )
    declared_sha = _declare(ver["id"], manifest)

    row = _manifest_row(ver["id"])
    assert row["pack_contract_version"] == PACK_CONTRACT_VERSION_REFERENCE
    assert row["requirement_manifest_sha256"] == declared_sha
    assert (
        hashlib.sha256(row["requirement_manifest_json"].encode("utf-8")).hexdigest()
        == declared_sha
    )

    # authored artwork rides the REAL MF-END-03 ingest route; distinct pixels
    # per key so the references are INDEPENDENT.
    uploaded = {}
    for gray, key in ((10, FRONT), (90, SIDE), (170, BACK)):
        resp = _upload(client, ver["id"], _png_bytes(gray=gray), key=key)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["reference_key"] == key
        uploaded[key] = body["sha256"]

    result = _validation(client, ver["id"])
    assert result["status"] == "valid"
    assert result["complete"] is True
    assert result["missing_slots"] == []
    assert result["errors"] == []
    _no_pose_wording(result)

    published = _publish(client, ver["id"], ver["revision"])
    assert published["status"] == "published"
    snapshot = json.loads(published["validation_json"])
    assert snapshot["pack_contract_version"] == PACK_CONTRACT_VERSION_REFERENCE
    assert snapshot["manifest_version"] == 1
    assert snapshot["requirement_manifest_sha256"] == declared_sha
    assert snapshot["required_keys"] == [FRONT, SIDE, BACK]
    assert {ref["key"] for ref in snapshot["references"]} == set(uploaded)
    for ref in snapshot["references"]:
        assert ref["artifact_sha256"] == uploaded[ref["key"]]
    assert snapshot["asset_count"] == 3
    assert "core_slots" not in snapshot  # the legacy six-slot gate never ran

    after = _manifest_row(ver["id"])
    assert after["status"] == "published"


def test_acceptance_opaque_reference_admitted_when_alpha_declared_false(
    client: TestClient,
) -> None:
    """D2-01 fix: an opaque RGB reference is publishable when ITS requirement
    declares alpha: false — the legacy unconditional alpha gate is not applied
    to the reference branch (and is still applied to legacy packs, below)."""
    char = _create_character(client, "ref-opaque")
    ver = _create_version(client, char)
    _declare(ver["id"], _manifest([_requirement(FRONT, False)]))

    resp = _upload(client, ver["id"], _png_bytes(mode="RGB"), key=FRONT)
    assert resp.status_code == 201, resp.text

    result = _validation(client, ver["id"])
    assert result["complete"] is True
    assert result["status"] == "valid"
    assert result["errors"] == []
    published = _publish(client, ver["id"], ver["revision"])
    assert published["status"] == "published"


def test_negative_bare_key_defaults_to_alpha_required(client: TestClient) -> None:
    """A bare-string requirement defaults to alpha REQUIRED (fail closed)."""
    char = _create_character(client, "ref-bare")
    ver = _create_version(client, char)
    _declare(ver["id"], _manifest([FRONT]))
    resp = _upload(client, ver["id"], _png_bytes(mode="RGB"), key=FRONT)
    assert resp.status_code == 201, resp.text

    result = _validation(client, ver["id"])
    assert result["complete"] is True  # nothing missing …
    assert result["status"] == "invalid"  # … but it is NOT valid
    assert any(FRONT in err and "no real transparency" in err for err in result["errors"])
    assert not any("pose" in err.lower() for err in result["errors"])

    resp = _publish_attempt(client, ver["id"], ver["revision"])
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["missing_slots"] == []
    assert any(FRONT in err and "alpha: true" in err for err in detail["errors"])
    _no_pose_wording(detail)


def test_acceptance_validation_reports_complete_and_status_separately(
    client: TestClient,
) -> None:
    """complete == False (a key is missing) and complete == True (all keys
    present but an asset is opaque) are BOTH reachable, and neither answer is
    conflated with the other; validation never mutates the row."""
    char = _create_character(client, "ref-sep")
    ver = _create_version(client, char)
    _declare(
        ver["id"],
        _manifest([_requirement(FRONT, True), _requirement(SIDE, True)]),
    )
    # ingest only FRONT with real transparency -> SIDE missing, still valid?? no:
    # missing entries are named, so status is invalid AND complete is False.
    assert _upload(client, ver["id"], _png_bytes(gray=31), key=FRONT).status_code == 201

    first = _validation(client, ver["id"])
    assert first["complete"] is False
    assert first["status"] == "invalid"
    assert first["missing_slots"] == [SIDE]
    assert any(SIDE in err and "Missing required reference" in err for err in first["errors"])
    _no_pose_wording(first)

    # read-only: no status/revision/validation_json mutation, even after a
    # second call.
    row = _manifest_row(ver["id"])
    assert row["status"] == "draft"
    assert row["revision"] == ver["revision"]
    assert row["validation_json"] is None
    second = _validation(client, ver["id"])
    assert second == first
    row2 = _manifest_row(ver["id"])
    assert row2["status"] == row["status"]
    assert row2["revision"] == row["revision"]
    assert row2["validation_json"] is None

    # now attach SIDE opaque (all-alpha-255 RGBA) -> complete True, invalid.
    assert (
        _upload(client, ver["id"], _png_bytes(mode="RGBA", alpha=255), key=SIDE).status_code
        == 201
    )
    third = _validation(client, ver["id"])
    assert third["complete"] is True
    assert third["status"] == "invalid"
    assert third["missing_slots"] == []


def test_negative_missing_reference_key_names_view_and_key(client: TestClient) -> None:
    char = _create_character(client, "ref-missing")
    ver = _create_version(client, char)
    _declare(
        ver["id"],
        _manifest(
            [_requirement(FRONT, True), _requirement(SIDE, True), _requirement(BACK, True)]
        ),
    )
    assert _upload(client, ver["id"], _png_bytes(gray=41), key=FRONT).status_code == 201
    assert _upload(client, ver["id"], _png_bytes(gray=42), key=BACK).status_code == 201

    result = _validation(client, ver["id"])
    assert result["complete"] is False
    assert result["missing_slots"] == [SIDE]
    assert any(
        f"Missing required reference {SIDE!r} (view 'side', role 'character')" in err
        for err in result["errors"]
    ), result["errors"]
    _no_pose_wording(result)

    resp = _publish_attempt(client, ver["id"], ver["revision"])
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["missing_slots"] == [SIDE]
    assert any(SIDE in err for err in detail["errors"])
    _no_pose_wording(detail)
    assert _manifest_row(ver["id"])["status"] == "draft"


def test_negative_manifest_sha_mismatch_refused(client: TestClient) -> None:
    char = _create_character(client, "ref-sha")
    ver = _create_version(client, char)
    _declare(ver["id"], _manifest([_requirement(FRONT, False)]))
    assert _upload(client, ver["id"], _png_bytes(mode="RGB"), key=FRONT).status_code == 201
    assert _validation(client, ver["id"])["status"] == "valid"

    _tamper_manifest(
        ver["id"],
        text=json.dumps(_manifest([_requirement(FRONT, False), SIDE]), sort_keys=True),
    )
    result = _validation(client, ver["id"])
    assert result["status"] == "invalid"
    assert result["complete"] is False  # the required set is not knowable
    assert any("Reference manifest SHA-256 mismatch" in err for err in result["errors"])
    resp = _publish_attempt(client, ver["id"], ver["revision"])
    assert resp.status_code == 422, resp.text
    assert any(
        "Reference manifest SHA-256 mismatch" in err
        for err in resp.json()["detail"]["errors"]
    )

    # the mismatch cannot be "fixed" by re-declaring through the API: the
    # declaration is write-once, so a tampered text can never be re-anchored.
    conflict = _declare_expecting_refusal(
        ver["id"], _manifest([FRONT]), PackVersionConflictError
    )
    assert "write-once" in str(conflict)


def test_negative_duplicate_reference_refused_at_declare_and_at_publish(
    client: TestClient,
) -> None:
    char = _create_character(client, "ref-dup")
    ver = _create_version(client, char)
    refusal = _declare_expecting_refusal(
        ver["id"], _manifest([FRONT, FRONT]), ValueError
    )
    assert "Duplicate reference requirement key" in str(refusal)

    # a stored duplicate (direct tamper) is still refused by the gate
    _declare(ver["id"], _manifest([_requirement(FRONT, False)]))
    dup_text = json.dumps(
        _manifest([_requirement(FRONT, False), _requirement(FRONT, True)]),
        sort_keys=True,
    )
    _tamper_manifest(
        ver["id"], text=dup_text, sha=hashlib.sha256(dup_text.encode()).hexdigest()
    )
    result = _validation(client, ver["id"])
    assert any("Duplicate reference requirement key" in err for err in result["errors"])
    assert _publish_attempt(client, ver["id"], ver["revision"]).status_code == 422


def test_negative_capability_floor_counts_independent_pixels(client: TestClient) -> None:
    char = _create_character(client, "ref-floor")
    ver = _create_version(client, char)
    _declare(
        ver["id"],
        _manifest(
            [_requirement(FRONT, True), _requirement(SIDE, True)],
            capabilities=["image_edit_multi_reference"],
        ),
    )
    same_bytes = _png_bytes(gray=77)
    assert _upload(client, ver["id"], same_bytes, key=FRONT).status_code == 201
    assert _upload(client, ver["id"], same_bytes, key=SIDE).status_code == 201

    result = _validation(client, ver["id"])
    assert result["complete"] is True  # both keys attached …
    assert result["status"] == "invalid"  # … yet the floor is not met
    assert any(
        "requires at least 1 role(s) with >= 2 independent reference(s)" in err
        for err in result["errors"]
    ), result["errors"]
    assert _publish_attempt(client, ver["id"], ver["revision"]).status_code == 422
    _no_pose_wording(result)


def test_negative_declaration_refusals_unknown_capability_version_empty(
    client: TestClient,
) -> None:
    char = _create_character(client, "ref-decl")
    ver = _create_version(client, char)
    cases = [
        (_manifest([FRONT], capabilities=["not_a_capability"]), "unknown engine capability"),
        (_manifest([FRONT], version=2), "Unsupported reference manifest version"),
        (_manifest([]), "requirements must be a non-empty list"),
        (_manifest(["front@villain"]), "is invalid"),
    ]
    for manifest, fragment in cases:
        refusal = _declare_expecting_refusal(ver["id"], manifest, ValueError)
        assert fragment in str(refusal), (fragment, str(refusal))
    # the failed declarations left the version legacy and manifest-free
    row = _manifest_row(ver["id"])
    assert row["pack_contract_version"] == PACK_CONTRACT_VERSION_LEGACY
    assert row["requirement_manifest_json"] is None
    assert row["requirement_manifest_sha256"] is None


def test_negative_mask_payload_never_satisfies_a_reference(client: TestClient) -> None:
    char = _create_character(client, "ref-mask")
    ver = _create_version(client, char)
    # alpha:false on purpose — the mask refusal is NOT an alpha-policy effect.
    _declare(ver["id"], _manifest([_requirement(FRONT, False)]))
    _attach_artifact(client, ver["id"], FRONT, data=_png_bytes(mode="L"))

    result = _validation(client, ver["id"])
    assert any(
        "single-channel greyscale representation" in err
        and "a mask is not authored artwork" in err
        for err in result["errors"]
    ), result["errors"]
    assert result["complete"] is True
    assert _publish_attempt(client, ver["id"], ver["revision"]).status_code == 422


def test_negative_reference_asset_integrity_failures(client: TestClient) -> None:
    char = _create_character(client, "ref-integrity")
    ver = _create_version(client, char)
    _declare(
        ver["id"],
        _manifest(
            [
                _requirement(FRONT, False),
                _requirement(SIDE, False),
                _requirement(BACK, False),
            ]
        ),
    )
    # FRONT: file disappears from managed storage
    _attach_artifact(client, ver["id"], FRONT, data=_png_bytes(mode="RGB", gray=5))
    front_rel = f"characters/mf_end_04/{ver['id']}/{FRONT.replace('@', '_')}.png"
    (_managed_root() / front_rel).unlink()
    # SIDE: below the resolution floor
    _attach_artifact(client, ver["id"], SIDE, data=_png_bytes(64, 64, mode="RGB", gray=6))
    # BACK: bytes on disk no longer match the registered checksum
    _attach_artifact(client, ver["id"], BACK, data=_png_bytes(mode="RGB", gray=7))
    back_rel = f"characters/mf_end_04/{ver['id']}/{BACK.replace('@', '_')}.png"
    _write_managed(back_rel, _png_bytes(mode="RGB", gray=8))

    result = _validation(client, ver["id"])
    assert any(
        f"Reference {FRONT!r} artifact file missing on disk" in err
        for err in result["errors"]
    ), result["errors"]
    assert any(
        "image resolution 64x64 is below the required 128x128" in err
        for err in result["errors"]
    ), result["errors"]
    assert any(
        f"Reference {BACK!r} SHA-256 mismatch" in err for err in result["errors"]
    ), result["errors"]
    assert result["complete"] is True
    assert _publish_attempt(client, ver["id"], ver["revision"]).status_code == 422


def test_negative_declare_requires_live_draft_and_is_write_once(client: TestClient) -> None:
    char = _create_character(client, "ref-draft")
    ver = _create_version(client, char)
    _declare(ver["id"], _manifest([_requirement(FRONT, False)]))
    # second declaration on the same draft: write-once conflict
    conflict = _declare_expecting_refusal(
        ver["id"], _manifest([SIDE]), PackVersionConflictError
    )
    assert "write-once" in str(conflict)

    # publish needs an attached (opaque, admitted) FRONT
    assert _upload(client, ver["id"], _png_bytes(mode="RGB"), key=FRONT).status_code == 201
    _publish(client, ver["id"], ver["revision"])

    # published: mutation refused — declare refuses with the immutable class
    immutable = _declare_expecting_refusal(
        ver["id"], _manifest([SIDE]), PackVersionImmutableError
    )
    assert "non-draft" in str(immutable)

    # archived: same refusal (never a draft again)
    char2 = _create_character(client, "ref-arch")
    ver2 = _create_version(client, char2)
    with _session() as session:
        row = session.get(CharacterPackVersion, ver2["id"])
        row.status = "archived"
        session.commit()
    archived = _declare_expecting_refusal(
        ver2["id"], _manifest([FRONT]), PackVersionImmutableError
    )
    assert "non-draft" in str(archived)


def test_negative_mutation_after_publish_refused_through_route(client: TestClient) -> None:
    char = _create_character(client, "ref-lock")
    ver = _create_version(client, char)
    _declare(ver["id"], _manifest([_requirement(FRONT, False)]))
    assert _upload(client, ver["id"], _png_bytes(mode="RGB", gray=8), key=FRONT).status_code == 201
    published = _publish(client, ver["id"], ver["revision"])
    frozen = json.loads(published["validation_json"])

    # attach to a published version: 409 via the route (existing contract)
    resp = client.post(
        f"/api/v2/characters/versions/{ver['id']}/assets",
        json={"pose_slot": SIDE, "artifact_id": "0" * 36},
    )
    assert resp.status_code == 409, resp.text

    # manifest tampered after publish (json + sha consistently rewritten):
    # re-publish is refused because the row no longer matches the snapshot.
    tampered = _manifest([_requirement(FRONT, False), _requirement(SIDE, False)])
    tampered_text = json.dumps(tampered, sort_keys=True)
    _tamper_manifest(
        ver["id"],
        text=tampered_text,
        sha=hashlib.sha256(tampered_text.encode()).hexdigest(),
    )
    resp = _publish_attempt(client, ver["id"], published["revision"])
    assert resp.status_code == 409, resp.text
    assert "frozen publish snapshot" in resp.json()["detail"]

    # …and the frozen snapshot itself still records the ORIGINAL manifest
    assert frozen["requirement_manifest_sha256"] != hashlib.sha256(
        tampered_text.encode()
    ).hexdigest()
    assert _manifest_row(ver["id"])["validation_json"] == published["validation_json"]


# ── legacy regression ─────────────────────────────────────────────────────────


def _attach_six(client: TestClient, ver_id: str, *, alpha: int = 200, gray: int = 9) -> None:
    for index, slot in enumerate(CORE_POSE_SLOTS):
        _attach_artifact(
            client, ver_id, slot, data=_png_bytes(alpha=alpha, gray=gray + index)
        )


def test_legacy_regression_six_slot_contract_unchanged(client: TestClient) -> None:
    char = _create_character(client, "legacy-ok")
    ver = _create_version(client, char)
    _attach_six(client, ver["id"])

    result = _validation(client, ver["id"])
    assert result["complete"] is True
    assert result["status"] == "valid"
    assert result["errors"] == []
    published = _publish(client, ver["id"], ver["revision"])
    snapshot = json.loads(published["validation_json"])
    assert snapshot["core_slots"] == list(CORE_POSE_SLOTS)
    assert snapshot["asset_count"] == 6
    assert "pack_contract_version" not in snapshot
    assert "requirement_manifest_sha256" not in snapshot


def test_legacy_regression_missing_slots_and_alpha_unchanged(client: TestClient) -> None:
    char = _create_character(client, "legacy-missing")
    ver = _create_version(client, char)
    _attach_artifact(client, ver["id"], "front")
    result = _validation(client, ver["id"])
    assert result["complete"] is False
    assert set(result["missing_slots"]) == set(CORE_POSE_SLOTS) - {"front"}
    assert result["errors"][0].startswith("Missing required core pose slots")
    resp = _publish_attempt(client, ver["id"], ver["revision"])
    assert resp.status_code == 422
    assert set(resp.json()["detail"]["missing_slots"]) == set(CORE_POSE_SLOTS) - {"front"}

    # legacy keeps the UNCONDITIONAL alpha policy (asymmetry by design)
    char2 = _create_character(client, "legacy-opaque")
    ver2 = _create_version(client, char2)
    _attach_six(client, ver2["id"], alpha=255)
    result2 = _validation(client, ver2["id"])
    assert result2["complete"] is True
    assert result2["status"] == "invalid"
    assert sum("no real transparency" in err for err in result2["errors"]) == 6
    assert "pose" in result2["errors"][0].lower()  # legacy wording, unchanged


def test_legacy_regression_reader_dto_has_no_branch_fields(client: TestClient) -> None:
    """The legacy reader contract (MF-END-02 pin) stays untouched: the branch
    is read by the repository from the row, never leaked into the DTO."""
    char = _create_character(client, "legacy-dto")
    ver = _create_version(client, char)
    with _session() as session:
        record = CharacterRepository(session).get_pack_version(
            ver["id"], DEFAULT_WORKSPACE_ID
        )
    assert not hasattr(record, "pack_contract_version")
    assert not hasattr(record, "requirement_manifest_json")
    assert not hasattr(record, "requirement_manifest_sha256")


def test_legacy_regression_publish_validation_error_has_errors_field(
    client: TestClient,
) -> None:
    """PackVersionValidationResult stays the same shape for both branches."""
    char = _create_character(client, "legacy-errors")
    ver = _create_version(client, char)
    with _session() as session:
        result = CharacterRepository(session).validate_pack_version(
            ver["id"], DEFAULT_WORKSPACE_ID
        )
    assert result.version_id == ver["id"]
    assert result.character_id == char
    assert result.workspace_id == DEFAULT_WORKSPACE_ID
    assert result.complete is False
    assert isinstance(result.errors, list) and result.errors
    with pytest.raises(PublishValidationFailedError) as excinfo, _session() as session:
        repo = CharacterRepository(session)
        repo.publish_pack_version(ver["id"], DEFAULT_WORKSPACE_ID, ver["revision"])
    assert excinfo.value.missing_slots
    assert excinfo.value.errors
