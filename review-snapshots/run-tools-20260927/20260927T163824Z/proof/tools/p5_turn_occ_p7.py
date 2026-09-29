"""TURN + OCC re-runs (anchors now staged), then the P7 assembly - all on the running server.

P7 is ComfyUI-native: LoadVideo x3 (the three accepted clips) + LoadAudio x3 (the three SOURCE
windows) -> AudioConcat chain -> ConcatenateVideo(videos autogrow, complete_audio) -> SaveVideo.
A decode check at the end proves frame count / duration / audio presence / reopenability.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
EVID = PROOF / "evidence"
BASE = "http://127.0.0.1:8321"
sys.path.insert(0, str(PROOF / "tools"))
import p567_runs  # noqa: E402  (reuse the tested job runner)

PID = int(sys.argv[1]) if len(sys.argv) > 1 else 31292
p567_runs.PID = PID

CLIPS = {"BOOK": PROOF / "output" / "p3b" / "animate2_book_p3b_00001_.mp4",
         "TURN": PROOF / "output" / "p5_turn" / "animate2_turn_p5_00001_.mp4",
         "OCC": PROOF / "output" / "p5_occ" / "animate2_occ_p5_00001_.mp4"}
SOURCES = {"BOOK": "BOOK_src.mp4", "TURN": "TURN_795_src.mp4", "OCC": "OCC_14768_src.mp4"}


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build_p7_graph() -> tuple[dict, dict]:
    g = {}
    staged = {}
    for i, shot in enumerate(("BOOK", "TURN", "OCC")):
        src = CLIPS[shot]
        dst = PROOF / "inputs" / f"p7_{shot.lower()}.mp4"
        if not dst.exists() or sha(dst) != sha(src):
            shutil.copy2(src, dst)
        staged[shot] = {"clip_from": str(src.relative_to(PROOF)).replace("\\", "/"),
                        "clip_to": f"inputs/p7_{shot.lower()}.mp4", "sha256": sha(dst),
                        "bytes": dst.stat().st_size,
                        "byte_identical": sha(dst) == sha(src),
                        "audio_source": SOURCES[shot]}
        g[str(10 + i)] = {"class_type": "LoadVideo", "inputs": {"file": f"p7_{shot.lower()}.mp4"}}
        g[str(20 + i)] = {"class_type": "LoadAudio", "inputs": {"audio": SOURCES[shot]}}
    g["31"] = {"class_type": "AudioConcat",
               "inputs": {"audio1": ["20", 0], "audio2": ["21", 0], "direction": "after"}}
    g["32"] = {"class_type": "AudioConcat",
               "inputs": {"audio1": ["31", 0], "audio2": ["22", 0], "direction": "after"}}
    g["40"] = {"class_type": "ConcatenateVideo",
               "inputs": {"videos.video0": ["10", 0], "videos.video1": ["11", 0],
                          "videos.video2": ["12", 0], "codec": "auto",
                          "complete_audio": ["32", 0]}}
    g["50"] = {"class_type": "SaveVideo",
               "inputs": {"video": ["40", 0], "filename_prefix": "p7/assembly_v1",
                          "format": "auto", "format.codec": "auto", "codec": "auto"}}
    return g, staged


def main() -> int:
    out = {"artifact": "P7_RUN.json", "runs": {}}
    # ---- 1. TURN and OCC ---------------------------------------------------------------
    for name, graph_rel, out_rel, receipt, seed in (
            ("TURN", "graphs/animate2_turn.p5.api.json", "output/p5_turn", "P5_TURN_RECEIPT.json",
             2026092801),
            ("OCC", "graphs/animate2_occ.p5.api.json", "output/p5_occ", "P5_OCC_RECEIPT.json",
             2026092802)):
        try:
            out["runs"][name] = p567_runs.run_job(name, graph_rel, out_rel, receipt, seed)
        except Exception as e:  # noqa: BLE001
            out["runs"][name] = {"completed": False, "error": repr(e)[:300]}
            print(f"[{name}] ERROR {e!r}", flush=True)
    # ---- 2. P7 assembly ----------------------------------------------------------------
    graph, staged = build_p7_graph()
    p7 = PROOF / "graphs" / "p7_assembly.api.json"
    p7.write_text(json.dumps(graph, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    outdir = PROOF / "output" / "p7"
    outdir.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in outdir.rglob("*") if p.is_file()}
    req = urllib.request.Request(BASE + "/prompt", data=json.dumps(
        {"prompt": graph, "client_id": "mf-p7-assembly"}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            pid_ = json.loads(r.read())["prompt_id"]
        print(f"[P7] prompt_id {pid_}", flush=True)
        hist, deadline = None, time.time() + 1800
        while time.time() < deadline:
            try:
                h = json.loads(urllib.request.urlopen(f"{BASE}/history/{pid_}", timeout=60).read())
            except Exception:  # noqa: BLE001
                h = {}
            if pid_ in h and (h[pid_].get("status") or {}).get("completed"):
                hist = h[pid_]
                break
            time.sleep(5)
        msgs = (hist or {}).get("status", {}).get("messages", [])
        stamps = {m[0]: m[1].get("timestamp") for m in msgs
                  if isinstance(m, list) and len(m) == 2 and isinstance(m[1], dict)}
        wall = (round((stamps["execution_success"] - stamps["execution_start"]) / 1000.0, 2)
                if stamps.get("execution_success") and stamps.get("execution_start") else None)
        after = sorted(p for p in outdir.rglob("*") if p.is_file() and p.name not in before)
        media = [{"file": str(p.relative_to(PROOF / "output")).replace("\\", "/"),
                  "bytes": p.stat().st_size, "sha256": sha(p)} for p in after]
        p7rec = {"artifact": "P7_ASSEMBLY.json", "prompt_id": pid_, "completed": bool(hist),
                 "graph": "graphs/p7_assembly.api.json", "graph_sha256": sha(p7),
                 "staged": staged, "server_side_wall_s": wall, "output_files": media,
                 "order": ["BOOK (p3b)", "TURN (p5)", "OCC (p5)"],
                 "audio_method": "ComfyUI-native: LoadAudio x3 on the SOURCE windows + AudioConcat "
                                 "chain feeding ConcatenateVideo.complete_audio",
                 "quality_accepted": False}
        (EVID / "P7_ASSEMBLY.json").write_text(json.dumps(p7rec, indent=1, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
        print(f"[P7] completed={bool(hist)} wall={wall}s files={[m['file'] for m in media]}",
              flush=True)
    except Exception as e:  # noqa: BLE001
        out["runs"]["P7"] = {"completed": False, "error": repr(e)[:400]}
        print(f"[P7] ERROR {e!r}", flush=True)
    (EVID / "P7_RUN.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n",
                                      encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
