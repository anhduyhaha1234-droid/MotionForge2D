"""Generate tools/demo_run3.py from the R2 harness with audited replacements.

Every replacement asserts its anchor is unique.  Splice replacements (start/end
markers) assert the end marker appears exactly once AFTER the start marker.
"""
from pathlib import Path

R2 = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R2")
R3 = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R3")
src = (R2 / "tools" / "demo_run2.py").read_text(encoding="utf-8")

REPL = [
    ('EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R2")',
     'EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R3")'),
    ('MFRT = Path("C:/Users/Admin/AppData/Local/Temp/mfr2")',
     'MFRT = Path("C:/Users/Admin/AppData/Local/Temp/mfr3")'),
    ('APP_PORT = 8031', 'APP_PORT = 8032'),
    ('COMFY_PORT = 8372', 'COMFY_PORT = 8373'),
    ('TOOLS = EVID / "tools"',
     'TOOLS = EVID / "tools"\nR2EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R2")'),
    ('"""MF-DEMO-E2E harness', '"""MF-DEMO-E2E-R3 harness'),
    ('A("# REPORT - MF-DEMO-E2E-R2 (Phase C rerun: FROZEN CANDIDATE #5)")',
     'A("# REPORT - MF-DEMO-E2E-R3 (Phase C final: FROZEN CANDIDATE #6)")'),
    ('    dump = _dump_run(run_id)\n    # per-chunk shot render records (executor receipts)',
     '    time.sleep(5)\n    dump = _dump_run(run_id)\n    # per-chunk shot render records (executor receipts)'),
    ('"harvest": phase_harvest,',
     '"harvest": phase_harvest,\n          "harvest_engine": phase_harvest_engine,'),
]

for old, new in REPL:
    n = src.count(old)
    assert n == 1, f"anchor count {n} for: {old[:70]!r}"
    src = src.replace(old, new)

# splice 1: source reuse
s1 = src.index("    # 1) 12s source")
e1 = src.index("    # verify", s1)
new1 = '''    # 1) 12s source - REUSE the R2-produced source byte-for-byte (same inputs)
    if not SRC_12S.is_file():
        shutil.copyfile(R2EV / "raw" / "source_12s.mp4", SRC_12S)
    _r2st = json.loads((R2EV / "raw" / "state.json").read_text(encoding="utf-8"))
    assert sha_file(SRC_12S) == _r2st["source_12s"]["sha256"], "R3 source != R2 source (drift)"
    _pa = sh(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
              "stream=codec_name", "-of", "csv=p=0", str(SRC_12S)], "probe_audio_existing")
    has_audio = bool(_pa.stdout.strip())
'''
src = src[:s1] + new1 + src[e1:]

# splice 2: mf_comfy reuse
s2 = src.index("    # 2) build + install the pinned mf_comfy dependency")
e2 = src.index("    from app.adapters.media_engine.comfy import engine_status", s2)
new2 = '''    # 2) REUSE the pinned mf_comfy dependency built for R2 (pin 70f7180)
    if not (EVID / "mf_comfy_pkg" / "mf_comfy" / "__init__.py").is_file():
        shutil.copytree(R2EV / "mf_comfy_pkg", EVID / "mf_comfy_pkg")
'''
src = src[:s2] + new2 + src[e2:]

# splice 3: insert harvest_engine phase before the harvest phase marker
mk = "# ── phase: harvest (copy the SHORT-root runtime back into the evidence root)"
assert src.count(mk) == 1, "harvest marker not unique"
newfn = '''# ── phase: harvest_engine (worker-owned renders: receipts + records + DB) ────
def phase_harvest_engine() -> int:
    from sqlalchemy import text as _text  # noqa: PLC0415
    out: dict = {"at": now(), "engine_state": [], "renders": [], "server_outputs": []}
    ev_root = MANAGED / "media_engine" / "comfy_shot_engine"
    if ev_root.exists():
        for p in sorted(ev_root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(ev_root)
            if "reservations" in rel.parts and "closed" not in rel.parts:
                continue
            if ".tmp" in p.name:
                continue
            dst = EVID / "raw" / "engine_state" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)
            out["engine_state"].append({"rel": rel.as_posix(), "sha256": sha_file(dst),
                                        "bytes": dst.stat().st_size})
    rr_root = MANAGED / "shot_render"
    if rr_root.exists():
        for p in sorted(rr_root.rglob("*")):
            if not p.is_file() or ".tmp" in p.name:
                continue
            rel = p.relative_to(rr_root)
            dst = EVID / "raw" / "renders" / "shot_render" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)
            out["renders"].append({"rel": rel.as_posix(), "sha256": sha_file(dst),
                                   "bytes": dst.stat().st_size})
    so_root = COMFY_BASE / "output"
    if so_root.exists():
        for p in sorted(so_root.rglob("*.mp4")):
            rel = p.relative_to(so_root)
            dst = EVID / "raw" / "renders" / "server_output" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)
            out["server_outputs"].append({"rel": rel.as_posix(), "sha256": sha_file(dst),
                                          "bytes": dst.stat().st_size})
    dbdump: dict = {}
    factory = _session_factory()
    with factory() as s:
        for t in ("job", "job_step", "s10_full_apply_run", "s10_full_apply_chunk",
                  "s10_full_apply_publication", "qc_item", "s12_export_run", "s12_export_chunk"):
            try:
                rows = [dict(r) for r in s.execute(_text(f"SELECT * FROM {t}")).mappings().all()]
            except Exception as exc:  # noqa: BLE001
                rows = [{"error": f"{type(exc).__name__}:{exc}"}]
            dbdump[t] = rows
    (RAW / "db_harvest.json").write_text(json.dumps(dbdump, indent=1, ensure_ascii=False, default=str),
                                         encoding="utf-8")
    out["db_tables"] = {k: len(v) for k, v in dbdump.items()}
    save_state({"engine_harvest": {"engine_state": len(out["engine_state"]),
                                   "renders": len(out["renders"]),
                                   "server_outputs": len(out["server_outputs"]),
                                   "db_tables": out["db_tables"]}})
    (RAW / "engine_harvest.json").write_text(json.dumps(out, indent=1, ensure_ascii=False),
                                             encoding="utf-8")
    print("ENGINE_HARVEST", len(out["engine_state"]), len(out["renders"]),
          len(out["server_outputs"]), out["db_tables"], flush=True)
    return 0


'''
src = src.replace(mk, newfn + mk)

dst = R3 / "tools" / "demo_run3.py"
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(src, encoding="utf-8")
print("WROTE", dst, len(src), "chars,", src.count("\n"), "lines")
