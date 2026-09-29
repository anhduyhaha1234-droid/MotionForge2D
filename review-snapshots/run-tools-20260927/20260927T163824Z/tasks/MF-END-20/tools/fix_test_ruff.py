"""MF-END-20 test ruff cleanup (bounded, count==1 asserts)."""
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-20")
path = WT / "tests/product_delivery/test_mf_end_20.py"
raw = path.read_bytes().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
data = raw.replace("\r\n", "\n") if nl == "\r\n" else raw

E = [
    (
        '        "span": {"source": {**base["source"], "span": {"start_frame": 1, "end_frame_exclusive": 10}}},\n',
        '        "span": {\n'
        '            "source": {**base["source"], "span": {"start_frame": 1, "end_frame_exclusive": 10}}\n'
        "        },\n",
    ),
    (
        '    assert json.loads(sidecar.read_text(encoding="utf-8"))["output_sha256"] == receipt["output_sha256"]\n',
        '    sidecar_doc = json.loads(sidecar.read_text(encoding="utf-8"))\n'
        '    assert sidecar_doc["output_sha256"] == receipt["output_sha256"]\n',
    ),
    (
        '            request=_request(), result=_result(out, "engine_out/ck_0001_00001_.mp4"), attempt_row_id=old_id\n',
        "            request=_request(),\n"
        '            result=_result(out, "engine_out/ck_0001_00001_.mp4"),\n'
        "            attempt_row_id=old_id,\n",
    ),
    (
        '        assert cache.lookup(workspace_id="default", content_key=shot_content_key(_request())) is None\n',
        "        assert (\n"
        '            cache.lookup(workspace_id="default", content_key=shot_content_key(_request()))\n'
        "            is None\n"
        "        )\n",
    ),
    (
        '            request=_request(), result=_result(out, "engine_out/ck_0001_00001_.mp4"), attempt_row_id=row_id\n',
        "            request=_request(),\n"
        '            result=_result(out, "engine_out/ck_0001_00001_.mp4"),\n'
        "            attempt_row_id=row_id,\n",
    ),
    (
        '        assert cache.invalidate_shot(workspace_id="default", shot_id="BOOK", reason="qc retry BOOK") == 1\n',
        "        count = cache.invalidate_shot(\n"
        '            workspace_id="default", shot_id="BOOK", reason="qc retry BOOK"\n'
        "        )\n"
        "        assert count == 1\n",
    ),
    (
        '            workspace_id="default", component="cast", digest=book_texture["cast"], reason="cast repack"\n',
        '            workspace_id="default",\n'
        '            component="cast",\n'
        '            digest=book_texture["cast"],\n'
        '            reason="cast repack",\n',
    ),
    (
        '        assert cache.invalidate_shot(workspace_id="default", shot_id="BOOK", reason="user redraw") == 1\n',
        "        count = cache.invalidate_shot(\n"
        '            workspace_id="default", shot_id="BOOK", reason="user redraw"\n'
        "        )\n"
        "        assert count == 1\n",
    ),
    (
        '                " revision_after) VALUES (\'r1\',\'default\',\'p1\',\'run-a\',\'corr-1\',\'mask\',\'[\\"layer_a\\"]\',"\n',
        '                " revision_after) VALUES (\'r1\',\'default\',\'p1\',\'run-a\',\'corr-1\',"\n'
        '                "\'mask\',\'[\\"layer_a\\"]\',"\n',
    ),
    (
        '                " revision_after) VALUES (\'r2\',\'default\',\'p1\',\'run-a\',\'corr-2\',\'z_order\',\'[\\"layer_a\\"]\',"\n',
        '                " revision_after) VALUES (\'r2\',\'default\',\'p1\',\'run-a\',\'corr-2\',"\n'
        '                "\'z_order\',\'[\\"layer_a\\"]\',"\n',
    ),
    (
        '                " next_index, executed_json, completed) VALUES (\'corr-1\',\'default\',\'run-a\',0,\'[]\',0)"\n',
        '                " next_index, executed_json, completed) VALUES"\n'
        '                " (\'corr-1\',\'default\',\'run-a\',0,\'[]\',0)"\n',
    ),
    (
        '        assert state["corrections"] == {"total": 2, "kinds": {"mask": 1, "z_order": 1}, "affected_total": 3}\n',
        '        assert state["corrections"] == {\n'
        '            "total": 2,\n'
        '            "kinds": {"mask": 1, "z_order": 1},\n'
        '            "affected_total": 3,\n'
        "        }\n",
    ),
    (
        '        assert state["per_shot"] == {"BOOK": {"chunks": 2, "verified": 2}, "TURN": {"chunks": 1, "verified": 1}}\n',
        '        assert state["per_shot"] == {\n'
        '            "BOOK": {"chunks": 2, "verified": 2},\n'
        '            "TURN": {"chunks": 1, "verified": 1},\n'
        "        }\n",
    ),
    (
        '        s.execute(text("UPDATE s10_full_apply_chunk SET state=\'failed\', verified=0 WHERE id=:c"), {"c": ids[2]})\n',
        "        s.execute(\n"
        '            text("UPDATE s10_full_apply_chunk SET state=\'failed\', verified=0 WHERE id=:c"),\n'
        '            {"c": ids[2]},\n'
        "        )\n",
    ),
    (
        '                    " attempt, artifact_id, content_hash, natural_key) VALUES (:cid,\'default\',\'run-1\',"\n',
        '                    " attempt, artifact_id, content_hash, natural_key)"\n'
        '                    " VALUES (:cid,\'default\',\'run-1\',"\n',
    ),
    (
        '                " revision_after) VALUES (\'rx\',\'default\',\'p1\',\'run-1\',\'corr-x\',\'mask\',\'[\\"layer_a\\"]\',"\n',
        '                " revision_after) VALUES (\'rx\',\'default\',\'p1\',\'run-1\',\'corr-x\',"\n'
        '                "\'mask\',\'[\\"layer_a\\"]\',"\n',
    ),
    (
        '        before = svc.preservation_report(workspace_id="default", run_id="run-1", correction_id="corr-x")\n',
        "        before = svc.preservation_report(\n"
        '            workspace_id="default", run_id="run-1", correction_id="corr-x"\n'
        "        )\n",
    ),
    (
        '        after = svc.preservation_report(workspace_id="default", run_id="run-1", correction_id="corr-x")\n',
        "        after = svc.preservation_report(\n"
        '            workspace_id="default", run_id="run-1", correction_id="corr-x"\n'
        "        )\n",
    ),
    (
        '            svc.preservation_report(workspace_id="default", run_id="run-OTHER", correction_id="corr-x")\n',
        "            svc.preservation_report(\n"
        '                workspace_id="default", run_id="run-OTHER", correction_id="corr-x"\n'
        "            )\n",
    ),
    (
        '        attempt_2 = f"shot-mf20-0001#2"\n',
        '        attempt_2 = "shot-mf20-0001#2"\n',
    ),
    (
        "import hashlib\nimport json\nimport os\nimport shutil\nimport uuid\n",
        "import contextlib\nimport hashlib\nimport json\nimport os\nimport shutil\n",
    ),
    (
        "        if shot_root.exists() and not any(shot_root.iterdir()):\n"
        "            try:\n"
        "                shot_root.rmdir()\n"
        "            except OSError:\n"
        "                pass\n",
        "        if shot_root.exists() and not any(shot_root.iterdir()):\n"
        "            with contextlib.suppress(OSError):\n"
        "                shot_root.rmdir()\n",
    ),
]

for old, new in E:
    count = data.count(old)
    assert count == 1, f"anchor count {count} != 1 for {old[:80]!r}"
    data = data.replace(old, new)

out = data.replace("\n", nl) if nl == "\r\n" else data
path.write_bytes(out.encode("utf-8"))
print("TEST_RUFF_FIX_OK")
