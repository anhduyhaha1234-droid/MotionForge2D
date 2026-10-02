"""Adapt the R3 harness into the R4 harness (deterministic, count-asserted).

Reads MF-DEMO-E2E-R3/tools/demo_run3.py, applies the R4 delta (paths, ports,
seed: artifact_owner + staggered segments + real mask; journey: cast mappings +
scene-graph edges via real HTTP; new audio phase BEFORE qc; qc 2xx gate +
readiness; export without attach; verify 640x360 + audio), writes
MF-DEMO-E2E-R4/tools/demo_run4.py.  Every replacement is count-asserted.
"""
from __future__ import annotations

import py_compile
from pathlib import Path

R4 = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R4")
R3 = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R3")
src = R3 / "tools" / "demo_run3.py"
dst = R4 / "tools" / "demo_run4.py"
text = src.read_text(encoding="utf-8")

REPL = []


def add(old: str, new: str, n: int = 1) -> None:
    REPL.append((old, new, n))


# ── paths / ports ────────────────────────────────────────────────────────────
add('tasks/MF-DEMO-E2E-R3")', 'tasks/MF-DEMO-E2E-R4")')
add('MFRT = Path("C:/Users/Admin/AppData/Local/Temp/mfr3")',
    'MFRT = Path("C:/Users/Admin/AppData/Local/Temp/mfr4")')
add('APP_PORT = 8032', 'APP_PORT = 8033')
add('COMFY_PORT = 8373', 'COMFY_PORT = 8374')
add('R2EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/'
    '20260927T163824Z/tasks/MF-DEMO-E2E-R2")',
    'R3EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/'
    '20260927T163824Z/tasks/MF-DEMO-E2E-R3")\nR2EV = R3EV  # R4 reuses the R3-verified source + mf_comfy pin')
add('Phases (argv[1]): prep | app | journey | monitor | qc | export | verify | report | shutdown',
    'Phases (argv[1]): prep | app | journey | monitor | audio | qc | export | verify | report | shutdown')

# ── prep: source identity now comes from R3 ──────────────────────────────────
add('    _r2st = json.loads((R2EV / "raw" / "state.json").read_text(encoding="utf-8"))\n'
    '    assert sha_file(SRC_12S) == _r2st["source_12s"]["sha256"], "R3 source != R2 source (drift)"',
    '    _r3st = json.loads((R2EV / "raw" / "state.json").read_text(encoding="utf-8"))\n'
    '    assert sha_file(SRC_12S) == _r3st["source_12s"]["sha256"], "R4 source != R3 source (drift)"')

# ── seed delta 1: artifact_owner(source) so ATTACH_ORIGINAL_AUDIO resolves ───
add('        cols = {str(r[1]) for r in s.execute(text("PRAGMA table_info(video_item)"))}',
    '        s.execute(text("INSERT INTO artifact_owner(artifact_id,owner_type,owner_id,purpose)"\n'
    '                       " VALUES (:a,\'video_item\',:v,\'source\')"), {"a": src_art, "v": vid})\n'
    '        cols = {str(r[1]) for r in s.execute(text("PRAGMA table_info(video_item)"))}')

# ── seed delta 2: real non-empty annotation mask (QC band) ───────────────────
add('        mimg = np.zeros((40, 40, 4), dtype=np.uint8)\n'
    '        mimg[:, :, 3] = 255\n'
    '        cv2.imwrite(str(mask_abs), mimg)',
    '        mimg = np.zeros((360, 640), dtype=np.uint8)\n'
    '        mimg[36:144, 64:256] = 255  # non-empty annotation mask (QC band)\n'
    '        cv2.imwrite(str(mask_abs), mimg)')

# ── seed delta 3: record character ids (cast mappings need them) ─────────────
add('            char = f"ch-{_uuid.uuid4().hex[:6]}"',
    '            char = f"ch-{_uuid.uuid4().hex[:6]}"\n'
    '            out.setdefault("characters", {})[role] = char')

