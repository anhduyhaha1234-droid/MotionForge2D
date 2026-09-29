"""Adapt the R1 harness (demo_run.py) into the R2 harness (demo_run2.py).

Deterministic, replace-once edits with found/not-found assertions so a silent
no-op is impossible.  Reads/writes UTF-8; refuses if any anchor is missing.
"""
import sys
from pathlib import Path

P = Path(sys.argv[1])
src = P.read_text(encoding="utf-8")
orig = src

EDITS = [
    # 1) evidence root
    ('EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E")',
     'EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R2")'),
    # 2) short MOTIONFORGE_ROOT (F3: reservation filename MAX_PATH)
    ('APP_ROOT = EVID / "app-runtime"',
     'MFRT = Path("C:/Users/Admin/AppData/Local/Temp/mfr2")\n'
     'APP_ROOT = MFRT  # F3: keep MOTIONFORGE_ROOT SHORT; runtime harvested back to EVID'),
    # 3) fresh ports
    ('APP_PORT = 8028', 'APP_PORT = 8031'),
    ('COMFY_PORT = 8371', 'COMFY_PORT = 8372'),
    # 4) monitor: record persisted chunk members (F1 proof)
    ('    result = {"transitions": transitions, "final_status": final_status, "db": dump,\n'
     '              "shot_records": records, "gpu_samples": gpu_samples[-8:],',
     '    chunk_members = {str(c.get("id")): c.get("member_layer_ids_json") for c in dump["chunks"]}\n'
     '    result = {"transitions": transitions, "final_status": final_status, "db": dump,\n'
     '              "chunk_members": chunk_members, "shot_records": records, "gpu_samples": gpu_samples[-8:],'),
    # 5) shutdown calls the harvest
    ('    por = sh(["git", "status", "--porcelain"], "porcelain", cwd=WT)',
     '    phase_harvest()\n'
     '    por = sh(["git", "status", "--porcelain"], "porcelain", cwd=WT)'),
    # 6) dispatch entry
    ('"verify": phase_verify, "report": phase_report, "shutdown": phase_shutdown,',
     '"verify": phase_verify, "report": phase_report, "shutdown": phase_shutdown,\n'
     '          "harvest": phase_harvest,'),
    # 7) report: title + candidate disclosure + evidence-root output
    ('    A("# REPORT — MF-DEMO-E2E (Phase C: DEMO THẬT trên FROZEN CANDIDATE #4)")',
     '    A("# REPORT - MF-DEMO-E2E-R2 (Phase C rerun: FROZEN CANDIDATE #5)")'),
    ('    A("- DISCLOSURE: packet ghi HEAD `951543664e3bd9a76b0e4b3a4c37d0b1f37959ab`; `git rev-parse --verify` → fatal (không tồn tại); HEAD thật cùng prefix 9 = `951543664` + `ed10e0d…`.")',
     '    A("- Candidate HEAD do tai cho: `" + str(st.get("app", {}).get("candidate_head", "?")) + "`")'),
    ('    (RAW / "REPORT.md").write_text("\\n".join(lines) + "\\n", encoding="utf-8")',
     '    (EVID / "REPORT.md").write_text("\\n".join(lines) + "\\n", encoding="utf-8")'),
]

for old, new in EDITS:
    n = src.count(old)
    assert n == 1, f"anchor found {n} times (want 1): {old[:80]!r}"
    src = src.replace(old, new)

# 8) insert the harvest phase before the __main__ dispatch
HARVEST = '''
# ── phase: harvest (copy the SHORT-root runtime back into the evidence root) ─
def phase_harvest() -> int:
    out = {"at": now(), "files": [], "skipped_live": []}
    dst_root = EVID / "raw" / "runtime_harvest"
    for sub in ("media_engine/comfy_shot_engine", "shot_render", "shot_render_cache",
                "s10_full_apply"):
        src_root = MANAGED / sub
        if not src_root.exists():
            continue
        for p in sorted(src_root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(MANAGED)
            if "reservations" in rel.parts or ".tmp" in p.name:
                continue
            dst = dst_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(p, dst)
            except PermissionError:
                out["skipped_live"].append(rel.as_posix())
                continue
            out["files"].append({"rel": rel.as_posix(), "sha256": sha_file(dst),
                                 "bytes": dst.stat().st_size})
    if DB.is_file():
        dst = dst_root / "data" / DB.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DB, dst)
        out["files"].append({"rel": "data/" + DB.name, "sha256": sha_file(dst),
                             "bytes": dst.stat().st_size})
    (RAW / "harvest_receipt.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    save_state({"harvest_summary": {"files": len(out["files"]), "skipped_live": out["skipped_live"]}})
    print("HARVEST", len(out["files"]), "files; skipped_live", len(out["skipped_live"]), flush=True)
    return 0


if __name__ == "__main__":'''
anchor = '\nif __name__ == "__main__":'
assert src.count(anchor) == 1
src = src.replace(anchor, HARVEST)

P.write_text(src, encoding="utf-8")
print("OK edits applied:", len(EDITS), "replacements +1 insert; bytes", len(orig), "->", len(src))
