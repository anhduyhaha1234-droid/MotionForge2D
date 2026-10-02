"""Preset character asset importer workflow (S06-T02, corrected).

Imports pre-existing preset pose assets into a new draft Character pack:

- Discovers pose files through the explicit :class:`PresetLayoutManifest`
  adapter, which documents the repository's real ``presets/characters/``
  layout (``<set>_<pose>.png``) and maps layout pose names to canonical
  slots.  Explicit ``pose_mapping`` overrides discovery.
- Rejects absolute paths, drive/UNC paths and ``..`` traversal in explicit
  mappings; every resolved source file is enforced to live inside
  *preset_dir*.
- Copies files into managed storage (``artifacts/characters/``) without ever
  mutating the original preset source files.
- Registers a managed ``Artifact`` row (state ``ready``) for every copied
  file with its SHA-256 checksum and byte size.
- Creates a draft ``Character`` plus its first ``CharacterPackVersion`` (v1).
- Attaches every available pose asset to its ``pose_slot``.

Managed-file publication is transaction-safe: every file written during an
import is tracked, and the importer deletes them if the import fails OR if
the owning session is rolled back (``after_rollback``), so a later database
failure never leaves orphan files behind.  The caller owns commit; this
service only flushes so the returned records and artifact IDs are usable
before commit.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.persistence.artifacts import ManagedRoot, is_within
from app.persistence.characters import (
    CharacterRecord,
    CharacterRepository,
    PackVersionRecord,
    _ensure_workspace,
)
from app.persistence.models import CORE_POSE_SLOTS, Artifact
from app.workflow.preset_layout_manifest import PresetLayoutManifest

#: Image extension → MIME type used for registered Artifact rows.
_MIME_BY_SUFFIX: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

#: Extensions probed when no explicit pose mapping entry is provided.
_POSE_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp")


class CharacterPresetImporter:
    """Imports preset character image directories into workspace character packs."""

    def __init__(self, session: Session, storage_root: Path | None = None) -> None:
        self._session = session
        self._storage_root: Path = (
            Path(storage_root) if storage_root is not None else Path("artifacts")
        )
        self._manifest = PresetLayoutManifest()
        #: Managed relative paths written by the current import operation.
        self._written: list[str] = []
        self._transaction_listeners: tuple[object, object] | None = None

    def import_preset(
        self,
        workspace_id: str,
        name: str,
        code: str,
        preset_dir: Path,
        pose_mapping: dict[str, str] | None = None,
        set_name: str | None = None,
        character_type: str = "character",
        symmetry: str = "symmetric",
        description: str | None = None,
    ) -> tuple[CharacterRecord, PackVersionRecord]:
        """Import a directory of pose images into a new draft Character pack.

        Args:
            workspace_id: Target workspace ID.
            name: Character display name.
            code: Unique character code.
            preset_dir: Directory containing preset pose image files.
            pose_mapping: Optional map of pose_slot -> filename (e.g.
                ``{'front': 'pose_0.png'}``).  When omitted, files are
                discovered through :class:`PresetLayoutManifest` using the
                repository's real preset layout.  Explicit mapping values
                must be plain filenames inside *preset_dir*: absolute paths,
                drive/UNC paths and ``..`` traversal are rejected.
            set_name: Optional explicit set prefix for manifest discovery
                (e.g. ``'tho_cute'``).  When *pose_mapping* is omitted and
                *preset_dir* mixes poses from multiple character sets,
                discovery raises ``AmbiguousPresetLayoutError`` unless
                *set_name* selects one set.
            character_type: ``'character'``, ``'prop'``, or ``'other'``.
            symmetry: ``'symmetric'`` or ``'asymmetric'``.
            description: Optional character description.

        Returns:
            Tuple of (CharacterRecord, PackVersionRecord) with attached assets.

        Raises:
            FileNotFoundError: if *preset_dir* does not exist.
            CharacterCodeConflictError: if *code* is already active in the
                workspace.
            ValueError: if an explicit mapping value is unsafe (absolute,
                traverses parents, escapes *preset_dir*) or names a file
                that does not exist inside *preset_dir*; or if manifest
                discovery finds an ambiguous multi-set layout.
        """
        if not preset_dir.is_dir():
            raise FileNotFoundError(f"Preset directory {preset_dir} does not exist")

        # Resolve pose files FIRST (discovery/containment failures happen
        # before any DB row or managed file is created).
        if pose_mapping is not None:
            mapping = dict(pose_mapping)
        else:
            mapping = self._manifest.discover(preset_dir, set_name)

        _ensure_workspace(self._session, workspace_id)
        repo = CharacterRepository(self._session)
        managed = ManagedRoot(self._storage_root)

        # Reset per-operation tracking and arm transaction cleanup: files
        # written by this import are removed if the transaction rolls back,
        # and tracking is disarmed once the transaction commits so a LATER
        # rollback of the same session never deletes committed files.
        self._written = []
        self._register_transaction_listeners()

        try:
            # 1. Create draft Character
            char_record = repo.create_character(
                workspace_id=workspace_id,
                name=name,
                code=code,
                character_type=character_type,
                symmetry=symmetry,
                description=description,
            )

            # 2. Create draft Pack Version 1
            ver_record = repo.create_pack_version(char_record.id, workspace_id)

            for slot in CORE_POSE_SLOTS:
                src_file = self._resolve_pose_file(preset_dir, slot, mapping)
                if src_file is None:
                    continue

                # Copy file into managed storage; the original is only read.
                dest_filename = f"{slot}_{uuid.uuid4().hex[:8]}{src_file.suffix}"
                rel_path = f"characters/{workspace_id}/{char_record.id}/{dest_filename}"
                with src_file.open("rb") as stream:
                    sha256, size_bytes = managed.atomic_write_stream(rel_path, stream)
                self._written.append(rel_path)

                # Register Artifact in state ready
                art = Artifact(
                    workspace_id=workspace_id,
                    kind="image",
                    relative_path=rel_path,
                    state="ready",
                    sha256=sha256,
                    size_bytes=size_bytes,
                    mime_type=_MIME_BY_SUFFIX.get(
                        src_file.suffix.lower(), "application/octet-stream"
                    ),
                )
                self._session.add(art)
                self._session.flush()

                # Attach asset to pose slot
                repo.attach_asset(
                    version_id=ver_record.id,
                    workspace_id=workspace_id,
                    pose_slot=slot,
                    artifact_id=art.id,
                )

            # Refetch pack version with attached assets
            updated_ver = repo.get_pack_version(ver_record.id, workspace_id)
            return char_record, updated_ver
        except BaseException:
            # Any failure (including a later DB flush/attach error) must not
            # leave orphan managed files behind.
            self.cleanup_written_files()
            raise

    def cleanup_written_files(self) -> None:
        """Delete every managed file written by this importer (best-effort).

        Idempotent and containment-safe: only files recorded by this importer
        instance are removed, and only paths that resolve inside the managed
        root are touched.  Empty parent directories are pruned up to (not
        including) the managed root.
        """
        if not self._written:
            return
        managed = ManagedRoot(self._storage_root)
        for rel in list(self._written):
            try:
                path = managed.resolve(rel)
                if path.is_file():
                    path.unlink()
                parent = path.parent
                while parent != managed.root and parent.exists():
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
            except Exception:  # noqa: BLE001 - cleanup is best-effort
                continue
        self._written = []

    def _register_transaction_listeners(self) -> None:
        """Arm per-operation cleanup for this session's transaction.

        - ``after_rollback``: the import's transaction ended in rollback, so
          every managed file written by this operation is removed (covers
          both mid-import failures and caller rollback before commit).
        - ``after_commit``: the import's transaction committed, so the
          managed files are legitimately published; per-operation tracking
          is disarmed so a LATER rollback of the same session (an unrelated
          transaction) can never delete committed files.
        """
        if self._transaction_listeners is None:

            def _on_commit(_session: Session) -> None:
                self._written = []

            def _on_rollback(_session: Session) -> None:
                self.cleanup_written_files()

            self._transaction_listeners = (_on_commit, _on_rollback)
            event.listen(self._session, "after_commit", _on_commit)
            event.listen(self._session, "after_rollback", _on_rollback)

    def _resolve_pose_file(
        self, preset_dir: Path, slot: str, mapping: dict[str, str]
    ) -> Path | None:
        """Locate the preset source file for a pose slot, if present."""
        candidate_name = mapping.get(slot)
        if candidate_name is None:
            return None
        return self._validate_mapping_name(preset_dir, slot, candidate_name)

    def _validate_mapping_name(
        self, preset_dir: Path, slot: str, candidate_name: str
    ) -> Path:
        """Validate an explicit mapping value and return its resolved Path.

        Rejects absolute paths, drive/UNC paths, empty names and ``..``
        traversal, and enforces containment of the resolved file under
        *preset_dir* (symlinks included).  An explicit mapping that names a
        missing file raises instead of silently skipping the slot.
        """
        raw = str(candidate_name).replace("\\", "/")
        if raw == "" or raw in (".", "./"):
            raise ValueError(
                f"Invalid pose mapping for slot {slot!r}: empty filename"
            )
        if raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
            raise ValueError(
                f"Invalid pose mapping for slot {slot!r}: absolute paths are "
                f"not allowed: {candidate_name!r}"
            )
        if raw.startswith("//"):
            raise ValueError(
                f"Invalid pose mapping for slot {slot!r}: UNC paths are not "
                f"allowed: {candidate_name!r}"
            )
        if ".." in raw.split("/"):
            raise ValueError(
                f"Invalid pose mapping for slot {slot!r}: parent traversal is "
                f"not allowed: {candidate_name!r}"
            )

        candidate = preset_dir / raw
        if not is_within(candidate, preset_dir):
            raise ValueError(
                f"Invalid pose mapping for slot {slot!r}: path escapes the "
                f"preset directory: {candidate_name!r}"
            )
        if not candidate.is_file():
            raise ValueError(
                f"Invalid pose mapping for slot {slot!r}: file not found in "
                f"preset directory: {candidate_name!r}"
            )
        return candidate
