
# S11-T01-BA-PREFLIGHT — LOG (append-only)

## 2026-08-21T01:57:00+07:00 / 2026-08-20T18:57:00Z — RECOVERY (502 → resume same session)
- Cause: 9Router HTTP 502 connect timeout (transient; not model mismatch). Also one resume attempt failed
  due to CLI syntax (`hermes --resume <id> --max-turns` invalid) — corrected to `hermes chat --resume`.
- Session: 20260821_011356_05c03e resumed correctly (proc_aa429b59bb3b, PID 10292), muse, ocg/muse-spark-1.2-contributor, reasoning max.
- No writes yet at first failure (read-only lane anyway).
