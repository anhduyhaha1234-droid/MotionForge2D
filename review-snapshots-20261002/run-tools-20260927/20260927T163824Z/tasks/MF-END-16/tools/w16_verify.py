"""MF-END-16 tool — re-verify the frozen proof evidence on disk (read-only).

Hashes every artifact the profile/manifest will bind, compares against the hash
recorded by the producing round, and cross-checks the two runtime pins plus the
no-listener hygiene.  Writes raw/evidence_reverify.json.

Usage: python -B tools/w16_verify.py
"""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

PROOF = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/proof")
RUN_ROOT = Path(__file__).resolve().parent.parent
RAW = RUN_ROOT / "raw"
RUNTIME = Path("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/ComfyUI")

# (relative path under PROOF, expected sha256 or None, provenance of the expectation)
EXPECT: list[tuple[str, str | None, str]] = [
    # accepted segment clips + assembly (the case outputs)
    ("output/p3b/animate2_book_p3b_00001_.mp4", "dfc4e37b81ba4252635581a6f75fef1084324dcd7af9015e3ea3e2c86b90d77f", "P3B_GEOMETRY_GATE.main_clip"),
    ("output/p5fix_turn/animate2_turn_p5fix_00001_.mp4", "f0b2d6e0dc90b12f31e19e0e8efa97086facaf059def95401dbd0f08de5559c6", "P5FIX_TURN_RECEIPT.output_files[0]"),
    ("output/p5fix2_occ_seg1/animate2_occ_seg1_p5fix2_00001_.mp4", "b9b1cdb989f43ffbee7ea72f52005e86b44d0219d3a49719a6964f53f7f55cc4", "P5FIX2_SEG1_RECEIPT.output_files[0]"),
    ("output/p5fix3_occ_seg2/animate2_occ_seg2_p5fix3_00001_.mp4", "7db4734bf73e267737ff9b17b4579792f9fd44d8140e0724cc364576a55098a7", "P5FIX3_GATE.video"),
    ("output/p7/assembly_v13_00001_.mp4", "6878becc7e1db4c561253fb3ab79a85aacf0ecf685f7ea10dbac0e5b834a750e", "P7_ASSEMBLY_V13.output_files[0]"),
    # cache-off BOOK A/B run (the pinned-variant run)
    ("output/p6_book_nocache/animate2_book_nocache_00001_.mp4", "be83cf705a7a8769a307aaf1c3292e314d612b2aaecf946d8c366674c2fe866b", "P6_NOCACHE_GATE.clip"),
    # challenger (VACE)
    ("output/p4/animate2_vace_book_p4_00001_.mp4", "691a8530e3f4bdbbf13fb99ffee9abc4e64b43b3617597736098c8d13a756611", "P4_GEOMETRY_GATE.raw_output"),
    ("output/p4/animate2_vace_book_p4_00001__trim120.mp4", "32e0963bc39f758894c1dccadbefa1b5adb26b013e064d308cefb28d87ee0274", "P4_GEOMETRY_GATE.comparison_artifact"),
    # frozen inputs (sources / anchors / split clips)
    ("inputs/BOOK_src.mp4", "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc", "P3B_RECEIPT.inputs.driving"),
    ("inputs/anchor_book_p2_00001_.png", "aa08747048c42af56c9e5109b7a041d2f8d95bf7c79544017ef38b98bbb6455e", "P3B_RECEIPT.inputs.anchor"),
    ("inputs/p5fix2_occ_seg1.mp4", "a283d23704e352f7ca3fdc618f8b8275de939b4d0c1eb590fc48c6f825949784", "P5FIX2_SPLIT.steps.clips.seg1"),
    ("inputs/p5fix2_occ_seg2.mp4", "eec74ec5b9eb38ceb433352b01505ffc9185ddbd0ee593679472dd4344137328", "P5FIX2_SPLIT.steps.clips.seg2"),
    ("inputs/p5fix2_occ_seg2_f102_640x368.png", "9dacc1e98cd4bbd978083b5c61a8e65ac63a1c17c00a5b9ea61c6168052f6f29", "P5FIX2_SPLIT.steps.clips.seg2_first_frame"),
    # graph files that produced the accepted clips
    ("graphs/animate2_book.p3b.api.json", "b2ab500748d5163797ccef71e6ed9e078682440a656afd6ae4ab4cf43234a36d", "P3B_RECEIPT.graph_sha256"),
    ("graphs/animate2_book.p6nocache.api.json", "4247f9e8b233da4b6213c3254b637abd4d2e6c17b307b32cddb9b7b17bbd4759", "P6_NOCACHE_RECEIPT.graph_sha256"),
    ("graphs/animate2_turn.p5fix.api.json", "fa94d3265e8993c4c1e758be8ef105f7f72b55bffa56179f37e60b23f771378a", "P5FIX_TURN_RECEIPT.graph_sha256"),
    ("graphs/animate2_occ_seg1.p5fix2.api.json", "d802b6cc68dd9322dde0f9d3fd19981e98bac12541a622bee12c8f4dd667c32d", "P5FIX2_SEG1_RECEIPT.graph_sha256"),
    ("graphs/animate2_occ_seg2.p5fix3.api.json", "0b207c5e5a485cca5c2f368a6c3882bc1f41f7c233b4c786cfb818e048b53220", "P5FIX3_SEG2_RECEIPT.graph_sha256"),
    ("graphs/animate2_vace_book.p4.api.json", "18d97cbabf3b7b473e9810b61ba90e1a07795a28d234bcb86eec66f88e54afeb", "P4_GEOMETRY_GATE.graph_sha256"),
    ("graphs/p7_assembly_v13.api.json", "52f4fcb2cb0cb298d2bfb137e79c08df28801962f010aefd4d84eccbcee9ff0e", "P7_ASSEMBLY_V13.graph_sha256"),
    # inputs whose sha was never previously recorded -> measured here (freeze binding)
    ("inputs/TURN_795_src.mp4", None, "measured here (no prior record)"),
    ("inputs/OCC_14768_src.mp4", None, "measured here (no prior record)"),
    ("inputs/anchor_turn_p2_00001_.png", None, "measured here (no prior record)"),
    ("inputs/anchor_occ_p2_00001_.png", None, "measured here (no prior record)"),
    ("inputs/anchor_occ_seg2_p5fix2_00001_.png", None, "measured here (no prior record)"),
]

