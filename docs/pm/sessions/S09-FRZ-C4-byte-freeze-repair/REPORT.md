# S09-FRZ-C4 — REPORT — Byte-freeze repair (newline normalization ONLY)

- Worker: S09-FRZ-C4 meta @ 9Router, HEAD ee10e55a809c84d5cb5d4a3046a1ee78828528d0
- Manifest v4 frozen_at 2026-08-25T23:15:00+07:00
- Da khoi phuc 7 file ve LF UTF-8 no BOM, giu nguyen code va final-newline; 13/13 direct MATCH.

## Bang before

| File | Expected (v4) | Before direct | Before normalized | direct==exp | norm==exp | CRLF? | BOM? |
|---|---|---|---|---|---|---|---|
| app/services/renderer_contract.py | 93329785f6bc8d753f46a08576136a62d82aa44c4db8f2939e0490a363bb28e4 | 61b31f4ce2f25cb7a1f6e2f3a54550149543c0f4f9810f9d63c6f8c05dc14db2 | 93329785f6bc8d753f46a08576136a62d82aa44c4db8f2939e0490a363bb28e4 | DIFF | MATCH | True | False |
| app/services/renderer_router.py | cdd0362fa5969d84342f7e4d8cfe6cd7d09c96aa14feb619a745b7ff2e18e7b8 | 8dafdc357c872e1de92671b15e15e72abfa86587a8327b611ed873885cf21830 | cdd0362fa5969d84342f7e4d8cfe6cd7d09c96aa14feb619a745b7ff2e18e7b8 | DIFF | MATCH | True | False |
| app/adapters/renderer/__init__.py | e750e07f302916994f172b3e9a61a89976b2460836ab3ec3c58b5a6f6da70e2e | e750e07f302916994f172b3e9a61a89976b2460836ab3ec3c58b5a6f6da70e2e | e750e07f302916994f172b3e9a61a89976b2460836ab3ec3c58b5a6f6da70e2e | MATCH | MATCH | False | False |
| app/adapters/renderer/benchmark_harness.py | 5d985a26d3b74b8ec8fb41def850d9b45e7a3d24b4a8b699a79a53bc60457d5f | 152b6d0cb579ec9ef42c1a9a2fc1ecc2ff09dfc912158cba42b96adce600699f | 5d985a26d3b74b8ec8fb41def850d9b45e7a3d24b4a8b699a79a53bc60457d5f | DIFF | MATCH | True | False |
| app/adapters/renderer/encode_base.py | 1c4e50a477c25983fa4d699f1bbba5ba4c6f8446af0c9d34bcdc2d66b25b88a3 | 847a757ac9e3491ca3795414d6bbdffb1c05e56c33ab0a192d40740403494286 | 1c4e50a477c25983fa4d699f1bbba5ba4c6f8446af0c9d34bcdc2d66b25b88a3 | DIFF | MATCH | True | False |
| app/adapters/renderer/ffmpeg_binary.py | 079a7425273ed5becf866d078a63673d3f36ae658b212bf61be25686f622df30 | 81b71bf9a60aac6400beda1de3e181d5c7a31e6887fa615185d383c2f80f33f7 | 079a7425273ed5becf866d078a63673d3f36ae658b212bf61be25686f622df30 | DIFF | MATCH | True | False |
| app/adapters/renderer/nvenc.py | 0ad930324732a4ea8af4cd60f0f05db52c1df280af7e162f517f6eb5b94e6dd4 | 0ad930324732a4ea8af4cd60f0f05db52c1df280af7e162f517f6eb5b94e6dd4 | 0ad930324732a4ea8af4cd60f0f05db52c1df280af7e162f517f6eb5b94e6dd4 | MATCH | MATCH | False | False |
| app/adapters/renderer/pose_swap_adapter.py | c409f2f1cc8e9eb7bf415b9f503b2ec1449b681923b2bfd6f9b600a6f8137634 | 4ca3dce7c611c6b3e9d0c91e82ce26fc90e969067f1b14b4fcf69706a2ef5041 | c409f2f1cc8e9eb7bf415b9f503b2ec1449b681923b2bfd6f9b600a6f8137634 | DIFF | MATCH | True | False |
| app/adapters/renderer/sprite_affine_adapter.py | 6b2712ad8a17077f707a60d038a36a6326399c4974c13cc4dd4139175b3bb749 | 4fc8b249481f6c81236785b6ce4e45e2733ad45b137ed0f08bcd535e1d581c22 | 6b2712ad8a17077f707a60d038a36a6326399c4974c13cc4dd4139175b3bb749 | DIFF | MATCH | True | False |
| app/services/renderer_routes/__init__.py | 9b3c7bee7ad8a47900eb9d6bd26c3077a27cdf8f3c18ecb2d6edf3a08c526891 | 9b3c7bee7ad8a47900eb9d6bd26c3077a27cdf8f3c18ecb2d6edf3a08c526891 | 9b3c7bee7ad8a47900eb9d6bd26c3077a27cdf8f3c18ecb2d6edf3a08c526891 | MATCH | MATCH | False | False |
| app/services/renderer_routes/adaptive_pose_swap.py | c00740cf0706d7c605d4b07d68e4308928d1cfadc85dd489007035739689a08c | c00740cf0706d7c605d4b07d68e4308928d1cfadc85dd489007035739689a08c | c00740cf0706d7c605d4b07d68e4308928d1cfadc85dd489007035739689a08c | MATCH | MATCH | False | False |
| app/services/renderer_routes/benchmark_results.py | 65d877263076ba1e1f95bf4a0332b9e1df6e9d4ae528f9461c3c610a406b11b5 | 65d877263076ba1e1f95bf4a0332b9e1df6e9d4ae528f9461c3c610a406b11b5 | 65d877263076ba1e1f95bf4a0332b9e1df6e9d4ae528f9461c3c610a406b11b5 | MATCH | MATCH | False | False |
| app/services/renderer_routes/composite.py | 3b419d8b6a76dcf618888997ed3cda004f11ccada667d42a63e5973aa3ee7184 | 3b419d8b6a76dcf618888997ed3cda004f11ccada667d42a63e5973aa3ee7184 | bbc9daa28c0053b8a61f0fc90b40c5c91919ad182183314ded6e04fe2ec17d8a | MATCH | DIFF | True | False |

## Assert truoc ghi 7 file

7 file norm == expected PASS.

## Thao tac ghi

CRLF->LF duy nhat, do dai giam dung so CRLF (contract -889, router -372, benchmark -177, encode -211, ffmpeg -104, pose_swap -221, sprite -192).

## Bang after

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

13/13 direct MATCH verified tren disk.

## Gate

| Gate | Ket qua |
|---|---|
| git diff --check | exit 0, chi warning autocrlf |
| py_compile 7 file | PASS |
| import smoke | PASS renderer_contract/router |
| full tests | SKIP |

## Write-set audit

Sua dung 7 file allowlist, khong dung forbidden. composite.py de CRLF theo v4 (forbidden) — neu chuan hoa se gay DIFF.

## Trang thai

STATUS: TASK_SUBMITTED (S09-FRZ-C4)
PROCESS exit 0 — 13/13 direct MATCH.
