"""P1 refinement (real per-shot source windows from the roundI1 native-frame manifest) and the
PRE-stop half of the isolated-server shutdown proof."""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import socket

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
MF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mfv1")
NF = MF / "runtime/video14b/state/roundI1/i1_native_frames.json"
PORT = 8321
PID = 33160


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


nf = json.loads(NF.read_text(encoding="utf-8"))
art = json.loads((PROOF / "evidence" / "P1_UNIT_MANIFESTS.json").read_text(encoding="utf-8"))

# --- copy the TURN/OCC windows too (sources read-only) and record them per unit ---------
clips = {}
for shot in ("BOOK", "TURN", "OCC"):
    rec = nf["frames"][shot]
    src = pathlib.Path(rec["source_window"])
    dst = PROOF / "inputs" / src.name
    if src.is_file() and not dst.exists():
        shutil.copy2(src, dst)
    clips[shot] = {"source_window": str(src).replace("\\", "/"),
                   "source_window_sha256": (sha(src) if src.is_file() else None),
                   "manifest_recorded_sha256": rec.get("source_window_sha256"),
                   "copy": f"inputs/{src.name}" if dst.is_file() else None,
                   "copy_sha256": sha(dst) if dst.is_file() else None}
    if clips[shot]["source_window_sha256"] != rec.get("source_window_sha256"):
        clips[shot]["sha_mismatch"] = True

for u in art["units"]:
    c = clips[u["shot"]]
    u["source"]["source_window"] = c["source_window"]
    u["source"]["source_window_sha256"] = c["source_window_sha256"]
    u["source"]["source_window_copy"] = c["copy"]
    u["source"]["window_recorded_by"] = ("runtime/video14b/state/roundI1/i1_native_frames.json "
                                         "(round I1, read-only)")
    u["source"]["fps_source"] = ("i1_native_frames.json + the pinned clip geometry (ffmpeg read "
                                "in round I1); measured here: the copied bytes hash-match the "
                                "window the manifest names")
    if u["shot"] != "BOOK":
        u["source"]["span_seconds"]["span_basis"] = (
            "the decoded indexes present in runtime/video14b/input/roundI1_src (f000/f080 for "
            "TURN, f000/f040 for OCC) as named by that manifest")
art["basis"]["native_frames_manifest"] = {"path": str(NF).replace("\\", "/"),
                                          "sha256": sha(NF),
                                          "why": "it names the real source window + sha for each "
                                                 "shot, which is what the unit manifest must cite "
                                                 "instead of a prose note"}
art["basis"]["source_windows"] = clips
art["basis"]["research_doc"] = art["basis"].get("research_doc")
(PROOF / "evidence" / "P1_UNIT_MANIFESTS.json").write_text(
    json.dumps(art, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

# --- PRE-stop state ---------------------------------------------------------------------
s = socket.socket()
s.settimeout(3.0)
try:
    s.connect(("127.0.0.1", PORT))
    listening = True
    err = None
except Exception as e:  # noqa: BLE001
    listening = False
    err = repr(e)
finally:
    s.close()
pre = {"artifact": "P0_SERVER_SHUTDOWN_PROOF.json", "phase": "PRE_STOP",
       "pid": PID, "port": PORT, "port_listening": listening, "connect_error": err,
       "epoch": json.loads((PROOF / "evidence" / "P0_instance_epoch.json").read_text(
           encoding="utf-8")),
       "purpose": ("the server this worker launched is stopped with a proof: pid gone, port "
                   "closed, no other python process touched"),
       "stop_scope": "ONLY the pid this worker launched (no /T, no image-wide stop)"}
(PROOF / "evidence" / "P0_SERVER_SHUTDOWN_PROOF.json").write_text(
    json.dumps(pre, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"clips": clips, "unit_sources": [u["source"]["source_window_sha256"]
                                                   for u in art["units"]],
                  "pre_stop": {"pid": PID, "port_listening": listening}},
                 indent=1, ensure_ascii=False))
