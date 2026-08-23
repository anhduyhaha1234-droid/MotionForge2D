"""Project preset manager — save/load character mapping presets.

S08-H02-C2: all client-controlled preset names/filenames are validated and
contained through :func:`safe_preset_output_path` (save) and
:func:`safe_preset_path` (apply) BEFORE any filesystem join.  A hostile name
(or a ``..``/separator/absolute/drive-qualified/symlink-escape) is rejected
with :class:`InvalidPresetNameError` (mapped to a stable 4xx by the routes) —
it can never escape ``<project>/presets`` and never reaches ``project.json``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path, PurePath
from typing import Any

from pydantic import BaseModel, Field

#: Preset filenames that must never be overwritten (Windows is
#: case-insensitive).  ``project.json`` is the project's own manifest.
_RESERVED_PRESET_FILENAMES: frozenset[str] = frozenset({"project.json"})


class InvalidPresetNameError(ValueError):
    """A preset name/filename is not safe to join into a preset path."""


def _reject_hostile(name: str, *, label: str) -> str:
    """Validate a single-segment preset name/filename; raise on hostility.

    Returns the ``name`` unchanged when safe.  Rejects slash/backslash/
    ``..``/dot-only/absolute/drive-qualified/control-byte/reserved inputs.
    Control bytes are detected BEFORE any null-stripping so ``a\\x00b`` is
    refused, never silently sanitized.
    """
    raw_input = name or ""
    if any(ord(c) < 32 for c in raw_input):
        raise InvalidPresetNameError(f"{label} contains control bytes")
    raw = raw_input.strip().replace("\x00", "")
    if not raw:
        raise InvalidPresetNameError(f"{label} is empty")
    if "/" in raw or "\\" in raw or ".." in raw or raw.strip(".") == "":
        raise InvalidPresetNameError(
            f"{label} contains forbidden path characters"
        )
    if Path(raw).is_absolute() or PurePath(raw).name != raw:
        raise InvalidPresetNameError(
            f"{label} must be a single safe segment (no drives/slashes)"
        )
    return raw


def slugify_preset_name(name: str) -> str:
    """Strict single-segment slug for a preset display name.

    The slug drives the FILE name; the original *name* is kept as display
    metadata inside the JSON.  Never returns ``.``/``..``/empty (falls back to
    ``preset``).  NOTE (S08-H02-C3): the slug is a *base* only — collisions of
    DISTINCT display names onto one slug are resolved by
    :func:`unique_preset_output_path` so no existing preset is overwritten.
    """
    slug = re.sub(r"[^a-z0-9_-]+", "_", (name or "").lower()).strip("_")
    if not slug:
        return "preset"
    return slug


def _assert_presets_root_contained(presets_dir: Path, project_dir: Path) -> None:
    """Anchor the presets root (unresolved AND resolved) inside the project dir.

    ``project_dir`` is already validated by the caller (``pwf._project_dir`` +
    ``_assert_contained``).  If ``<project>/presets`` is itself a junction or
    symlink pointing OUTSIDE the project, the literal path passes the first
    check but its RESOLVED path exits the validated project root — the
    save/apply is rejected with :class:`InvalidPresetNameError` (stable 422,
    zero side effects).  Raising on the root relocation covers BOTH the save
    and the apply resolver because each calls this before any filesystem join.
    """
    project_abs = Path(project_dir).resolve()
    unresolved = Path(presets_dir)
    resolved = Path(presets_dir).resolve()
    if unresolved != project_abs and not unresolved.is_relative_to(project_abs):
        raise InvalidPresetNameError("presets root escapes the project directory")
    if resolved != project_abs and not resolved.is_relative_to(project_abs):
        raise InvalidPresetNameError(
            "presets root resolves outside the project directory"
        )


def _stored_preset_name(path: Path) -> str | None:
    """Best-effort read of an existing preset's stored ``name`` (None if not).

    Used to tell an in-place update (same display name) from a COLLISION
    (different display name mapping to the same slug).  An unreadable/foreign
    file conservatively yields None so it is never clobbered.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, dict):
        name = data.get("name")
        if isinstance(name, str) and name:
            return name
    return None


