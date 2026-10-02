"""MF-END-20 Windows long-path probe at REAL managed roots (evidence script).

Probes >260-char managed-root paths through the production cache sidecar
writer at (a) the task run-area managed root and (b) the machine's configured
managed root (app.api.deps.get_managed_root()), then cleans up and records
every measurement as JSON.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-20")
sys.path.insert(0, str(WT))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.services.shot_reskin_cache import ShotReskinCache, _long_path  # noqa: E402


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def probe(real_root: Path, tag: str) -> dict[str, object]:
    real_root.mkdir(parents=True, exist_ok=True)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    sf = sessionmaker(bind=engine)
    long_shot = "shot_" + "S" * 120
    long_chunk = "ck_" + "C" * 130
    shot_root = real_root / "shot_render_cache"
    my_dir = shot_root / long_shot
    result: dict[str, object] = {
        "tag": tag,
        "root": str(real_root),
        "root_chars": len(str(real_root)),
    }
    try:
        payload = {
            "shot_id": long_shot,
            "chunk_id": long_chunk,
            "output_relative_path": "engine_out/x_00001_.mp4",
            "output_sha256": "a" * 64,
            "state": "valid",
        }
        with sf() as s:
            cache = ShotReskinCache(s, managed_root=real_root)
            rel, sidecar_sha = cache._write_receipt_sidecar(payload)
            s.commit()
        target = real_root / rel
        resolved = _long_path(target)
        result.update(
            {
                "relative_path": rel,
                "path_chars": len(str(target)),
                "extended_length_form_chars": len(str(resolved)),
                "write": "OK",
                "exists_via_extended_form": bool(resolved.is_file()),
                "sha256_pinned": sidecar_sha,
                "sha256_read_back": _sha_file(resolved),
                "read_roundtrip_ok": bool(
                    json.loads(resolved.read_text(encoding="utf-8"))["chunk_id"] == long_chunk
                ),
                "plain_form_readable": bool(target.is_file()),
                "staging_orphans": len(list(_long_path(my_dir).glob(".*.staging"))),
            }
        )
    finally:
        if my_dir.exists():
            shutil.rmtree(Path("\\\\?\\" + str(my_dir)), ignore_errors=True)
        result["cleanup_dir_removed"] = not my_dir.exists()
        if shot_root.exists() and not any(shot_root.iterdir()):
            try:
                shot_root.rmdir()
            except OSError:
                pass
        result["root_survives"] = real_root.is_dir()
    return result


def main(out_path: Path) -> int:
    roots: list[tuple[str, Path]] = [
        (
            "task_run_area",
            Path(
                r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                r"20260927T163824Z/tasks/MF-END-20/managed"
            ),
        )
    ]
    try:
        from app.api import deps

        roots.append(("configured_managed_root", Path(deps.get_managed_root())))
    except Exception as exc:  # noqa: BLE001
        roots.append(("configured_managed_root", Path(f"<unavailable: {type(exc).__name__}>")))
    measurements = []
    for tag, root in roots:
        if not str(root).startswith("C:") and "unavailable" in str(root):
            measurements.append({"tag": tag, "root": str(root), "skipped": True})
            continue
        measurements.append(probe(root, tag))
    report = {
        "task": "MF-END-20",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "os": os.name,
        "measurements": measurements,
        "all_writes_ok": all(m.get("write") == "OK" for m in measurements if not m.get("skipped")),
        "all_over_260": all(int(m.get("path_chars", 0)) > 260 for m in measurements if not m.get("skipped")),
        "all_cleaned": all(m.get("cleanup_dir_removed") for m in measurements if not m.get("skipped")),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("all_writes_ok", "all_over_260", "all_cleaned")}, sort_keys=True))
    for m in measurements:
        print(json.dumps(m, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