# ── seed delta 4: exactly ONE segment starts at each scene boundary ──────────
add('            sf, ef, sms, ems = scenes[scene_i]\n',
    '            sf, ef, sms, ems = scenes[scene_i]\n'
    '            off = {"BOOK-P2": 1, "BOOK-P3": 2, "BOOK-P4": 3}.get(role, 0)\n'
    '            sf += off\n'
    '            sms = int(sf * 1000 / 30)\n')

# ── journey delta: cast mappings + scene-graph edges (real HTTP routes) ──────
add('    save_state({"pinned": pinned})\n    print("pinned", len(pinned), flush=True)',
    '''    save_state({"pinned": pinned})
    print("pinned", len(pinned), flush=True)

    # ── 5b. project cast mappings (HTTP, real route) ─────────────────────
    if not st.get("cast_mappings"):
        cast_out = {}
        for role in seed["reskin_configs"]:
            sc, body = http("POST", "/api/v2/project-cast",
                            {"project_id": pid, "object_role_id": seed["roles"][role],
                             "character_id": seed["characters"][role],
                             "pack_version_id": seed["pack_versions"][role],
                             "idempotency_key": f"demo-cast-{role}-{pid}"})
            assert sc in (200, 201), f"cast mapping {role} failed: {sc} {body}"
            cast_out[role] = {"status": sc, "id": (body or {}).get("id")}
        save_state({"cast_mappings": cast_out})
        print("cast mappings", len(cast_out), flush=True)

    # ── 5c. scene-graph annotation edges (HTTP, real routes) ─────────────
    if not st.get("graph_edges"):
        seg = seed["segments"]  # roles order: BOOK-P1..4, TURN-CERT, OCC-PEN
        edges = [
            ("occlusions", {"project_id": pid, "video_item_id": vid,
                            "occluder_segment_id": seg[1], "occludee_segment_id": seg[0],
                            "start_frame": 10, "end_frame": 110,
                            "start_time_ms": 333, "end_time_ms": 3666,
                            "algorithm": "demo-annotation", "algorithm_version": "1",
                            "confidence": 0.9, "confidence_source": "user",
                            "reasons": ["demo seed interaction facts"],
                            "idempotency_key": f"demo-occ-{pid}"}),
            ("contacts", {"project_id": pid, "video_item_id": vid,
                          "source_segment_id": seg[0], "target_segment_id": seg[1],
                          "contact_kind": "touch", "start_frame": 10, "end_frame": 110,
                          "start_time_ms": 333, "end_time_ms": 3666,
                          "algorithm": "demo-annotation", "algorithm_version": "1",
                          "confidence": 0.9, "confidence_source": "user",
                          "reasons": ["demo seed interaction facts"],
                          "idempotency_key": f"demo-con-{pid}"}),
        ]
        edge_out = {}
        for path, payload in edges:
            sc, body = http("POST", f"/api/v2/structural-evidence/{path}", payload)
            assert sc in (200, 201), f"edge {path} failed: {sc} {body}"
            edge_out[path] = {"status": sc, "id": (body or {}).get("id")}
        save_state({"graph_edges": edge_out})
        print("graph edges", edge_out, flush=True)''')

# ── qc phase: 2xx gate + proper state/readiness reads ────────────────────────
add('    qc = {"submit_status": sc, "submit_body": body, "at": now()}\n    if sc != 202:',
    '    qc = {"submit_status": sc, "submit_body": body, "at": now()}\n    if not (200 <= sc < 300):')
add('        sc2, listing = http("GET", f"/api/v2/projects/{pid}/qc-check-runs")',
    '        sc2, listing = http("GET", f"/api/v2/projects/{pid}/qc-check-runs/{vid}")')
add('''            if isinstance(listing, dict):
                rows = listing.get("runs") or listing.get("check_runs") or listing.get("items") or []
                for r in rows:
                    if str(r.get("video_item_id")) == str(vid):
                        state = str(r.get("state") or r.get("status") or "")
            qc["state"] = state''',
    '''            if isinstance(listing, dict):
                state = str(listing.get("run_state") or listing.get("job_state") or "")
                qc["state_detail"] = {k: listing.get(k) for k in
                                      ("run_state", "job_state", "summary", "latest_error",
                                       "zero_item_completion", "evidence_matches")}
            qc["state"] = state''')
