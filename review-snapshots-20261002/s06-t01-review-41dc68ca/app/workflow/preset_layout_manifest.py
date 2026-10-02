"""Explicit manifest of the repository's real preset-character layout.

The repository ships preset character sets under ``presets/characters/`` as
``<set>_<pose>.png`` files — e.g. ``boy_hacker_three_quarter.png``,
``tho_cute_talking.png``, ``gau_nau_standing.png``.  Canonically named files
(``front.png``) are also recognized for compatibility with hand-built packs.

This module documents that layout and adapts layout pose names to the
canonical pack pose slots (``CORE_POSE_SLOTS``):

====================  ===================  ==================================
Layout pose name      Canonical slot       Semantic rationale
====================  ===================  ==================================
``front``             ``front``            Exact canonical name.
``three_quarter``     ``three_quarter``    Exact canonical name.
``side``              ``side``             Exact canonical name.
``back``              ``back``             Exact canonical name.
``sitting``           ``sitting``          Exact canonical name.
``walking``           ``walking``          Exact canonical name.
``talking``           ``front``            A face-on dialogue pose is the
                                           canonical front view.
``standing``          ``side``             A static upright figure is
                                           represented as a side/profile
                                           view; locomotion is covered by
                                           the ``walking`` slot.
====================  ===================  ==================================

The mapping is a bijection over the repository's six-pose sets (``back``,
``sitting``, ``standing``, ``talking``, ``three_quarter``, ``walking``), so a
complete six-pose set discovers all six canonical slots and is publishable.

**Set selection contract (S06-C2).**  Discovery never mixes pose files from
different character sets.  ``discover`` operates on exactly ONE set:

- pass ``set_name`` (e.g. ``'tho_cute'``) to select the ``<set>_<pose>.png``
  files of that set explicitly; a missing set raises
  :class:`AmbiguousPresetLayoutError`;
- with ``set_name=None`` the directory must contain files of exactly one set
  (or only canonical/bare pose files); a directory holding poses from
  multiple sets — like the repository's shared ``presets/characters/`` — is
  rejected with :class:`AmbiguousPresetLayoutError` listing the candidate
  sets, instead of silently taking the first pose per slot across sets.
"""

from __future__ import annotations

from pathlib import Path

from app.persistence.models import CORE_POSE_SLOTS

#: Image suffixes the manifest recognizes.
_IMAGE_SUFFIXES: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp")

#: Semantic mapping from repository layout pose names to canonical slots.
POSE_NAME_TO_SLOT: dict[str, str] = {
    "front": "front",
    "three_quarter": "three_quarter",
    "side": "side",
    "back": "back",
    "sitting": "sitting",
    "walking": "walking",
    "talking": "front",  # face-on dialogue pose → canonical front view
    "standing": "side",  # static upright figure → canonical side view
}


class AmbiguousPresetLayoutError(ValueError):
    """Raised when a preset directory mixes poses from multiple character sets."""


class PresetLayoutManifest:
    """Discovers pose files for ONE character set in a preset directory.

    Layout: ``presets/characters/<set>_<pose>.png`` where ``<pose>`` is one
    of the documented layout pose names (see module docstring).  Canonical
    files (``<slot>.png``) are recognized as well.

    Discovery is deterministic: files are scanned in sorted filename order,
    and a file whose stem is exactly a canonical slot name takes precedence
    over a suffix-mapped file targeting the same slot.
    """

    #: Human-readable description of the repository layout this manifest
    #: adapts.
    layout_description = "presets/characters/<set>_<pose>.png"

    #: The documented semantic mapping (module constant, exposed for tests).
    semantic_mapping: dict[str, str] = POSE_NAME_TO_SLOT

    def discover(
        self, preset_dir: Path, set_name: str | None = None
    ) -> dict[str, str]:
        """Return ``{canonical_slot: filename}`` for ONE character set.

        Args:
            preset_dir: The preset directory to scan (e.g. the repository's
                ``presets/characters`` directory).
            set_name: Optional explicit set prefix (e.g. ``'tho_cute'``).
                When omitted, the directory must contain files from exactly
                one set (or only canonical/bare pose files); otherwise
                :class:`AmbiguousPresetLayoutError` is raised.

        Returns:
            Map of canonical slot name to the relative filename inside
            *preset_dir* for the selected set.  Files that do not match the
            documented layout are ignored.

        Raises:
            FileNotFoundError: if *preset_dir* does not exist or is not a
                directory.
            AmbiguousPresetLayoutError: if *set_name* is omitted and the
                directory mixes poses from multiple character sets, or if an
                explicit *set_name* is not present in the directory.
        """
        if not preset_dir.is_dir():
            raise FileNotFoundError(f"Preset directory {preset_dir} does not exist")

        grouped: dict[str | None, dict[str, str]] = {}
        for path in sorted(preset_dir.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            parsed = self._parse_stem(path.stem)
            if parsed is None:
                continue
            sname, slot = parsed
            bucket = grouped.setdefault(sname, {})
            if slot in bucket:
                # A canonical-named file wins over a suffix-mapped file for
                # the same slot; otherwise keep the first (sorted) file.
                if path.stem in CORE_POSE_SLOTS:
                    bucket[slot] = path.name
                continue
            bucket[slot] = path.name

        if set_name is not None:
            selected = grouped.get(set_name)
            if selected is None:
                available = sorted(k for k in grouped if k is not None)
                raise AmbiguousPresetLayoutError(
                    f"Preset set {set_name!r} not found in {preset_dir} "
                    f"(available sets: {available or 'none'})"
                )
            return dict(selected)

        named_sets = [k for k in grouped if k is not None]
        canonical_files = grouped.get(None, {})
        if len(named_sets) > 1 or (len(named_sets) == 1 and canonical_files):
            raise AmbiguousPresetLayoutError(
                f"Preset directory {preset_dir} contains poses from multiple "
                f"character sets: {sorted(named_sets)}; pass set_name= to "
                f"select one explicitly"
            )
        if len(named_sets) == 1:
            return dict(grouped[named_sets[0]])
        return dict(canonical_files)

    def _parse_stem(self, stem: str) -> tuple[str | None, str] | None:
        """Parse a filename stem into ``(set_name_or_None, canonical_slot)``.

        Returns None when the stem matches no documented layout pose.

        Pose names may themselves contain underscores (``three_quarter``),
        so the suffix is matched against the known pose-name set rather than
        a naive last-underscore split.  Longer pose names are tried first so
        ``boy_hacker_three_quarter`` resolves to ``three_quarter`` (not
        ``quarter``).
        """
        if stem in CORE_POSE_SLOTS:
            return None, stem
        for pose in sorted(POSE_NAME_TO_SLOT, key=len, reverse=True):
            if stem == pose:
                return None, POSE_NAME_TO_SLOT[pose]
            if stem.endswith(f"_{pose}") and len(stem) > len(pose) + 1:
                return stem[: -len(pose) - 1], POSE_NAME_TO_SLOT[pose]
        return None
