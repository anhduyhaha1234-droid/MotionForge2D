# S09-FRZ-C6 — verify — EOL exit hardening (J1 v4 byte-freeze)

- Session: S09-FRZ-C6-EOL-GUARD — meta reasoning max — worktree `C:/Users/Admin/MotionForge2D-worktrees/s08-integration` — branch `codex/s08-integration` — HEAD `ee10e55a809c84d5cb5d4a3046a1ee78828528d0`
- Time: 2026-08-27 15:01 UTC+07:00+07
- Manifest: `output/s09/20260823_sprint_full/j1-c3/renderer_freeze_manifest_v4.json` — version 4 — frozen_at 2026-08-25T23:15:00+07:00 — sha256 `ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5` (prefix `ae92247b8bfd...` — UNCHANGED, J1-v4 must remain unchanged)
- Rules: `C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md` 180 lines SHA256 `987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25` — RULES_LOADED
- Preflight: MOTIONFORGE_DATABASE_URL=UNSET — `.gitattributes` missing at start — 6/13 direct MATCH, 7 CRLF-only drifts confirmed EOL-only (token-identical) — J1-v4 unchanged — no shared DB, no global server, ports attribution below
- Owner: new session S09-FRZ-C6-EOL-GUARD — exclusive write-set only `.gitattributes` + exactly 13 manifest files + `output/.../frz-c6/**` + `docs/pm/sessions/S09-FRZ-C6-EOL-GUARD/**`

## 1. Preflight — EOL-only diagnostic (before any write)

All 7 drifts verified EOL-only before normalize: CRLF->LF gives manifest hash, token stream identical (tokenize string compare after stripping CR), line payloads identical after splitting on CRLF vs LF, no BOM, no lone CR.

