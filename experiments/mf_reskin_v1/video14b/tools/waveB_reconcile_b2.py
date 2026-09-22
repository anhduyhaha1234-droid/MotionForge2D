"""MF-V1-VIDEO14B wave B closeout (b2) — C1 reconciliation, read-only.

Continues the b1 round WITHOUT resubmitting anything.  Proves, from live engine
state plus the run records already on disk, that the wave-B Animate-2 work is
TERMINAL and that no prompt is in flight:

  * GET /queue     -> queue_running / queue_pending must both be empty
  * GET /history   -> every prompt this task submitted must be terminal
  * reservations/  -> every attempt marker must be closed (a2, a3, a4); an
                      attempt with NO marker proves it never reached the POST
  * presubmit_state.json + run_record.json + *.stdout.txt per attempt -> what
                      each attempt actually did and the exact error, so
                      `submit_calls` is counted from evidence, not assumed

The tool NEVER posts a prompt, never starts/stops a process, never writes media.
It only reads HTTP, the JSON records and writes one JSON report.

usage:
  python waveB_reconcile_b2.py <attempts_dir> <runtime_dir> <out_json> [--base-url URL]
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ATTEMPTS = ("run_b3_book4s", "run_b3_book4s_a2", "run_b3_book4s_a3", "run_b3_book4s_a4")
# a1 is refused client-side before any POST -> a reservation marker would be an
# artefact; the absence of the marker is itself the evidence.
NO_MARKER_EXPECTED = {"run_b3_book4s"}


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def get_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return {"ok": True, "status": resp.status,
                    "body": json.loads(resp.read().decode("utf-8", "replace"))}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def jload(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return None


def count_outputs(entry: dict) -> dict:
    """A history entry's 'outputs' is keyed by node id; an input passthrough node
    (LoadVideo) is listed too, so 'n outputs' must be counted per node, not read
    off a length."""
    per_node: dict[str, list[str]] = {}
    for nid, payload in (entry.get("outputs") or {}).items():
        files = []
        for key, val in payload.items():
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and item.get("filename"):
                        files.append(f"{item.get('filename')}|{item.get('type')}|{key}")
        per_node[str(nid)] = sorted(files)
    return per_node


def main() -> int:
    attempts_dir = _p(sys.argv[1])
    runtime = _p(sys.argv[2])
    out_json = _p(sys.argv[3])
    base_url = "http://127.0.0.1:8310"
    if "--base-url" in sys.argv:
        base_url = sys.argv[sys.argv.index("--base-url") + 1]

    epoch = jload(runtime / "instance_epoch.json") or {}
    queue = get_json(base_url + "/queue")
    hist = get_json(base_url + "/history?max_items=50")

    attempts: list[dict] = []
    for name in ATTEMPTS:
        d = attempts_dir / name
        pre = jload(d / "presubmit_state.json") or {}
        rec = jload(d / "run_record.json") or {}
        ad = jload(d / "adapter_stage_output.json") or {}
        stdout = jload(attempts_dir / f"{name}.stdout.txt") or {}
        result = rec.get("result") or ad or {}
        attempt_id = pre.get("attempt_id") or rec.get("attempt_id")
        markers = []
        for cand in sorted((runtime / "reservations").glob("closed/*.json")) + \
                sorted((runtime / "reservations").glob("*.json")):
            m = jload(cand) or {}
            if m.get("attempt_id") == attempt_id:
                markers.append({"file": str(cand).replace("\\", "/"),
                                "outcome": m.get("outcome"),
                                "prompt_id": m.get("prompt_id"),
                                "closed_at": m.get("closed_at"),
                                "closed_at_local": (
                    datetime.fromtimestamp(m["closed_at"], tz=timezone.utc).astimezone()
                    .strftime("%Y-%m-%d %H:%M:%S%z") if m.get("closed_at") else None),
                                "error_code": ((m.get("close_evidence") or {}).get("error") or {}).get("code"),
                                "artifact_count": (m.get("close_evidence") or {}).get("artifact_count"),
                                "sha256": sha256_file(cand)})
        closed = [m for m in markers if m["outcome"] == "terminal_success"
                  or m["error_code"]]
        attempts.append({
            "attempt_id": attempt_id,
            "dir": str(d).replace("\\", "/"),
            "attempt_dir_exists": d.is_dir(),
            "graph_sha256": pre.get("graph_sha256"),
            "engine": pre.get("engine"),
            "presubmit_written_at_local": pre.get("written_at_local"),
            "presubmit_submit_started_field": pre.get("submit_started"),
            "record_status": result.get("status"),
            "record_prompt_id": result.get("prompt_id"),
            "record_error": result.get("error"),
            "record_wall_s": rec.get("wall_s"),
            "stdout_status": stdout.get("status"),
            "stdout_prompt_id": stdout.get("prompt_id"),
            "stdout_error": stdout.get("error"),
            "stdout_wall_s": stdout.get("wall_s"),
            "adapter_status": ad.get("status"),
            "adapter_error_code": (ad.get("error_dict") or {}).get("code"),
            "adapter_artifacts": len(ad.get("artifacts") or []),
            "reservation_markers": markers,
            "marker_expected_absent": name in NO_MARKER_EXPECTED,
            "resolved": bool(closed) or name in NO_MARKER_EXPECTED,
            # a POST happened iff a marker was opened (opened before the POST) --
            # a1 was refused client-side, so it has no marker and 0 submits.
            "submit_calls": 1 if markers else 0,
        })

    history_entries = []
    verdicts = []
    for pid, entry in ((hist.get("body") or {}).items() if hist.get("ok") else []):
        st = entry.get("status") or {}
        status_str = st.get("status_str")
        verdicts.append(status_str)
        history_entries.append({
            "prompt_id": pid,
            "status_str": status_str,
            "completed": st.get("completed"),
            "terminal": status_str in ("success", "error"),
            "outputs_by_node": count_outputs(entry),
        })

    report = {
        "artifact": "reconcile_b2.json",
        "task_id": "MF-V1-VIDEO14B",
        "wave": "B",
        "round": "b2 (closeout continuation)",
        "generated_at_local": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z"),
        "read_only": {"posted_prompt": False, "started_engine": False,
                      "stopped_process": False, "wrote_media": False},
        "engine": {"base_url": base_url,
                   "instance_epoch": epoch,
                   "listener_accepts": queue.get("ok")},
        "queue_probe": {"ok": queue.get("ok"), "status": queue.get("status"),
                        "queue_running": (queue.get("body") or {}).get("queue_running"),
                        "queue_pending": (queue.get("body") or {}).get("queue_pending"),
                        "error": queue.get("error")},
        "history_probe": {"ok": hist.get("ok"), "entries": len(history_entries),
                          "status_strs": sorted(set(verdicts)),
                          "all_terminal": bool(history_entries) and all(
                              e["terminal"] for e in history_entries)},
        "history": history_entries,
        "attempts": attempts,
        "submit_calls_total": sum(a["submit_calls"] for a in attempts),
        "attempts_unresolved": [a["attempt_id"] for a in attempts if not a["resolved"]],
        "conclusion": None,
    }
    qr = (queue.get("body") or {})
    nothing_in_flight = (queue.get("ok") and not qr.get("queue_running")
                         and not qr.get("queue_pending")
                         and report["history_probe"]["all_terminal"]
                         and not report["attempts_unresolved"])
    report["conclusion"] = {
        "no_prompt_in_flight": bool(nothing_in_flight),
        "a4_terminal_success": any(a["record_status"] == "validated"
                                   and a["attempt_id"].endswith("a4") for a in attempts),
        "resubmit_needed": False,
        "adopted_instead_of_resubmitted": None,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(json.dumps({"no_prompt_in_flight": report["conclusion"]["no_prompt_in_flight"],
                      "history_entries": report["history_probe"]["entries"],
                      "status_strs": report["history_probe"]["status_strs"],
                      "submit_calls_total": report["submit_calls_total"],
                      "attempts_unresolved": report["attempts_unresolved"]}, indent=1))
    return 0 if nothing_in_flight else 1


if __name__ == "__main__":
    raise SystemExit(main())
