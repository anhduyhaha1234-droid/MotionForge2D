# S09-FRZ-C6-EOL-GUARD — REPORT — EOL exit hardening (J1 v4 byte-freeze)

- Worker: S09-FRZ-C6-EOL-GUARD — new session — meta reasoning max TTFB 900 fallback OFF — `C:/Users/Admin/MotionForge2D-worktrees/s08-integration` branch `codex/s08-integration` HEAD `ee10e55a809c84d5cb5d4a3046a1ee78828528d0`
- Time: 2026-08-27 14:36-15:12 +07 — Rules `C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md` 180 lines SHA256 `987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25` — RULES_LOADED
- Manifest: `output/s09/20260823_sprint_full/j1-c3/renderer_freeze_manifest_v4.json` version 4 — frozen_at 2026-08-25T23:15:00+07:00 — head `ee10e55a809c84d5cb5d4a3046a1ee78828528d0` — sha256 `ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5` — UNCHANGED (J1-v4 must remain unchanged)

## Bang before (at J0, before any write — exact bytes on disk)

| File | Expected (v4) | Before direct | Before normalized | direct==exp | norm==exp | CRLF? | BOM? | CRLF cnt |
|---|---|---|---|---|---|---|---|---|
| app/services/renderer_contract.py | 93329785f6bc8d753f46a08576136a62d82aa44c4db8f2939e0490a363bb28e4 | 61b31f4ce2f25cb7a1f6e2f3a54550149543c0f4f9810f9d63c6f8c05dc14db2 | 93329785f6bc8d753f46a08576136a62d82aa44c4db8f2939e0490a363bb28e4 | DIFF | MATCH | True | False | 889 |
| app/services/renderer_router.py | cdd0362fa5969d84342f7e4d8cfe6cd7d09c96aa14feb619a745b7ff2e18e7b8 | 8dafdc357c872e1de92671b15e15e72abfa86587a8327b611ed873885cf21830 | cdd0362fa5969d84342f7e4d8cfe6cd7d09c96aa14feb619a745b7ff2e18e7b8 | DIFF | MATCH | True | False | 372 |
| app/adapters/renderer/__init__.py | e750e07f302916994f172b3e9a61a89976b2460836ab3ec3c58b5a6f6da70e2e | e750e07f302916994f172b3e9a61a89976b2460836ab3ec3c58b5a6f6da70e2e | e750e07f302916994f172b3e9a61a89976b2460836ab3ec3c58b5a6f6da70e2e | MATCH | MATCH | False | False | 0 |
| app/adapters/renderer/benchmark_harness.py | 5d985a26d3b74b8ec8fb41def850d9b45e7a3d24b4a8b699a79a53bc60457d5f | 152b6d0cb579ec9ef42c1a9a2fc1ecc2ff09dfc912158cba42b96adce600699f | 5d985a26d3b74b8ec8fb41def850d9b45e7a3d24b4a8b699a79a53bc60457d5f | DIFF | MATCH | True | False | 177 |
| app/adapters/renderer/encode_base.py | 1c4e50a477c25983fa4d699f1bbba5ba4c6f8446af0c9d34bcdc2d66b25b88a3 | 847a757ac9e3491ca3795414d6bbdffb1c05e56c33ab0a192d40740403494286 | 1c4e50a477c25983fa4d699f1bbba5ba4c6f8446af0c9d34bcdc2d66b25b88a3 | DIFF | MATCH | True | False | 211 |
| app/adapters/renderer/ffmpeg_binary.py | 079a7425273ed5becf866d078a63673d3f36ae658b212bf61be25686f622df30 | 81b71bf9a60aac6400beda1de3e181d5c7a31e6887fa615185d383c2f80f33f7 | 079a7425273ed5becf866d078a63673d3f36ae658b212bf61be25686f622df30 | DIFF | MATCH | True | False | 104 |
| app/adapters/renderer/nvenc.py | 0ad930324732a4ea8af4cd60f0f05db52c1df280af7e162f517f6eb5b94e6dd4 | 0ad930324732a4ea8af4cd60f0f05db52c1df280af7e162f517f6eb5b94e6dd4 | 0ad930324732a4ea8af4cd60f0f05db52c1df280af7e162f517f6eb5b94e6dd4 | MATCH | MATCH | False | False | 0 |
| app/adapters/renderer/pose_swap_adapter.py | c409f2f1cc8e9eb7bf415b9f503b2ec1449b681923b2bfd6f9b600a6f8137634 | 4ca3dce7c611c6b3e9d0c91e82ce26fc90e969067f1b14b4fcf69706a2ef5041 | c409f2f1cc8e9eb7bf415b9f503b2ec1449b681923b2bfd6f9b600a6f8137634 | DIFF | MATCH | True | False | 221 |
| app/adapters/renderer/sprite_affine_adapter.py | 6b2712ad8a17077f707a60d038a36a6326399c4974c13cc4dd4139175b3bb749 | 4fc8b249481f6c81236785b6ce4e45e2733ad45b137ed0f08bcd535e1d581c22 | 6b2712ad8a17077f707a60d038a36a6326399c4974c13cc4dd4139175b3bb749 | DIFF | MATCH | True | False | 192 |
| app/services/renderer_routes/__init__.py | 9b3c7bee7ad8a47900eb9d6bd26c3077a27cdf8f3c18ecb2d6edf3a08c526891 | 9b3c7bee7ad8a47900eb9d6bd26c3077a27cdf8f3c18ecb2d6edf3a08c526891 | 9b3c7bee7ad8a47900eb9d6bd26c3077a27cdf8f3c18ecb2d6edf3a08c526891 | MATCH | MATCH | False | False | 0 |
| app/services/renderer_routes/adaptive_pose_swap.py | c00740cf0706d7c605d4b07d68e4308928d1cfadc85dd489007035739689a08c | c00740cf0706d7c605d4b07d68e4308928d1cfadc85dd489007035739689a08c | c00740cf0706d7c605d4b07d68e4308928d1cfadc85dd489007035739689a08c | MATCH | MATCH | False | False | 0 |
| app/services/renderer_routes/benchmark_results.py | 65d877263076ba1e1f95bf4a0332b9e1df6e9d4ae528f9461c3c610a406b11b5 | 65d877263076ba1e1f95bf4a0332b9e1df6e9d4ae528f9461c3c610a406b11b5 | 65d877263076ba1e1f95bf4a0332b9e1df6e9d4ae528f9461c3c610a406b11b5 | MATCH | MATCH | False | False | 0 |
| app/services/renderer_routes/composite.py | 3b419d8b6a76dcf618888997ed3cda004f11ccada667d42a63e5973aa3ee7184 | 3b419d8b6a76dcf618888997ed3cda004f11ccada667d42a63e5973aa3ee7184 | bbc9daa28c0053b8a61f0fc90b40c5c91919ad182183314ded6e04fe2ec17d8a | MATCH | DIFF | True | False | 695 |