add('    qc["listing"] = runs',
    '''    qc["listing"] = runs
    if job_id:
        qc["job_final_state"] = _poll_job(str(job_id), deadline_s=1800)
        sc2b, state_body = http("GET", f"/api/v2/projects/{pid}/qc-check-runs/{vid}")
        if sc2b == 200:
            qc["state_final"] = state_body
    sc_r, readiness = http("GET", f"/api/v2/projects/{pid}/qc-check-runs/{vid}/readiness")
    qc["readiness"] = {"status": sc_r, "body": readiness}''')

# ── new phase: audio attach BEFORE qc (full band needs the envelope) ─────────
add('def phase_export() -> int:',
    '''def phase_audio() -> int:
    """Original-audio attach (durable job through the public action route).

    Runs BEFORE the QC submit: the full-band compose reads the latest
    COMPLETED ATTACH_ORIGINAL_AUDIO attempt envelope for the audio detectors.
    """
    st = load_state()
    pid, vid = st["project_id"], st["video_id"]
    sc, body = http("POST", f"/api/v2/projects/{pid}/original-audio-attach",
                    {"video_item_id": vid})
    out: dict = {"status": sc, "body": body, "at": now()}
    job_id = None
    if isinstance(body, dict):
        job_id = body.get("job_id") or body.get("id") or (body.get("job") or {}).get("id")
        out["recheck"] = {"job_id": body.get("recheck_job_id"),
                          "state": body.get("recheck_state")}
    out["job_id"] = job_id
    if job_id:
        out["final_state"] = _poll_job(str(job_id), deadline_s=1200)
    save_state({"audio": out})
    (RAW / "audio_receipt.json").write_text(json.dumps(out, indent=1, ensure_ascii=False),
                                            encoding="utf-8")
    print("AUDIO", sc, out.get("final_state"), flush=True)
    return 0 if (200 <= sc < 300) else 1


def phase_export() -> int:''')

# ── export phase: drop the attach block (phase_audio owns it) ────────────────
add('''    # 1. original-audio attach (durable job through the public action route)
    sc, body = http("POST", f"/api/v2/projects/{pid}/original-audio-attach", {"video_item_id": vid})
    out["audio_attach"] = {"status": sc, "body": body}
    job_id = None
    if isinstance(body, dict):
        job_id = body.get("job_id") or body.get("id") or (body.get("job") or {}).get("id")
    if job_id:
        out["audio_attach"]["job_id"] = job_id
        out["audio_attach"]["final_state"] = _poll_job(str(job_id))
    print("audio attach:", sc, out["audio_attach"].get("final_state"), flush=True)''',
    '''    # 1. audio attach ran in phase_audio BEFORE qc (the full-band compose
    #    reads the completed ATTACH_ORIGINAL_AUDIO envelope).
    out["audio_attach"] = st.get("audio", {})''')

# ── verify: conformed geometry + audio required ──────────────────────────────
add('''    ok = (verify["video"]["width"] == 640 and verify["video"]["height"] == 368
          and verify["video"]["frames"] == 360 and verify["decode_ok"] and monotonic)''',
    '''    ok = (verify["video"]["width"] == 640 and verify["video"]["height"] == 360
          and verify["video"]["frames"] == 360 and verify["decode_ok"] and monotonic
          and verify["audio"] is not None)''')

# ── main map ─────────────────────────────────────────────────────────────────
add('    fn = {"prep": phase_prep, "app": phase_app, "journey": phase_journey,\n'
    '          "monitor": phase_monitor, "qc": phase_qc, "export": phase_export,',
    '    fn = {"prep": phase_prep, "app": phase_app, "journey": phase_journey,\n'
    '          "monitor": phase_monitor, "audio": phase_audio, "qc": phase_qc,\n'
    '          "export": phase_export,')

for old, new, n in REPL:
    found = text.count(old)
    assert found == n, f"replacement expected {n} got {found}: {old[:90]!r}"
    text = text.replace(old, new)

dst.write_text(text, encoding="utf-8")
py_compile.compile(str(dst), doraise=True)
print("WROTE", dst, len(text), "chars; py_compile OK; replacements:", len(REPL))
