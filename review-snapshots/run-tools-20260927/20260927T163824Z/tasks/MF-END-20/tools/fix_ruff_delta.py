"""MF-END-20 ruff delta fixer: bounded preimage replacements (count==1 each)."""
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-20")

EDITS: dict[str, list[tuple[str, str]]] = {
    "app/services/shot_reskin_cache.py": [
        (
            '        safe_chunk = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in chunk_id) or "chunk"\n',
            '        safe_chunk = (\n'
            '            "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in chunk_id) or "chunk"\n'
            '        )\n',
        ),
        (
            '        rel = self._receipt_sidecar_rel(str(payload.get("shot_id") or ""), str(payload.get("chunk_id") or ""))\n',
            '        rel = self._receipt_sidecar_rel(\n'
            '            str(payload.get("shot_id") or ""), str(payload.get("chunk_id") or "")\n'
            '        )\n',
        ),
        (
            "        receipt = self.lookup(workspace_id=workspace_id, content_key=content_key, verify_bytes=verify_bytes)\n",
            "        receipt = self.lookup(\n"
            "            workspace_id=workspace_id, content_key=content_key, verify_bytes=verify_bytes\n"
            "        )\n",
        ),
        (
            '                "WHERE workspace_id=:ws AND attempt_row_id=:rid AND state IN (\'prepared\',\'submitted\')"\n',
            '                "WHERE workspace_id=:ws AND attempt_row_id=:rid "\n'
            '                "AND state IN (\'prepared\',\'submitted\')"\n',
        ),
        (
            '                "UPDATE shot_reskin_cache_attempt SET state=\'completed\', updated_at=CURRENT_TIMESTAMP "\n',
            '                "UPDATE shot_reskin_cache_attempt SET state=\'completed\', "\n'
            '                "updated_at=CURRENT_TIMESTAMP "\n',
        ),
        (
            '                    "receipt_rel_path=:sc, receipt_file_sha256=:scsha, updated_at=CURRENT_TIMESTAMP "\n',
            '                    "receipt_rel_path=:sc, receipt_file_sha256=:scsha, "\n'
            '                    "updated_at=CURRENT_TIMESTAMP "\n',
        ),
        (
            '                    "input_digest, graph_digest, model_digest, params_digest, output_relative_path, "\n',
            '                    "input_digest, graph_digest, model_digest, params_digest, "\n'
            '                    "output_relative_path, "\n',
        ),
        (
            "    def status(self, *, workspace_id: str | None = None, run_id: str | None = None) -> dict[str, Any]:\n",
            "    def status(\n"
            "        self, *, workspace_id: str | None = None, run_id: str | None = None\n"
            "    ) -> dict[str, Any]:\n",
        ),
        (
            '        return {"schema_version": SCHEMA_VERSION, "checked": checked, "live": checked, "statements_used": 1}\n',
            "        return {\n"
            '            "schema_version": SCHEMA_VERSION,\n'
            '            "checked": checked,\n'
            '            "live": checked,\n'
            '            "statements_used": 1,\n'
            "        }\n",
        ),
        (
            "class ShotCacheRefusal(RuntimeError):\n",
            "class ShotCacheRefusal(RuntimeError):  # noqa: N818 - mirrors the executor refusal naming\n",
        ),
        (
            "        except BaseException:\n"
            "            try:\n"
            "                tmp.unlink(missing_ok=True)\n"
            "            except Exception:\n"
            "                pass\n"
            "            raise\n",
            "        except BaseException:\n"
            "            with contextlib.suppress(Exception):\n"
            "                tmp.unlink(missing_ok=True)\n"
            "            raise\n",
        ),
        (
            "import hashlib\nimport json\nimport os\nimport uuid\n",
            "import contextlib\nimport hashlib\nimport json\nimport os\nimport uuid\n",
        ),
    ],
    "app/services/s10_recompute.py": [
        (
            "        for row in record_rows:\n"
            "            try:\n"
            '                affected_total += len(json.loads(str(row["affected_chunk_ids_json"])))\n'
            "            except Exception:\n"
            "                pass\n"
            '            kind = str(row["correction_kind"] or "")\n'
            "            kinds[kind] = kinds.get(kind, 0) + 1\n",
            "        for row in record_rows:\n"
            '            kind = str(row["correction_kind"] or "")\n'
            "            kinds[kind] = kinds.get(kind, 0) + 1\n"
            "            try:\n"
            '                affected_ids = json.loads(str(row["affected_chunk_ids_json"]))\n'
            "            except (TypeError, ValueError):\n"
            "                affected_ids = []\n"
            "            affected_total += len(affected_ids)\n",
        ),
    ],
    "app/workflow/s10_full_apply_jobs.py": [
        (
            "                    _ShotReskinCache(_guard_sess, managed_root=managed_root).assert_run_receipts_live(\n"
            "                        workspace_id=ws, run_id=run_id\n"
            "                    )\n",
            "                    _guard = _ShotReskinCache(_guard_sess, managed_root=managed_root)\n"
            "                    _guard.assert_run_receipts_live(workspace_id=ws, run_id=run_id)\n",
        ),
    ],
}

for rel, edits in EDITS.items():
    path = WT / rel
    raw = path.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    data = raw.replace("\r\n", "\n") if nl == "\r\n" else raw
    for old, new in edits:
        count = data.count(old)
        assert count == 1, f"{rel}: anchor count {count} != 1 for {old[:70]!r}"
        data = data.replace(old, new)
    out = data.replace("\n", nl) if nl == "\r\n" else data
    path.write_bytes(out.encode("utf-8"))
    print(f"FIXED {rel}: {len(edits)} edits, newline={nl!r}")
print("FIXER_OK")
