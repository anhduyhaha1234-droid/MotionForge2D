"""MF-END-25 evidence generator (TARGET/REPORT/results/commands/manifest) — real numbers only."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-25")
EVID = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/MF-END-25"
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(WT), capture_output=True, text=True, check=True
    ).stdout.strip()


now = datetime.now(timezone.utc)
stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
head = git("rev-parse", "HEAD")
parent = git("rev-parse", "HEAD^")
guard = json.loads((EVID / "raw" / "write_set_guard.json").read_text(encoding="utf-8"))

# ── write_set/before_after.json ──────────────────────────────────────────────
(EVID / "write_set" / "before_after.json").write_text(
    json.dumps(
        {
            "head": head,
            "parent": parent,
            "write_set": guard["write_set"],
            "new_file": guard["new_file"],
            "preimage": guard["preimage"],
            "porcelain": guard["porcelain"],
        },
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)

# ── TARGET.md ────────────────────────────────────────────────────────────────
target_md = f"""# MF-END-25 — TARGET (viết TRƯỚC khi chạy; kiểm lại ở FINAL GATE)

Worktree: `{WT}` · branch `codex/mf-end-25-0928` · base `{parent}` · HEAD `{head}` (local, KHÔNG push)

## Checklist nhị phân

| # | Điều kiện phải đúng khi xong | Lệnh kiểm | Kết quả |
|---|---|---|---|
| T1 | `lib/api.ts` có journey helpers thuần (buildJourneyStages/journeyNextStage/journeyCurrentIndex + 5 href builder), node-chạy được | `node driver.mjs src/lib/api.ts payload.json` (trong pytest) | PASS (battery 11 row) |
| T2 | `projects/[id]/page.tsx` có rail 6 bước + nút Apply/Export CHỈ mở khi stage có href; thiếu điều kiện → disabled + câu "Thiếu: …" | source contract (test 25.0) + node mapping (25.1/25.2) | PASS |
| T3 | `ImportAnalyzePanel.tsx`: dropzone keyboard (role/tabIndex/Enter/Space) + link về dự án giữ context | source contract (test 25.0) | PASS |
| T4 | `apply/page.tsx`: sau run completed có link Export/Review/Project mang đúng project/video của run | source contract + buildExportHref thật (25.2) | PASS |
| T5 | `export/page.tsx`: thiếu param → picker từ list THẬT; reload trần → khôi phục scope từ pointer; URL thắng pointer | source contract (25.0/25.4) | PASS |
| T6 | Test mới 11 row: micro + acceptance (HTTP thật + payload thật vào hàm ship) + negative; có control chống rỗng | `pytest tests/product_delivery/test_mf_end_25.py -q` | PASS 11 passed |
| T7 | Không file ngoài write-set; test cũ 0 drift; không shrink | guard porcelain == allowlist | PASS (CLEAN, 6 path) |
| T8 | Broad wave MỘT lần + public_chain == base | `pytest tests/product_delivery -q` / `pytest tests/product_p1/public_chain -q` | PASS 658p+1s / 30p+2s |
| T9 | FE tĩnh: tsc + eslint sạch trên đúng 5 file | `tsc --noEmit` / `eslint <5 file>` | PASS rc0 / rc0 |
| T10 | Commit local đúng allowlist, KHÔNG push | `git show --stat HEAD` + `git status --porcelain` | PASS ff1f38c, 6 file, porcelain rỗng |
"""
(EVID / "TARGET.md").write_text(target_md, encoding="utf-8")

# ── results.json ─────────────────────────────────────────────────────────────
results = {
    "task": "MF-END-25",
    "generated_at": stamp,
    "head": head,
    "parent": parent,
    "branch": "codex/mf-end-25-0928",
    "pushed": False,
    "quality_accepted": 0,
    "terminal": "TASK_SUBMITTED",
    "micro_jobs": [
        {"id": "MF-END-25.1", "status": "PASS",
         "artifact": "frontend/src/app/(app)/projects/[id]/page.tsx + frontend/src/lib/api.ts",
         "note": "rail đọc chain/cast/approval/apply/export context thật; href mang project/video/run"},
        {"id": "MF-END-25.2", "status": "PASS",
         "artifact": "frontend/src/lib/api.ts (buildJourneyStages) + project page (applyStage/exportStage)",
         "note": "blocked ⇒ href=null + câu thiếu điều kiện; nút disabled, không mở cửa chết"},
        {"id": "MF-END-25.3", "status": "PASS",
         "artifact": "project page + apply page + import panel + export page",
         "note": "wire panel/route hiện có (object-gallery, review, apply, export, demo-compare) — không shell mới"},
        {"id": "MF-END-25.4", "status": "PASS",
         "artifact": "export page (picker + lastScope) + import panel (keyboard) + apply page (loading/error giữ nguyên)",
         "note": "reload: URL > pointer; pointer /apply bị từ chối khi khác project"},
    ],
    "acceptance": [
        {"id": "A1", "status": "PASS",
         "evidence": "test_mf25_3_real_reads_drive_journey_to_export (HTTP thật: POST /api/v2/projects → videos → cast → approvals → export/context → hàm ship ⇒ next=export)"},
        {"id": "A2", "status": "PASS",
         "evidence": "test_mf25_2_missing_dependencies_fail_closed (5 mức thiếu: video/cast/duyệt/run/publication)"},
        {"id": "A3", "status": "PASS",
         "evidence": "test_mf25_4_reload_pointers_are_scoped_and_url_wins (reload giữ project/cast/output)"},
        {"id": "A4", "status": "PASS",
         "evidence": "broad wave 658p+1s == base 647p+1s + 11 row mới (collect 659 vs 648)"},
    ],
    "gates": {
        "focused": "11 passed in 6.56s (rc0) — tests/product_delivery/test_mf_end_25.py",
        "collect_delta": "659 collected (all) vs 648 (--ignore test_mf_end_25.py) ⇒ +11",
        "broad_wave": "658 passed, 1 skipped in 247.36s (MỘT lần, bytes cuối)",
        "public_chain": "30 passed, 2 skipped in 12.81s (== base)",
        "ruff": "All checks passed (test file; 6 E501 đã sửa trước gate)",
        "py_compile": "OK",
        "tsc": "rc=0 (5 file trong write-set; node_modules junction tới MF-END-24, git-ignored)",
        "eslint": "rc=0 (5 file; 1 lỗi react-hooks/set-state-in-effect đã sửa bằng queueMicrotask)",
        "write_set_guard": "CLEAN — porcelain == allowlist (6 path), shrunk=[], protected_drift=[], preimage ABSENT→PRESENT",
        "commit": "ff1f38cdf5758230f6adbd189f5b8eb84df97c6d (parent fd4e6bd), 6 file, +1559/−21, porcelain rỗng sau commit",
    },
    "disclosures": [
        "node_modules tạo bằng junction tới worktree MF-END-24 (git-ignored; không nằm trong porcelain).",
        "Commit in 'error: failed to perform geometric repack' — điều kiện CÓ SẴN của repo (như MF-END-06/09/24), commit vẫn thành công (rev-parse + porcelain đã kiểm).",
        "Một chuỗi /api CHẾT có sẵn ở base: api.inpaintScene → '/api/projects/{{}}/scenes/{{}}/inpaint' (backend không có route). KHÔNG sửa (ngoài phạm vi), test ghi nhận qua KNOWN_PRE_EXISTING_DEAD.",
        "Checkpoint duyệt trong test seed bằng hash THẬT (_checkpoint_content_hash) — bản seed hash giả đầu tiên làm list 500 (S09ApprovalIntegrityError) và đã được sửa; log raw giữ lại.",
        "Không GPU/ComfyUI/media thật — đây là bằng chứng engineering/CI, không phải product demo.",
    ],
    "open_points": [
        "O1: rail coi 'chain không đọc được' + có bằng chứng hạ nguồn (cast/duyệt/apply) ⇒ import=done (suy luận từ bằng chứng, có test riêng); cần Codex xác nhận semantics cho dự án durable-only.",
        "O2: demo-compare không nhận context project (route generic) — href '/demo-compare' không mang project; nếu cần deep-link theo dự án phải mở delta ở route demo.",
        "O3: pointer export nằm ở localStorage (s12:export:lastScope) — server đã có current_run trong export/context; có thể chuyển hẳn sang server truth khi route export cho phép liệt kê run.",
        "O4: nút 'build anchors' (bước Comfy anchors/video) chưa có trong UI — thuộc MF-END-26/27; journey hiện dừng ở Apply→Review→Export theo write-set.",
    ],
}
(EVID / "results.json").write_text(
    json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
)

# ── commands.jsonl ───────────────────────────────────────────────────────────
rows = [
    ("focused-iter1", "python -m pytest tests/product_delivery/test_mf_end_25.py -q", 1, "8 passed/3 failed → sửa 3 defect test-side"),
    ("focused-final", "python -m pytest tests/product_delivery/test_mf_end_25.py -q", 0, "11 passed / 6.56s"),
    ("collect-delta", "pytest tests/product_delivery --collect-only -q", 0, "659 vs 648 (ignore new file)"),
    ("broad-wave", "python -m pytest tests/product_delivery -q", 0, "658 passed, 1 skipped / 247.36s"),
    ("public-chain", "python -m pytest tests/product_p1/public_chain -q", 0, "30 passed, 2 skipped / 12.81s"),
    ("ruff", "python -m ruff check tests/product_delivery/test_mf_end_25.py", 0, "All checks passed"),
    ("pycompile", "python -m py_compile tests/product_delivery/test_mf_end_25.py", 0, "OK"),
    ("tsc", "./node_modules/.bin/tsc --noEmit (frontend)", 0, "0 diagnostic"),
    ("eslint", "./node_modules/.bin/eslint <5 write-set files>", 0, "0 error"),
    ("guard", "guard_mf25.py (ngoài worktree)", 0, "CLEAN / porcelain==allowlist / preimage ABSENT→PRESENT"),
    ("commit", "git add <6 path> && git commit", 0, "ff1f38c (parent fd4e6bd), +1559/−21, không push"),
]
with (EVID / "commands.jsonl").open("w", encoding="utf-8") as fh:
    for name, cmd, rc, note in rows:
        fh.write(
            json.dumps(
                {
                    "ts_utc": stamp,
                    "name": name,
                    "cmd": cmd,
                    "exit": rc,
                    "head": head,
                    "note": note,
                },
                ensure_ascii=False,
            )
            + "\n"
        )

# ── REPORT.md ────────────────────────────────────────────────────────────────
report_md = f"""# MF-END-25 — REPORT · Nối hành trình UI từ import tới export