| File | Expected (v4) | Before direct | Before normalized | direct==exp | norm==exp | CRLF? | BOM? | CRLF cnt | LF cnt |
|---|---|---|---|---|---|---|---|---|---|
| app/services/renderer_contract.py | 93329785f6bc8d753f46a08576136a62d82aa44c4db8f2939e0490a363bb28e4 | 61b31f4ce2f25cb7a1f6e2f3a54550149543c0f4f9810f9d63c6f8c05dc14db2 | 93329785f6bc8d753f46a08576136a62d82aa44c4db8f2939e0490a363bb28e4 | DIFF | MATCH | True | False | 889 | 0 |
| app/services/renderer_router.py | cdd0362fa5969d84342f7e4d8cfe6cd7d09c96aa14feb619a745b7ff2e18e7b8 | 8dafdc357c872e1de92671b15e15e72abfa86587a8327b611ed873885cf21830 | cdd0362fa5969d84342f7e4d8cfe6cd7d09c96aa14feb619a745b7ff2e18e7b8 | DIFF | MATCH | True | False | 372 | 0 |
| app/adapters/renderer/__init__.py | e750e07f302916994f172b3e9a61a89976b2460836ab3ec3c58b5a6f6da70e2e | e750e07f302916994f172b3e9a61a89976b2460836ab3ec3c58b5a6f6da70e2e | e750e07f302916994f172b3e9a61a89976b2460836ab3ec3c58b5a6f6da70e2e | MATCH | MATCH | False | False | 0 | 32 |
| app/adapters/renderer/benchmark_harness.py | 5d985a26d3b74b8ec8fb41def850d9b45e7a3d24b4a8b699a79a53bc60457d5f | 152b6d0cb579ec9ef42c1a9a2fc1ecc2ff09dfc912158cba42b96adce600699f | 5d985a26d3b74b8ec8fb41def850d9b45e7a3d24b4a8b699a79a53bc60457d5f | DIFF | MATCH | True | False | 177 | 0 |
| app/adapters/renderer/encode_base.py | 1c4e50a477c25983fa4d699f1bbba5ba4c6f8446af0c9d34bcdc2d66b25b88a3 | 847a757ac9e3491ca3795414d6bbdffb1c05e56c33ab0a192d40740403494286 | 1c4e50a477c25983fa4d699f1bbba5ba4c6f8446af0c9d34bcdc2d66b25b88a3 | DIFF | MATCH | True | False | 211 | 0 |
| app/adapters/renderer/ffmpeg_binary.py | 079a7425273ed5becf866d078a63673d3f36ae658b212bf61be25686f622df30 | 81b71bf9a60aac6400beda1de3e181d5c7a31e6887fa615185d383c2f80f33f7 | 079a7425273ed5becf866d078a63673d3f36ae658b212bf61be25686f622df30 | DIFF | MATCH | True | False | 104 | 0 |
| app/adapters/renderer/nvenc.py | 0ad930324732a4ea8af4cd60f0f05db52c1df280af7e162f517f6eb5b94e6dd4 | 0ad930324732a4ea8af4cd60f0f05db52c1df280af7e162f517f6eb5b94e6dd4 | 0ad930324732a4ea8af4cd60f0f05db52c1df280af7e162f517f6eb5b94e6dd4 | MATCH | MATCH | False | False | 0 | 102 |
| app/adapters/renderer/pose_swap_adapter.py | c409f2f1cc8e9eb7bf415b9f503b2ec1449b681923b2bfd6f9b600a6f8137634 | 4ca3dce7c611c6b3e9d0c91e82ce26fc90e969067f1b14b4fcf69706a2ef5041 | c409f2f1cc8e9eb7bf415b9f503b2ec1449b681923b2bfd6f9b600a6f8137634 | DIFF | MATCH | True | False | 221 | 0 |
| app/adapters/renderer/sprite_affine_adapter.py | 6b2712ad8a17077f707a60d038a36a6326399c4974c13cc4dd4139175b3bb749 | 4fc8b249481f6c81236785b6ce4e45e2733ad45b137ed0f08bcd535e1d581c22 | 6b2712ad8a17077f707a60d038a36a6326399c4974c13cc4dd4139175b3bb749 | DIFF | MATCH | True | False | 192 | 0 |
| app/services/renderer_routes/__init__.py | 9b3c7bee7ad8a47900eb9d6bd26c3077a27cdf8f3c18ecb2d6edf3a08c526891 | 9b3c7bee7ad8a47900eb9d6bd26c3077a27cdf8f3c18ecb2d6edf3a08c526891 | 9b3c7bee7ad8a47900eb9d6bd26c3077a27cdf8f3c18ecb2d6edf3a08c526891 | MATCH | MATCH | False | False | 0 | 86 |
| app/services/renderer_routes/adaptive_pose_swap.py | c00740cf0706d7c605d4b07d68e4308928d1cfadc85dd489007035739689a08c | c00740cf0706d7c605d4b07d68e4308928d1cfadc85dd489007035739689a08c | c00740cf0706d7c605d4b07d68e4308928d1cfadc85dd489007035739689a08c | MATCH | MATCH | False | False | 0 | 703 |
| app/services/renderer_routes/benchmark_results.py | 65d877263076ba1e1f95bf4a0332b9e1df6e9d4ae528f9461c3c610a406b11b5 | 65d877263076ba1e1f95bf4a0332b9e1df6e9d4ae528f9461c3c610a406b11b5 | 65d877263076ba1e1f95bf4a0332b9e1df6e9d4ae528f9461c3c610a406b11b5 | MATCH | MATCH | False | False | 0 | 302 |
| app/services/renderer_routes/composite.py | 3b419d8b6a76dcf618888997ed3cda004f11ccada667d42a63e5973aa3ee7184 | 3b419d8b6a76dcf618888997ed3cda004f11ccada667d42a63e5973aa3ee7184 | bbc9daa28c0053b8a61f0fc90b40c5c91919ad182183314ded6e04fe2ec17d8a | MATCH | DIFF | True | False | 695 | 0 |

- 7 drift files: direct DIFF / norm MATCH — exclusively CRLF on-disk (core.autocrlf) — EOL-only drift proven via `tokenize` + line-split check — no semantic/token/whitespace delta beyond CR — BLOCKED_WITH_FINDINGS not triggered.
- 5 frozen-LF files: direct MATCH / norm MATCH — untouched LF.
- `app/services/renderer_routes/composite.py`: direct MATCH with CRLF hash `3b419d8b6a76...` — norm DIFF — manifest bytes are CRLF — must remain CRLF via `.gitattributes text eol=crlf`.

