"""Stage-root path scoping.

`COMFYUI_HUNYUAN_CONTROL.md` requires output paths/filenames to be scoped to a
stage root and never arbitrary. ComfyUI returns `{filename, subfolder, type}` for
every produced artifact; every one of those is resolved through `StagePaths`,
which refuses absolute paths, drive letters, `..` traversal and symlink escape.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .errors import PathScopeViolation

_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_UNC_RE = re.compile(r"^(\\\\|//)")


def _reject_fragment(value: str, field: str) -> None:
    if not isinstance(value, str):
        raise PathScopeViolation(f"{field} must be a string", field=field, value=repr(value))
    if "\x00" in value:
        raise PathScopeViolation(f"{field} contains NUL", field=field)
    if _DRIVE_RE.match(value):
        raise PathScopeViolation(f"{field} is an absolute drive path", field=field, value=value)
    if _UNC_RE.match(value):
        raise PathScopeViolation(f"{field} is a UNC path", field=field, value=value)
    if os.path.isabs(value) or value.startswith("/") or value.startswith("\\"):
        raise PathScopeViolation(f"{field} is absolute", field=field, value=value)
    parts = re.split(r"[\\/]+", value)
    if any(p == ".." for p in parts):
        raise PathScopeViolation(f"{field} contains traversal", field=field, value=value)


class StagePaths:
    """Resolves every artifact path inside one immutable stage root."""

    def __init__(self, stage_root: str | os.PathLike[str]) -> None:
        self.root = Path(stage_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, filename: str, subfolder: str = "") -> Path:
        """Resolve a ComfyUI `{subfolder, filename}` pair inside the stage root."""
        _reject_fragment(subfolder or "", "subfolder")
        _reject_fragment(filename, "filename")
        candidate = self.root.joinpath(*(subfolder or "").replace("\\", "/").split("/"))
        candidate = candidate.joinpath(*filename.replace("\\", "/").split("/"))
        resolved = candidate.resolve()
        root_str = str(self.root)
        resolved_str = str(resolved)
        if resolved_str != root_str and not resolved_str.startswith(root_str + os.sep):
            raise PathScopeViolation(
                "resolved artifact path escapes the stage root",
                stage_root=root_str,
                resolved=resolved_str,
                filename=filename,
                subfolder=subfolder,
            )
        return resolved

    def stage_dir(self, *parts: str) -> Path:
        for p in parts:
            _reject_fragment(p, "stage_dir part")
        d = self.root.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def assert_inside(self, path: str | os.PathLike[str]) -> Path:
        resolved = Path(path).resolve()
        root_str = str(self.root)
        if str(resolved) != root_str and not str(resolved).startswith(root_str + os.sep):
            raise PathScopeViolation(
                "path is outside the stage root", stage_root=root_str, resolved=str(resolved)
            )
        return resolved