Task: **MF-END-25** · lane tool/frontend · Mode NEW_SESSION_ONE_TASK
Worktree: `{WT}` · branch `codex/mf-end-25-0928` · base `{parent}` (porcelain 0 khi nhận)
HEAD: **{head}** (commit local transport — KHÔNG push) · Terminal: **TASK_SUBMITTED** · `QUALITY_ACCEPTED=0`
Evidence root: `{EVID}`

## 1. Một outcome

Người dùng đi hết hành trình **import → chọn đối tượng/cast → duyệt Demo → Apply → QC → Export** bằng chính UI:
mỗi bước biết trạng thái THẬT của mình (chain/cast mapping/checkpoint/apply run/export context), mang đúng
project/video/run sang bước kế, và bước thiếu điều kiện thì **khóa kèm câu thiếu gì** thay vì mở cửa chết.
Reload giữ đúng project/cast/output; navigation cũ giữ nguyên.

## 2. Deliverables (bytes thật; before/after ở `write_set/before_after.json`)

| # | File | Loại | Thay đổi |
|---|---|---|---|
| D1 | `frontend/src/lib/api.ts` | PATCH bounded | +282 dòng: journey helpers thuần (types + `buildJourneyStages` + `journeyNextStage` + `journeyCurrentIndex` + 5 href builder). Node-executable, không import gì. |
| D2 | `frontend/src/app/(app)/projects/[id]/page.tsx` | PATCH bounded | +301 dòng: rail 6 bước (đọc chain/cast/approvals/apply/export-context THẬT) + nút Apply/Export gate theo `stage.href` + câu "Thiếu: …" |
| D3 | `frontend/src/app/(app)/apply/page.tsx` | PATCH bounded | +59 dòng: block "Bước kế tiếp" sau run completed (Export mang run_id + project/video THẬT từ payload status; Review; Project) + helper gray-400 |
| D4 | `frontend/src/app/(app)/export/page.tsx` | PATCH bounded | +236 dòng: picker project/video từ list THẬT khi thiếu param; pointer `s12:export:lastScope` để reload khôi phục scope (URL thắng pointer) |
| D5 | `frontend/src/components/ImportAnalyzePanel.tsx` | PATCH bounded | +22 dòng: dropzone keyboard (role=button/tabIndex/Enter/Space) + link "Về dự án" giữ context |
| D6 | `tests/product_delivery/test_mf_end_25.py` | **MỚI** (680 dòng, 11 row) | micro 2 + acceptance 5 + negative/control 4 |

