"""FINAL GATE MF-DEMO-E2E-R3: regenerate sha256 manifest + live PASS/FAIL checks.

Run 1: writes raw/sha256_manifest.txt/.json, prints gate lines, writes
raw/final_gate_r3.txt. Re-run: identical verdict (manifest stable in shape).
"""
import hashlib
import json
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R3")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION")
DB = Path("C:/Users/Admin/AppData/Local/Temp/mfr3/data/motionforge.db")
EXPECT_HEAD = "db238390dd18751080c1aee1f2a718fa9ca04f5c"
EXPECT_DEMO = "6de96ac723db87195f23f88397f5450dedaa52ef7aee4a53bd8817be013961f4"
EXPECT_BYTES = 3766511
fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (" | " + str(detail) if detail else ""))
    if not ok:
        fails.append(name)


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


# 0) regenerate the sha256 manifest over the whole evidence root
manifest = EVID / "raw" / "sha256_manifest.txt"
json_twin = EVID / "raw" / "sha256_manifest.json"
rows, entries = [], []
for p in sorted(EVID.rglob("*")):
    if not p.is_file() or p in (manifest, json_twin):
        continue
    rel = p.relative_to(EVID).as_posix()
    rows.append(f"{sha(p)}  {rel}  {p.stat().st_size}")
    entries.append({"rel": rel, "sha256": rows[-1].split("  ")[0], "bytes": p.stat().st_size})
manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")
json_twin.write_text(json.dumps({"count": len(entries), "files": entries}, indent=1), encoding="utf-8")
print("MANIFEST", len(entries), "files; bytes", sum(e["bytes"] for e in entries))

# 1) tree
head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WT, capture_output=True, text=True).stdout.strip()
porc = subprocess.run(["git", "status", "--porcelain"], cwd=WT, capture_output=True, text=True).stdout
check("HEAD == candidate #6 (db23839)", head == EXPECT_HEAD, head)
check("tree porcelain == 0", porc.strip() == "", repr(porc[:120]))

# 2) evidence files exist
for rel in ("REPORT.md", "FINDINGS.md", "TARGET.md", "raw/commands.jsonl", "raw/state.json",
            "raw/app_launch.json", "raw/comfy_epoch.json", "raw/comfy_shutdown.json",
            "raw/harvest_receipt.json", "raw/engine_harvest.json", "raw/db_harvest.json",
            "raw/extra_http.json", "raw/run_result.json", "raw/qc_receipt.json",
            "raw/export_receipt.json", "raw/ffprobe_demo.txt", "raw/verify_receipt.json",
            "raw/preview_contact_sheet.png", "raw/sha256_manifest.txt", "raw/sha256_manifest.json",
            "raw/export/demo_final.mp4", "raw/app_receipts/stitch_shot_chunks.mp4.evidence.json"):
    check("exists " + rel, (EVID / rel).is_file() and (EVID / rel).stat().st_size > 0)

# 3) demo identity (app-path publication)
demo = EVID / "raw/export/demo_final.mp4"
check("demo sha256 == publication", sha(demo) == EXPECT_DEMO, sha(demo))
check(f"demo bytes == {EXPECT_BYTES}", demo.stat().st_size == EXPECT_BYTES, str(demo.stat().st_size))
v = json.loads((EVID / "raw/verify_receipt.json").read_text(encoding="utf-8"))
vv = v["video"]
check("video 640x368x360 decode_ok pts_monotonic",
      vv["width"] == 640 and vv["height"] == 368 and vv["frames"] == 360
      and v.get("decode_ok") is True and vv.get("pts_monotonic") is True, json.dumps(vv))
check("publication declared sha == file sha",
      (v.get("publication") or {}).get("declared_sha") == EXPECT_DEMO, str((v.get("publication") or {}).get("declared_sha")))
check("contact sheet >0", (EVID / "raw/preview_contact_sheet.png").stat().st_size > 0)

# 4) DB truth: completed run, 3 chunks, publication
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
run = con.execute("SELECT id,status FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1").fetchone()
check("run terminal completed", run["status"] == "completed", dict(run))
ch = list(con.execute("SELECT chunk_index,state,verified,member_layer_ids_json FROM s10_full_apply_chunk"
                      " WHERE run_id=? ORDER BY chunk_index", (run["id"],)))
