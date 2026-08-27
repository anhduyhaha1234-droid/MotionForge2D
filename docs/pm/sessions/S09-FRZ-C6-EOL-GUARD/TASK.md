# S09-FRZ-C6-EOL-GUARD — TASK — EOL exit hardening (J1 v4 byte-freeze)

## Authority
- Codex S09-C5 PM REVIEW 2026-08-27 — F1 (P1) — C6 EOL exit hardening prompt section 4
- Manager prompt: `C:/Users/Admin/MotionForge2D/docs/pm/prompts/S09_C6_EXIT_HARDENING_MANAGER_2026-08-27.md` (Wave A PREP, Wave A task S09-FRZ-C6-EOL-GUARD = new session)
- Workspace: `C:/Users/Admin/MotionForge2D-worktrees/s08-integration` branch `codex/s08-integration` HEAD `ee10e55a809c84d5cb5d4a3046a1ee78828528d0`
- Rules: `C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md` 180 lines SHA256 `987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25` — RULES_LOADED
- Model: `meta` reasoning max TTFB 900 fallback OFF — owner new session S09-FRZ-C6-EOL-GUARD

## Preflight J0-C6 (14:36)
- Manifest `output/s09/20260823_sprint_full/j1-c3/renderer_freeze_manifest_v4.json` sha256 `ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5` (21 lines, CRLF on disk but content hash matches)
- Direct 6/13 MATCH, 7 CRLF-only drifts confirmed EOL-only (93329785, cdd0362f, 5d985a26, 1c4e50a4, 079a7425, c409f2f1, 6b2712ad normalize to expected) — seven CRLF-only, no semantic change
- `.gitattributes` missing at J0 — J1-v4 unchanged — diagnosis consistent with `core.autocrlf=true` on Windows
- `MOTIONFORGE_DATABASE_URL` UNSET — isolated basetemp per run — no shared DB — no global server while Wave A writers active — ports attribution clean

## Nhiem vu (Wave A — PREP)
Add durable EOL contract that was outside old one-shot FRZ-C4 write set — make J1-v4 direct-byte freeze stable on Windows without semantic code change and without changing the manifest.

## Exclusive write-set (CHI duoc sua)
- Repository root `.gitattributes`;
- Exactly the 13 files named by `output/s09/20260823_sprint_full/j1-c3/renderer_freeze_manifest_v4.json`;
- `output/s09/20260823_sprint_full/frz-c6/**`;
- One new session folder `docs/pm/sessions/S09-FRZ-C6-EOL-GUARD/**`.

Forbidden: all other `app/**` beyond the 13, all backend/frontend tests, fixtures, QA launchers, T03/T04/T06B files, MAIN/docs, migrations, S10/S11/S13.

Additional guards: MOTIONFORGE_DATABASE_URL UNSET with isolated basetemp — no shared DB. No global test/production server while Wave A writers active — file-local syntax only. Use unique temp/cache roots. No commit/push.

## Required (khong doi code semantics, khong doi manifest, chi EOL)
1. Verify truoc khi ghi: moi drift trong 7 file tren la EOL-only — CRLF -> LF cho ra manifest hash dung, khong co semantic/token/whitespace khac. Neu mismatch khong phai EOL -> BLOCKED_WITH_FINDINGS, khong normalize, khong sua manifest.
2. Tao `.gitattributes` voi path-specific attributes cho dung 13 file: 12 file co manifest bytes LF phai `text eol=lf`; `app/services/renderer_routes/composite.py` co manifest bytes CRLF phai `text eol=crlf`. Dung exact repo-relative paths, khong wildcard.
3. Restore exact on-disk bytes to manifest values — dung `python` ghi dung LF (hoac CRLF cho composite) truoc do da verify, khong doi token, whitespace ngoai EOL, BOM hay final-newline.
4. Run `git check-attr text eol` cho ca 13 files va direct SHA verification `hashlib.sha256(p.read_bytes()).hexdigest()` cho ca 13, so voi manifest. Luu per-file before/after table vao `output/s09/.../frz-c6/verify.md` va `docs/pm/sessions/S09-FRZ-C6-EOL-GUARD/verify.md`.

## Acceptance
- Manifest van `ae92247b...` unchanged (direct sha prefix `ae92247b`).
- 13/13 direct MATCH (khong dung LF-normalized fallback) — includes composite CRLF.
- Attributes pin dung EOL per file — `git check-attr` 12×lf + 1×crlf.
- `python -m py_compile` / import smoke PASS cho 13 files.
- Khong doi duong dan khac.

## Terminal
Ghi `TASK_SUBMITTED` phase `PREP / AWAITING_B1_JOIN` roi exit de Manager lam B1. Khong chay global test/production/Chromium, khong commit/push.

## Phases
- J0 preflight + EOL-only token/line diagnostic (see LOG sec 1)
- Write `.gitattributes` (13 exact paths, LF no BOM, 682 B)
- Normalize 7 drift files CRLF->LF via python write_bytes (size delta == CRLF count)
- Verify 13/13 direct + attributes + py_compile/import + manifest unchanged + guards
- Persist `output/.../frz-c6/verify.md` + `before_after_sha.json` + `git_check_attr.txt` and session copy `docs/pm/sessions/S09-FRZ-C6-EOL-GUARD/verify.md`
- Report TASK_SUBMITTED PREP / AWAITING_B1_JOIN — exit for Manager B1 join