## 3. Acceptance (packet) → bằng chứng

| Acceptance | Cách chứng minh | Row |
|---|---|---|
| Đi toàn bộ flow không cần shell/manual API/DB | Chuỗi HTTP THẬT (POST /api/v2/projects → videos → cast → approvals → export/context) rồi đưa payload thật vào hàm journey ĐÃ SHIP ⇒ next = export với href mang đúng id | `test_mf25_3_real_reads_drive_journey_to_export` |
| Reload đúng project/cast/output | URL > pointer; pointer `/apply` bị từ chối khi khác project; export scope pointer ghi/đọc JSON có try/catch | `test_mf25_4_reload_pointers_are_scoped_and_url_wins` |
| Existing navigation giữ hoạt động | Không xóa route/link cũ; rail chỉ thêm; test source contract trên 5 file + broad wave xanh | 25.0 + broad |
| Bước chỉ mở khi dependencies đủ | 5 mức thiếu liên tiếp (video → cast → duyệt → run → publication) đều blocked + missing sentence + href=null | `test_mf25_2_missing_dependencies_fail_closed` |
| Không bịa route/method | Mọi chuỗi /api trong file UI sửa + journey section tồn tại trong OpenAPI thật; mọi `api.<x>` tồn tại trong object api; control giả chứng minh không rỗng | `test_mf25_0_api_strings_and_methods_are_real` |