def unique_preset_output_path(
    presets_dir: Path, project_dir: Path, display_name: str
) -> Path:
    """ATOMIC exclusive reservation of a collision-safe output path (save).

    S08-H02-C4 (Finding 1) — the previous ``while candidate.exists()`` check
    was a check-then-*write* race: two saves of DISTINCT display names that
    slugify identically (``A!`` and ``A?`` -> ``a``) could both observe that
    ``a.json`` does not exist and both commit to it; the later write silently
    clobbered the earlier preset (Codex repro: same_target=True,
    files=['a.json'], errors=[]).

    This version claims the file with an ATOMIC exclusive reservation —
    ``os.open(O_CREAT|O_EXCL)`` — inside the retry loop.  Exactly one save can
    own ``a.json``; every loser retries the next server-owned numeric suffix
    (``a-2.json``, ``a-3.json``, ...) until it exclusively owns a file of its
    own.  Two concurrent successful saves therefore ALWAYS produce two
    DISTINCT durable presets; neither can ever silently overwrite the other,
    and the collision decision never depends on a process-local ``exists()``.

    Re-saving the SAME display name still updates its own file in place: when
    the existing file was fully written and carries the same display name, it
    is returned unchanged for in-place update (no new suffix accumulates).

    The reservation creates the (empty) file, which the caller then hands to
    :meth:`PresetService.save_preset` to fill with the JSON document.  A file
    reserved-but-not-yet-written is never mistaken for an existing preset
    (empty/unreadable JSON yields ``None`` from :func:`_stored_preset_name`,
    so it can never be clobbered by the same-name fast path).
    """
    base = safe_preset_output_path(presets_dir, project_dir, display_name)
    base.parent.mkdir(parents=True, exist_ok=True)
    slug = base.stem
    candidate = base
    n = 2
    while True:
        try:
            fd = os.open(
                candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
            )
            os.close(fd)
            return candidate  # exclusively reserved; caller writes it next.
        except FileExistsError:
            stored = _stored_preset_name(candidate)
            if stored is not None and stored.casefold() == display_name.casefold():
                return candidate  # same-named preset -> in-place update
            if n > 10000:  # pragma: no cover - unreachable safety cap
                raise InvalidPresetNameError(
                    "unable to reserve a unique preset filename"
                ) from None
            candidate = base.with_name(f"{slug}-{n}.json")
            n += 1


def safe_preset_output_path(
    presets_dir: Path, project_dir: Path, display_name: str
) -> Path:
    """Validated, containment-checked preset path under *presets_dir* (save).

    ``display_name`` is validated first (hostile → :class:`InvalidPresetNameError`)
    and kept as display metadata; the FILE name is a strict slug.  The presets
    root itself (unresolved AND resolved) is anchored to the validated
    *project_dir* (:func:`_assert_presets_root_contained`), then the returned
    path is resolved and proven strictly under ``presets_dir``.
    """
    _reject_hostile(display_name, label="preset name")
    filename = f"{slugify_preset_name(display_name)}.json"
    if filename.casefold() in _RESERVED_PRESET_FILENAMES:
        raise InvalidPresetNameError(
            "preset filename collides with a reserved project entry"
        )
    # Lexical pre-check BEFORE any side effect: the absolute (unresolved)
    # presets root must already lie under the absolute project dir.  Running
    # before mkdir means a hostile project path can never cause a directory
    # to be created outside the project; the resolved junction/symlink check
    # (below) still follows it and is now race-free on Windows.
    abs_presets = Path(presets_dir).absolute()
    abs_project = Path(project_dir).absolute()
    if abs_presets != abs_project and not abs_presets.is_relative_to(abs_project):
        raise InvalidPresetNameError("presets root escapes the project directory")
    # S08-H02-C4 (Finding 1): materialize the presets container BEFORE the
    # resolve()-based checks.  On Windows, Path.resolve() can canonicalize
    # the SAME path differently depending on whether the directory already
    # exists, so a concurrent first-save that creates the dir between two
    # internal resolve() calls can spuriously fail the containment checks.
    # Creating the container up-front (valid names only — hostile/reserved
    # inputs and lexical escapes already raised above; an existing junction
    # root is a no-op and is then rejected by the check that follows) makes
    # every resolve() stable and race-free.
    presets_dir.mkdir(parents=True, exist_ok=True)
    _assert_presets_root_contained(presets_dir, project_dir)
    base = Path(presets_dir).resolve()
    target = base / filename
    try:
        resolved = target.resolve(strict=False)
    except OSError:
        resolved = target.absolute()
    if resolved != base and not resolved.is_relative_to(base):
        raise InvalidPresetNameError(
            "preset path escapes the presets directory"
        )
    return resolved


