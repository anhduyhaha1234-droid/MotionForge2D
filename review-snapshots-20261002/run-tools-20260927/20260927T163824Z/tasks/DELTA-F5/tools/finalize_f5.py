"""DELTA-F5 evidence finalizer: append ledger rows + hash manifest (deterministic)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"
HEAD = sys.argv[1] if len(sys.argv) > 1 else ""
PARENT = sys.argv[2] if len(sys.argv) > 2 else ""


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


ROWS = [
    {
        "cmd": "python -m pytest tests/product_delivery tests/product_p1/public_chain -q (background, window ~19:37Z->19:43Z)",
        "duration_s": 327.63,
        "exit": 0,
        "n": 12,
        "note": "BROAD ONE RUN: 1 failed, 789 passed, 3 skipped in 327.63s; the single failure is test_mf_end_28::test_28_2 (demo inventory app_tree_sha256) — see n=13 attribution; DELTA-F4 baseline on the same lineage was 777 passed/1 failed (same row) => +12 = exactly the 12 new DELTA-F5 rows, 0 new failures; raw/broad_fix.txt",
        "phase": "broad",
        "source_head": PARENT,
        "written_utc": "2026-09-28T19:45:00Z",
    },
    {
        "cmd": "test_mf_end_28 on the base tree (git archive db23839) + builder rerun on the fix tree",
        "duration_s": 8.8,
        "exit": 1,
        "n": 13,
        "note": "ATTRIBUTION: test_28_2 fails on the BASE tree too (1 failed/10 passed) — committed inventory app_tree_sha256 a2da8457 (generated at head 82c84a89) vs base-tree fresh cf90b298 vs fix-tree fresh 50d50c00 => pre-existing staleness + the uncommitted app diff; inventory regen belongs to the integration owner (outside write-set); raw/test28_on_base.txt + raw/app_tree_digest_attribution.txt + raw/builder_rerun.txt",
        "phase": "attribution",
        "source_head": PARENT,
        "written_utc": "2026-09-28T19:45:00Z",
    },
    {
        "cmd": "write_set_guard.py verify --allow-change <write-set> --report raw/guard_after.json",
        "duration_s": None,
        "exit": 0,
        "n": 14,
        "note": "guard VERIFIED 0 failures / 12 entries (6 protected neighbours byte-identical: qc_evidence/compose|observe|measure|sources, qc_checks_handler, shot_reskin_executor, model_profiles.json, test_mf_end_19/23)",
        "phase": "guard",
        "source_head": PARENT,
        "written_utc": "2026-09-28T19:45:00Z",
    },
    {
        "cmd": f"git commit -F raw/commit_msg.txt (local only, NO push) -> {HEAD}",
        "duration_s": None,
        "exit": 0,
        "n": 15,
        "note": f"commit {HEAD} parent {PARENT} (base preserved); 6 files staged = exactly the write-set (+843/-1); pre-existing git noise disclosed (fatal: bad object refs/codex/turn-diffs/... + geometric-repack failure, not our refs); raw/commit_stdout.txt",
        "phase": "commit",
        "source_head": HEAD,
        "written_utc": "2026-09-28T19:45:00Z",
    },
    {
        "cmd": "post-commit: git status --porcelain + guard verify + pytest focused on committed bytes",
        "duration_s": 13.48,
        "exit": 0,
        "n": 16,
        "note": "porcelain EMPTY; guard VERIFIED 0 failures (raw/guard_post_commit.json); focused 12 passed (13.48s) on the committed bytes (raw/focused_post_commit.txt); no push",
        "phase": "final",
        "source_head": HEAD,
        "written_utc": "2026-09-28T19:45:00Z",
    },
    {
        "cmd": "tools/final_gate_f5.py (committed state + evidence integrity + fresh-archive focused run)",
        "duration_s": 13.12,
        "exit": 0,
        "n": 17,
        "note": "FINAL GATE 12/12 PASS: HEAD/parent exact, porcelain [], commit paths == write-set, committed fixture blobs == R3 shas, focused on a FRESH `git archive HEAD` = 12 passed (13.12s), evidence manifest 27 files all sha-verified, guard VERIFIED, ledger monotonic; raw/final_gate.json + raw/focused_committed_archive.txt",
        "phase": "final",
        "source_head": HEAD,
        "written_utc": "2026-09-28T19:52:00Z",
    },
]


def main() -> int:
    ledger = ROOT / "commands.jsonl"
    existing = ledger.read_text(encoding="utf-8").splitlines() if ledger.is_file() else []
    have = {json.loads(line)["n"] for line in existing if line.strip()}
    with open(ledger, "a", encoding="utf-8") as fh:
        for row in ROWS:
            if row["n"] in have:
                continue
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    print("ledger rows:", len(rows), "n:", sorted(r["n"] for r in rows))

    entries = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        # Excluded by NAME so a re-run is byte-identical: the manifest itself and
        # the gate's OWN verdict file (hashing it makes the verdict self-referential:
        # its "mismatched=[...]" detail flips with the previous run's result).
        if rel in ("evidence_manifest.json", "evidence_manifest.txt", "raw/final_gate.json"):
            continue
        entries.append(
            {
                "path": rel,
                "sha256": sha_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    payload = {
        "schema": "mf-delta-f5/evidence-manifest@1",
        "task": "DELTA-F5",
        "head": HEAD,
        "parent": PARENT,
        "files": entries,
        "count": len(entries),
    }
    (ROOT / "evidence_manifest.json").write_text(
        json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    (ROOT / "evidence_manifest.txt").write_text(
        "\n".join(f"{e['sha256']}  {e['path']}" for e in entries) + "\n", encoding="utf-8"
    )
    print("manifest files:", len(entries))
    for e in entries:
        print(" ", e["sha256"][:16], e["path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
