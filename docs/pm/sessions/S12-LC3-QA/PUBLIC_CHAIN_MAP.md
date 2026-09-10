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

