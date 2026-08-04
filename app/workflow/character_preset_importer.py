"""Preset character asset importer workflow (S06-T02).

Imports pre-existing preset assets into draft Character packs without mutating
original source files, calculating SHA256 checksums and creating ready Artifacts.
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.persistence.characters import (
    CharacterRecord,
    CharacterRepository,
    PackVersionRecord,
    _ensure_workspace,
)
from app.persistence.models import CORE_POSE_SLOTS, Artifact


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class CharacterPresetImporter:
    """Imports preset character image directories into workspace character packs."""

    def __init__(self, session: Session, storage_root: Path | None = None) -> None:
        self._session = session
        self._storage_root = storage_root or Path("artifacts")

    def import_preset(
        self,
        workspace_id: str,
        name: str,
        code: str,
        preset_dir: Path,
        pose_mapping: dict[str, str] | None = None,
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
            pose_mapping: Optional map of pose_slot -> filename (e.g. {'front': 'pose_0.png'}).
                Defaults to slot_name + '.png' or '.jpg'.
            character_type: 'character', 'prop', or 'other'.
            symmetry: 'symmetric' or 'asymmetric'.
            description: Optional character description.

        Returns:
            Tuple of (CharacterRecord, PackVersionRecord).
        """
        if not preset_dir.is_dir():
            raise FileNotFoundError(f"Preset directory {preset_dir} does not exist")

        _ensure_workspace(self._session, workspace_id)
        repo = CharacterRepository(self._session)

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

        # 3. Process pose slots
        mapping = pose_mapping or {}
        dest_dir = self._storage_root / "characters" / workspace_id / char_record.id
        dest_dir.mkdir(parents=True, exist_ok=True)

        for slot in CORE_POSE_SLOTS:
            # Find candidate file
            candidate_name = mapping.get(slot)
            src_file: Path | None = None
            if candidate_name:
                cand = preset_dir / candidate_name
                if cand.is_file():
                    src_file = cand
            else:
                for ext in [".png", ".jpg", ".jpeg", ".webp"]:
                    cand = preset_dir / f"{slot}{ext}"
                    if cand.is_file():
                        src_file = cand
                        break

            if src_file is None:
                continue

            # Copy file to managed storage without mutating original
            dest_filename = f"{slot}_{uuid.uuid4().hex[:8]}{src_file.suffix}"
            dest_path = dest_dir / dest_filename
            shutil.copy2(src_file, dest_path)

            # Register Artifact
            sha = _sha256_file(dest_path)
            size = dest_path.stat().st_size
            rel_path = f"characters/{workspace_id}/{char_record.id}/{dest_filename}"

            art = Artifact(
                workspace_id=workspace_id,
                kind="image",
                relative_path=rel_path,
                state="ready",
                sha256=sha,
                size_bytes=size,
                mime_type="image/png" if src_file.suffix == ".png" else "image/jpeg",
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
