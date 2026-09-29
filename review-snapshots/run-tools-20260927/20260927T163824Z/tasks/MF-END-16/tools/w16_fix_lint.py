"""One-off refactor: rewrap the 18 over-long lines ruff flagged in test_mf_end_16.py."""

from pathlib import Path

P = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-16/tests/product_delivery/test_mf_end_16.py")
text = P.read_text(encoding="utf-8")

PAIRS = [
    (
        '"""MF-END-16 — wan_shot_v1 + model_profiles: profile và phép đo chất lượng/chi phí (acceptance + negatives).',
        '"""MF-END-16 — wan_shot_v1 + model_profiles: profile và phép đo chất lượng/chi phí.',
    ),
    (
        '    differing = [k for k in run_graph\n'
        '                 if json.dumps(run_graph[k], sort_keys=True) != json.dumps(delivered[k], sort_keys=True)]',
        '    differing = [\n'
        '        k for k in run_graph\n'
        '        if json.dumps(run_graph[k], sort_keys=True) != json.dumps(delivered[k], sort_keys=True)\n'
        '    ]',
    ),
    (
        '    assert segs["OCC_SEG1"]["source_span"] == [0, 102] and segs["OCC_SEG1"]["output_span"] == [0, 102]',
        '    assert segs["OCC_SEG1"]["source_span"] == [0, 102]\n'
        '    assert segs["OCC_SEG1"]["output_span"] == [0, 102]',
    ),
    (
        '    assert segs["OCC_SEG2"]["source_span"] == [102, 120] and segs["OCC_SEG2"]["output_span"] == [0, 18]',
        '    assert segs["OCC_SEG2"]["source_span"] == [102, 120]\n'
        '    assert segs["OCC_SEG2"]["output_span"] == [0, 18]',
    ),
    (
        '        assert row["source"]["repo"] in ("Comfy-Org/Wan-Animate-2", "Comfy-Org/Wan_2.1_ComfyUI_repackaged")',
        '        assert row["source"]["repo"] in (\n'
        '            "Comfy-Org/Wan-Animate-2", "Comfy-Org/Wan_2.1_ComfyUI_repackaged")',
    ),
    (
        '    assert rows["OCC_SEG1"]["source"]["frames"] == 102 and rows["OCC_SEG2"]["source"]["frames"] == 18',
        '    assert rows["OCC_SEG1"]["source"]["frames"] == 102\n'
        '    assert rows["OCC_SEG2"]["source"]["frames"] == 18',
    ),
    (
        '    assert peaks["p3b_cache_on"] == 10973 and peaks["p6_cache_off"] == 10763 and peaks["p5_overlap16"] == 11224',
        '    assert peaks["p3b_cache_on"] == 10973\n'
        '    assert peaks["p6_cache_off"] == 10763\n'
        '    assert peaks["p5_overlap16"] == 11224',
    ),
    (
        '        (PROOF_ROOT / "output/p6_book_nocache/animate2_book_nocache_00001_.mp4", OUTPUT_SHAS["BOOK_PINNED_VARIANT"]),',
        '        (PROOF_ROOT / "output/p6_book_nocache/animate2_book_nocache_00001_.mp4",\n'
        '         OUTPUT_SHAS["BOOK_PINNED_VARIANT"]),',
    ),
    (
        '        (PROOF_ROOT / "output/p5fix2_occ_seg1/animate2_occ_seg1_p5fix2_00001_.mp4", OUTPUT_SHAS["OCC_SEG1"]),',
        '        (PROOF_ROOT / "output/p5fix2_occ_seg1/animate2_occ_seg1_p5fix2_00001_.mp4",\n'
        '         OUTPUT_SHAS["OCC_SEG1"]),',
    ),
    (
        '        (PROOF_ROOT / "output/p5fix3_occ_seg2/animate2_occ_seg2_p5fix3_00001_.mp4", OUTPUT_SHAS["OCC_SEG2"]),',
        '        (PROOF_ROOT / "output/p5fix3_occ_seg2/animate2_occ_seg2_p5fix3_00001_.mp4",\n'
        '         OUTPUT_SHAS["OCC_SEG2"]),',
    ),
    (
        '    ("pad_target_changed", lambda g: g["P3B_PAD"]["inputs"].update({"target_width": 482, "target_height": 854})),',
        '    ("pad_target_changed",\n'
        '     lambda g: g["P3B_PAD"]["inputs"].update({"target_width": 482, "target_height": 854})),',
    ),
    (
        '    ("size_points_at_dead_node", lambda g: g["672:596"]["inputs"].__setitem__("image", ["672:600", 0])),',
        '    ("size_points_at_dead_node",\n'
        '     lambda g: g["672:596"]["inputs"].__setitem__("image", ["672:600", 0])),',
    ),
    (
        '    ("prefix_diverged", lambda g: g["292"]["inputs"].__setitem__("filename_prefix", "other/prefix")),',
        '    ("prefix_diverged",\n'
        '     lambda g: g["292"]["inputs"].__setitem__("filename_prefix", "other/prefix")),',
    ),
    (
        '    ("lora_swapped", lambda g: g["672:579"]["inputs"].__setitem__("lora_name", "some_other_lora.safetensors")),',
        '    ("lora_swapped",\n'
        '     lambda g: g["672:579"]["inputs"].__setitem__("lora_name", "some_other_lora.safetensors")),',
    ),
    (
        '    doc["graph"]["672:594"] = {"class_type": "WanAnimate2Cache",\n'
        '                               "inputs": {"device": "gpu", "dtype": "int8", "model": ["672:588", 0]}}',
        '    doc["graph"]["672:594"] = {\n'
        '        "class_type": "WanAnimate2Cache",\n'
        '        "inputs": {"device": "gpu", "dtype": "int8", "model": ["672:588", 0]},\n'
        '    }',
    ),
    (
        '    ("unreachable_node", lambda g: g.__setitem__("ORPHAN", {"class_type": "PrimitiveInt", "inputs": {"value": 1}})),',
        '    ("unreachable_node",\n'
        '     lambda g: g.__setitem__("ORPHAN", {"class_type": "PrimitiveInt", "inputs": {"value": 1}})),',
    ),
    (
        '@pytest.mark.parametrize("name,mutate", STRUCTURAL_NEGATIVES, ids=[m[0] for m in STRUCTURAL_NEGATIVES])',
        '@pytest.mark.parametrize(\n'
        '    "name,mutate", STRUCTURAL_NEGATIVES, ids=[m[0] for m in STRUCTURAL_NEGATIVES]\n'
        ')',
    ),
    (
        '        if p["cost"]["accepted_seconds"] == 0 and p["cost"]["cost_per_accepted_second"] != "UNDEFINED":\n'
        '            return False',
        '        cost = p["cost"]\n'
        '        if cost["accepted_seconds"] == 0 and cost["cost_per_accepted_second"] != "UNDEFINED":\n'
        '            return False',
    ),
]

for old, new in PAIRS:
    count = text.count(old)
    assert count == 1, f"anchor count {count} for: {old[:70]!r}"
    text = text.replace(old, new)

P.write_text(text, encoding="utf-8")
print("patched", len(PAIRS), "anchors")
