"""Debug the long-path probe: where does the sidecar actually land?"""
import os
import sys
from pathlib import Path

sys.path.insert(0, r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-20")
from app.services.shot_reskin_cache import ShotReskinCache, _long_path

root = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-20/managed")
root.mkdir(parents=True, exist_ok=True)
shot = "shot_" + "S" * 20  # short first, to see the mechanics
chunk = "ck_" + "C" * 20

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
engine = create_engine("sqlite+pysqlite:///:memory:")
SF = sessionmaker(bind=engine)
with SF() as s:
    cache = ShotReskinCache(s, managed_root=root)
    print("managed_root attr:", cache._managed_root, "os.name", os.name)
    rel, sha = cache._write_receipt_sidecar(
        {"shot_id": shot, "chunk_id": chunk, "output_relative_path": "x.mp4",
         "output_sha256": "a" * 64, "state": "valid"}
    )
    s.commit()
print("rel:", rel)
plain = root / rel
prefixed = Path("\\\\?\\" + str(plain))
print("plain:", len(str(plain)), plain.is_file())
print("prefixed:", len(str(prefixed)), prefixed.is_file())
import shutil
shutil.rmtree(Path("\\\\?\\" + str(root / "shot_render_cache")), ignore_errors=True)
print("cleaned:", not (root / "shot_render_cache").exists())