check("3 chunks completed+verified", len(ch) == 3 and all(c["state"] == "completed" and c["verified"] == 1 for c in ch),
      str([(c["chunk_index"], c["state"], c["verified"]) for c in ch]))
mem0 = json.loads(ch[0]["member_layer_ids_json"] or "[]")
check("chunk0 members == 4 (F1)", len(mem0) == 4, str(len(mem0)))
pub = con.execute("SELECT COUNT(*) c FROM s10_full_apply_publication WHERE run_id=?", (run["id"],)).fetchone()
check("publication count == 1", pub["c"] == 1, str(pub["c"]))
job = con.execute("SELECT job_type,state FROM job ORDER BY created_at DESC LIMIT 1").fetchone()
check("job s10_full_apply completed", job["job_type"] == "s10_full_apply" and job["state"] == "completed", dict(job))

# 5) engine receipts: 3 validated + images/animated proof + released reservations
evd = sorted((EVID / "raw" / "engine_state" / "evidence").glob("*.engine_evidence.json"))
check("3 engine receipts", len(evd) == 3, str(len(evd)))
ok_ev = True
for p in evd:
    d = json.loads(p.read_text(encoding="utf-8"))
    sp = d.get("video_shape_proof") or {}
    ok = (d.get("status") == "validated" and (d.get("info") or {}).get("submit_count") == 1
          and any(str(b).startswith("images:") for b in sp.get("proven_animated") or []))
    ok_ev = ok_ev and ok
check("all engine receipts validated + submit_count 1 + images:animated", ok_ev)
rel = sorted((EVID / "raw" / "engine_state" / "reservations" / "closed").glob("*.released.json"))
check("3 reservations released", len(rel) == 3, str(len(rel)))

# 6) typed refusals (F5 chain) present with exact codes
qc = json.loads((EVID / "raw" / "qc_receipt.json").read_text(encoding="utf-8"))
qc_msg = json.dumps(qc.get("submit_body") or {}, ensure_ascii=False)
check("QC submit 422 typed geometry", qc.get("submit_status") == 422 and "different geometry" in qc_msg
      and "QC_EVIDENCE_MALFORMED" in qc_msg, qc_msg[:160])
ex = json.loads((EVID / "raw" / "export_receipt.json").read_text(encoding="utf-8"))
ex_msg = json.dumps((ex.get("submit") or {}).get("body") or {}, ensure_ascii=False)
check("export submit 409 readiness typed", (ex.get("submit") or {}).get("status") == 409
      and "export requires ready" in ex_msg, ex_msg[:160])
xh = json.loads((EVID / "raw" / "extra_http.json").read_text(encoding="utf-8"))
check("QC readiness not_run", xh["qc_readiness"]["body"]["status"] == "not_run",
      str(xh["qc_readiness"]["body"]["status"]))

# 7) commands.jsonl rows + ts
rows = (EVID / "raw" / "commands.jsonl").read_text(encoding="utf-8").strip().splitlines()
check("commands.jsonl rows == 68", len(rows) == 68, str(len(rows)))
check("commands rows carry ts", all(json.loads(r).get("ts") for r in rows if r.strip()))

# 8) shutdown + ports closed live
sd = json.loads((EVID / "raw" / "comfy_shutdown.json").read_text(encoding="utf-8"))
check("app pid gone + port closed", sd["app"]["pid_gone"] and sd["app"]["port_closed"], str(sd["app"]))
check("comfy pid gone + port closed + POST_STOP_VERIFIED",
      sd["comfy"]["pid_gone"] and sd["comfy"]["port_closed"] and sd.get("POST_STOP_VERIFIED") is True)
for port in (8032, 8373):
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect(("127.0.0.1", port))
        live = True
    except Exception:
        live = False
    finally:
        s.close()
    check(f"port {port} closed (live)", not live)

# 9) manifest self-check: demo line
man = (EVID / "raw/sha256_manifest.txt").read_text(encoding="utf-8")
line = [ln for ln in man.splitlines() if "  raw/export/demo_final.mp4  " in ln]
check("manifest line for demo matches", bool(line) and line[0].startswith(EXPECT_DEMO),
      line[0][:80] if line else "missing")

verdict = "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}"
out = "\n".join([f"MANIFEST {len(entries)} files", f"GATE: {verdict}"])
(EVID / "raw" / "final_gate_r3.txt").write_text(out + "\n", encoding="utf-8")
print()
print("GATE:", verdict)
sys.exit(1 if fails else 0)