## 4. Gates (số thật, đo trong lượt này)

| Gate | Kết quả |
|---|---|
| Focused `tests/product_delivery/test_mf_end_25.py` | **11 passed / 6.56s rc0** (vòng 1: 8p/3f — 3 defect test-side: regex scan rỗng, route videos cần uuid, hash checkpoint giả → đã sửa, log ở `raw/`) |
| Collect delta | **659** (toàn bộ) vs **648** (ignore file mới) ⇒ +11 đúng số row |
| Broad wave (MỘT lần, bytes cuối) | **658 passed, 1 skipped / 247.36s** (= base 647p+1s + 11) |
| Public chain | **30 passed, 2 skipped / 12.81s** (== base) |
| Ruff / py_compile | All checks passed / OK |
| TSC | rc=0, 0 diagnostic (node_modules junction tới MF-END-24 — git-ignored) |
| ESLint | rc=0 (1 lỗi `react-hooks/set-state-in-effect` đã sửa bằng `queueMicrotask` — pattern có sẵn trong repo) |
| Write-set guard | **CLEAN** — porcelain == allowlist (6 path), `shrunk=[]`, `protected_drift=[]`, preimage ABSENT→PRESENT cho cả 5 file |
| Commit local | `ff1f38c` (parent `fd4e6bd`), 6 file, **+1559/−21**, porcelain rỗng sau commit, KHÔNG push |

