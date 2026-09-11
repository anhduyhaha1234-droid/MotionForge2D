# S12-LC3-QA R1 — public chain map

Status: `BLOCKED_EXTERNAL_AUTHORITY_FIXTURE` (evidence-only; no row or sprint
approval). This map records one bounded run of the public boundary probe on
candidate `91bf577a2706a3351f7a72f9142fbd7b9c5671c3`.

Raw evidence: [q1-r1-public-legacy-worker-authority-final.json](evidence/q1-r1-public-legacy-worker-authority-final.json), with the exact command, stdout, stderr, and exit files sharing that basename. Runtime/database was isolated at
`C:\Users\Admin\mfqa\s12-lc3-r1\20260910T103100Z\QA\`; the probe reports
`manual_sql_used: false`. Alembic migration was the only database bootstrap;
acceptance authority/readiness/completion was never inserted by SQL or ORM.

## Observed identity and state chain

| Step | Public method and route | Identity returned/used | Observed state and mutation count |
|---|---|---|---|
| 1 | `POST /api/v2/projects` with `{"name":"S12-LC3-Q1-public-probe"}` | `project_id=a138aae0-e47f-486e-8977-3fc9b0e5c6f2` | `201`, server-owned durable project; counts `projects=1, video_items=0, artifacts=0, jobs=0, s12_export_runs=0` |
| 2 | `POST /api/v2/projects/{uuid}/videos` with title | `video_item_id=626fa321-eb04-4409-b5d4-f7be7ec634d3` | `201`, status `imported`, `source_artifact_id=null`; counts `projects=1, video_items=1, artifacts=0, jobs=0, s12_export_runs=0` |
| 3 | ffmpeg-generated real fixture, `32x32`, 10 fps, 1 second | `upload-fixture.mp4` under the isolated QA root | Decodable MP4; no user/demo asset |
| 4 | `POST /api/projects` with legacy name | `project_id=eb7ae227ca22` (12-hex from `ProjectWorkflowService.create_project`) | `201`; legacy filesystem project created; durable counts unchanged from step 2 |
| 5 | `POST /api/projects/eb7ae227ca22/video` multipart upload | server filename `source_*.mp4` | `200`; real upload published under server-owned name; durable counts unchanged |
| 6 | `POST /api/projects/eb7ae227ca22/analyze` with generation `1` | `video_item_id=ac93d720-122c-41ad-8fad-d48cf4d594f5`, import job `3937a4f3-ef07-4206-a965-f4de6414d5ca` | `200`; public legacy analyze created the durable shell and import chain |
| 7 | bounded `GET /api/projects/eb7ae227ca22/analyze?generation=1` reads, max 10 seconds | source artifact `7087b85b-050f-52bd-b521-6f5e60f80b3d`, proxy artifact `ca358178-a898-56e6-80bf-1e0185b5052b` | chain reached `completed`, import/proxy/scene jobs completed, `scenes_count=1`, source SHA `bce0018453ff8594a4c1f4bd8287fc5cf84b980b1a713a795fabec5a77096977`; final counts `projects=2, video_items=2, artifacts=2, jobs=3, s12_export_runs=0` |
| 8 | `GET /api/v2/projects/eb7ae227ca22/export/context?video_item_id=ac93d720-122c-41ad-8fad-d48cf4d594f5` | IDs above are followed exactly | `200`; source dimensions/timing resolved (`32x32`, `1000ms`, `10/1`), but reasons are `S12_EXPORT_FULL_APPLY_MISSING` and `S12_EXPORT_LOCK_MISSING` |
| 9 | `POST /s12-exports/submit` for the clean UUID project/video | server-owned context revision | `409` with `export context not current: ['S12_EXPORT_FULL_APPLY_MISSING', 'S12_EXPORT_LOCK_MISSING']`; no additional job/run mutation (`s12_export_runs=0`, jobs unchanged) |

The legacy path therefore is a valid bounded source → durable worker → source
artifact/proxy/scene chain. It is not a completed Full Apply or S12 export and
is not counted as normal-product export acceptance.

## Authority route inventory and exact responses

The real `/openapi.json` response in the raw JSON lists:

- durable project/video create/read routes under `/api/v2/projects/...`, but no
  `/api/v2/projects/{project_id}/videos/{video_id}/import` path;
- `POST /api/v2/reskin-configs`, `POST /api/v2/project-cast`,
  `POST /api/v2/s09-approvals/reapprove`, and
  `POST /api/v2/projects/{project_id}/full-apply`;
- read/retry/cancel Full Apply routes and the read-only
  `/api/v2/s09-approvals/{checkpoint_id}/full-apply-authority` route;
- no structural-lock creation route in the OpenAPI path set.

The bounded calls were:

```text
POST /api/v2/projects/a138aae0-e47f-486e-8977-3fc9b0e5c6f2/videos/626fa321-eb04-4409-b5d4-f7be7ec634d3/import
404 {"detail":"Not Found"}

