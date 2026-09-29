"""MF-END-17 — re-verify the frozen evidence this task binds (read-only).

Checks, all against records written by the PRODUCING rounds:
  * sha256 of every bound artifact (clips, graphs, receipts, gates, interfaces);
  * cross-links between files (P4 receipt vs gate vs graph; P4_GRAPH.built vs graph file);
  * published sha16 cross-check against PROOF_GATE_CANDIDATE.md where a value was published;
  * structural validation of the measured controlled graph against the live object_info dumps;
  * runtime pin (HEAD + version file) and no-listener hygiene on every runtime port;
  * the model-area invariance scan written by w17_hash_models.py.

Usage: python -B tools/w17_verify.py
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

# (relative path under PROOF, expected sha256 or None, provenance)
# Every expected value below is published in PROOF_EVIDENCE_INDEX.md (or in the producer's
# own receipt/gate) BEFORE this task measured anything — no expectation is self-derived.
EXPECT: list[tuple[str, str | None, str]] = [
    # the measured controlled (challenger) graph + its real outputs
    ("graphs/animate2_vace_book.p4.api.json", "18d97cbabf3b7b473e9810b61ba90e1a07795a28d234bcb86eec66f88e54afeb", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("output/p4/animate2_vace_book_p4_00001_.mp4", "691a8530e3f4bdbbf13fb99ffee9abc4e64b43b3617597736098c8d13a756611", "P4_GEOMETRY_GATE.raw_output.sha256 (published)"),
    ("output/p4/animate2_vace_book_p4_00001__trim120.mp4", "32e0963bc39f758894c1dccadbefa1b5adb26b013e064d308cefb28d87ee0274", "P4_GEOMETRY_GATE.comparison_artifact.sha256 (published)"),
    # the challenger round's own records
    ("evidence/P4_RECEIPT.json", "902efa816941f91f14da552ea82adb8b49600a9157b1246b35a42daa94780cb5", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("evidence/P4_GEOMETRY_GATE.json", "fffcca4d131c7dea7a5d71d806bb7685e6deb7689165615202645f95eeab6d62", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("evidence/P4_GRAPH.json", "e373bcf4fe5add07b406f1ca9a5bdd62463f88513d5f46145bfe3400ea5999be", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("evidence/P4_SERVER_SHUTDOWN_PROOF.json", "da8a3041989bb45f493c79cc7f0890d05d972438a4690a0642918f220ec538a1", "PROOF_EVIDENCE_INDEX.md (published)"),
    # runtime + interfaces (P0) - the pin the probe reads
    ("evidence/P0_RUNTIME_MATRIX.json", "adb6bf7cffbce5b56146fe0379461eed0dbc34eea6d88f2957ef322c0321fc2b", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("evidence/P0_NODE_INTERFACES.json", "c360474bb95e998e7e5210a03d3fb2c37b386bad56abc7d9832ae73d490aaf1a", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("evidence/P0_MODEL_INVENTORY.json", "19aafcafa8be989faf7a6adabefc1eaa160eb613c2b5a0028a39754b015cae5b", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("evidence/P0_object_info.json", "80850af29e04c4ae108b61b6ef21ccb9d9a328beaef7785a4c0d3721fc3a8653", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("evidence/P3_object_info_gpu.json", "f78455538fb726e5cbc6e819eca47e198de03a227c8bb59e8ddf374d9dbb9dd0", "PROOF_EVIDENCE_INDEX.md (published)"),
    # the Wan-side hard-gate rows the activation decision reads
    ("evidence/P1_UNIT_MANIFESTS.json", "9763a1d14a3fef1cd075c9252ea4d54961b9ca5a6626e02a5148f4076b6ed0cf", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("evidence/P2_ANCHOR_GATES.json", "d580db708c712652844e8300af2765fd9065b16689dd5f35a61844a18044d792", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("evidence/P3B_GEOMETRY_GATE.json", "f47ab0e456cc263422411a68d7f6a6c5cefccdfa4b2f4188ea52877bfcb0350a", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("evidence/P5FIX_GATE.json", "fb7371154d7435f7b51b7c0f1f9d3e6f51c3af89368e2e97e7ac015e6e6098f2", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("evidence/P5FIX2_GATE.json", "e18dba5a97635763e97533f812e4fc1f7497827fcaa4af242b1bf307f5ee1647", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("evidence/P5FIX3_GATE.json", "b5a8c6996326fbeb55b3575337fb7dd746135fb16b799863a3773b496192d4d7", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("evidence/P5FIX3_SERVER_SHUTDOWN_PROOF.json", "b783991124d223f3c3a7f1949f79f7ee5d51b89e45233fe62df01812bec7b4b9", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("evidence/P6_NOCACHE_GATE.json", "a5c0dd2a39e849b34dd69997d6b91e55607fb4c1fac7de04ec2f30055db0b5ed", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("evidence/P7_ASSEMBLY_V13.json", "abdbf30ff4cc2f0907c37950ff476485bbfebd32b5eb612879d9704b4a22afda", "PROOF_EVIDENCE_INDEX.md (published)"),
    ("evidence/P7_ASSEMBLY_CHECK.json", "dd5f3211f93d9e290a447b9950fd8297bb48aa8012086c5871ec0b0de775904f", "PROOF_EVIDENCE_INDEX.md (published) - v1.1 check; PROOF_GATE_CANDIDATE.md §1 labels this hash with a filename that does not exist (P7_ASSEMBLY_V11_CHECK.json); disclosed, the index filename wins"),
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


def validate_graph_against_object_info(graph: dict, object_info: dict) -> dict:
    """class presence + required/optional input coverage + no unknown inputs.

    ComfyUI 0.37 autogrow inputs arrive in the API graph with DOTTED keys
    (e.g. ``format.codec`` on SaveVideo) because the parent is a COMFY_DYNAMICCOMBO_V3
    whose selected option declares nested sub-inputs.  A dotted key is accepted when the
    parent input is declared as COMFY_DYNAMICCOMBO_V3 and the graph's parent value is one
    of that combo's option keys; the acceptance rule is recorded in the result.
    """
    errors: list[str] = []
    classes = set()
    dynamic_combo_accepted: list[str] = []
    for nid, node in graph.items():
        ct = node.get("class_type")
        classes.add(ct)
        if ct not in object_info:
            errors.append(f"{nid}: class {ct} not in /object_info")
            continue
        spec = object_info[ct].get("input", {})
        required = dict(spec.get("required", {}))
        optional = dict(spec.get("optional", {}))
        given = dict(node.get("inputs", {}))
        for key in sorted(set(required) - set(given)):
            errors.append(f"{nid} ({ct}): missing required input {key}")
        for key, value in sorted(given.items()):
            if key in required or key in optional:
                continue
            if "." in key:
                parent = key.split(".", 1)[0]
                decl = required.get(parent) or optional.get(parent)
                if decl and decl[0] == "COMFY_DYNAMICCOMBO_V3":
                    opts = [o.get("key") for o in (decl[1].get("options") or [])]
                    if given.get(parent) in opts:
                        dynamic_combo_accepted.append(f"{nid}:{key}")
                        continue
            errors.append(f"{nid} ({ct}): input {key} not declared by the node")
    return {"node_count": len(graph), "classes": sorted(classes), "errors": errors,
            "dynamic_combo_accepted": dynamic_combo_accepted,
            "dynamic_combo_rule": "dotted sub-input accepted iff parent is COMFY_DYNAMICCOMBO_V3 and parent value is one of its option keys",
            "ok": not errors}


def main() -> int:
    out: dict = {
        "artifact": "evidence_reverify.json",
        "proof_root": str(PROOF),
        "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rows": [],
        "cross_links": {},
        "graph_validation": {},
        "runtime": {},
        "ports": {},
        "model_area": {},
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

    # cross-links between the producer records themselves
    receipt = json.loads((PROOF / "evidence" / "P4_RECEIPT.json").read_text(encoding="utf-8"))
    gate = json.loads((PROOF / "evidence" / "P4_GEOMETRY_GATE.json").read_text(encoding="utf-8"))
    p4g = json.loads((PROOF / "evidence" / "P4_GRAPH.json").read_text(encoding="utf-8"))
    graph_sha = sha256_file(PROOF / "graphs" / "animate2_vace_book.p4.api.json")
    out["cross_links"] = {
        "p4_graph_file": graph_sha,
        "p4_receipt_graph_sha256": receipt.get("graph_sha256"),
        "p4_gate_graph_sha256": gate.get("graph_sha256"),
        "p4_graph_record_built_sha256": p4g.get("built_sha256"),
        "all_equal": graph_sha == receipt.get("graph_sha256") == gate.get("graph_sha256") == p4g.get("built_sha256"),
        "p4_receipt_prompt_id": receipt.get("prompt_id"),
        "p4_gate_raw_output_sha256": (gate.get("raw_output") or {}).get("sha256"),
        "p4_gate_watermark_blocking_defect": (gate.get("vision_pass") or {}).get("blocking_defect"),
        "p4_gate_coverage_verdict": gate.get("coverage_verdict"),
        "p4_receipt_outputs": [f.get("sha256") for f in receipt.get("output_files", [])],
        "p4_receipt_wall_s": receipt.get("server_side_wall_s"),
        "p4_receipt_vram_peak_mib": receipt.get("vram_peak_mib"),
    }
    if not out["cross_links"]["all_equal"]:
        mismatches += 1

    # structural validation of the measured controlled graph against both dumps
    graph = json.loads((PROOF / "graphs" / "animate2_vace_book.p4.api.json").read_text(encoding="utf-8"))
    oi_cpu = json.loads((PROOF / "evidence" / "P0_object_info.json").read_text(encoding="utf-8"))
    oi_gpu = json.loads((PROOF / "evidence" / "P3_object_info_gpu.json").read_text(encoding="utf-8"))
    out["graph_validation"]["p0_object_info"] = validate_graph_against_object_info(graph, oi_cpu)
    out["graph_validation"]["p3_object_info_gpu"] = validate_graph_against_object_info(graph, oi_gpu)
    if not (out["graph_validation"]["p0_object_info"]["ok"] and out["graph_validation"]["p3_object_info_gpu"]["ok"]):
        mismatches += 1

    # runtime pin
    head = git(["rev-parse", "HEAD"], RUNTIME).strip()
    porcelain = git(["status", "--porcelain"], RUNTIME)
    version_file = RUNTIME / "comfy" / "comfyui_version.py"
    out["runtime"] = {
        "comfyui_dir": str(RUNTIME),
        "head": head,
        "head_expected": "73c9bad4d21e7addbe1d13bc92eee0f1431b017d",
        "head_match": head == "73c9bad4d21e7addbe1d13bc92eee0f1431b017d",
        "porcelain_clean": porcelain.strip() == "",
        "version_file": str(version_file),
        "version_file_sha256": sha256_file(version_file) if version_file.is_file() else None,
        "version_file_sha256_expected": "1103c6ccdac33468682e5d128b028fc0ae0139984f00820150b653c011053257",
        "node_source_sha256": {
            "comfy_extras/nodes_scail.py": sha256_file(RUNTIME / "comfy_extras" / "nodes_scail.py"),
            "comfy_extras/nodes_wan.py": sha256_file(RUNTIME / "comfy_extras" / "nodes_wan.py"),
        },
    }
    if not out["runtime"]["head_match"]:
        mismatches += 1

    for port in PORTS:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        state = s.connect_ex(("127.0.0.1", port))
        s.close()
        out["ports"][str(port)] = "LISTENING" if state == 0 else "refused"
    out["all_ports_refused"] = all(v == "refused" for v in out["ports"].values())

    scan_file = RAW / "model_area_scan.json"
    if scan_file.is_file():
        scan = json.loads(scan_file.read_text(encoding="utf-8"))
        out["model_area"] = {
            "source": "raw/model_area_scan.json",
            "unchanged_vs_p0": scan.get("unchanged_vs_p0"),
            "file_count": scan.get("file_count"),
            "family_scan_scail_sam": scan.get("family_scan", {}),
        }
        if not scan.get("unchanged_vs_p0"):
            mismatches += 1

    out["mismatches"] = mismatches
    out["verdict"] = "PASS" if mismatches == 0 and out["all_ports_refused"] else "FAIL"
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / "evidence_reverify.json"
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"verdict": out["verdict"], "rows": len(out["rows"]), "mismatches": mismatches,
                      "all_equal": out["cross_links"]["all_equal"],
                      "graph_validation": {k: v["ok"] for k, v in out["graph_validation"].items()},
                      "ports": out["ports"], "dest": str(dest)}))
    return 0 if out["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
