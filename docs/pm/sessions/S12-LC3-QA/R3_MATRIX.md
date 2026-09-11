# S12-LC3-R3 QA evidence map

Candidate: `e17f772cf85d388a3c53cd70c11a3b7f60868992` at start of the R3
bounded attempt. Route: `gpt-5.6-luna`, high, fallback OFF. This is evidence
transport only; no row or sprint is APPROVED or CLOSED.

## S01-S10 producer/consumer map

| Stage | R3 evidence and current status |
|---|---|
| S01 legacy source identity | `POST /api/projects` returned project `27ff27234a0b` (12-hex); public upload returned the source artifact and UUID video `7513a010-767c-4309-aa87-9d47a0ecf860`. Demonstrated in raw `public-producer-chain-20260911T035817Z.json`. |
| S02 import/analyze durable shell | Public analyze followed returned generation/video; import/proxy/scene jobs completed through `_ensure_durable_shell` (`app/workflow/analyze_orchestrator.py:702`). Demonstrated. |
| S03 extraction worker | Public extraction returned job `802bf597-31d6-4331-9e88-e3b160d99a33`; durable worker completed and published five outputs under QA-only deterministic policy. Mechanism evidence only. |
| S04 roles/occurrences/evidence | Returned two current roles, two occurrences, and two current structural-evidence segments; role confirmation used returned revision. Demonstrated as producer inputs. |
| S05 character/version/assets | Public character/version creation, six returned ready artifact attaches, validation `complete=true/errors=[]`, and publish `200`. Demonstrated. |
| S06 cast/config consumers | ProjectCast `201` and ReskinConfig `201` used actual returned IDs; config had `structural_lock_manifest_id=null`. Demonstrated pre-lock graph only. |
| S07 StructuralLock producer | OpenAPI has no public create/activate path; persistence exists at `app/persistence/structural_lock.py:495`. No manifest row was produced: first genuine missing producer. BLOCKED. |
| S08 approved application authority | Public S09 v1 submit and reapprove returned `201`, but v2 authority was `verified=true` and `full_apply_executable=false` with no lock/source. BLOCKED downstream of S07. |
| S09 Full Apply | Public S10 submit with returned checkpoint/hash/revision returned `422 {"detail":"v2 authority has no frozen source artifact (incomplete authority)"}`. Not demonstrated. |
| S10 S12 export/media/UI | Context returned missing lock/full-apply; submit returned `409` with `S12_EXPORT_FULL_APPLY_MISSING` and `S12_EXPORT_LOCK_MISSING`; no normal worker/publisher/result/media/UI reached. Not demonstrated/not run. |

## C01-C32

| Row | Exact R3 mapping | R3 status |
|---|---|---|
| C01 | Prior T03C closure evidence retained; R3 producer-chain run did not rerun acceptance row. | CARRY_FORWARD_ONLY |
| C02 | Prior T01/T02 capability/profile evidence retained; no R3 row run. | CARRY_FORWARD_ONLY |
| C03 | Prior T01 provenance evidence retained; R3 source bytes are fresh and hash-recorded, but this does not replace row proof. | CARRY_FORWARD_ONLY |
| C04 | `public-producer-chain-20260911T035817Z.json`: returned legacy project/video/source IDs and completed import/proxy/scene chain. | PARTIAL |
| C05 | Prior T03C denial evidence retained; R3 did not rerun denial row. | CARRY_FORWARD_ONLY |
| C06 | Prior T03A replay evidence retained; R3 did not rerun acceptance row. | CARRY_FORWARD_ONLY |
| C07 | Prior T03A identity/orphan evidence retained; R3 did not rerun acceptance row. | CARRY_FORWARD_ONLY |
| C08 | Prior typed loser/barrier evidence retained; R3 did not touch RETRY-owned tests. | CARRY_FORWARD_ONLY |
| C09 | Prior T03A lease-fencing evidence retained; R3 did not rerun acceptance row. | CARRY_FORWARD_ONLY |
| C10 | Prior R1 T03B 4K mechanism evidence retained; normal export not reached in R3. | CARRY_FORWARD_ONLY |
| C11 | Prior geometry/letterbox evidence retained; no normal media reached. | CARRY_FORWARD_ONLY |
| C12 | Prior source-lock/timing evidence retained; current public source/evidence inputs are recorded. | CARRY_FORWARD_ONLY |
| C13 | Prior four VAL correction nodes retained; VAL-owned bytes were not touched. | CARRY_FORWARD_ONLY |
| C14 | No normal-product committed-progress kill/restart proof; S10 was blocked. | NOT_DEMONSTRATED |
| C15 | Prior RETRY failures retained; RETRY-owned tests were not rerun before terminal. | BLOCKED |
| C16 | Fresh raw evidence records public legacy upload/analyze/durable extraction and actual IDs; extraction policy is QA-only mechanism evidence. | PARTIAL |
| C17 | No normal-product publisher/result publication-fence proof; `F01` remains open. | OPEN / NOT_DEMONSTRATED |
| C18 | No normal-product atomic publication-failure proof; `F02` remains open. | OPEN / NOT_DEMONSTRATED |
| C19 | Prior T04A validator evidence retained; no R3 row run. | CARRY_FORWARD_ONLY |
| C20 | No valid Full Apply authority; real Export UI not run. | NOT_RUN |
| C21 | No valid Full Apply authority; reload/recovery UI not run. | NOT_RUN |
| C22 | Public S12 submit stopped at `409`; no result/media/playback; mechanism fixture remains separate. | NOT_DEMONSTRATED |
| C23 | Packaging/stage gate not run in R3. | NOT_REASSESSED |
| C24 | Package hash/dependency gate not run in R3. | NOT_REASSESSED |
| C25 | Harness started/stopped its isolated worker/orchestrator and disposed the engine; raw cleanup is recorded. | PARTIAL |
| C26 | Public S10 stopped at `422`; no normal Full Apply/export and no fabricated authority. | BLOCKED |
| C27 | No normal-product cancel/expiry/restart reached after authority block. | BLOCKED |
| C28 | No normal-product audio media; prior mechanism-only audio evidence retained. | BLOCKED |
| C29 | Clean-host/human playback gate remains external and not run. | NOT_RUN |
| C30 | Retained-data migration gate not run in R3. | NOT_REASSESSED |
| C31 | Prior full-tree collection evidence retained; R3 harness was compile/static checked only. | COLLECTION_ONLY |
| C32 | R3 HEAD, route, allowlist, raw hashes, containment, and cleanup are recorded; no closure gate. | PARTIAL |

Open findings remain `C17`, `C18`, `F01`, and `F02`. RETRY/VAL terminal and
INT candidate-pin gates were not satisfied in this R3 attempt, so RETRY modules
and UI checks are explicitly `NOT_RUN`, not passes.