POST /api/projects/a138aae0-e47f-486e-8977-3fc9b0e5c6f2/video
404 {"detail":"Project not found"}

POST /api/v2/reskin-configs
404 {"detail":"object role ownership mismatch"}

GET /api/v2/project-cast/picker/packs
200 {"limit":50,"offset":0,"packs":[],"query":null,"total":0,"workspace_id":"default"}

POST /api/v2/s09-approvals/reapprove?workspace_id=default
404 {"detail":"ReskinConfig 'missing-public-config' not found in workspace"}

POST /api/v2/projects/a138aae0-e47f-486e-8977-3fc9b0e5c6f2/full-apply?workspace_id=default
404 {"detail":"ApplyCheckpoint 'missing-public-checkpoint' not found in workspace"}
```

The missing-UUID durable import call is a separate v2 source-ingest contract
gap. The legacy analyze path can materialize a durable shell with the legacy
12-hex project identity through `AnalyzeOrchestrator._ensure_durable_shell`,
but it does not create a current S09 Full Apply authority. The first exact
missing authority contract is a public/service-owned way to produce and pin a
valid `StructuralLockManifest` (and its route/segment evidence) for the
current source generation. Reapproval only consumes a `ReskinConfig`; its
v2 authority is deliberately non-executable without that lock. The next
missing prerequisites observed in a clean database are a published pack and
owned role/config graph, as shown by the empty picker and the config-create
404. No fabricated IDs were retried after those fail-closed responses.

## Ownership and mutation boundary

- `ProjectWorkflowService.create_project` owns the legacy 12-hex filesystem
  project; the durable v2 project service owns UUID projects.
- `AnalyzeOrchestrator._ensure_durable_shell` owns the legacy-to-durable
  shell bridge; its worker owns import, proxy, and scene jobs and published
  source/proxy artifacts.
- S09 reapproval is a read/validate-then-insert immutable checkpoint path;
  S10 Full Apply is the submit path that would enqueue durable Full Apply only
  after server-owned authority validation.
- S12 export context/submit remained read-only/fail-closed in this probe.
- The UI seed that directly inserts completed Full Apply rows is explicitly
  excluded from this map and from normal-product evidence.

## R2 fresh public evidence

Candidate: `codex/s12-lc3-luna-qa` at
`7dfbca84456501c3a995490e98741604d149aabf`. Route: `gpt-5.6-luna`, high,
fallback OFF. This section is a new isolated probe; the R1 record above is
preserved as historical evidence.

Raw evidence and exact command envelope:

- `C:\Users\Admin\Documents\Codex\2026-09-05\files-pasted-by-the-user-codex\outputs\s12-luna-c3-r2\20260910T124058Z\q2\public-chain-v2-20260910T125705Z.json`
  (SHA256 `AE477C28459D9BBD3A904949CC0918F52DD84EC22386849DAAF01BB5A8C36F39`)
- `C:\Users\Admin\Documents\Codex\2026-09-05\files-pasted-by-the-user-codex\outputs\s12-luna-c3-r2\20260910T124058Z\q2\public-chain-v2-command-20260910T125705Z.json`
  (SHA256 `CBFD4271BCF5CE73346DA8B4DC899D0C3AB024238C5DFD48864CC793BD6DF708`)
- Probe argv: `python scripts/s12/s12_lc3_probe.py --work-root C:\Users\Admin\mfqa\s12-lc3-r2\20260910T124058Z\QA\Q2-public-chain-v2 --evidence <raw evidence path>`; cwd is the QA worktree; duration `10.7718887329102s`; exit `0`. The probe envelope did not include epoch start/end fields.

Runtime and database were contained under
`C:\Users\Admin\mfqa\s12-lc3-r2\20260910T124058Z\QA\Q2-public-chain-v2\`;
database was `data\probe.db`, managed root was `artifacts`, and
`manual_sql_used=false`. The durable worker was started and stopped by the
probe. No demo or live-main path was used.

The fresh public IDs were:

| Boundary | Returned identity | Observed result |
|---|---|---|
| v2 project create | `927abd13-58ad-466e-a420-b344870f84df` | `POST /api/v2/projects/` → `201` |
| v2 video create | `ff6bba00-062c-480b-8408-538a532588cd` | `POST /api/v2/projects/{project_id}/videos` → `201`, `status=imported`, no source artifact |
| legacy project create | `3902d80b8bf1` | `POST /api/projects` → `201`; 12-hex `ProjectWorkflowService` identity |
| legacy durable video | `18585f88-6590-40d2-9acf-7594a7eb7877` | returned by public legacy analyze; UUID durable shell |
| source artifact | `0b36ae99-96da-508d-af59-10bb439d047f` | published by the durable worker |
| proxy artifact | `2af7f681-55b8-53f0-ae59-9d84a0aadb81` | published by the durable worker |

The legacy chain reached `completed` with `scenes_count=1`, three completed
jobs (`59f91218-5a29-4cfd-8910-4a580057683d`,
`29cd7de2-27d6-45cd-a589-b6d80341168f`,
`2053b3f0-504a-4c5b-8019-cdc2befa608d`), two artifacts, and source SHA256
`bce0018453ff8594a4c1f4bd8287fc5cf84b980b1a713a795fabec5a77096977`.
That is source-ingest/analyze evidence only; it is not Full Apply or S12
export evidence.

The v2 context for the actual v2 project/video returned `200` with
`full_apply_run_id=null`, `checkpoint=null`, `lock=null`, `plan=null`, and
reasons `S12_EXPORT_FULL_APPLY_MISSING` and `S12_EXPORT_LOCK_MISSING`.
`POST /s12-exports/submit` returned `409` with
`export context not current: ['S12_EXPORT_FULL_APPLY_MISSING', 'S12_EXPORT_LOCK_MISSING']`.
Before submit, counts were `projects=2, video_items=2, artifacts=2, jobs=3,
s12_export_runs=0`; after the rejected submit, `jobs=3,
s12_export_runs=0`.

The actual-ID scoped reads against the legacy 12-hex project and returned
UUID video all returned `200`, but were empty/not-ready: reskin configs `0`,
object roles `0`, project-cast mappings `0`, S09 approvals `0`, and project
readiness `status=not_run`, `video run_state=never_run`. Thus this run did not
reach a valid current StructuralLock or Full Apply prerequisite. The clean
v2 identity is separate from the completed legacy chain; a legacy upload
against the v2 UUID returned `404 Project not found`, which is secondary
identity-boundary evidence, not the first blocker.

The OpenAPI snapshot recorded the real create/upload/analyze, v2 context,
ReskinConfig, role/cast, S09 approval/reapprove, full-apply, and S12 routes.
There is no v2 durable video import path and no StructuralLock manifest
creation path in the OpenAPI path set. The first valid missing prerequisite
after the returned source/evidence, role/pack/cast, and config producers is a
supported server-owned path that can produce and pin a current
StructuralLockManifest for the returned source generation; without it, S09 can
only return a verified but non-executable snapshot and S10 cannot construct an
executable authority. The guessed missing-ID calls and their 404s are retained
only as secondary raw evidence.

Status remains `BLOCKED_EXTERNAL_AUTHORITY_FIXTURE`; normal-product S12
submit → worker → publisher → result/media and real UI interaction were not
demonstrated. No assertion, completed authority, run, job, or media row was
fabricated.

## R3 fresh producer-chain evidence

R3 was run from QA HEAD `e17f772cf85d388a3c53cd70c11a3b7f60868992` using
`gpt-5.6-luna`, reasoning `high`, fallback `OFF`. The harness is a new
QA-owned executable at
`tests/s12/s12-lc3-qa-r3/r3_public_producer_chain_harness.py`; it uses an
isolated migrated SQLite database and managed root and never inserts authority,
readiness, completion, or export rows. The deterministic extractor is marked
`FIXTURE_ONLY_ENGINEERING_MECHANISM`, not normal-product evidence.

Raw command envelope, stdout/result, and stderr are retained at the R3
evidence root:

- `public-producer-chain-20260911T035817Z.command.json` — SHA-256
  `9C38ECC5392E3BC8539B3FE6B719CEC5404CF5F2AE998743CDD563377B056AE9`
- `public-producer-chain-20260911T035817Z.stdout.txt` — SHA-256
  `C97FA33215908D4352BEDB547E1B8E8B3A68141696AEA10FA75E8683497612EA`
- `public-producer-chain-20260911T035817Z.stderr.txt` — SHA-256
  `124F2F3866280D26F6F7521251EBD7BE954CA24C07F3C1082D964EACCD181F54`
- `public-producer-chain-20260911T035817Z.json` — SHA-256
  `C97FA33215908D4352BEDB547E1B8E8B3A68141696AEA10FA75E8683497612EA`

Exact command envelope: cwd
`C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-qa`, start
`2026-09-11T03:58:17.6701313Z`, end `2026-09-11T03:58:30.2858493Z`,
duration `12.615718s`, exit `0`; argv was
`python tests/s12/s12-lc3-qa-r3/r3_public_producer_chain_harness.py --work-root C:\Users\Admin\mfqa\s12-lc3-r3\20260911T034253Z\QA\public-producer-r3-capture-20260911T035817Z --evidence C:\Users\Admin\Documents\Codex\2026-09-05\files-pasted-by-the-user-codex\outputs\s12-luna-c3-r3\20260911T034253Z\public-producer-chain-20260911T035817Z.json`.

The runtime and database were contained under
`C:\Users\Admin\mfqa\s12-lc3-r3\20260911T034253Z\QA\public-producer-r3-capture-20260911T035817Z\`;
the worker and analyze orchestrator were stopped and the engine disposed.
Fresh returned identities were:

| Boundary | Returned identity | Result |
|---|---|---|
| Legacy project create | `27ff27234a0b` | `POST /api/projects` → `201`; server-created 12-hex project |
| Legacy analyze video | `7513a010-767c-4309-aa87-9d47a0ecf860` | `POST /api/projects/27ff27234a0b/analyze` → `200`; UUID durable shell |
| Legacy source/proxy | `c3a42ae2-7260-5107-8da8-2b795075db31` / `a5bd78a7-f3e1-5de7-8ecf-a4c2e0f3ca17` | import, proxy, scene jobs all completed; one scene; source SHA from uploaded 256x256 MP4 |
| DISCOVER_OBJECTS job | `802bf597-31d6-4331-9e88-e3b160d99a33` | `POST /api/v2/object-intelligence/extraction` → `201`; durable worker completed and published 5 outputs |
| Current roles/occurrences | `role_id=8511d899-f27f-5cc3-8151-678e4a0a6bca` plus one other returned role | `GET /api/v2/object-intelligence/roles?video_item_id=...` → `200`; two current roles and two occurrences; role confirmation used returned revision |
| Character/version/asset | `character_id=09e90320-efb4-4a62-9cc2-257b39dbfd83`, `pack_version_id=890e2e5c-8574-4d67-8654-3e13deadd92a`, image artifact `9a451a01-fed8-589b-b11c-977615fdd59c` | public character create/version, six public attaches, validation `complete=true/errors=[]`, publish `200` |
| Project cast | `f1e89003-2df8-4fda-a976-9592ea189558` | `POST /api/v2/project-cast` → `201`, actual role/character/version IDs |
| ReskinConfig | `d78a4a7e-eda5-4028-b0fe-d33b69f39c1e` | `POST /api/v2/reskin-configs` → `201`, actual cast/config pins |

The exact producer/consumer route graph and source call-sites were:

| Stage | Public route/method and request shape | Owner/source call-site | Observed state |
|---|---|---|---|
| Legacy identity/upload | `POST /api/projects` JSON `{name}`; `POST /api/projects/{project_id}/video` multipart `file` | `app/api/routes/projects.py:228-230`, `:329-331`; `ProjectWorkflowService.create_project` at `app/workflow/project_workflow.py:61` | 12-hex project and server-owned uploaded filename; no ID fabrication |
| Legacy durable chain | `POST /api/projects/{project_id}/analyze` JSON `{generation,title}`; bounded `GET .../analyze?generation=1` | `app/api/routes/projects.py:2399-2401`, `:2446-2447`; `AnalyzeOrchestrator._ensure_durable_shell` at `app/workflow/analyze_orchestrator.py:702` | import/proxy/scene jobs completed; source/proxy artifacts and returned UUID video |
| Extraction producer | `POST /api/v2/object-intelligence/extraction` JSON `{project_id,video_item_id,generation}`; `GET /{job_id}`, `/outputs`, `/graph` | `app/api/routes/object_extraction.py:92-94`, `:511`, `:558`, `:619`; `submit_discover_objects` at `app/services/object_extraction.py:2793` | QA-only deterministic server policy completed; ready managed image masks, roles, occurrences, structural segments |
| Role/occurrence consumer | `GET /api/v2/object-intelligence/roles`; `PATCH /roles/{role_id}` with returned revision; occurrence evidence read from returned role | `app/api/routes/object_intelligence.py:95-98`, `:230-232`, `:263-280` | current scope `generation=1`; no standalone occurrence row was fabricated |
| Character producer | `POST /api/v2/characters`; `POST /api/v2/characters/{id}/versions`; `POST /api/v2/characters/versions/{id}/assets` `{pose_slot,artifact_id}`; `GET .../validation`; `POST .../publish` `{revision}` | `app/api/routes/durable_characters.py:49-51`, `:200-202`, `:229-231`, `:342-344`, `:266-268` | six required slots attached to returned ready extraction artifact; validation passed and version published |
| Cast consumer | `POST /api/v2/project-cast` `{project_id,object_role_id,character_id,pack_version_id,idempotency_key}` | `app/api/routes/project_cast.py:59-61` | mapping `201`; server checked current generation, published complete pack, ownership, and kind |
| Reskin consumer | `POST /api/v2/reskin-configs` with actual role/character/version/cast IDs and typed params | `app/api/routes/reskin_config.py:48-50` | config `201`; `structural_lock_manifest_id=null`, `lock_policy_version=null` |
| Structural evidence consumer | `GET /api/v2/structural-evidence/segments?video_item_id=...` | `app/api/routes/structural_evidence.py:409-411` | two current extraction-produced segments returned; no StructuralLockManifest row |
| S09 v1/v2 consumers | `POST /api/v2/s09-approvals`; `POST /api/v2/s09-approvals/reapprove`; `GET /api/v2/s09-approvals/{checkpoint_id}/full-apply-authority` | `app/api/routes/s09_approval.py:100-105`, `:166-171`, `:229-233`; `S09ApprovalRepository.submit_checkpoint_v2` at `app/services/s09_approval.py:648` | v1 and v2 requests both returned `201`; v2 authority `verified=true` but `full_apply_executable=false`, no lock/source/role mappings |
| S10 consumer | `POST /api/v2/projects/{project_id}/full-apply` with returned v2 checkpoint ID/hash and `expected_checkpoint_revision=1` | `app/api/routes/s10_full_apply.py:952-953` | `422 {"detail":"v2 authority has no frozen source artifact (incomplete authority)"}`; counts unchanged |
| S12 consumer | `GET /api/v2/projects/{project_id}/export/context?video_item_id=...`; `POST /s12-exports/submit` `{project_id,video_item_id,profile_id}` | `app/api/routes/s12_export_preflight.py:49-53`; `app/api/routes/s12_export.py:194-195` | context `200` with `full_apply_run_id=null`, `checkpoint=null`, `lock=null`, `plan=null`; submit `409` with exact missing reasons |

The authoritative mutation-count snapshot after the failed S10 and failed S12
consumer was: `projects=1`, `video_items=1`, `jobs=4`, `artifacts=7`,
`characters=1`, `pack_versions=1`, `character_assets=6`, `roles=2`,
`occurrences=2`, `project_cast_mappings=1`, `reskin_configs=1`,
`structural_lock_manifests=0`, `s09_approvals=2`, `s12_export_runs=0`.
The before/after S12 counts were identical.

### First genuine missing producer

The raw OpenAPI path set contains structural-evidence segment/motion/contact
routes and S09 correction route surfaces, but no `StructuralLockManifest`
creation/activation route. The persistence capability exists at
`app/persistence/structural_lock.py:495` (`StructuralLockRepository.create_manifest`)
and route decisions can be persisted by
`app/persistence/structural_lock.py:743` (`record_render_route`), but the
captured public graph has no route that produces and activates a current
manifest. The public v1 approval can therefore create a non-executable
checkpoint, and reapproval can create a verified v2 snapshot whose exact
eligibility is:

`no structural lock manifest pinned; full apply requires manifest authority (reapproval after pinning)`

The subsequent public S10 response is:

`422 {"detail":"v2 authority has no frozen source artifact (incomplete authority)"}`

The subsequent public S12 response is:

`409 {"detail":"export context not current: ['S12_EXPORT_FULL_APPLY_MISSING', 'S12_EXPORT_LOCK_MISSING']"}`

This is not an empty-picker or invented-UUID conclusion: the valid legacy
public chain, current extraction roles/occurrences/segments, published pack,
cast mapping, and ReskinConfig all succeeded first. The exact upstream scope
is recorded once in `UPSTREAM_SCOPE_PROPOSAL_R3.md`. Normal-product S12
worker/publisher/result/media and UI playback remain not demonstrated.
