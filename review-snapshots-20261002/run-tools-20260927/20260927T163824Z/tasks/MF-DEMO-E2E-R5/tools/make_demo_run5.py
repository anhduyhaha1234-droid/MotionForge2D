"""Adapt the R4 harness into the R5 harness (deterministic, count-asserted).

Reads MF-DEMO-E2E-R4/tools/demo_run4.py and applies the R5 deltas:
- paths/ports: R5 evidence root, Temp/mfr5, ports 8035/8375;
- prep reuses the R4-verified source + mf_comfy pin;
- seed: per-role masks (6 distinct boxes, occlusion pair overlaps with
  exclusive areas each) + rendered-side mask (subset of BOOK-P1 geometry)
  + artifact_owner(video_item, purpose='mask');
- qc phase: harvest the completed job's per-detector matrix + qc_item rows.

Writes MF-DEMO-E2E-R5/tools/demo_run5.py.  Every replacement count-asserted.
"""
from __future__ import annotations

import py_compile
from pathlib import Path

RUNS = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z")
R5 = RUNS / "tasks" / "MF-DEMO-E2E-R5"
R4 = RUNS / "tasks" / "MF-DEMO-E2E-R4"
src = R4 / "tools" / "demo_run4.py"
dst = R5 / "tools" / "demo_run5.py"
text = src.read_text(encoding="utf-8")

REPL = []


def add(old: str, new: str, n: int = 1) -> None:
    REPL.append((old, new, n))


# ── header / paths / ports ───────────────────────────────────────────────────
add('"""MF-DEMO-E2E-R3 harness', '"""MF-DEMO-E2E-R5 harness')
add('tasks/MF-DEMO-E2E-R4")', 'tasks/MF-DEMO-E2E-R5")')
add('MFRT = Path("C:/Users/Admin/AppData/Local/Temp/mfr4")',
    'MFRT = Path("C:/Users/Admin/AppData/Local/Temp/mfr5")')
add('APP_PORT = 8033', 'APP_PORT = 8035')
add('COMFY_PORT = 8374', 'COMFY_PORT = 8375')
add('R3EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/'
    '20260927T163824Z/tasks/MF-DEMO-E2E-R3")\n'
    'R2EV = R3EV  # R4 reuses the R3-verified source + mf_comfy pin',
    'R4EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/'
    '20260927T163824Z/tasks/MF-DEMO-E2E-R4")\n'
    'R2EV = R4EV  # R5 reuses the R4-verified source + mf_comfy pin')

# ── prep: source identity now comes from R4 ──────────────────────────────────
add('    _r3st = json.loads((R2EV / "raw" / "state.json").read_text(encoding="utf-8"))\n'
    '    assert sha_file(SRC_12S) == _r3st["source_12s"]["sha256"], "R4 source != R3 source (drift)"',
    '    _r4st = json.loads((R2EV / "raw" / "state.json").read_text(encoding="utf-8"))\n'
    '    assert sha_file(SRC_12S) == _r4st["source_12s"]["sha256"], "R5 source != R4 source (drift)"')

