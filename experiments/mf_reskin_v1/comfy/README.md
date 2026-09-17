# MF ComfyUI stage adapter (MF-V1-COMFY)

Isolated execution adapter for a **local, loopback-only** ComfyUI server.

```
mf_comfy/
  transport.py   HTTP + WebSocket to 127.0.0.1 only; version-aware capabilities
  adapter.py     ComfyStageAdapter: preflight -> submit -> queue/history/ws -> validate -> contract
  pinning.py     workflow hash, node-inventory hash, model file hashes
  paths.py       StagePaths: every artifact must resolve inside the stage root
  lease.py       exclusive instance lease (+ instance epoch for restart detection)
  gpugate.py     one heavy GPU stage at a time (cross-process byte lock)
  contract.py    StageInput/StageOutput + COMFY_STAGE_CONTRACT.json builder
  resources.py   measured peak VRAM/RAM sampling
  errors.py      22 typed failures, all with stable `code`
workflows/mf_light_sdxl_v1.json   pinned workflow (API format)
tests/           28 adapter (fake transport) + 31 unit + 9 real-server
```

## Guarantees

1. **One submission per attempt.** A second submission raises
   `MF_COMFY_BLIND_RESUBMIT_REFUSED`. There is no retry of a prompt anywhere.
2. **Timeout after submit is ambiguous.** Reconciliation uses `/queue`, `/history/{id}` and
   the instance epoch: still queued ⇒ `unresolved`; epoch gone ⇒
   `MF_COMFY_SERVER_EPOCH_CHANGED`; otherwise `MF_COMFY_AMBIGUOUS_AFTER_SUBMIT`. Never a
   second submit.
3. **WebSocket is progress-only.** A dropped socket is reconnected and is neither failure
   nor completion. `/history/{prompt_id}` is the completion authority.
4. **Artifacts are not trusted.** They are re-materialised inside the stage root, hashed
   there, fully decoded, and rejected if `.partial`, zero-byte, undecodable, of the wrong
   server type, hash-mismatched, or path-escaping.
5. **`/interrupt` needs the lease.** The exclusive instance lease must be held for *that*
   prompt_id with a live instance epoch and live holder pid, otherwise
   `MF_COMFY_LEASE_NOT_HELD` and **no HTTP call is made**.
6. **One heavy GPU stage at a time** via a cross-process lock; a contender gets
   `MF_COMFY_GPU_STAGE_BUSY` instead of a second model on the card.
7. **The graph is never edited.** FPS/duration/resolution are caller-owned; an OOM is
   reported, never masked by shrinking the job.

## Run

```bash
VP=runtime/comfy/venv/Scripts/python.exe
$VP tools/serve_comfy.py --port 8199          # loopback only, writes instance_epoch.json
$VP -m pytest tests/ -q                       # real-server tests skip if the server is down
```

## Stop (required — the wave allows one heavy GPU stage at a time)

Never leave this server holding VRAM after a proof: the card is 12,227 MiB and an idle
server still holds ~7.4 GiB. Shutdown is a task-local tool — never `killall`/`pkill`
(this machine runs Hermes on Python):

```bash
python EV/COMFY/tools/stop_comfy.py           # identity-checked: epoch pid + matching
                                              # launcher ancestors, leaf -> root, no /T
```

It proves the target's identity from `runtime/comfy/instance_epoch.json`, posts ComfyUI's
own `/free {"unload_models": true, "free_memory": true}`, stops the verified pids one at a
time, and writes `EV/COMFY/raw/comfy_shutdown.json` with argv, cwd, before/after
`nvidia-smi` readings and the closed-port proof. A repeat run is harmless
(`ALREADY_STOPPED`) and never overwrites that evidence. Measured (continuation-01): VRAM
7,490 → 862 → 623 MiB of 12,227 MiB, port `8199` closed, zero python processes outside
this task's own chain touched. Full steps: `EV/COMFY/DOWNLOAD_MANIFEST.md` §F.

Adapter states are `submitted → queued → generated → validated`, plus `unresolved` and
`failed`. `accepted`/`published` belong to MotionForge — the adapter never emits them.

Fake-transport tests prove the adapter's contract only; engine proof requires a real run
against the real server (see `EV/COMFY/REPORT.md` §3).
