"""MF-END-10 — sinh evidence: commands.jsonl, results.json, evidence_manifest.json.

Ghi MỘT lượt sau khi writer xong (disclosure: không append theo thời gian thực).
Thời lượng mỗi lệnh lấy từ CHÍNH output của lệnh đó (pytest/npm tự in); cột
``recorded_at`` là thời điểm ghi file (UTC) và được nêu rõ trong REPORT.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

EVID = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-10"
)

NOW = datetime.now(UTC).isoformat()

COMMANDS = [
    # (label, command, cwd, rc, outcome, duration_s, artifact)
    ("preflight-head", "git log --oneline -3 && git status --porcelain && git rev-parse HEAD",
     "MF-END-10", 0, "PASS", None, "raw/preflight.txt"),
    ("baseline-product_delivery", "python -m pytest tests/product_delivery -q --no-header",
     "MF-END-10", 0, "PASS 259 passed, 1 skipped", 156.87, "raw/baseline_product_delivery.txt"),
    ("baseline-public_chain", "python -m pytest tests/product_p1/public_chain -q --no-header",
     "MF-END-10", 0, "PASS 30 passed, 2 skipped", 16.33, "raw/baseline_public_chain.txt"),
    ("preimage-flip", "python - <<PY (git show base blobs + regex)", "MF-END-10", 0,
     "FEATURE_ABSENT: test/module/wiring ABSENT, endpoint strings = 0", None, "raw/preimage_flip.txt"),
    ("fe-tsc-baseline", "npx tsc --noEmit", "frontend", 0, "PASS (no diagnostics)", None,
     "raw/fe_tsc_baseline.txt"),
    ("focused-run1", "python -m pytest tests/product_delivery/test_mf_end_10.py -q --no-header",
     "MF-END-10", 1, "FAIL 4 failed, 18 passed (defect test-side)", 32.90, "raw/focused_run1.txt"),
    ("focused-run2", "python -m pytest tests/product_delivery/test_mf_end_10.py -q --no-header",
     "MF-END-10", 1, "FAIL 1 failed, 21 passed (UI convention check quá chặt)", 33.17, "raw/focused_run2.txt"),
    ("focused-run3", "python -m pytest tests/product_delivery/test_mf_end_10.py -q --no-header",
     "MF-END-10", 1, "FAIL 1 failed, 21 passed (CompatibilityWarnings gray-500 pre-existing)", 38.44,
     "raw/focused_run3.txt"),
    ("focused-run4", "python -m pytest tests/product_delivery/test_mf_end_10.py -q --no-header",
     "MF-END-10", 0, "PASS 22 passed", 37.41, "raw/focused_run4.txt"),
    ("fe-tsc", "npx tsc --noEmit", "frontend", 0, "PASS (no diagnostics)", None, "raw/fe_tsc.txt"),
    ("fe-eslint-scope", "npx eslint src/features/reference-library src/features/project-cast 'src/app/(app)/characters/page.tsx'",
     "frontend", 1, "FAIL 1 error react-hooks/set-state-in-effect (module mới)", None, "raw/fe_eslint_scoped_before.txt"),
    ("fe-eslint-scope-fixed", "npx eslint src/features/reference-library src/features/project-cast 'src/app/(app)/characters/page.tsx'",
     "frontend", 0, "PASS 0 errors, 2 warnings (no-img-element, cùng pattern pre-existing)", None,
     "raw/fe_eslint_scoped_after.txt"),
    ("ruff-new-test", "python -m ruff check tests/product_delivery/test_mf_end_10.py",
     "MF-END-10", 0, "PASS All checks passed", None, "raw/ruff_mf_end_10.txt"),
    ("npm-ci", "npm ci --prefer-offline --no-audit --no-fund", "frontend", 0,
     "PASS (node_modules thật trong worktree; junction đã gỡ vì Turbopack từ chối symlink ngoài root)",
     44.0, "raw/npm_ci.txt"),
    ("fe-build-1", "npm run build", "frontend", 1,
     "FAIL TurbopackInternalError: Symlink node_modules invalid (junction -> ngoài root)", 66.0,
     "raw/next_build_junction_fail.txt"),
    ("fe-build-2", "npm run build", "frontend", 0, "PASS (12 static pages, /characters xanh)",
     53.0, "raw/next_build.txt"),
    ("focused-final", "python -m pytest tests/product_delivery/test_mf_end_10.py -q --no-header",
     "MF-END-10", 0, "PASS 22 passed", 33.34, "raw/focused_final.txt"),
    ("broad-wave", "python -m pytest tests/product_delivery -q --no-header", "MF-END-10", 0,
     "PASS 281 passed, 1 skipped (== 259 baseline + 22 test mới)", 208.99, "raw/broad_wave.txt"),
    ("public-chain-post", "python -m pytest tests/product_p1/public_chain -q --no-header",
     "MF-END-10", 0, "PASS 30 passed, 2 skipped (== base)", 15.01, "raw/public_chain_post.txt"),
    ("guard-porcelain", "git status --porcelain", "MF-END-10", 0,
     "PASS 6 dòng == allowlist (4 M + 2 ?? nhóm)", None, "raw/porcelain.txt"),
    ("write-set-bytes", "python tools/write_set_bytes.py", "MF-END-10", 0,
     "PASS before/after sha256+bytes+lines cho 10 path", None, "raw/write_set_bytes.json"),
    ("fe-tsc-eslint-final", "npx tsc --noEmit && npx eslint <3 path trong write-set>", "frontend", 0,
     "PASS tsc 0 diagnostic, eslint 0 error", None, "raw/fe_tsc_final.txt + raw/fe_eslint_final.txt"),
    ("commit-local", "git add <10 path trong allowlist> && git commit -m 'MF-END-10...'", "MF-END-10", 0,
     "PASS head 4d60a2f parent c0c99519, 10 file +2504/-1, KHÔNG push; log bad-object/geometric-repack là pre-existing",
     None, "raw/commit_info.txt"),
    ("final-gate", "manifest hash verify + commit scope + porcelain + worktree==HEAD", "MF-END-10", 0,
     "PASS 29/29 hash match, 10/10 path trong allowlist, porcelain 0", None, "raw/final_gate.txt"),
    ("verify-after-commit", "python -m pytest tests/product_delivery/test_mf_end_10.py -q --no-header",
     "MF-END-10", 0, "PASS 22 passed (chạy lại SAU commit — fresh verification, worktree không đổi)",
     38.09, "raw/verify_after_commit.txt"),
]

RESULTS = [
    {"id": "MF-END-10.1", "status": "PASS",
     "detail": "Đọc frontend AGENTS/next docs tại chỗ, tái dùng shell + component hiện hữu; module mới chỉ dùng @/lib/api + palette biến CSS",
     "artifact": "frontend/src/features/reference-library/"},
    {"id": "MF-END-10.2", "status": "PASS",
     "detail": "Bảng view tham chiếu: trạng thái/thiếu theo validation thật; nhập ảnh (reference-artwork) và tạo asset thiếu (asset job) ngay trên UI",
     "artifact": "frontend/src/features/reference-library/ReferenceViewBoard.tsx"},
    {"id": "MF-END-10.3", "status": "PASS",
     "detail": "Bảng gợi ý: bộ đang ghim đọc từ server + ứng viên kèm lý do (VI) + series pin + MỘT nút xác nhận gọi recommendations/confirm",
     "artifact": "frontend/src/features/reference-library/CastRecommendationPanel.tsx"},
    {"id": "MF-END-10.4", "status": "PASS",
     "detail": "Loading/empty/error/retry + keyboard (Tab/Enter/Space/Escape) cho mọi khối mới; lỗi hiển thị typed, không lộ chi tiết engine",
     "artifact": "raw/mfend10_run5.txt"},
    {"id": "acceptance-E2E", "status": "PASS",
     "detail": "22 row PASS: suggestion read-only + reasons; confirm 1 thao tác + replay 0 mutation; reload giữ pin; update kho không tự đổi pin (series pin thắng hạng); upload làm missing_slots giảm; job bền vững submit/status/cancel/retry; chuỗi đầu-cuối thiếu→bổ sung→ghim",
     "artifact": "tests/product_delivery/test_mf_end_10.py"},
    {"id": "negative-controls", "status": "PASS",
     "detail": "11 row âm: trace lệch pack (409), thiếu/stale expected_revision (422/409), pack chưa publish (409), mask bị từ chối (422), version published (409), prompt thiếu view (422), key đã có asset (409), view ngoài từ vựng (422), job lạ (404), role lạ (404) — tất cả zero mutation",
     "artifact": "raw/focused_final.txt"},
    {"id": "FE-gates", "status": "PASS",
     "detail": "tsc --noEmit sạch; eslint 0 error (2 warning no-img-element trùng pattern pre-existing); npm run build xanh 12 route",
     "artifact": "raw/next_build.txt"},
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    with (EVID / "commands.jsonl").open("w", encoding="utf-8") as fh:
        for label, command, cwd, rc, outcome, duration, artifact in COMMANDS:
            fh.write(
                json.dumps(
                    {
                        "task": "MF-END-10",
                        "label": label,
                        "command": command,
                        "cwd": cwd,
                        "rc": rc,
                        "outcome": outcome,
                        "duration_seconds": duration,
                        "artifact": artifact,
                        "recorded_at_utc": NOW,
                        "time_source": "output của chính lệnh (pytest/npm in); file ghi một lượt sau khi chạy",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    payload = {
        "task": "MF-END-10",
        "generated_at_utc": NOW,
        "rows": RESULTS,
        "counts": {
            "rows": len(RESULTS),
            "pass": sum(1 for r in RESULTS if r["status"] == "PASS"),
            "fail": sum(1 for r in RESULTS if r["status"] == "FAIL"),
        },
        "test_rows": {"focused": "22 passed", "broad": "281 passed, 1 skipped",
                      "public_chain": "30 passed, 2 skipped"},
    }
    (EVID / "results.json").write_text(
        json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    manifest = {"task": "MF-END-10", "generated_at_utc": NOW, "files": {}}
    for path in sorted(EVID.rglob("*")):
        if path.is_file() and path.name != "evidence_manifest.json":
            manifest["files"][str(path.relative_to(EVID)).replace("\\", "/")] = {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
    (EVID / "evidence_manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print("commands:", len(COMMANDS), "results:", len(RESULTS), "manifest:", len(manifest["files"]))


if __name__ == "__main__":
    main()
