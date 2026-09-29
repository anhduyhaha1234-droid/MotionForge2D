"""Final gate for MF-DEMO-E2E-R2 — every line prints PASS/FAIL from live checks."""
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R2")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION")
DB = Path("C:/Users/Admin/AppData/Local/Temp/mfr2/data/motionforge.db")
EXPECT_HEAD = "82c84a890349fd2d2251b753d00c5f03f798063d"
EXPECT_DEMO = "945b51b12340995cfc47c84fc04035131b9725739acd859c4123576c0b9d1e8c"
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


# 1) tree: run was on candidate #5; current HEAD must CONTAIN it as ancestor; tree clean
head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WT, capture_output=True, text=True).stdout.strip()
anc = subprocess.run(["git", "merge-base", "--is-ancestor", EXPECT_HEAD, "HEAD"], cwd=WT).returncode == 0
porc = subprocess.run(["git", "status", "--porcelain"], cwd=WT, capture_output=True, text=True).stdout
check("candidate #5 is ancestor of HEAD", anc, f"HEAD={head}")
check("tree porcelain == 0", porc.strip() == "", repr(porc[:120]))

# 2) evidence files exist
for rel in ("REPORT.md", "FINDINGS.md", "TARGET.md", "raw/commands.jsonl", "raw/state.json",
            "raw/app_launch.json", "raw/comfy_epoch.json", "raw/comfy_shutdown.json",
            "raw/harvest_receipt.json", "raw/run_result.json", "raw/qc_receipt.json",
            "raw/export_receipt.json", "raw/engine_receipt.json", "raw/ffprobe_demo.txt",
            "raw/verify_receipt.json", "raw/preview_contact_sheet.png", "raw/sha256_manifest.txt",
            "raw/sha256_manifest.json", "raw/export/demo_final.mp4"):
    check("exists " + rel, (EVID / rel).is_file() and (EVID / rel).stat().st_size > 0)

# 3) demo video identity
demo = EVID / "raw/export/demo_final.mp4"
check("demo sha256", sha(demo) == EXPECT_DEMO, sha(demo))
check("demo bytes==1061277", demo.stat().st_size == 1061277, str(demo.stat().st_size))
v = json.loads((EVID / "raw/verify_receipt.json").read_text(encoding="utf-8"))
vv = v["video"]
check("video 640x368x360 decode_ok pts_monotonic",
      vv["width"] == 640 and vv["height"] == 368 and vv["frames"] == 360
      and v.get("decode_ok") is True and vv.get("pts_monotonic") is True, json.dumps(vv))
check("contact sheet >0", (EVID / "raw/preview_contact_sheet.png").stat().st_size > 0)

# 4) DB truth: run failed (F4), members persisted (F1), no publication
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
run = con.execute("SELECT id,status FROM s10_full_apply_run ORDER BY created_at DESC LIMIT 1").fetchone()
check("run terminal failed (F4 blocked)", run["status"] == "failed", dict(run))
ch = con.execute("SELECT member_layer_ids_json FROM s10_full_apply_chunk WHERE run_id=? AND chunk_index=0",
                 (run["id"],)).fetchone()
mem = json.loads(ch["member_layer_ids_json"] or "[]")
check("F1 members persisted (chunk0 len==4)", len(mem) == 4, str(mem))
pub = con.execute("SELECT COUNT(*) c FROM s10_full_apply_publication WHERE run_id=?", (run["id"],)).fetchone()
check("no publication (fail-closed)", pub["c"] == 0, str(pub["c"]))
job = con.execute("SELECT error_json FROM job ORDER BY created_at DESC LIMIT 1").fetchone()
check("job error == F4 message", "replacement_assets missing entry for layer" in (job["error_json"] or ""))

# 5) engine evidence: 3 validated + shape proof images+animated
for tag in ("ck_4329192f1", "ck_577f96949", "ck_adb68f792"):
    d = json.loads((EVID / f"raw/engine_state/evidence/shot-demo-{tag}.engine_evidence.json").read_text(encoding="utf-8"))
    sp = d.get("video_shape_proof") or {}
    ok = d.get("status") == "validated" and any(b.startswith("images:") for b in sp.get("proven_animated") or [])
    check(f"engine {tag} validated + images/animated", ok, f"prompt={d.get('prompt_id')}")

# 6) commands.jsonl row count + UTC stamps
rows = (EVID / "raw/commands.jsonl").read_text(encoding="utf-8").strip().splitlines()
check("commands.jsonl rows == 28", len(rows) == 28, str(len(rows)))
check("commands rows carry ts", all(json.loads(r).get("ts") for r in rows if r.strip()))

# 7) shutdown + no leftover servers of this run
sd = json.loads((EVID / "raw/comfy_shutdown.json").read_text(encoding="utf-8"))
check("app pid gone + port closed", sd["app"]["pid_gone"] and sd["app"]["port_closed"], str(sd["app"]))
check("comfy pid gone + port closed + POST_STOP_VERIFIED",
      sd["comfy"]["pid_gone"] and sd["comfy"]["port_closed"] and sd.get("POST_STOP_VERIFIED") is True)

# 8) manifest self-check: recompute demo line from manifest
man = (EVID / "raw/sha256_manifest.txt").read_text(encoding="utf-8")
line = [l for l in man.splitlines() if "  raw/export/demo_final.mp4  " in l]
check("manifest line for demo matches", bool(line) and line[0].startswith(EXPECT_DEMO), line[0][:80] if line else "missing")

print()
print("GATE:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)
