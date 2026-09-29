"""MF-END-20 smoke: exercise the cache module end-to-end on a real sqlite file."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-20")))
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services.shot_reskin_cache import (
    ShotCacheRefusal,
    ShotReskinCache,
    run_cached_shot_render,
    shot_content_key,
    shot_key_texture,
)

root = Path(r"C:/Users/Admin/AppData/Local/Temp/mf20_smoke")
root.mkdir(parents=True, exist_ok=True)
(tmp := root / "managed").mkdir(exist_ok=True)
db = root / "smoke.db"
if db.exists():
    db.unlink()
engine = create_engine(f"sqlite+pysqlite:///{db}")
SF = sessionmaker(bind=engine)

art = tmp / "out" / "shot_00001_.mp4"
art.parent.mkdir(parents=True, exist_ok=True)
art.write_bytes(b"FAKE-MP4-" + b"x" * 100)
import hashlib

sha = hashlib.sha256(art.read_bytes()).hexdigest()

request = {
    "workspace_id": "default",
    "project_id": "p1",
    "shot_id": "BOOK",
    "chunk_id": "ck_1",
    "attempt_id": "shot-attempt-1",
    "backend": {"backend": "comfy_shot_engine", "profile_id": "wan", "graph_file": "g.json",
                "graph_sha256": "a" * 64, "capability": "cap", "seed": 7, "output_node": "246"},
    "graph": {"file": "g.json", "file_sha256": "a" * 64},
    "parameters": {"prompt": "p", "filename_prefix": "x"},
    "staged_inputs": {"anchor": {"relative_path": "a.png", "sha256": "b" * 64}},
    "anchor": {"relative_path": "a.png", "sha256": "b" * 64},
    "cast": [{"role": "BOOK-P1", "character_id": "ch", "pack_version_id": "pv",
              "references": [{"key": "k", "sha256": "c" * 64}]}],
    "source": {"relative_path": "s.mp4", "sha256": "d" * 64, "size_bytes": 10,
               "fps": {"num": 30, "den": 1}, "span": {"start_frame": 0, "end_frame_exclusive": 10}},
    "output_contract": {"width": 640, "height": 368, "fps_num": 30, "fps_den": 1,
                        "frame_count": 10, "container": "mp4", "video_codec": "h264",
                        "audio": {"mode": "source_remux"}},
}
texture = shot_key_texture(request)
assert len(texture) == 7, texture
key = shot_content_key(request)
print("KEY", key[:16], "components", sorted(texture))

calls = {"n": 0}


def render():
    calls["n"] += 1
    return {"output_relative_path": "out/shot_00001_.mp4", "output_sha256": sha,
            "output_size_bytes": art.stat().st_size, "decoded_sha256": "e" * 64,
            "decoded_frame_count": 10, "fps_num": 30, "fps_den": 1, "prompt_id": "pid-1",
            "graph_object_sha256_submitted": "f" * 64}


out1 = run_cached_shot_render(session_factory=SF, managed_root=tmp, workspace_id="default",
                              run_id="run-1", request=request, render=render)
assert out1["cache_hit"] is False and calls["n"] == 1, out1
print("FIRST", "receipt", out1["receipt"]["receipt_id"][:8], "sidecar", out1["receipt"]["receipt_rel_path"])
assert (tmp / str(out1["receipt"]["receipt_rel_path"])).is_file()

out2 = run_cached_shot_render(session_factory=SF, managed_root=tmp, workspace_id="default",
                              run_id="run-1", request=request, render=render)
assert out2["cache_hit"] is True and calls["n"] == 1, (out2["cache_hit"], calls["n"])
print("REPLAY", "cache_hit", out2["cache_hit"], "posts", calls["n"])

with SF() as s:
    c = ShotReskinCache(s, managed_root=tmp)
    st = c.status(workspace_id="default")
    ro = c.reopen_state(workspace_id="default", run_id="run-1")
    print("STATUS", json.dumps(st))
    print("REOPEN", json.dumps({k: ro[k] for k in ("statements_used", "attempts", "receipts", "rows_total")}))
    assert st["statements_used"] == 2 and ro["statements_used"] == 1
    assert st["attempts"]["total"] == 1 and st["receipts"]["total"] == 1
    g = c.assert_run_receipts_live(workspace_id="default", run_id="run-1")
    print("GUARD", g)
    # tamper -> guard refuses
    art.write_bytes(b"TAMPERED")
    try:
        c.assert_run_receipts_live(workspace_id="default", run_id="run-1")
        raise AssertionError("guard must refuse tampered receipt")
    except ShotCacheRefusal as exc:
        print("GUARD_REFUSED", exc.code.value)
    art.write_bytes(b"FAKE-MP4-" + b"x" * 100)
    # in-doubt restart
    req2 = json.loads(json.dumps(request))
    req2["chunk_id"] = "ck_2"
    req2["attempt_id"] = "shot-attempt-2"
    req2["source"]["span"]["end_frame_exclusive"] = 20
    with SF() as s:
        c = ShotReskinCache(s, managed_root=tmp)
        b = c.begin_attempt(workspace_id="default", request=req2, run_id="run-1")
        assert b["action"] == "submit", b
        c.mark_submitted(workspace_id="default", attempt_row_id=b["attempt"]["attempt_row_id"])
        s.commit()
    with SF() as s:
        c = ShotReskinCache(s, managed_root=tmp)
        b2 = c.begin_attempt(workspace_id="default", request=req2, run_id="run-1")
        print("IN_DOUBT", b2["action"])
        assert b2["action"] == "in_doubt"
        b3 = c.begin_attempt(workspace_id="default", request=req2, run_id="run-1", retry=True)
        print("RETRY", b3["action"], "superseded", b3["superseded"]["state"], "no", b3["attempt"]["attempt_no"])
        s.commit()
print("SMOKE_OK")