## 2. .gitattributes (path-specific, exact repo-relative, no wildcard)

Created at repository root `.gitattributes` — 13 lines — UTF-8 no BOM LF only — pins exact EOL per manifest bytes:

```
app/services/renderer_contract.py text eol=lf
app/services/renderer_router.py text eol=lf
app/adapters/renderer/__init__.py text eol=lf
app/adapters/renderer/benchmark_harness.py text eol=lf
app/adapters/renderer/encode_base.py text eol=lf
app/adapters/renderer/ffmpeg_binary.py text eol=lf
app/adapters/renderer/nvenc.py text eol=lf
app/adapters/renderer/pose_swap_adapter.py text eol=lf
app/adapters/renderer/sprite_affine_adapter.py text eol=lf
app/services/renderer_routes/__init__.py text eol=lf
app/services/renderer_routes/adaptive_pose_swap.py text eol=lf
app/services/renderer_routes/benchmark_results.py text eol=lf
app/services/renderer_routes/composite.py text eol=crlf
```

- 12 files with manifest LF bytes -> `text eol=lf`
- 1 file (`composite.py`) with manifest CRLF bytes -> `text eol=crlf`
- No wildcard, no extra lines for other paths.

### git check-attr text eol (all 13)

```
app/services/renderer_contract.py: text: set
app/services/renderer_contract.py: eol: lf
app/services/renderer_router.py: text: set
app/services/renderer_router.py: eol: lf
app/adapters/renderer/__init__.py: text: set
app/adapters/renderer/__init__.py: eol: lf
app/adapters/renderer/benchmark_harness.py: text: set
app/adapters/renderer/benchmark_harness.py: eol: lf
app/adapters/renderer/encode_base.py: text: set
app/adapters/renderer/encode_base.py: eol: lf
app/adapters/renderer/ffmpeg_binary.py: text: set
app/adapters/renderer/ffmpeg_binary.py: eol: lf
app/adapters/renderer/nvenc.py: text: set
app/adapters/renderer/nvenc.py: eol: lf
app/adapters/renderer/pose_swap_adapter.py: text: set
app/adapters/renderer/pose_swap_adapter.py: eol: lf
app/adapters/renderer/sprite_affine_adapter.py: text: set
app/adapters/renderer/sprite_affine_adapter.py: eol: lf
app/services/renderer_routes/__init__.py: text: set
app/services/renderer_routes/__init__.py: eol: lf
app/services/renderer_routes/adaptive_pose_swap.py: text: set
app/services/renderer_routes/adaptive_pose_swap.py: eol: lf
app/services/renderer_routes/benchmark_results.py: text: set
app/services/renderer_routes/benchmark_results.py: eol: lf
app/services/renderer_routes/composite.py: text: set
app/services/renderer_routes/composite.py: eol: crlf
```

- All 13 return `text: set` + expected `eol` (12x lf, 1x crlf) — attributes pinned correctly.

## 3. Restore exact on-disk bytes to manifest values (EOL-only)

Method: `python` read raw bytes -> verify normalized hash == expected (else BLOCKED) -> `raw.replace(b"\r\n", b"\n")` -> `write_bytes` UTF-8 no BOM — preserves token, whitespace outside EOL, final-newline; only CR stripped. No manifest edit, no code semantics change.

Applied to exactly 7 drift files; 6 already-matching files untouched.

Size delta == CRLF count per file (one CR per line):

- renderer_contract: 36993 -> 36104 (-889)
- renderer_router: 15992 -> 15620 (-372)
- benchmark_harness: 6499 -> 6322 (-177)
- encode_base: 7876 -> 7665 (-211)
- ffmpeg_binary: 3528 -> 3424 (-104)
- pose_swap: 8271 -> 8050 (-221)
- sprite_affine: 7169 -> 6977 (-192)

## 4. After — direct SHA verification (13/13 direct MATCH, no LF-normalized fallback)

