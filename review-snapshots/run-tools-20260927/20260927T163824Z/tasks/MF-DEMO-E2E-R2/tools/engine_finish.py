"""Finish the R2 engine phase after the harness harvest crashed on MAX_PATH.

Does only: copy the 3 accepted shot outputs + engine evidence + released
reservation receipts into the evidence root (long-path safe), assemble the 12s
demo (concat copy + source audio remux), write raw/engine_receipt.json.
No GPU, no re-render, no product code touched.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R2")
MFRT = Path("C:/Users/Admin/AppData/Local/Temp/mfr2")
MANAGED = MFRT / "artifacts"
RAW = EVID / "raw"
EXPORT = RAW / "export"


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_copy(src: Path, dst: Path, note: str = "") -> dict:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return {"src": str(src), "dst": str(dst.relative_to(EVID)).replace("\\", "/"),
            "sha256": sha_file(dst), "bytes": dst.stat().st_size, "note": note}


def main() -> int:
    st = json.loads((RAW / "state.json").read_text(encoding="utf-8"))
    shots = list((st.get("engine") or {}).get("shots") or [])
    assert len(shots) == 3, f"expected 3 engine shots in state, got {len(shots)}"

    out: dict = {"shots": shots, "harvest": {"outputs": [], "evidence": [],
                                             "reservations_closed": [], "windows": []},
                 "assembly": {}}

    # 1) the engine-accepted outputs
    for s in shots:
        src = MANAGED / str(s["output_relative_path"])
        assert src.is_file(), f"engine output missing: {src}"
        assert sha_file(src) == s["output_sha256"], f"output sha drift {src}"
        name = Path(str(s["output_relative_path"])).name
        rec = safe_copy(src, RAW / "renders" / "outputs" / name)
        rec["shot_id"] = s["shot_id"]
        out["harvest"]["outputs"].append(rec)
    # sibling _00002_ files from the same stage dir (published alongside; copied for completeness)
    stage_dir = MANAGED / "media_engine/comfy_shot_engine/stage/s10_full_apply/demo"
    sib = []
    for p in sorted(stage_dir.glob("*.mp4")):
        if not p.name.endswith("_00001_.mp4"):
            r = safe_copy(p, RAW / "renders" / "outputs" / p.name, "sibling-take")
            sib.append(r)
    out["harvest"]["sibling_takes"] = sib

    # 2) engine evidence + epoch + gpu lock state
    ev_dir = MANAGED / "media_engine/comfy_shot_engine/evidence"
    for p in sorted(ev_dir.glob("*.json")):
        out["harvest"]["evidence"].append(safe_copy(p, RAW / "engine_state" / "evidence" / p.name))
    out["harvest"]["evidence"].append(safe_copy(
        MANAGED / "media_engine/comfy_shot_engine/instance_epoch.json",
        RAW / "engine_state" / "instance_epoch.json"))

    # 3) released reservations (long names -> shortened dst, original recorded)
    rc_dir = MANAGED / "media_engine/comfy_shot_engine/reservations/closed"
    if rc_dir.is_dir():
        for p in sorted(rc_dir.glob("*.json")):
            short = p.name[:16] + "__" + p.name.split("__", 1)[-1].replace(".released.json", "") + ".released.json"
            rec = safe_copy(p, RAW / "engine_state" / "reservations_closed" / short,
                            "src-name: " + p.name)
            out["harvest"]["reservations_closed"].append(rec)

    # 4) staged windows (the chunk driving inputs the engine actually uploaded)
    wins_dir = MANAGED / "media_engine/comfy_shot_engine/stage/inputs"
    for p in sorted(wins_dir.rglob("*.mp4")):
        out["harvest"]["windows"].append(safe_copy(p, RAW / "renders" / "windows" / p.name))

    # 5) assemble the 12s demo: concat the 3 accepted outputs + original audio remux
    outs = [MANAGED / str(s["output_relative_path"]) for s in shots]
    lst = RAW / "concat_shots.txt"
    lst.write_text("\n".join("file '" + str(p).replace("\\", "/") + "'" for p in outs) + "\n",
                   encoding="utf-8")
    concat_v = RAW / "shots_concat.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", "-an", str(concat_v)], check=True, timeout=300)
    demo = EXPORT / "demo_final.mp4"
    demo.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(concat_v), "-i", str(RAW / "source_12s.mp4"),
                    "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                    "-t", "12.0", str(demo)], check=True, timeout=300)
    assert demo.is_file() and demo.stat().st_size > 0, "assembled demo missing"
    out["assembly"] = {"concat_manifest": str(lst), "mode": "concat copy + source audio remux (-t 12.0)",
                       "demo": {"path": str(demo), "sha256": sha_file(demo),
                                "bytes": demo.stat().st_size}}
    out["source_sha"] = st["source_12s"]["sha256"]

    (RAW / "engine_receipt.json").write_text(json.dumps(out, indent=1, ensure_ascii=False),
                                             encoding="utf-8")
    # patch state: keep the engine section + record demo
    eng = st.get("engine") or {}
    eng["harvest"] = out["harvest"]
    eng["demo"] = out["assembly"]["demo"]
    st["engine"] = eng
    (RAW / "state.json").write_text(json.dumps(st, indent=1, ensure_ascii=False), encoding="utf-8")
    print("DEMO_READY", out["assembly"]["demo"]["sha256"], out["assembly"]["demo"]["bytes"], flush=True)
    print("harvested:", len(out["harvest"]["outputs"]), "outputs,", len(out["harvest"]["evidence"]),
          "evidence,", len(out["harvest"]["reservations_closed"]), "released,", len(out["harvest"]["windows"]),
          "windows,", len(sib), "sibling takes", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