- 7 drift files: direct DIFF / norm MATCH — exclusively CRLF — proven EOL-only via `tokenize` + line-split payload identity — no BOM, no lone CR — safe to normalize CRLF->LF.
- 5 frozen LF files: direct MATCH — untouched.
- `composite.py`: direct MATCH with CRLF hash — norm DIFF — manifest bytes are CRLF — must stay CRLF.

## Assert truoc ghi 7 file

For each of the 7: `hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest() == expected` PASS — else would have been `BLOCKED_WITH_FINDINGS` without write. All 7 PASS.

## Thao tac ghi

- 7 files written via `python` `write_bytes(raw.replace(b"\r\n", b"\n"))` UTF-8 no BOM — preserves final-newline — verified `b"\r\n" not in` after.
- Size delta == CRLF count (one CR stripped per line): contract -889, router -372, benchmark -177, encode -211, ffmpeg -104, pose_swap -221, sprite -192.

## Bang after (direct SHA verification — 13/13 direct MATCH, no normalized fallback)

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

13/13 direct MATCH verified on disk via `hashlib.sha256(p.read_bytes()).hexdigest()` — no normalized fallback.

## .gitattributes

Created at repo root — 13 exact repo-relative paths — no wildcard — UTF-8 no BOM LF only — 682 B:

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

`git check-attr text eol` for all 13 — 12× `eol: lf` + `composite eol: crlf` — all `text: set` — full output persisted in `frz-c6/git_check_attr.txt` and `verify.md` (§2).

Note: transient wildcard overwrite (~15:01) remediated — logged in LOG.md §2 — final file is correct 13-line form above.

## Gate

| Gate | Result |
|---|---|
| Manifest sha256 still `ae92247b8bfd...` | PASS — `ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5` |
| 13/13 direct SHA vs manifest | PASS — direct only, no normalized fallback |
| `git check-attr text eol` 13 | PASS — 12 lf + 1 crlf pinned |
| `python -m py_compile` 13 files | PASS |
| import smoke 10 modules | PASS — renderer_contract/router + 5 adapters + 3 routes |
| MOTIONFORGE_DATABASE_URL UNSET | PASS — isolated basetemp, no shared DB |
| No global test/production/Chromium | PASS — not executed per task scope |
| Forbidden write-set | PASS — no `app/**` beyond the 13, no tests/fixtures/QA/T03/T04/T06B, no MAIN/docs/migrations — details in LOG §5 |
| No commit/push | PASS |
| Ports attribution | Clean — no C6 dev server — netstat no owned ports |

## Write-set audit

Modified only allowlist: `.gitattributes` + 7 of the 13 (EOL-only). Correctly NOT modified: 6 already-matching manifest files (including composite CRLF — altering it to LF would have broken its direct hash `3b419d8b`). No other paths introduced by C6 beyond `output/.../frz-c6/**` and `docs/pm/sessions/S09-FRZ-C6-EOL-GUARD/**`. Pre-existing sprint dirty outside allowlist retained per guards — not C6-introduced.

## Evidence

- `output/s09/20260823_sprint_full/frz-c6/verify.md` (and session copy `docs/pm/sessions/S09-FRZ-C6-EOL-GUARD/verify.md`) — per-file before/after tables, git check-attr, size deltas, guards
- `output/s09/20260823_sprint_full/frz-c6/before_after_sha.json` — machine-readable before/after SHAs
- `output/s09/20260823_sprint_full/frz-c6/git_check_attr.txt` — live `git check-attr` output
- `.gitattributes` (682 B, LF no BOM) — live on disk + in verify.md

## Status

**TASK_SUBMITTED — phase PREP / AWAITING_B1_JOIN** — exit for Manager B1 (all acceptance met: manifest unchanged ae92247b..., 13/13 direct, attributes pinned, py_compile/import PASS, no forbidden writes — awaiting barrier B1 verification before integration).

— S09-FRZ-C6-EOL-GUARD owner — 2026-08-27 15:12 +07