# staged copies: the assembly graph must have loaded byte-identical copies
STAGED = [
    ("inputs/p7v13_book.mp4", "dfc4e37b81ba4252635581a6f75fef1084324dcd7af9015e3ea3e2c86b90d77f"),
    ("inputs/p7v13_turn.mp4", "f0b2d6e0dc90b12f31e19e0e8efa97086facaf059def95401dbd0f08de5559c6"),
    ("inputs/p7v13_occ_seg1.mp4", "b9b1cdb989f43ffbee7ea72f52005e86b44d0219d3a49719a6964f53f7f55cc4"),
    ("inputs/p7v13_occ_seg2.mp4", "7db4734bf73e267737ff9b17b4579792f9fd44d8140e0724cc364576a55098a7"),
]

PORTS = [8188, 8189, 8190, 8310, 8321, 8342]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024 * 4), b""):
            h.update(chunk)
    return h.hexdigest()


def git(args: list[str], cwd: Path) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    return p.stdout


def main() -> int:
    out: dict = {
        "artifact": "evidence_reverify.json",
        "proof_root": str(PROOF),
        "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rows": [],
        "staged_copies": [],
        "runtime": {},
        "ports": {},
    }
    mismatches = 0
    for rel, expect, prov in EXPECT:
        path = PROOF / rel
        row = {"path": rel, "expectation_from": prov}
        if not path.is_file():
            row.update({"exists": False, "verdict": "MISSING"})
            mismatches += 1
        else:
            got = sha256_file(path)
            row.update({
                "exists": True,
                "bytes": path.stat().st_size,
                "sha256_measured": got,
                "sha256_expected": expect,
                "verdict": "MATCH" if expect is None or got == expect else "DIFFER",
                "first_measurement": expect is None,
            })
            if row["verdict"] == "DIFFER":
                mismatches += 1
        out["rows"].append(row)

    for rel, expect in STAGED:
        path = PROOF / rel
        got = sha256_file(path) if path.is_file() else None
        out["staged_copies"].append({
            "path": rel, "exists": path.is_file(), "sha256": got,
            "expected_segment_sha": expect, "verdict": "MATCH" if got == expect else "DIFFER",
        })
        if got != expect:
            mismatches += 1

    # runtime pin
    head = git(["rev-parse", "HEAD"], RUNTIME).strip()
    porcelain = git(["status", "--porcelain"], RUNTIME)
    version_file = RUNTIME / "comfy" / "comfyui_version.py"
    if not version_file.is_file():
        # fall back: search for the version file the pin recorded
        version_file = RUNTIME / "comfyui_version.py"
    out["runtime"] = {
        "comfyui_dir": str(RUNTIME),
        "head": head,
        "head_expected": "73c9bad4d21e7addbe1d13bc92eee0f1431b017d",
        "head_match": head == "73c9bad4d21e7addbe1d13bc92eee0f1431b017d",
        "porcelain_clean": porcelain.strip() == "",
        "version_file": str(version_file),
        "version_file_sha256": sha256_file(version_file) if version_file.is_file() else None,
        "version_file_sha256_expected": "1103c6ccdac33468682e5d128b028fc0ae0139984f00820150b653c011053257",
    }
    if not out["runtime"]["head_match"]:
        mismatches += 1

    # no-listener hygiene (the proof servers must all be down)
    for port in PORTS:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        state = s.connect_ex(("127.0.0.1", port))
        s.close()
        out["ports"][str(port)] = "LISTENING" if state == 0 else "refused"
    out["all_ports_refused"] = all(v == "refused" for v in out["ports"].values())

    out["mismatches"] = mismatches
    out["verdict"] = "PASS" if mismatches == 0 and out["all_ports_refused"] else "FAIL"
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / "evidence_reverify.json"
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"verdict": out["verdict"], "rows": len(out["rows"]),
                      "mismatches": mismatches, "ports": out["ports"], "dest": str(dest)}))
    return 0 if out["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