# ── seed delta: per-role masks + rendered-side mask (F-R4-3/F-R4-4) ───────────
add('''        mask_art = f"art-mask-{_uuid.uuid4().hex[:6]}"
        mask_rel = f"s10_full_apply/_authority/{vid}/mask.png"
        mask_abs = MANAGED / mask_rel
        mimg = np.zeros((360, 640), dtype=np.uint8)
        mimg[36:144, 64:256] = 255  # non-empty annotation mask (QC band)
        cv2.imwrite(str(mask_abs), mimg)
        s.execute(text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision)"
                       " VALUES (:id,:w,'image',:rel,'ready',:sha,:sz,1)"),
                  {"id": mask_art, "w": WS, "rel": mask_rel, "sha": sha_file(mask_abs), "sz": mask_abs.stat().st_size})''',
    '''        # per-role masks (R5, F-R4-4): DIFFERENT box per role; BOOK-P2 (occluder)
        # overlaps BOOK-P1 (occludee) with a non-empty exclusive area on BOTH sides.
        MASK_BOXES = {"BOOK-P1": (64, 36, 256, 144), "BOOK-P2": (192, 108, 384, 216),
                      "BOOK-P3": (384, 36, 576, 144), "BOOK-P4": (64, 216, 256, 324),
                      "TURN-CERT": (480, 36, 640, 144), "OCC-PEN": (320, 144, 512, 252)}
        mask_art_by_role = {}
        for _rname, _box in MASK_BOXES.items():
            _slug = _rname.replace("-", "_")
            _mid = f"art-mask-{_slug.lower()}-{_uuid.uuid4().hex[:4]}"
            _mrel = f"s10_full_apply/_authority/{vid}/masks/mask_{_slug}.png"
            _mabs = MANAGED / _mrel
            _mabs.parent.mkdir(parents=True, exist_ok=True)
            _mimg = np.zeros((360, 640), dtype=np.uint8)
            _bx0, _by0, _bx1, _by1 = _box
            _mimg[_by0:_by1, _bx0:_bx1] = 255
            cv2.imwrite(str(_mabs), _mimg)
            s.execute(text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision)"
                           " VALUES (:id,:w,'image',:rel,'ready',:sha,:sz,1)"),
                      {"id": _mid, "w": WS, "rel": _mrel, "sha": sha_file(_mabs),
                       "sz": _mabs.stat().st_size})
            mask_art_by_role[_rname] = _mid
        # rendered-side mask artifact (R5, F-R4-3): DISTINCT sha, same canvas,
        # subset region of BOOK-P1 so the rendered|expected comparison is
        # measurable; carries artifact_owner(video_item, purpose='mask') — the
        # exact signature rendered_minus_expected_masks() reads.
        rmask_art = f"art-rmask-{_uuid.uuid4().hex[:4]}"
        rmask_rel = f"s10_full_apply/_authority/{vid}/masks/rendered_mask.png"
        rmask_abs = MANAGED / rmask_rel
        rmask_abs.parent.mkdir(parents=True, exist_ok=True)
        rmimg = np.zeros((360, 640), dtype=np.uint8)
        rmimg[40:140, 68:252] = 255  # rendered-side mask: subset geometry of BOOK-P1
        cv2.imwrite(str(rmask_abs), rmimg)
        s.execute(text("INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,size_bytes,revision)"
                       " VALUES (:id,:w,'image',:rel,'ready',:sha,:sz,1)"),
                  {"id": rmask_art, "w": WS, "rel": rmask_rel, "sha": sha_file(rmask_abs),
                   "sz": rmask_abs.stat().st_size})
        s.execute(text("INSERT INTO artifact_owner(artifact_id,owner_type,owner_id,purpose)"
                       " VALUES (:a,'video_item',:v,'mask')"), {"a": rmask_art, "v": vid})''')

add('                mask_artifact_id=mask_art,',
    '                mask_artifact_id=mask_art_by_role[role],')

add('''    out["source_artifact_id"] = src_art
    out["source_rel"] = src_rel
    out["source_sha"] = src_sha
    return out''',
    '''    out["source_artifact_id"] = src_art
    out["source_rel"] = src_rel
    out["source_sha"] = src_sha
    out["mask_artifacts"] = dict(mask_art_by_role)
    out["rendered_mask_artifact"] = rmask_art
    out["mask_boxes"] = {k: list(v) for k, v in MASK_BOXES.items()}
    return out''')

# ── qc delta: harvest the detector matrix + items ────────────────────────────
add('''    sc_r, readiness = http("GET", f"/api/v2/projects/{pid}/qc-check-runs/{vid}/readiness")
    qc["readiness"] = {"status": sc_r, "body": readiness}''',
    '''    sc_r, readiness = http("GET", f"/api/v2/projects/{pid}/qc-check-runs/{vid}/readiness")
    qc["readiness"] = {"status": sc_r, "body": readiness}

    # ── R5: detector matrix (job attempt payload) + qc_item rows ─────────
    from sqlalchemy import text as _t  # noqa: PLC0415
    WS = _ws_id()
    _factory = _session_factory()
    with _factory() as s:
        _att = None
        if job_id:
            _att = s.execute(_t("SELECT result_json FROM job_attempt WHERE job_id=:j"
                                " ORDER BY attempt DESC LIMIT 1"), {"j": str(job_id)}).scalar()
        _items = [dict(r) for r in s.execute(_t(
            "SELECT id,reason_code,severity,status,layer_ref_id FROM qc_item"
            " WHERE workspace_id=:w"), {"w": WS}).mappings().all()]
    qc["items_rows"] = _items
    if _att:
        try:
            _doc = json.loads(_att)
            qc["job_result"] = {"completed": _doc.get("completed"), "scope": _doc.get("scope"),
                                "summary": _doc.get("summary"),
                                "zero_item_completion": _doc.get("zero_item_completion")}
        except Exception as exc:  # noqa: BLE001
            qc["job_result"] = {"error": f"{type(exc).__name__}:{exc}"}
    (RAW / "qc_items.json").write_text(json.dumps({"items": _items}, indent=1, ensure_ascii=False),
                                       encoding="utf-8")
    if qc.get("job_result"):
        (RAW / "qc_job_payload.json").write_text(json.dumps(qc["job_result"], indent=1,
                                                            ensure_ascii=False), encoding="utf-8")''')

for old, new, n in REPL:
    found = text.count(old)
    assert found == n, f"replacement expected {n} got {found}: {old[:90]!r}"
    text = text.replace(old, new)

dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(text, encoding="utf-8")
py_compile.compile(str(dst), doraise=True)
print("WROTE", dst, len(text), "chars; py_compile OK; replacements:", len(REPL))
