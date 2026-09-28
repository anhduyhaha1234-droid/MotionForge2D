"""Durable Character Library persistence service and repository (S06-T01).

Implements workspace-scoped Character, Pack Version, and Asset CRUD and publishing
under the S06-T01 domain contract.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.persistence.artifacts import ManagedPathError, ManagedRoot, hash_file
from app.persistence.models import (
    CORE_POSE_SLOTS,
    PACK_CONTRACT_VERSION_LEGACY,
    PACK_CONTRACT_VERSION_REFERENCE,
    Artifact,
    Character,
    CharacterAsset,
    CharacterPackVersion,
)


class CharacterError(Exception):
    """Base exception for Character Library operations."""


class CharacterNotFoundError(CharacterError):
    """Character row not found in workspace."""


class CharacterConflictError(CharacterError):
    """CAS revision mismatch or stale state."""


class CharacterCodeConflictError(CharacterError):
    """Active character code collision in workspace."""


class PackVersionNotFoundError(CharacterError):
    """Pack version not found."""


class PackVersionConflictError(CharacterError):
    """Pack version CAS revision or version collision."""


class PackVersionImmutableError(CharacterError):
    """Attempted modification of a published, immutable Pack Version."""


class PublishValidationFailedError(CharacterError):
    """Publish gate rejected due to missing Core slots or invalid assets."""

    def __init__(
        self,
        message: str,
        missing_slots: list[str],
        errors: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.missing_slots = missing_slots
        #: Full validator error list (slot completeness + asset integrity).
        self.errors: list[str] = list(errors or [])


class AssetNotFoundError(CharacterError):
    """Pose asset not found in the pack version (404)."""


class AssetNotReadyError(CharacterError):
    """Pose asset artifact is not in a servable ready state (409)."""


class AssetContentError(CharacterError):
    """Pose asset content failed MIME/integrity/containment checks (422)."""


#: Approved MIME types the content endpoint may serve (pose preview images).
#: Mirrors the extensions the S06-T02 preset importer registers.
APPROVED_IMAGE_MIME_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif"}
)


@dataclass(frozen=True)
class AssetRecord:
    id: str
    pack_version_id: str
    workspace_id: str
    pose_slot: str
    artifact_id: str
    created_at: datetime
    updated_at: datetime
    #: Snapshot of the linked Artifact row (None when the Artifact is missing
    #: or was not loaded).  The publish validator uses these to verify state,
    #: checksum and size before allowing a pack to publish.
    artifact_state: str | None = None
    artifact_sha256: str | None = None
    artifact_size_bytes: int | None = None
    artifact_relative_path: str | None = None
    artifact_mime_type: str | None = None


@dataclass(frozen=True)
class PackVersionRecord:
    id: str
    character_id: str
    workspace_id: str
    version: int
    status: str
    validation_json: str | None
    published_at: datetime | None
    revision: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    assets: list[AssetRecord]


@dataclass(frozen=True)
class CharacterRecord:
    id: str
    workspace_id: str
    name: str
    code: str
    character_type: str
    symmetry: str
    status: str
    default_version_id: str | None
    description: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


@dataclass(frozen=True)
class PackVersionValidationResult:
    """Read-only draft validation outcome (S06-R02).

    Computed by the authoritative publish validator without publishing or
    mutating the pack.
    """

    version_id: str
    character_id: str
    workspace_id: str
    complete: bool
    missing_slots: list[str]
    errors: list[str]


def normalize_character_code(code: str) -> str:
    """Trim and validate character code."""
    normalized = code.strip()
    if not normalized:
        raise ValueError("Character code cannot be empty")
    if len(normalized) > 64:
        raise ValueError("Character code cannot exceed 64 characters")
    return normalized


def _map_asset(asset: CharacterAsset) -> AssetRecord:
    art = asset.artifact
    return AssetRecord(
        id=asset.id,
        pack_version_id=asset.pack_version_id,
        workspace_id=asset.workspace_id,
        pose_slot=asset.pose_slot,
        artifact_id=asset.artifact_id,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        artifact_state=art.state if art is not None else None,
        artifact_sha256=art.sha256 if art is not None else None,
        artifact_size_bytes=art.size_bytes if art is not None else None,
        artifact_relative_path=art.relative_path if art is not None else None,
        artifact_mime_type=art.mime_type if art is not None else None,
    )


def _map_version(version: CharacterPackVersion) -> PackVersionRecord:
    return PackVersionRecord(
        id=version.id,
        character_id=version.character_id,
        workspace_id=version.workspace_id,
        version=version.version,
        status=version.status,
        validation_json=version.validation_json,
        published_at=version.published_at,
        revision=version.revision,
        created_at=version.created_at,
        updated_at=version.updated_at,
        archived_at=version.archived_at,
        assets=[_map_asset(a) for a in (version.assets or [])],
    )


def _map_character(char: Character) -> CharacterRecord:
    return CharacterRecord(
        id=char.id,
        workspace_id=char.workspace_id,
        name=char.name,
        code=char.code,
        character_type=char.character_type,
        symmetry=char.symmetry,
        status=char.status,
        default_version_id=char.default_version_id,
        description=char.description,
        revision=char.revision,
        created_at=char.created_at,
        updated_at=char.updated_at,
        archived_at=char.archived_at,
    )


def _ensure_workspace(session: Session, workspace_id: str) -> None:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.persistence.models import Workspace
    session.execute(
        sqlite_insert(Workspace)
        .values(id=workspace_id, name=workspace_id)
        .on_conflict_do_nothing(index_elements=[Workspace.id])
    )


#: Eager-load pose assets together with their Artifact rows so the publish
#: validator can check state/checksum/size metadata without N+1 lazy loads.
_ASSET_ARTIFACT_LOAD = (
    joinedload(CharacterPackVersion.assets).joinedload(CharacterAsset.artifact)
)


class CharacterRepository:
    """Read/write repository for Character Library within one Session."""

    def __init__(self, session: Session, storage_root: Path | None = None) -> None:
        self._session = session
        #: Managed storage root used by the publish validation gate.
        self._storage_root: Path = (
            Path(storage_root) if storage_root is not None else Path("artifacts")
        )

    def create_character(
        self,
        workspace_id: str,
        name: str,
        code: str,
        character_type: str = "character",
        symmetry: str = "symmetric",
        description: str | None = None,
    ) -> CharacterRecord:
        _ensure_workspace(self._session, workspace_id)
        norm_code = normalize_character_code(code)
        norm_name = name.strip()
        if not norm_name:
            raise ValueError("Character name cannot be empty")

        # Check code collision among active characters
        existing = self._session.scalar(
            select(Character).where(
                Character.workspace_id == workspace_id,
                func.lower(Character.code) == norm_code.lower(),
                Character.status != "archived",
            )
        )
        if existing is not None:
            raise CharacterCodeConflictError(
                f"Active character code {norm_code!r} already exists in workspace"
            )

        char = Character(
            workspace_id=workspace_id,
            name=norm_name,
            code=norm_code,
            character_type=character_type,
            symmetry=symmetry,
            status="draft",
            description=description,
            revision=1,
        )
        self._session.add(char)
        self._session.flush()
        return _map_character(char)

    def list_characters(
        self,
        workspace_id: str,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CharacterRecord], int]:
        query = select(Character).where(Character.workspace_id == workspace_id)
        if not include_archived:
            query = query.where(Character.status != "archived")

        total = self._session.scalar(
            select(func.count(Character.id)).where(
                Character.workspace_id == workspace_id,
                *( [] if include_archived else [Character.status != "archived"] )
            )
        ) or 0

        query = query.order_by(Character.created_at.desc(), Character.id.asc())
        rows = self._session.scalars(query.offset(offset).limit(limit)).all()
        return [_map_character(c) for c in rows], int(total)

    def get_character(self, character_id: str, workspace_id: str) -> CharacterRecord:
        char = self._session.scalar(
            select(Character).where(
                Character.id == character_id,
                Character.workspace_id == workspace_id,
            )
        )
        if char is None:
            raise CharacterNotFoundError(f"Character {character_id!r} not found")
        return _map_character(char)

    def update_character(
        self,
        character_id: str,
        workspace_id: str,
        revision: int,
        name: str | None = None,
        code: str | None = None,
        character_type: str | None = None,
        symmetry: str | None = None,
        description: str | None = None,
    ) -> CharacterRecord:
        char = self._session.scalar(
            select(Character).where(
                Character.id == character_id,
                Character.workspace_id == workspace_id,
            )
        )
        if char is None:
            raise CharacterNotFoundError(f"Character {character_id!r} not found")

        if char.revision != revision:
            raise CharacterConflictError(
                f"CAS revision mismatch: expected {char.revision}, got {revision}"
            )

        if code is not None:
            norm_code = normalize_character_code(code)
            if norm_code.lower() != char.code.lower():
                existing = self._session.scalar(
                    select(Character).where(
                        Character.workspace_id == workspace_id,
                        func.lower(Character.code) == norm_code.lower(),
                        Character.status != "archived",
                        Character.id != character_id,
                    )
                )
                if existing is not None:
                    raise CharacterCodeConflictError(
                        f"Active character code {norm_code!r} already in use"
                    )
                char.code = norm_code

        if name is not None:
            norm_name = name.strip()
            if not norm_name:
                raise ValueError("Character name cannot be empty")
            char.name = norm_name

        if character_type is not None:
            char.character_type = character_type
        if symmetry is not None:
            char.symmetry = symmetry
        if description is not None:
            char.description = description

        char.revision += 1
        self._session.flush()
        return _map_character(char)

    def archive_character(
        self, character_id: str, workspace_id: str, revision: int
    ) -> CharacterRecord:
        char = self._session.scalar(
            select(Character).where(
                Character.id == character_id,
                Character.workspace_id == workspace_id,
            )
        )
        if char is None:
            raise CharacterNotFoundError(f"Character {character_id!r} not found")

        if char.status == "archived":
            return _map_character(char)

        if char.revision != revision:
            raise CharacterConflictError(
                f"CAS revision mismatch: expected {char.revision}, got {revision}"
            )

        char.status = "archived"
        char.archived_at = datetime.now(UTC)
        char.revision += 1
        self._session.flush()
        return _map_character(char)

    def create_pack_version(
        self, character_id: str, workspace_id: str
    ) -> PackVersionRecord:
        _ensure_workspace(self._session, workspace_id)
        char = self._session.scalar(
            select(Character).where(
                Character.id == character_id,
                Character.workspace_id == workspace_id,
            )
        )
        if char is None:
            raise CharacterNotFoundError(f"Character {character_id!r} not found")

        max_ver = self._session.scalar(
            select(func.max(CharacterPackVersion.version)).where(
                CharacterPackVersion.character_id == character_id
            )
        ) or 0

        next_ver = max_ver + 1
        version = CharacterPackVersion(
            character_id=character_id,
            workspace_id=workspace_id,
            version=next_ver,
            status="draft",
            revision=1,
        )
        self._session.add(version)
        self._session.flush()
        return _map_version(version)

    def list_pack_versions(
        self, character_id: str, workspace_id: str
    ) -> list[PackVersionRecord]:
        versions = self._session.scalars(
            select(CharacterPackVersion)
            .options(_ASSET_ARTIFACT_LOAD)
            .where(
                CharacterPackVersion.character_id == character_id,
                CharacterPackVersion.workspace_id == workspace_id,
            )
            .order_by(CharacterPackVersion.version.asc())
        ).unique().all()
        return [_map_version(v) for v in versions]

    def get_pack_version(
        self, version_id: str, workspace_id: str
    ) -> PackVersionRecord:
        version = self._session.scalar(
            select(CharacterPackVersion)
            .options(_ASSET_ARTIFACT_LOAD)
            .where(
                CharacterPackVersion.id == version_id,
                CharacterPackVersion.workspace_id == workspace_id,
            )
        )
        if version is None:
            raise PackVersionNotFoundError(f"Pack version {version_id!r} not found")
        return _map_version(version)

    def get_pack_version_for_character(
        self,
        character_id: str,
        version_id: str,
        workspace_id: str,
    ) -> PackVersionRecord:
        """Return a pack version verified to belong to *character_id*.

        Raises:
            PackVersionNotFoundError: version missing, foreign to the
                character, or in another workspace (404 semantics).
        """
        version = self._session.scalar(
            select(CharacterPackVersion)
            .options(_ASSET_ARTIFACT_LOAD)
            .where(
                CharacterPackVersion.id == version_id,
                CharacterPackVersion.character_id == character_id,
                CharacterPackVersion.workspace_id == workspace_id,
            )
        )
        if version is None:
            raise PackVersionNotFoundError(
                f"Pack version {version_id!r} not found for character {character_id!r}"
            )
        return _map_version(version)

    def attach_asset(
        self,
        version_id: str,
        workspace_id: str,
        pose_slot: str,
        artifact_id: str,
    ) -> AssetRecord:
        _ensure_workspace(self._session, workspace_id)
        version = self._session.scalar(
            select(CharacterPackVersion)
            .options(_ASSET_ARTIFACT_LOAD)
            .where(
                CharacterPackVersion.id == version_id,
                CharacterPackVersion.workspace_id == workspace_id,
            )
        )
        if version is None:
            raise PackVersionNotFoundError(f"Pack version {version_id!r} not found")

        if version.status == "published":
            raise PackVersionImmutableError("Cannot attach assets to a published Pack Version")

        artifact = self._session.scalar(
            select(Artifact).where(
                Artifact.id == artifact_id,
                Artifact.workspace_id == workspace_id,
            )
        )
        if artifact is None or artifact.state != "ready":
            raise ValueError(f"Artifact {artifact_id!r} is invalid or not in ready state")

        existing_asset = next(
            (a for a in version.assets if a.pose_slot == pose_slot), None
        )
        if existing_asset is not None:
            existing_asset.artifact_id = artifact_id
            existing_asset.updated_at = datetime.now(UTC)
            self._session.flush()
            return _map_asset(existing_asset)

        asset = CharacterAsset(
            pack_version_id=version_id,
            workspace_id=workspace_id,
            pose_slot=pose_slot,
            artifact_id=artifact_id,
        )
        self._session.add(asset)
        self._session.flush()
        return _map_asset(asset)

    def declare_reference_manifest(
        self,
        version_id: str,
        workspace_id: str,
        manifest: str | Mapping[str, Any],
    ) -> PackVersionRecord:
        """Declare the FROZEN requirement manifest of a reference pack (MF-END-04).

        Write-once on a live draft: sets ``pack_contract_version`` to
        ``reference_pack_v1`` and records the manifest text plus its SHA-256,
        computed over the stored UTF-8 text and never re-derived later.  The
        manifest is structurally validated here (version, contract, reference
        keys, duplicates, capabilities) so a draft can never carry a
        declaration that the publish gate must refuse outright; publication
        re-validates it against the attached assets.

        Raises:
            PackVersionNotFoundError: version missing or foreign (404).
            PackVersionImmutableError: version is not a live draft (409).
            PackVersionConflictError: a manifest is already declared for this
                version — the declaration is write-once (409).
            ValueError: the manifest is not a structurally valid reference
                manifest (422 semantics).
        """
        from app.workflow.character_validator import (  # noqa: PLC0415
            PackContractBranch,
            parse_reference_manifest,
        )

        version = self._session.scalar(
            select(CharacterPackVersion).where(
                CharacterPackVersion.id == version_id,
                CharacterPackVersion.workspace_id == workspace_id,
            )
        )
        if version is None:
            raise PackVersionNotFoundError(f"Pack version {version_id!r} not found")

        if version.status != "draft" or version.archived_at is not None:
            raise PackVersionImmutableError(
                "Cannot declare a reference manifest on a non-draft Pack "
                f"Version (status={version.status!r})"
            )
        if version.requirement_manifest_json is not None:
            raise PackVersionConflictError(
                "A reference manifest is already declared for this Pack "
                "Version (declaration is write-once)"
            )

        if isinstance(manifest, str):
            text = manifest
        elif isinstance(manifest, Mapping):
            text = json.dumps(
                dict(manifest),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        else:
            raise ValueError("manifest must be a JSON string or a mapping")

        text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        parsed = parse_reference_manifest(
            PackContractBranch(
                pack_contract_version=PACK_CONTRACT_VERSION_REFERENCE,
                requirement_manifest_json=text,
                requirement_manifest_sha256=text_sha256,
            )
        )
        if parsed.errors:
            raise ValueError("invalid reference manifest: " + "; ".join(parsed.errors))

        version.pack_contract_version = PACK_CONTRACT_VERSION_REFERENCE
        version.requirement_manifest_json = text
        version.requirement_manifest_sha256 = text_sha256
        self._session.flush()
        return _map_version(version)

    def _reference_publish_snapshot(
        self, version: CharacterPackVersion, manifest
    ) -> str:
        """Freeze the reviewed declaration at publish (MF-END-04.3).

        Records the branch, the manifest identity and the EXACT per-key
        artifact hashes that were validated, so a published reference pack is
        provably the manifest that was reviewed.
        """
        record = _map_version(version)
        attached = {asset.pose_slot: asset for asset in record.assets}
        return json.dumps(
            {
                "validated_at": datetime.now(UTC).isoformat(),
                "pack_contract_version": PACK_CONTRACT_VERSION_REFERENCE,
                "manifest_version": manifest.manifest_version,
                "requirement_manifest_sha256": version.requirement_manifest_sha256,
                "required_keys": [req.key for req in manifest.requirements],
                "references": [
                    {
                        "key": req.key,
                        "artifact_id": attached[req.key].artifact_id,
                        "artifact_sha256": attached[req.key].artifact_sha256,
                    }
                    for req in manifest.requirements
                    if req.key in attached
                ],
                "asset_count": len(version.assets),
            }
        )

    def _verify_frozen_reference_snapshot(self, version: CharacterPackVersion) -> None:
        """Refuse when a published reference pack no longer matches its frozen
        publish snapshot (the manifest is immutable after publish).

        Raised as a 409-class conflict: the row state no longer matches
        the frozen snapshot this publish call is asked to re-affirm.  (The
        publish route translates PackVersionConflictError and
        PublishValidationFailedError; PackVersionImmutableError is not part
        of the publish route contract and would surface as an unmapped
        error.)"""
        try:
            snapshot = json.loads(version.validation_json or "")
        except ValueError as exc:
            raise PackVersionConflictError(
                "Published reference pack has no readable publish snapshot; "
                "refusing to re-publish"
            ) from exc
        if (
            snapshot.get("pack_contract_version") != PACK_CONTRACT_VERSION_REFERENCE
            or snapshot.get("requirement_manifest_sha256")
            != version.requirement_manifest_sha256
        ):
            raise PackVersionConflictError(
                "Published reference pack manifest no longer matches the "
                "frozen publish snapshot: mutation after publish is refused"
            )

    def publish_pack_version(
        self, version_id: str, workspace_id: str, revision: int
    ) -> PackVersionRecord:
        version = self._session.scalar(
            select(CharacterPackVersion)
            .options(_ASSET_ARTIFACT_LOAD)
            .where(
                CharacterPackVersion.id == version_id,
                CharacterPackVersion.workspace_id == workspace_id,
            )
        )
        if version is None:
            raise PackVersionNotFoundError(f"Pack version {version_id!r} not found")

        if version.revision != revision:
            raise PackVersionConflictError(
                f"CAS revision mismatch: expected {version.revision}, got {revision}"
            )

        if version.status == "published":
            # A published reference pack must still be the declared manifest
            # that was frozen at publish; a mutated row is refused here.
            if version.pack_contract_version == PACK_CONTRACT_VERSION_REFERENCE:
                self._verify_frozen_reference_snapshot(version)
            return _map_version(version)

        from app.workflow.character_validator import (  # noqa: PLC0415 - avoids import cycle
            PackContractBranch,
            parse_reference_manifest,
            reference_pack_completeness,
            validate_character_pack,
        )

        branch = PackContractBranch(
            pack_contract_version=(
                version.pack_contract_version or PACK_CONTRACT_VERSION_LEGACY
            ),
            requirement_manifest_json=version.requirement_manifest_json,
            requirement_manifest_sha256=version.requirement_manifest_sha256,
        )
        record = _map_version(version)

        # Full validation gate (S06-T03 correction; reference branch
        # MF-END-04).  The repository itself runs the complete validator —
        # requirement completeness, Artifact ready state, on-disk file
        # existence, size/checksum integrity, image decode, per-requirement
        # transparency and resolution policy — so an invalid pack cannot
        # publish through the API OR through a direct service call.
        manifest = None
        if branch.pack_contract_version == PACK_CONTRACT_VERSION_LEGACY:
            present_slots = {a.pose_slot for a in version.assets}
            missing_slots = [
                slot for slot in CORE_POSE_SLOTS if slot not in present_slots
            ]
            errors = validate_character_pack(record, self._storage_root)
        else:
            manifest = parse_reference_manifest(branch)
            _complete, missing_slots = reference_pack_completeness(record, manifest)
            errors = validate_character_pack(record, self._storage_root, branch=branch)
        if errors:
            raise PublishValidationFailedError(
                f"Cannot publish pack version: {'; '.join(errors)}",
                missing_slots=missing_slots,
                errors=errors,
            )

        version.status = "published"
        version.published_at = datetime.now(UTC)
        if manifest is not None:
            version.validation_json = self._reference_publish_snapshot(
                version, manifest
            )
        else:
            version.validation_json = json.dumps({
                "validated_at": datetime.now(UTC).isoformat(),
                "core_slots": list(CORE_POSE_SLOTS),
                "asset_count": len(version.assets),
            })
        version.revision += 1
        self._session.flush()

        # Update character status to ready if it was draft
        char = self._session.scalar(
            select(Character).where(Character.id == version.character_id)
        )
        if char is not None and char.status in ("draft", "needs_review"):
            char.status = "ready"
            if char.default_version_id is None:
                char.default_version_id = version.id
            char.revision += 1
            self._session.flush()

        return _map_version(version)

    def set_default_version(
        self, character_id: str, workspace_id: str, version_id: str | None, revision: int
    ) -> CharacterRecord:
        char = self._session.scalar(
            select(Character).where(
                Character.id == character_id,
                Character.workspace_id == workspace_id,
            )
        )
        if char is None:
            raise CharacterNotFoundError(f"Character {character_id!r} not found")

        if char.revision != revision:
            raise CharacterConflictError(
                f"CAS revision mismatch: expected {char.revision}, got {revision}"
            )

        if version_id is not None:
            version = self._session.scalar(
                select(CharacterPackVersion).where(
                    CharacterPackVersion.id == version_id,
                    CharacterPackVersion.character_id == character_id,
                    CharacterPackVersion.workspace_id == workspace_id,
                )
            )
            if version is None or version.status == "archived":
                raise PackVersionNotFoundError(
                    f"Version {version_id!r} not found or is archived"
                )

        char.default_version_id = version_id
        char.revision += 1
        self._session.flush()
        return _map_character(char)

    def resolve_asset_content(
        self,
        character_id: str,
        version_id: str,
        asset_id: str,
        workspace_id: str,
    ) -> tuple[AssetRecord, Path, str]:
        """Resolve a servable pose asset file for the content endpoint.

        Verifies the full ownership chain (version belongs to the character,
        asset belongs to the version, all in the workspace), then resolves the
        managed file strictly through :class:`ManagedRoot` containment and
        serves it only when it is a ready, existing, decodable image with an
        approved MIME type whose size/checksum match the registered metadata.

        Returns ``(asset, absolute_path, mime_type)``.

        Raises:
            PackVersionNotFoundError: version missing or foreign (404).
            AssetNotFoundError: asset missing or foreign (404).
            AssetNotReadyError: artifact not in ``ready`` state (409).
            AssetContentError: missing file, wrong MIME, corrupt image,
                checksum/size mismatch, or containment escape (422).
        """
        version = self.get_pack_version_for_character(
            character_id, version_id, workspace_id
        )
        asset = next((a for a in version.assets if a.id == asset_id), None)
        if asset is None:
            raise AssetNotFoundError(
                f"Asset {asset_id!r} not found in pack version {version_id!r}"
            )

        if asset.artifact_state != "ready":
            raise AssetNotReadyError(
                f"Asset {asset_id!r} artifact is not in ready state "
                f"(state={asset.artifact_state!r})"
            )

        if asset.artifact_mime_type not in APPROVED_IMAGE_MIME_TYPES:
            raise AssetContentError(
                f"Asset {asset_id!r} has no approved image MIME type "
                f"(type={asset.artifact_mime_type!r})"
            )

        if not asset.artifact_relative_path:
            raise AssetContentError(f"Asset {asset_id!r} has no managed path")

        managed = ManagedRoot(self._storage_root)
        try:
            path = managed.resolve(asset.artifact_relative_path)
        except ManagedPathError as exc:
            raise AssetContentError(
                f"Asset {asset_id!r} path escapes managed storage"
            ) from exc

        if not path.is_file():
            raise AssetNotFoundError(
                f"Asset {asset_id!r} content file is missing on disk"
            )

        stat = path.stat()
        if asset.artifact_size_bytes is None or stat.st_size != asset.artifact_size_bytes:
            raise AssetContentError(
                f"Asset {asset_id!r} size mismatch: registered "
                f"{asset.artifact_size_bytes} bytes, on disk {stat.st_size} bytes"
            )

        if not asset.artifact_sha256:
            raise AssetContentError(f"Asset {asset_id!r} is missing its SHA-256 checksum")
        if hash_file(path) != asset.artifact_sha256:
            raise AssetContentError(f"Asset {asset_id!r} SHA-256 checksum mismatch")

        try:
            with Image.open(path) as img:
                img.load()
        except Exception as exc:  # noqa: BLE001 - decode failure fails closed
            raise AssetContentError(
                f"Asset {asset_id!r} is not a decodable image"
            ) from exc

        return asset, path, asset.artifact_mime_type

    def validate_pack_version(
        self, version_id: str, workspace_id: str
    ) -> PackVersionValidationResult:
        """Read-only draft validation using the SAME validator as publish.

        Runs :func:`app.workflow.character_validator.validate_character_pack`
        — the authoritative publish gate, on the version's declared contract
        branch (legacy six-slot or reference manifest) — and returns
        requirement completeness plus the full actionable error list WITHOUT
        publishing or mutating the pack.  No database writes are performed by
        this method.

        ``complete`` and validation validity are separate answers and are
        never conflated: a pack can be ``complete`` and still carry errors
        (and therefore stay unpublishable), and a pack missing a required
        entry reports ``complete=False`` with every missing view/key named.
        """
        from app.workflow.character_validator import (  # noqa: PLC0415
            PackContractBranch,
            parse_reference_manifest,
            reference_pack_completeness,
            validate_character_pack,
        )

        version_row = self._session.scalar(
            select(CharacterPackVersion)
            .options(_ASSET_ARTIFACT_LOAD)
            .where(
                CharacterPackVersion.id == version_id,
                CharacterPackVersion.workspace_id == workspace_id,
            )
        )
        if version_row is None:
            raise PackVersionNotFoundError(f"Pack version {version_id!r} not found")
        version = _map_version(version_row)

        branch = PackContractBranch(
            pack_contract_version=(
                version_row.pack_contract_version or PACK_CONTRACT_VERSION_LEGACY
            ),
            requirement_manifest_json=version_row.requirement_manifest_json,
            requirement_manifest_sha256=version_row.requirement_manifest_sha256,
        )

        if branch.pack_contract_version == PACK_CONTRACT_VERSION_LEGACY:
            present_slots = {a.pose_slot for a in version.assets}
            missing_slots = [
                slot for slot in CORE_POSE_SLOTS if slot not in present_slots
            ]
            errors = validate_character_pack(version, self._storage_root)
            complete = not missing_slots
        else:
            manifest = parse_reference_manifest(branch)
            complete, missing_slots = reference_pack_completeness(version, manifest)
            errors = validate_character_pack(version, self._storage_root, branch=branch)

        return PackVersionValidationResult(
            version_id=version_id,
            character_id=version.character_id,
            workspace_id=workspace_id,
            complete=complete,
            missing_slots=missing_slots,
            errors=errors,
        )

