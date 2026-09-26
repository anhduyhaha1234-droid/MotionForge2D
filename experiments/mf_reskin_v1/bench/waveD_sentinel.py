"""MF-V1-BENCH round D - isolation sentinel: ledgers, scratch roots, packets, tests (CPU only).

Gate (all must hold):
  1. every protected ledger is byte-identical before/after this round (0 bytes appended) AND still
     matches the value recorded by an EARLIER round (independent cross-check, not a self-comparison);
  2. the frozen/submitted BENCH roots are zero-drift (per-file bytes+sha maps, before == after) and
     the digests recorded by round C reproduce exactly from disk today;
  3. the isolated scratch roots are zero-drift;
  4. with MF_BENCH_* absent from the environment (exactly the reviewer's condition that produced the
     F10 leak) the harness's default ledger still resolves to SCRATCH, and a scratch root pointed
     INSIDE an evidence root still fails closed instead of appending;
  5. `ruff --select F` on the bench sources is clean and the bench suite is green.

Usage:
  python experiments/mf_reskin_v1/bench/waveD_sentinel.py before   # run FIRST, before other work
  python experiments/mf_reskin_v1/bench/waveD_sentinel.py after    # runs the tests, then re-measures

Writes <D>/raw/d1_sentinel_before.json, d1_sentinel_after.json, d1_sentinel_ledger.json,
pytest_d.txt, ruff_d.txt and appends one run header to <D>/raw/cmd_transcript.jsonl.
Never writes to a protected root; never evaluates media; never takes a GPU lease.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mfv1/wt-bench")
BENCH_SRC = WT / "experiments" / "mf_reskin_v1" / "bench"
OUT = Path("C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/outputs/"
           "mf-core-tool-delivery-20260924/20260924T1557Z")
D = OUT / "BENCH"
RAW = D / "raw"
CORR = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
            "mf-reskin-correction-20260922/20260922T0955Z")
WAVE12 = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
              "mf-reskin-model-upgrade-20260922/20260922T0345Z")
PREV_B = Path("C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/outputs/"
              "mf-core-tool-delivery-20260923/20260923T1535Z")
PREV_C = Path("C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/outputs/"
              "mf-core-tool-delivery-20260924/20260924T1055Z")
# isolated scratch: Windows-native temp, SHORT path, never inside an evidence root (pitfall #17/#42/#44)
SCRATCH_D = Path("C:/Users/Admin/AppData/Local/Temp/mfbench_d")
OWN_LEDGER = RAW / "cmd_transcript.jsonl"

# ---- values recorded by EARLIER rounds (frozen evidence, cross-checked here, never re-derived) ----
RECORDED_LEDGERS = {
    "s1_correction_round_ledger": {
        "path": CORR / "BENCH" / "raw" / "cmd_transcript.jsonl",
        "role": "the old (partially lost) wave-1 ledger - submitted evidence packet",
        "bytes": 184680, "sha256": "21d5b178bcc838b5dbb6e3012a95ae13308bae04338f0a1bedefa07ebfc5e2a2"},
    "s2_correction_round_ledger_prefix": {
        "path": CORR / "BENCH" / "raw" / "cmd_transcript.jsonl",
        "role": "the frozen prefix of s1 (the bytes that survived the wave-1 overwrite)",
        "bytes": 184680, "sha256": "21d5b178bcc838b5dbb6e3012a95ae13308bae04338f0a1bedefa07ebfc5e2a2",
        "prefix_bytes": 173959,
        "prefix_sha256": "ed95c09986ddd85fd003f05f1591181a9cc32e94b9963a4957f63e31dfbf885b"},
    "s3_wave12_ledger": {
        "path": WAVE12 / "BENCH" / "raw" / "cmd_transcript.jsonl",
        "role": "wave-1/2 round ledger - submitted evidence packet",
        "bytes": 49496, "sha256": "04d9ff39be36bbcceb7977029f900681d449b4515943abe9a8da4b067386de38"},
    "s4_roundB_own_ledger": {
        "path": PREV_B / "BENCH" / "raw" / "cmd_transcript.jsonl",
        "role": "this lane's round-B packet ledger - frozen",
        "bytes": 334955, "sha256": "b62a9e98688cc9be4e2d572f5b9e79f5a65e92c584ec980a63034c1c4894a2b4"},
}
RECORDED_ROOTS = {
    "submitted_packet_correction_round": {
        "root": CORR / "BENCH", "files": 90,
        "digest": "28a5b9b39b24c9fc09a4db699f6eb1c10255a46252e2d49d328c0bcdcf383c66"},
    "submitted_packet_wave12": {
        "root": WAVE12 / "BENCH", "files": 53,
        "digest": "1954f940cca1ffe9cfbf5a595051a8192e30b2fb62ff225b08b141fe5fb8e962"},
    "own_previous_packet_20260923T1535Z": {
        "root": PREV_B / "BENCH", "files": 249,
        "digest": "a57bd0876306d9c25021ef7676a5b6d7b074f2ba332b7de28d4b2bb253f6e0d0"},
    "own_previous_packet_20260924T1055Z": {"root": PREV_C / "BENCH", "files": None, "digest": None},
}
RECORDED_SCRATCH = {
    "f10_basetemp_a": {"root": PREV_B / "BENCH" / "work" / "f10_basetemp_a",
                       "files": 29,
                       "digest": "4ab28079854e3a128b83f59ed5629765c1dfac8ebaa094c123c041e2e9aedb0a"},
    "f10_basetemp_flap2": {"root": PREV_B / "BENCH" / "work" / "f10_basetemp_flap2",
                           "files": 29,
                           "digest": "7a1a96ed4461ed1576a786ad2c6b412a49bac711034ec1e76b6aa0c852bb0686"},
    "m1_scratch": {"root": PREV_B / "BENCH" / "work" / "m1_scratch", "files": None, "digest": None},
    "roundC_basetemp": {"root": PREV_C / "BENCH" / "work" / "pytest_basetemp", "files": None,
                        "digest": None},
}
COMMANDS: list = []
ENV_CLEAN_KEYS = ("MF_BENCH_LEDGER", "MF_BENCH_WORK", "MF_BENCH_EV_OUT", "MF_BENCH_LEDGER_MODE")


def sha_b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run(cmd, **kw):
    t0 = time.time()
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
    out = p.stdout.decode("utf-8", "replace")
    COMMANDS.append({"argv": [str(c) for c in cmd], "exit_code": p.returncode,
                     "wall_s": round(time.time() - t0, 3)})
    return p.returncode, out


def root_snapshot(root: Path) -> dict:
    files = {}
    if root.exists():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                rel = str(p.relative_to(root)).replace("\\", "/")
                b = p.read_bytes()
                files[rel] = {"bytes": len(b), "sha256": sha_b(b)}
    return {"root": str(root), "files": len(files),
            "bytes_total": sum(v["bytes"] for v in files.values()),
            "digest": sha_b(json.dumps(files, sort_keys=True).encode()),
            "files_map": files}


def inside_any_evidence_root(path) -> bool:
    """Is `path` inside ANY BENCH packet root (the two submitted ones plus this lane's own)?

    This round's scratch must be provably outside all of them; the check is local and explicit so
    the answer cannot depend on which roots the harness happens to guard (see common.EVIDENCE_ROOTS,
    which deliberately covers only the two SUBMITTED packets).
    """
    def norm(p):
        return str(Path(p).resolve()).replace("\\", "/").lower().rstrip("/")
    p = norm(path)
    return any(p == r or p.startswith(r + "/")
               for r in (norm(x) for x in (CORR / "BENCH", WAVE12 / "BENCH", PREV_B / "BENCH",
                                           PREV_C / "BENCH", D)))


def snap_ledgers() -> dict:
    out = {}
    for name, rec in RECORDED_LEDGERS.items():
        b = rec["path"].read_bytes() if rec["path"].exists() else None
        row = {"path": str(rec["path"]), "role": rec["role"], "exists": b is not None,
               "bytes": len(b) if b is not None else None,
               "sha256": sha_b(b) if b is not None else None,
               "rows_newline_terminated": (b.count(b"\n") if b is not None else None),
               "prefix_bytes": None, "prefix_sha256": None,
               "recorded": {"bytes": rec["bytes"], "sha256": rec["sha256"],
                            "prefix_bytes": rec.get("prefix_bytes"),
                            "prefix_sha256": rec.get("prefix_sha256")}}
        if b is not None and rec.get("prefix_bytes"):
            pre = b[: rec["prefix_bytes"]]
            row["prefix_bytes"] = len(pre)
            row["prefix_sha256"] = sha_b(pre)
        row["matches_recorded"] = (row["bytes"] == rec["bytes"] and row["sha256"] == rec["sha256"]
                                   and row["prefix_bytes"] == rec.get("prefix_bytes")
                                   and row["prefix_sha256"] == rec.get("prefix_sha256"))
        out[name] = row
    return out


def snap_roots() -> dict:
    out = {}
    for name, rec in RECORDED_ROOTS.items():
        s = root_snapshot(rec["root"])
        s["recorded_files"] = rec["files"]
        s["recorded_digest"] = rec["digest"]
        s["matches_recorded"] = (rec["digest"] is None
                                 or (s["digest"] == rec["digest"] and s["files"] == rec["files"]))
        out[name] = s
    return out


def snap_scratch() -> dict:
    out = {}
    for name, rec in RECORDED_SCRATCH.items():
        s = root_snapshot(rec["root"])
        s["recorded_files"] = rec["files"]
        s["recorded_digest"] = rec["digest"]
        s["matches_recorded"] = (rec["digest"] is None
                                or (s["digest"] == rec["digest"] and s["files"] == rec["files"]))
        out[name] = s
    own = root_snapshot(SCRATCH_D)
    own["recorded_files"] = None
    own["recorded_digest"] = None
    own["matches_recorded"] = None
    out["roundD_scratch"] = own
    return out


def snapshot(phase: str) -> dict:
    return {"artifact": "d1_sentinel_%s.json" % phase, "task_id": "MF-V1-BENCH",
            "round": "D", "phase": phase, "session": os.environ.get("HERMES_SESSION_ID"),
            "when": time.strftime("%Y-%m-%dT%H:%M:%S"), "when_epoch": round(time.time(), 3),
            "kind": "read_only_sentinel_re_measurement", "tree": str(WT),
            "ledgers": snap_ledgers(), "roots": snap_roots(), "scratch": snap_scratch()}


def default_ledger_probe() -> dict:
    """What does the harness do with NO environment at all? (the F10 leak condition)"""
    code = (
        "import sys, json, os\n"
        "sys.path.insert(0, r'%s')\n"
        "import common as C\n"
        "res = {'env_MF_BENCH_LEDGER': os.environ.get('MF_BENCH_LEDGER'),\n"
        "       'resolved_ledger': str(C.ledger_path()),\n"
        "       'in_evidence_root': C.in_evidence_root(C.ledger_path()),\n"
        "       'evidence_roots': [str(x) for x in C.EVIDENCE_ROOTS]}\n"
        "print('PROBE=' + json.dumps(res))\n" % str(BENCH_SRC))
    env = dict(os.environ)
    for k in ENV_CLEAN_KEYS:
        env.pop(k, None)
    rc, out = run([sys.executable, "-c", code], cwd=str(WT), env=env)
    line = [ln for ln in out.splitlines() if ln.startswith("PROBE=")]
    res = json.loads(line[0][6:]) if line else {"error": out[-400:]}
    res["exit_code"] = rc

    code2 = (
        "import sys, json, os\n"
        "os.environ['MF_BENCH_WORK'] = r'%s'\n"
        "sys.path.insert(0, r'%s')\n"
        "import common as C\n"
        "try:\n"
        "    print('PROBE2=' + json.dumps({'raised': False, 'resolved': str(C.ledger_path())}))\n"
        "except RuntimeError as e:\n"
        "    print('PROBE2=' + json.dumps({'raised': True, 'type': 'RuntimeError',\n"
        "                                  'msg': str(e)[:200]}))\n"
        # the scratch root MUST be pointed at one of C.EVIDENCE_ROOTS (the two SUBMITTED packets),
        # not at this round's own root: measuring the wrong root is what a false "leak" is made of
        # (pitfall #55). This is byte-for-byte the reviewer's condition from round B.
        % (str(CORR / "BENCH" / "raw" / "_should_never_exist"), str(BENCH_SRC)))
    res["probe_target_scratch_root"] = str(CORR / "BENCH" / "raw" / "_should_never_exist")
    rc2, out2 = run([sys.executable, "-c", code2], cwd=str(WT), env=env)
    line2 = [ln for ln in out2.splitlines() if ln.startswith("PROBE2=")]
    res["scratch_inside_evidence_root_probe"] = (json.loads(line2[0][7:]) if line2
                                                 else {"error": out2[-400:]})
    res["fails_closed_when_scratch_is_inside_evidence_root"] = bool(
        res["scratch_inside_evidence_root_probe"].get("raised"))
    return res


def append_own_ledger(payload: dict) -> dict:
    """Append-only: never opens the ledger with mode 'w' (pitfall #29)."""
    RAW.mkdir(parents=True, exist_ok=True)
    before = {"exists": OWN_LEDGER.exists(),
              "bytes": OWN_LEDGER.stat().st_size if OWN_LEDGER.exists() else 0}
    before["sha256"] = sha_b(OWN_LEDGER.read_bytes()) if OWN_LEDGER.exists() else None
    header = {"run": "start", "task_id": "MF-V1-BENCH", "round": "D",
              "session": os.environ.get("HERMES_SESSION_ID"),
              "when": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "append",
              "note": "own ledger of this round; protected ledgers are never opened for writing"}
    with OWN_LEDGER.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(header, sort_keys=True) + "\n")
        for c in payload.get("commands", []):
            fh.write(json.dumps({"run": "cmd", **c}, sort_keys=True) + "\n")
        fh.write(json.dumps({"run": "end", "verdict": payload.get("SENTINEL"),
                             "when": time.strftime("%Y-%m-%dT%H:%M:%S")},
                            sort_keys=True) + "\n")
    after_b = OWN_LEDGER.stat().st_size
    return {"path": str(OWN_LEDGER), "before": before,
            "after_bytes": after_b, "bytes_appended_by_this_run": after_b - before["bytes"]}


def main() -> int:
    phase = sys.argv[1] if len(sys.argv) > 1 else ""
    if phase not in ("before", "after"):
        print("usage: waveD_sentinel.py before|after")
        return 2
    RAW.mkdir(parents=True, exist_ok=True)

    if phase == "before":
        snap = snapshot("before")
        (RAW / "d1_sentinel_before.json").write_text(json.dumps(snap, indent=1), encoding="utf-8")
        print("PHASE=before session=%s when=%s" % (snap["session"], snap["when"]))
        for k, v in snap["ledgers"].items():
            print("LEDGER %-32s %s B sha=%s recorded_match=%s"
                  % (k, v["bytes"], (v["sha256"] or "-")[:16], v["matches_recorded"]))
        for k, v in snap["roots"].items():
            print("ROOT   %-32s files=%s digest=%s recorded_match=%s"
                  % (k, v["files"], v["digest"][:16], v["matches_recorded"]))
        for k, v in snap["scratch"].items():
            print("SCRATCH %-31s files=%s digest=%s recorded_match=%s"
                  % (k, v["files"], v["digest"][:16], v["matches_recorded"]))
        return 0

    before = json.loads((RAW / "d1_sentinel_before.json").read_text(encoding="utf-8"))

    # ---- 5. fresh static + suite (no MF_BENCH_* in the environment) ----
    env = dict(os.environ)
    for k in ENV_CLEAN_KEYS:
        env.pop(k, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    rc_ruff, out_ruff = run(["ruff", "check", "--select", "F", str(BENCH_SRC)],
                            cwd=str(WT), env=env)
    (RAW / "ruff_d.txt").write_text("ruff check --select F %s -> rc=%s\n\n%s"
                                    % (BENCH_SRC, rc_ruff, out_ruff), encoding="utf-8")

    import shutil
    if SCRATCH_D.exists():
        shutil.rmtree(SCRATCH_D)
    cmd = [sys.executable, "-m", "pytest", str(BENCH_SRC), "-q", "-p", "no:cacheprovider",
           "--basetemp=" + str(SCRATCH_D)]
    rc_suite, out_suite = run(cmd, cwd=str(WT), env=env)
    suite_wall_s = COMMANDS[-1]["wall_s"]          # captured AT RUN TIME, not after later probes
    (RAW / "pytest_d.txt").write_text(
        "$ %s\ncwd=%s\nenv: MF_BENCH_* REMOVED\nbasetemp=%s (isolated Windows temp, outside every "
        "evidence root)\n\n%s" % (" ".join(cmd), WT, SCRATCH_D, out_suite), encoding="utf-8")

    # ---- 1 + 2 + 3. isolation ----
    after = snapshot("after")
    probe = default_ledger_probe()
    (RAW / "d1_sentinel_after.json").write_text(json.dumps(after, indent=1), encoding="utf-8")

    ledgers = {}
    for k in before["ledgers"]:
        b, a = before["ledgers"][k], after["ledgers"][k]
        ledgers[k] = {"path": a["path"], "role": a["role"],
                      "before": {f: b[f] for f in ("bytes", "sha256", "rows_newline_terminated",
                                                   "prefix_bytes", "prefix_sha256")},
                      "after": {f: a[f] for f in ("bytes", "sha256", "rows_newline_terminated",
                                                  "prefix_bytes", "prefix_sha256")},
                      "bytes_appended_by_this_round": (a["bytes"] or 0) - (b["bytes"] or 0),
                      "sha_unchanged": b["sha256"] == a["sha256"],
                      "byte_facts_identical": a["bytes"] == b["bytes"] and a["sha256"] == b["sha256"],
                      "matches_value_recorded_by_earlier_round": a["matches_recorded"],
                      "affirmed_by_phase_before": b["matches_recorded"]}

    roots = {}
    for k in before["roots"]:
        b, a = before["roots"][k], after["roots"][k]
        changed = sorted(set(b["files_map"]) | set(a["files_map"]))
        changed = [r for r in changed if b["files_map"].get(r) != a["files_map"].get(r)]
        roots[k] = {"root": a["root"], "files_before": b["files"], "files_after": a["files"],
                    "bytes_before": b["bytes_total"], "bytes_after": a["bytes_total"],
                    "digest_before": b["digest"], "digest_after": a["digest"],
                    "recorded_digest": a["recorded_digest"],
                    "digest_matches_recorded": a["matches_recorded"],
                    "changed_paths": changed,
                    "zero_drift": not changed and b["digest"] == a["digest"]}

    scratch = {}
    for k in before["scratch"]:
        b, a = before["scratch"][k], after["scratch"][k]
        changed = sorted(set(b["files_map"]) | set(a["files_map"]))
        changed = [r for r in changed if b["files_map"].get(r) != a["files_map"].get(r)]
        scratch[k] = {"root": a["root"], "files_before": b["files"], "files_after": a["files"],
                      "digest_before": b["digest"], "digest_after": a["digest"],
                      "recorded_digest": a.get("recorded_digest"),
                      "digest_matches_recorded": a.get("matches_recorded"),
                      "changed_paths": changed,
                      "zero_drift": not changed and b["digest"] == a["digest"],
                      # the round-D scratch root is created BY this round's test run on purpose, so
                      # growth there is expected; what must hold is that every PRE-EXISTING scratch
                      # root is untouched and that the new one is outside every evidence root.
                      "drift_expected": k == "roundD_scratch",
                      "note": ("fresh isolated scratch created by this round's suite - expected to "
                               "grow from empty" if k == "roundD_scratch" else
                               "pre-existing scratch root - must be byte-identical")}
    pre_scratch_zero = all(v["zero_drift"] for k, v in scratch.items() if k != "roundD_scratch")
    fresh = scratch["roundD_scratch"]
    fresh_scratch_ok = (fresh["files_before"] == 0 and fresh["files_after"] > 0
                        and not inside_any_evidence_root(SCRATCH_D))

    zero_appended = all(v["bytes_appended_by_this_round"] == 0 for v in ledgers.values())
    all_recorded = all(v["matches_value_recorded_by_earlier_round"] for v in ledgers.values())
    ok = (rc_ruff == 0 and rc_suite == 0 and zero_appended and all_recorded
          and all(d["zero_drift"] for d in roots.values()) and pre_scratch_zero and fresh_scratch_ok
          and not probe["in_evidence_root"]
          and probe["fails_closed_when_scratch_is_inside_evidence_root"])

    sent = {"artifact": "d1_sentinel_ledger.json", "task_id": "MF-V1-BENCH", "round": "D",
            "kind": "sentinel_packet_ledger_zero_drift_and_ledger_isolation",
            "session": after["session"], "when": after["when"],
            "before_file": str(RAW / "d1_sentinel_before.json"),
            "after_file": str(RAW / "d1_sentinel_after.json"),
            "gate": "every protected ledger keeps every byte and still matches the value recorded by "
                    "an earlier round; submitted packets and isolated scratch roots zero-drift; the "
                    "default ledger resolves to scratch and fails closed inside an evidence root; "
                    "ruff --select F clean; suite green",
            "ledgers": ledgers,
            "bytes_appended_to_protected_ledgers": sum(v["bytes_appended_by_this_round"]
                                                       for v in ledgers.values()),
            "all_ledgers_match_earlier_recorded_values": all_recorded,
            "roots_zero_drift": roots,
            "scratch_zero_drift": scratch,
            "pre_existing_scratch_zero_drift": pre_scratch_zero,
            "fresh_scratch": {"root": str(SCRATCH_D), "files_before": fresh["files_before"],
                              "files_after": fresh["files_after"],
                              "digest_after": fresh["digest_after"],
                              "outside_every_evidence_root": not inside_any_evidence_root(SCRATCH_D),
                              "ok": fresh_scratch_ok},
            "default_ledger_probe": probe,
            "static": {"command": "ruff check --select F %s" % BENCH_SRC, "exit_code": rc_ruff,
                       "output_path": str(RAW / "ruff_d.txt"), "clean": rc_ruff == 0,
                       "tail": out_ruff.strip().splitlines()[-2:]},
            "suite": {"command": " ".join(cmd), "cwd": str(WT), "exit_code": rc_suite,
                      "basetemp": str(SCRATCH_D),
                      "wall_s": suite_wall_s,
                      "output_path": str(RAW / "pytest_d.txt"), "green": rc_suite == 0,
                      "tail": out_suite.strip().splitlines()[-1] if out_suite.strip() else ""},
            "commands": COMMANDS,
            "SENTINEL": "PASS" if ok else "FAIL"}
    sent["own_ledger"] = append_own_ledger(sent)
    (RAW / "d1_sentinel_ledger.json").write_text(json.dumps(sent, indent=1), encoding="utf-8")

    print("RUFF_RC=%s clean=%s" % (rc_ruff, rc_ruff == 0))
    print("SUITE_RC=%s wall=%ss %s" % (rc_suite, sent["suite"]["wall_s"], sent["suite"]["tail"]))
    for k, v in ledgers.items():
        print("LEDGER %-32s before=%s B sha=%s | after=%s B sha=%s | appended=%s recorded_match=%s"
              % (k, v["before"]["bytes"], (v["before"]["sha256"] or "-")[:16],
                 v["after"]["bytes"], (v["after"]["sha256"] or "-")[:16],
                 v["bytes_appended_by_this_round"], v["matches_value_recorded_by_earlier_round"]))
    for k, v in roots.items():
        print("ROOT   %-32s files %s->%s digest %s zero_drift=%s recorded_match=%s"
              % (k, v["files_before"], v["files_after"], v["digest_after"][:16],
                 v["zero_drift"], v["digest_matches_recorded"]))
    for k, v in scratch.items():
        print("SCRATCH %-31s files %s->%s digest %s zero_drift=%s drift_expected=%s"
              % (k, v["files_before"], v["files_after"], v["digest_after"][:16], v["zero_drift"],
                 v["drift_expected"]))
    print("PRE_EXISTING_SCRATCH_ZERO_DRIFT=%s FRESH_SCRATCH_OK=%s outside_all_evidence_roots=%s"
          % (pre_scratch_zero, fresh_scratch_ok, not inside_any_evidence_root(SCRATCH_D)))
    print("PROBE_TARGET=%s" % probe.get("probe_target_scratch_root"))
    print("DEFAULT_LEDGER=%s in_evidence_root=%s fails_closed=%s"
          % (probe.get("resolved_ledger"), probe.get("in_evidence_root"),
             probe.get("fails_closed_when_scratch_is_inside_evidence_root")))
    print("OWN_LEDGER appended=%s B (append-only, mode 'a')"
          % sent["own_ledger"]["bytes_appended_by_this_run"])
    print("SENTINEL=%s" % sent["SENTINEL"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