`hashlib.sha256(p.read_bytes()).hexdigest()` compared directly to manifest — all 13 MUST be `MATCH`:

| File | Expected (v4) | After direct | After normalized | direct==exp | norm==exp | CRLF? |
|---|---|---|---|---|---|---|
| app/services/renderer_contract.py | 93329785f6bc8d753f46a08576136a62d82aa44c4db8f2939e0490a363bb28e4 | 93329785f6bc8d753f46a08576136a62d82aa44c4db8f2939e0490a363bb28e4 | 93329785f6bc8d753f46a08576136a62d82aa44c4db8f2939e0490a363bb28e4 | MATCH | MATCH | False |
| app/services/renderer_router.py | cdd0362fa5969d84342f7e4d8cfe6cd7d09c96aa14feb619a745b7ff2e18e7b8 | cdd0362fa5969d84342f7e4d8cfe6cd7d09c96aa14feb619a745b7ff2e18e7b8 | cdd0362fa5969d84342f7e4d8cfe6cd7d09c96aa14feb619a745b7ff2e18e7b8 | MATCH | MATCH | False |
| app/adapters/renderer/__init__.py | e750e07f302916994f172b3e9a61a89976b2460836ab3ec3c58b5a6f6da70e2e | e750e07f302916994f172b3e9a61a89976b2460836ab3ec3c58b5a6f6da70e2e | e750e07f302916994f172b3e9a61a89976b2460836ab3ec3c58b5a6f6da70e2e | MATCH | MATCH | False |
| app/adapters/renderer/benchmark_harness.py | 5d985a26d3b74b8ec8fb41def850d9b45e7a3d24b4a8b699a79a53bc60457d5f | 5d985a26d3b74b8ec8fb41def850d9b45e7a3d24b4a8b699a79a53bc60457d5f | 5d985a26d3b74b8ec8fb41def850d9b45e7a3d24b4a8b699a79a53bc60457d5f | MATCH | MATCH | False |
| app/adapters/renderer/encode_base.py | 1c4e50a477c25983fa4d699f1bbba5ba4c6f8446af0c9d34bcdc2d66b25b88a3 | 1c4e50a477c25983fa4d699f1bbba5ba4c6f8446af0c9d34bcdc2d66b25b88a3 | 1c4e50a477c25983fa4d699f1bbba5ba4c6f8446af0c9d34bcdc2d66b25b88a3 | MATCH | MATCH | False |
| app/adapters/renderer/ffmpeg_binary.py | 079a7425273ed5becf866d078a63673d3f36ae658b212bf61be25686f622df30 | 079a7425273ed5becf866d078a63673d3f36ae658b212bf61be25686f622df30 | 079a7425273ed5becf866d078a63673d3f36ae658b212bf61be25686f622df30 | MATCH | MATCH | False |
| app/adapters/renderer/nvenc.py | 0ad930324732a4ea8af4cd60f0f05db52c1df280af7e162f517f6eb5b94e6dd4 | 0ad930324732a4ea8af4cd60f0f05db52c1df280af7e162f517f6eb5b94e6dd4 | 0ad930324732a4ea8af4cd60f0f05db52c1df280af7e162f517f6eb5b94e6dd4 | MATCH | MATCH | False |
| app/adapters/renderer/pose_swap_adapter.py | c409f2f1cc8e9eb7bf415b9f503b2ec1449b681923b2bfd6f9b600a6f8137634 | c409f2f1cc8e9eb7bf415b9f503b2ec1449b681923b2bfd6f9b600a6f8137634 | c409f2f1cc8e9eb7bf415b9f503b2ec1449b681923b2bfd6f9b600a6f8137634 | MATCH | MATCH | False |
| app/adapters/renderer/sprite_affine_adapter.py | 6b2712ad8a17077f707a60d038a36a6326399c4974c13cc4dd4139175b3bb749 | 6b2712ad8a17077f707a60d038a36a6326399c4974c13cc4dd4139175b3bb749 | 6b2712ad8a17077f707a60d038a36a6326399c4974c13cc4dd4139175b3bb749 | MATCH | MATCH | False |
| app/services/renderer_routes/__init__.py | 9b3c7bee7ad8a47900eb9d6bd26c3077a27cdf8f3c18ecb2d6edf3a08c526891 | 9b3c7bee7ad8a47900eb9d6bd26c3077a27cdf8f3c18ecb2d6edf3a08c526891 | 9b3c7bee7ad8a47900eb9d6bd26c3077a27cdf8f3c18ecb2d6edf3a08c526891 | MATCH | MATCH | False |
| app/services/renderer_routes/adaptive_pose_swap.py | c00740cf0706d7c605d4b07d68e4308928d1cfadc85dd489007035739689a08c | c00740cf0706d7c605d4b07d68e4308928d1cfadc85dd489007035739689a08c | c00740cf0706d7c605d4b07d68e4308928d1cfadc85dd489007035739689a08c | MATCH | MATCH | False |
| app/services/renderer_routes/benchmark_results.py | 65d877263076ba1e1f95bf4a0332b9e1df6e9d4ae528f9461c3c610a406b11b5 | 65d877263076ba1e1f95bf4a0332b9e1df6e9d4ae528f9461c3c610a406b11b5 | 65d877263076ba1e1f95bf4a0332b9e1df6e9d4ae528f9461c3c610a406b11b5 | MATCH | MATCH | False |
| app/services/renderer_routes/composite.py | 3b419d8b6a76dcf618888997ed3cda004f11ccada667d42a63e5973aa3ee7184 | 3b419d8b6a76dcf618888997ed3cda004f11ccada667d42a63e5973aa3ee7184 | bbc9daa28c0053b8a61f0fc90b40c5c91919ad182183314ded6e04fe2ec17d8a | MATCH | DIFF | True |