def safe_preset_path(
    presets_dir: Path, project_dir: Path, preset_filename: str
) -> Path:
    """Validated, containment-checked preset path under *presets_dir* (apply).

    ``preset_filename`` must be a single safe segment ending in ``.json``.
    The presets root itself (unresolved AND resolved) is anchored to the
    validated *project_dir*, and then the target is resolved and proven to stay
    under ``presets_dir`` (directory/symlink/junction escape rejected).
    Hostile input → :class:`InvalidPresetNameError`.
    """
    _reject_hostile(preset_filename, label="preset filename")
    if not preset_filename.lower().endswith(".json"):
        raise InvalidPresetNameError("preset filename must end with .json")
    _assert_presets_root_contained(presets_dir, project_dir)
    base = Path(presets_dir).resolve()
    target = base / preset_filename
    try:
        resolved = target.resolve(strict=False)
    except OSError:
        resolved = target.absolute()
    if resolved != base and not resolved.is_relative_to(base):
        raise InvalidPresetNameError(
            "preset path resolves outside the presets directory"
        )
    return resolved


class CharacterMapping(BaseModel):
    """A single character-to-asset mapping."""

    original_name: str = ""
    replacement_asset: str = ""
    voice_config: dict[str, Any] = Field(default_factory=dict)
    replacement_config: dict[str, Any] = Field(default_factory=dict)


class ProjectPreset(BaseModel):
    """A reusable preset for character replacement configurations."""

    name: str = "Untitled Preset"
    description: str = ""
    version: str = "1.0.0"
    mappings: list[CharacterMapping] = Field(default_factory=list)
    dubbing_config: dict[str, Any] = Field(default_factory=dict)


class PresetService:
    """Save and load project presets."""

    def save_preset(
        self,
        preset: ProjectPreset,
        output_path: Path,
    ) -> Path:
        """Save preset to JSON file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            preset.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return output_path

    def load_preset(self, preset_path: Path) -> ProjectPreset:
        """Load preset from JSON file."""
        if not preset_path.exists():
            raise FileNotFoundError(f"Preset not found: {preset_path}")
        data = json.loads(preset_path.read_text(encoding="utf-8"))
        return ProjectPreset.model_validate(data)

    def list_presets(self, presets_dir: Path) -> list[dict[str, Any]]:
        """List all presets in a directory."""
        if not presets_dir.exists():
            return []
        presets: list[dict[str, Any]] = []
        for p in sorted(presets_dir.glob("*.json")):
            try:
                preset = self.load_preset(p)
                presets.append({
                    "filename": p.name,
                    "name": preset.name,
                    "description": preset.description,
                    "mapping_count": len(preset.mappings),
                })
            except Exception:
                continue
        return presets

    def apply_preset_to_project(
        self,
        preset: ProjectPreset,
        project_data: Any,
    ) -> int:
        """Apply preset mappings to matching objects in a project.

        Matches by original_name field.

        Returns:
            Number of objects updated.
        """
        updated = 0
        for mapping in preset.mappings:
            for obj in project_data.objects:
                if obj.name == mapping.original_name:
                    if mapping.replacement_config:
                        for k, v in mapping.replacement_config.items():
                            if hasattr(obj.replacement_config, k):
                                setattr(obj.replacement_config, k, v)
                    updated += 1
        return updated
