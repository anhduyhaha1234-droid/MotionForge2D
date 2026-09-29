"""MF-END-09 — fix the 6 remaining E501 lines (byte-exact, no fuzzy edits)."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-09")

PAIRS: list[tuple[str, str, str]] = [
    (
        "app/workflow/reference_asset_jobs.py",
        '            "model_id": Path(str(entry.get("file") or "")).stem or str(entry.get("role") or "model"),\n',
        "            \"model_id\": (\n"
        '                Path(str(entry.get("file") or "")).stem or str(entry.get("role") or "model")\n'
        "            ),\n",
    ),
    (
        "app/workflow/reference_asset_jobs.py",
        '                details={"source_reference_key": plan.source_reference_key, "present": present_keys},\n',
        "                details={\n"
        '                    "source_reference_key": plan.source_reference_key,\n'
        '                    "present": present_keys,\n'
        "                },\n",
    ),
    (
        "app/workflow/reference_asset_jobs.py",
        '            ReferenceAssetRefusalCode.RECEIPT_INCOMPLETE, "completed receipt lacks engine artifact facts"\n',
        "            ReferenceAssetRefusalCode.RECEIPT_INCOMPLETE,\n"
        '            "completed receipt lacks engine artifact facts",\n',
    ),
    (
        "app/workflow/reference_asset_jobs.py",
        "    key = idempotency_key or f\"reference_asset:{version_id}:{plan.content_key.split(':', 1)[-1][:40]}\"\n",
        "    digest = plan.content_key.split(\":\", 1)[-1][:40]\n"
        "    key = idempotency_key or f\"reference_asset:{version_id}:{digest}\"\n",
    ),
    (
        "app/workflow/reference_asset_jobs.py",
        '                ReferenceAssetRefusalCode.JOB_NOT_FOUND, f"no job {job_id}", details={"job_id": job_id}\n',
        "                ReferenceAssetRefusalCode.JOB_NOT_FOUND,\n"
        '                f"no job {job_id}",\n'
        '                details={"job_id": job_id},\n',
    ),
    (
        "tests/product_delivery/test_mf_end_09.py",
        '        **{**plan.__dict__, "source_sha256": raj._sha256_bytes(data), "source_size_bytes": len(data)}\n',
        "        **{\n"
        "            **plan.__dict__,\n"
        '            "source_sha256": raj._sha256_bytes(data),\n'
        '            "source_size_bytes": len(data),\n'
        "        }\n",
    ),
]


def main() -> int:
    for rel, old, new in PAIRS:
        path = ROOT / rel
        data = path.read_bytes()
        newline = b"\r\n" if b"\r\n" in data else b"\n"
        old_b = old.replace("\n", newline.decode()).encode("utf-8")
        new_b = new.replace("\n", newline.decode()).encode("utf-8")
        count = data.count(old_b)
        if count != 1:
            print(f"REFUSED {rel}: preimage count={count}")
            return 1
        path.write_bytes(data.replace(old_b, new_b))
        print(f"FIXED {rel}: {len(data)}->{(ROOT / rel).stat().st_size} B")
    print("sha256:", hashlib.sha256((ROOT / PAIRS[0][0]).read_bytes()).hexdigest()[:12])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