- 13/13 direct MATCH — proof uses direct bytes only (no normalized fallback). For composite.py the normalized is intentionally DIFF (manifest is CRLF).
- Manifest file sha256 still `ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5` — prefix `ae92247b` unchanged — manifest not modified.

## 5. py_compile / import smoke (13 files)

```
python -m py_compile app/services/renderer_contract.py ... app/services/renderer_routes/composite.py  -> PASS
import app.services.renderer_contract, app.services.renderer_router, app.adapters.renderer.* -> PASS
```

- 13 files py_compile PASS, no SyntaxError after EOL conversion.
- Import smoke for renderer_contract/router and all 5 renderer adapters PASS.

## 6. Guards

- MOTIONFORGE_DATABASE_URL=UNSET (verified via env — no DATABASE_URL/MOTIONFORGE_* set) — isolated basetemp per run — no shared DB.
- No global test/production server while Wave A writers active — not executed (per task: no global test/production/Chromium).
- Ports attribution: checked `netstat` — no dev server claimed for this task — task used no ports.
- Forbidden write-set: not modified — no `app/**` beyond the 13 manifest files, no backend/frontend tests, no fixtures, no QA launchers, no T03/T04/T06B files, no MAIN/docs, no migrations, no S10/S11/S13.
- git status shows pre-existing sprint diffs plus `.gitattributes` (untracked) and the 7 normalized files — no extra paths outside allowlist introduced by C6 beyond `frz-c6/**` and `docs/pm/sessions/S09-FRZ-C6-EOL-GUARD/**`.
- No commit/push performed.

## 7. Artifacts

- `output/s09/20260823_sprint_full/frz-c6/verify.md` (this file)
- `output/s09/20260823_sprint_full/frz-c6/before_after_sha.json` + `git_check_attr.txt`
- `docs/pm/sessions/S09-FRZ-C6-EOL-GUARD/verify.md` (copy)
- `docs/pm/sessions/S09-FRZ-C6-EOL-GUARD/TASK.md` / `LOG.md` / `REPORT.md`
- `.gitattributes` (13 lines, LF, no BOM)

## 8. Status

**TASK_SUBMITTED — phase PREP / AWAITING_B1_JOIN** — Manager to perform B1 verification (re-check 13/13 direct, attributes, manifest unchanged, no forbidden writes) before integrating.

— S09-FRZ-C6-EOL-GUARD owner, 2026-08-27 15:01 UTC+07:00+07