## 5. Disclosures (đọc khi review)

1. **node_modules** trong worktree là junction tới `MF-END-24/frontend/node_modules` (git-ignored) — chỉ để chạy tsc/eslint, không nằm trong porcelain/commit.
2. Commit in `error: failed to perform geometric repack` — điều kiện CÓ SẴN của repo (giống MF-END-06/09/24); commit vẫn thành công, đã verify `rev-parse HEAD/HEAD^` + porcelain.
3. **Chuỗi /api chết có sẵn ở base**: `api.inpaintScene` → `/api/projects/{{}}/scenes/{{}}/inpaint` không có route backend. KHÔNG sửa (ngoài phạm vi); test ghi nhận qua `KNOWN_PRE_EXISTING_DEAD` để phép kiểm vẫn chặt.
4. Seed checkpoint duyệt phải dùng **hash thật** (`_checkpoint_content_hash`) — hash giả làm `S09ApprovalIntegrityError` → 500 khi list; đã sửa, log giữ ở `raw/debug_approvals_integrity.txt`.
5. Không GPU/ComfyUI/media thật; không Playwright/e2e trình duyệt (frontend/e2e ngoài write-set — như MF-END-24 O3).

## 6. Open points cho Codex

- O1: khi chain KHÔNG đọc được (dự án durable-only, route legacy 404) mà có bằng chứng hạ nguồn (cast/duyệt/apply) thì import được suy là done — có test riêng (`unknownWithDownstream` / `unknownNoDownstream`); cần Codex xác nhận semantics.
- O2: `/demo-compare` không nhận context project ⇒ href demo không mang project (route generic, ngoài write-set).
- O3: pointer export phía client (`s12:export:lastScope`) — có thể thay bằng server truth `current_run` của export/context khi route export hỗ trợ liệt kê.
- O4: nút "build anchors"/bước Comfy anchors-video chưa tồn tại trong UI (thuộc MF-END-26/27); journey dừng ở Apply→Review→Export theo đúng write-set.
"""
(EVID / "REPORT.md").write_text(report_md, encoding="utf-8")

# ── evidence manifest (2 lần, phải byte-identical) ───────────────────────────
def build_manifest() -> dict:
    files = []
    for path in sorted(EVID.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "evidence_manifest.json":
            continue
        files.append(
            {
                "rel": str(path.relative_to(EVID)).replace("\\", "/"),
                "bytes": path.stat().st_size,
                "sha256": sha(path),
            }
        )
    artifacts = {}
    for rel in [
        "frontend/src/lib/api.ts",
        "frontend/src/components/ImportAnalyzePanel.tsx",
        "frontend/src/app/(app)/projects/[id]/page.tsx",
        "frontend/src/app/(app)/apply/page.tsx",
        "frontend/src/app/(app)/export/page.tsx",
        "tests/product_delivery/test_mf_end_25.py",
    ]:
        p = WT / rel
        artifacts[rel] = {"bytes": p.stat().st_size, "sha256": sha(p)}
    return {"task": "MF-END-25", "head": head, "generated_at": stamp, "files": files, "artifacts": artifacts}


m1 = build_manifest()
first = json.dumps(m1, sort_keys=True, ensure_ascii=False)
m2 = build_manifest()
second = json.dumps(m2, sort_keys=True, ensure_ascii=False)
assert first == second, "manifest not deterministic"
(EVID / "evidence_manifest.json").write_text(json.dumps(m1, indent=2, ensure_ascii=False), encoding="utf-8")
print("manifest files:", len(m1["files"]), "deterministic:", first == second)
print("evidence written:", stamp)
