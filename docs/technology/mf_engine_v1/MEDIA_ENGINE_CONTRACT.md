# MF Media Engine Contract V1 (S13 P00)

**Contract id:** `mf.media_engine.contract.v1`
**Schema authority:** `app/schemas/media_engine.py` (NEW, this task)
**Contract tests:** `tests/technology/test_media_engine_contract.py` (NEW, this task)
**Status:** PROPOSAL — goes to Codex review as `C-CONTRACT`. Nothing here is production
authority until Codex approves it. No S13 production task may be activated against an
unreviewed proposal.

This document is the prose half of a two-part contract: every rule below has a mechanical
counterpart in the schema module, and every mechanical rule has a test that fails when the
rule is removed (negative controls N1–N4, see §9).

---

## 1. What this module is, and what it deliberately is not

The media engine contract is a **vocabulary and a refusal boundary**. It is pure: pydantic
plus stdlib (`hashlib`, `json`, `datetime`, `enum`, `typing`). It owns:

- no database, no ORM model, no migration;
- no queue, no worker, no scheduler, no concurrency primitive;
- no HTTP route, no FastAPI dependency, no `app/api/app.py` include;
- no filesystem access, no network call, no model download.

It references — and never duplicates — two existing authorities:

| Existing authority | Path | What the contract borrows from it |
|---|---|---|
| Renderer route taxonomy | `app/persistence/models.py::RENDERER_ROUTES` (5 canonical routes), `app/services/renderer_contract.py` (`CapabilityDescriptor`, `RendererContractCode`, fail-closed `RendererRouterError` family) | the fail-closed "no silent fallback" rule, the `evidence_source` vocabulary (`measured_live`/`probed_config`/`declared`), the idea that a capability is only claimed with evidence |
| E01 durable jobs | `app/persistence/jobs.py` (`JobRepository`, leases, idempotency keys, attempts), `docs/architecture/DURABLE_JOB_CONTRACT.md` (V1.1) | job identity/ownership, lease fencing, idempotency, replay-safe windows, artifact staging/publication (§§5, 8, 9) |
| Publication | `app/services/s12_export/publication.py`, `app/services/s12_export/publication_lease_guard.py` | fail-closed publication, receipts, intent files, no silent overwrite |
| Approval audit | `app/services/s09_approval.py` (`S09ApprovalIntegrityError`, `ApprovalConflictError`) | immutable approval records, conflict-on-replay semantics |
| Managed artifacts | `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md`, `app/persistence/models.py::Artifact` | artifacts are addressed by id, never by path |

**Explicitly out of scope for this task** (see `EARLIER_SPRINT_DELTA.md`): rewiring the live
S09/S10 render path, any UI, any migration, any route. This task freezes the contract that a
later, separately-packeted integration step will implement against.

---

## 2. Capabilities are distinct and never degrade silently

```
image_edit_multi_reference
source_video_motion_transfer
video_edit_controlled
text_to_video
```

`MediaCapability` has exactly these four members — no aliases, no synonyms, no "generic
video" fallback value.

`SOURCE_LOCKED_CAPABILITIES = {source_video_motion_transfer, video_edit_controlled}`.
For a source-locked request, these substitutions are **forbidden outright**
(`FORBIDDEN_DEGRADATION_TARGETS`):

| Requested | May NOT be served as |
|---|---|
| `source_video_motion_transfer` | `text_to_video`, `image_edit_multi_reference` |
| `video_edit_controlled` | `text_to_video`, `image_edit_multi_reference`, `source_video_motion_transfer` |

Two rules make this load-bearing rather than decorative:

1. `CapabilitySet.assert_can_serve(requested, substitute=...)` raises
   `capability_degradation_refused` for a forbidden pair — **even when
   `operator_approved_substitution=True`**. Approval is not a licence to relabel a T2V
   result as a motion transfer: the artifact a user would receive is a different artifact,
   and no human sign-off changes that.
2. Any *allowed* substitution still refuses with `capability_degradation_refused` unless
   `operator_approved_substitution=True`. Substitution is never silent; it is explicit and
   auditable.

**Capability absence is explicit** (`CAPABILITY_ABSENCE_IS_EXPLICIT = True`). A
`CapabilityOffer` with `available=False` MUST carry `unavailable_reason_code` (validated);
an offer with `available=True` MUST NOT carry one. `assert_can_serve` on a capability that
is absent raises `media_capability_unavailable` — the engine never implies absence by
returning nothing.

---

## 3. Request DTO — ids, hashes and pins only

`MediaEngineRequest` (frozen, `extra="forbid"`):

| Field group | Fields |
|---|---|
| Identity | `workspace_id`, `project_id`, `series_id?`, `video_id`, `stage`, `attempt_id`, `job_id?` |
| Capability | `capability: MediaCapability` |
| Source lock | `source: SourceLock` — `source_artifact_id`, `source_sha256` (64 hex), `shot_range`, `pts_start_ticks`, `pts_end_ticks`, `fps_num`/`fps_den` |
| Cast | `cast: tuple[CastBinding, ...]` — `role` → `character_id` + immutable `pack_version_id` + `references: tuple[ReferenceArtifact, ...]` (id + sha256) + optional `style_version` |
| Pins | `pins: WorkflowPins` — `workflow_id`, `workflow_version`, `workflow_hash`, `model: ModelPin` (`model_id`, `revision`, `file_sha256`, `precision`), `nodes: tuple[NodePin, ...]` (`node_id`, `node_class`, `config_hash`), `config_hash`, `seed` |
| Output | `output: OutputContract` — geometry, fps, `frame_count`, container, codec, `audio: AudioHandoff`, `publishable_types` |
| Budget | `budget: ResourceBudget` — `resource_class`, `max_wall_seconds`, `max_vram_bytes`, `max_output_bytes` |

`ShotRange` is **inclusive** in the source clip's own index space
(`frame_count = end - start + 1`), which is the frame-index space the S12/BENCH work
already measured (`first_pts`/`last_pts`/timebase semantics). `SourceLock.timebase`
renders the rational fps as `num/den`.

### 3.1 Backend-managed artifacts are the authority

`MediaEngineRequest` declares `client_path: str | None` and `client_graph: dict | None`
**only so they can be refused with a typed code** rather than a generic pydantic error.
A non-`None` value raises:

- `client_artifact_path_refused` for `client_path`;
- `client_graph_refused` for `client_graph`.

The same rule holds one level down: `ReferenceArtifact.path` exists only to be refused
(`client_artifact_path_refused`). A caller addresses bytes by managed `artifact_id` +
`sha256`, never by filesystem path, never by a graph they composed client-side. This is the
schema-level expression of `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md`.

Cast roles must be unique within a request (validated); a role maps to exactly one
`CharacterID` + one immutable `PackVersion` (see `PACK_CAPABILITY_CONTRACT.md`).

---

## 4. Cache identity

```
Cache identity = source_sha256 + shot_range + pts + cast + pack + assets + style
               + workflow + model + settings
```

`CacheIdentity` carries the nine component digests plus `identity_version` and `digest`.
`cache_identity_for(request)` derives it **server-side from frozen request facts**; it is
never supplied by a caller. The payload that is hashed is declared once, in
`IDENTITY_COMPONENT_FIELDS`, and is used both by the constructor and by the object's own
`_check` — so the hashed payload and the validated fields cannot drift apart.

A parametrised test mutates each component (source sha, shot range, pts, cast, pack, assets,
style, workflow, model, node config, seed, settings) and asserts the digest **changes** for
every one of them: the nine components are proven present, not merely documented.

### 4.1 Reference change → invalidate the affected shots only

`invalidate_for_reference_change(entries, ReferenceChange)` returns an
`InvalidationReport` with `invalidated_entry_ids`, `invalidated_ranges` and
`unaffected_entry_ids`. `ReferenceChange.kind` is closed to
`character_id | pack_version | reference_artifact | style_version`.

The rule is shot-scoped, never global: a change to role `protagonist` invalidates the cache
entries whose `roles` include `protagonist` and leaves every other entry untouched. A
`style_version` change additionally hits entries pinned to a *different* style for that role.
A change naming a role no entry uses invalidates nothing — the report says so explicitly
rather than silently reporting success.

---

## 5. Replay — re-attach or refuse, never a second POST

`InflightReservation` is the durable record written **before** the upstream POST, with
`submit_state ∈ {outstanding, inflight, acked, ambiguous}` (the same lifecycle the COMFY
round froze). Invariants: `acked` requires a `prompt_id`; `outstanding`/`inflight` must not
carry one.

`ReplayAction` has exactly two members: `re_attach`, `refuse`. `resolve_replay(...)`
returns a `ReplayDecision`:

| Reservation state | Identity matches | Result | Reason code |
|---|---|---|---|
| `ambiguous` | — | refuse | `unresolved_ambiguous_reservation` |
| any | no | refuse | `reservation_identity_mismatch` |
| `acked` + prompt_id | yes | **re_attach** | `re_attach_acked_prompt` |
| `outstanding` / `inflight` | yes, other owner | refuse | `reservation_owned_by_other_session` |
| `outstanding` / `inflight` | yes, same owner | refuse | `reservation_not_acked_no_second_submit` |

`ReplayDecision.issues_post` is a constant `False` and is enforced: constructing a decision
with `issues_post=True` raises `replay_refused`. There is no third action and no code path
that can issue a second upstream submission for the same attempt — the structural reason a
replay cannot duplicate the POST.

---

## 6. Result DTO and lifecycle states

`MediaEngineResult` carries:

- **durable identity/ownership:** `prompt_id`, `server_epoch`, `owner_session`, `lease_id?`;
- **what was actually run:** `capability`, `identity: CacheIdentity`, `pins: WorkflowPins`;
- **what was produced:** `artifacts: tuple[ManagedArtifact, ...]` (each with `kind`,
  `media_type`, `sha256`, store-relative path, `size_bytes`, `publishable`);
- **decoding truth:** `decoded: DecodedMap` (`decoded_frames`, `first_pts_ticks`, `timebase`,
  and the full `mapping` output-frame → source-frame);
- **audio handoff:** `audio: AudioHandoff` (`source_remux` | `generated` | `silent`, with
  `source_artifact_id` mandatory for remux) — never an implicit passthrough;
- **typed terminal facts:** `MediaEngineFailure` (code/message/retryable) and
  `MediaEngineCancel` (requested_by/reason/at_utc).

States are **distinct**, never collapsed into a boolean:

```
generated → validated → reviewed → accepted → published
```

`STATE_TRANSITION_TABLE` is frozen and enforced by `StateTransition`:
`generated` may advance directly to `validated`/`reviewed`/`accepted`; `accepted` is the only
state that may reach `published`; `published` is terminal. `generated → published` raises
`state_transition_refused`. A `MediaEngineResult` in `published` state requires a publishable
artifact, and may carry neither `failure` nor `cancel`; `failure` and `cancel` are mutually
exclusive.

### 6.1 Artifacts and publication

`ManagedArtifact` refuses an absolute path, a drive-qualified path, a Windows path
separator-rooted path, and any `..` traversal segment (`client_artifact_path_refused`) —
paths are store-relative.

`kind ∈ {image, video, audio, pose_sheet, mask, graph}`. `PUBLISHABLE_ARTIFACT_KINDS =
(image, video, audio)`: a `mask`, `graph` or `pose_sheet` is a legitimate **managed
intermediate** and stays in the result, but marking one `publishable=True` raises
`artifact_not_managed`. `assert_publishable_set(artifacts, publishable_types=...)` is the
publication gate: it selects publishable artifacts, refuses when there are none
(`artifact_not_managed` — fail-closed, never an empty success), and refuses a
`publishable_types` set that is not a subset of the server-owned
`SERVER_PUBLISHABLE_TYPES = ("output",)`. `OutputContract` enforces the same narrowing rule,
so a caller can only ever **narrow** the publish allow-list. This mirrors the COMFY round's
`PUBLISHABLE_SERVER_TYPES` finding and the S12 publication authority.

---

## 7. Model registry

`ModelRegistryEntry` records: `role`, `model_id`, `revision`, `file_sha256`, `precision`,
`capabilities`, `hardware: tuple[HardwareProfile, ...]`, **`release_date`**,
**`repo_modified_date`**, `license_id`, `available`, `unavailable_reason_code`,
`download_requires_operator_action`.

- `release_date` is the upstream publication date of the model; `repo_modified_date` is when
  the local registry row was last touched. They are **different facts** and are stored
  separately (`dates_are_distinct_facts`). Neither may be derived from the other.
- `HardwareProfile` is a **measured** profile: `device`, `vram_bytes`,
  `measured_seconds_per_output_second`, `measured_at_utc`, `evidence_source`. A profile
  claiming `evidence_source="measured_live"` without a measurement and a timestamp is
  rejected — an unmeasured claim cannot masquerade as a measurement.
- Availability is explicit and two-sided: `available=False` requires a reason code;
  `available=True` must not carry one. `require_available(role)` raises `model_unavailable`
  (with the reason) for an absent or unavailable role — never a silent `None`.
- **No automatic download from a UI click.** `NO_AUTO_DOWNLOAD_FROM_UI = True`;
  `download_requires_operator_action=False` on an entry raises `auto_download_refused`; and
  `ModelRegistry.request_download(origin="ui_click")` always raises `auto_download_refused`.
  Model provisioning is out-of-band operator work; the registry is a lookup, not a downloader.

---

## 8. One job store, one concurrency engine, one GPU

```
E01_JOB_STORE = "e01_durable_jobs"
SECOND_JOB_DATABASE_ALLOWED = False
COMPETING_CONCURRENCY_ENGINE_ALLOWED = False
```

`assert_shared_stack(job_store=..., concurrency_engine=...)` raises
`second_job_store_refused` / `competing_concurrency_engine_refused` for anything other than
E01. `GpuLeaseView` is a **read-only view** over the E01 lease — it defaults both fields to
E01 and validates them on construction, so a view cannot be built against an invented store.

Image and video generation share the one lease. `GpuLeaseView.decide(request, ...)` grants
only when the lease is free; otherwise it queues the job and returns `granted=False`. There
is no priority bypass and no second holder. A job cannot be simultaneously holder and
queued, and a job occupies at most one queue position (both validated).
`GpuLeaseGrant.expired_at(now_utc)` answers expiry deterministically from the frozen
`YYYY-MM-DDTHH:MM:SSZ` string (validated by pattern) — lease time is judged by E01's fencing
rules, not re-implemented here.

---

## 9. Refusal taxonomy and its proofs

`MediaEngineRefusalCode` (12 codes, each carrying a detail string, surfaced via
`MediaEngineRefusal.as_dict()`): `media_capability_unavailable`,
`capability_degradation_refused`, `client_artifact_path_refused`, `client_graph_refused`,
`artifact_not_managed`, `replay_refused`, `model_unavailable`, `auto_download_refused`,
`gpu_lease_held`, `second_job_store_refused`, `competing_concurrency_engine_refused`,
`state_transition_refused`. Refusals are raised, never swallowed into a generic error.

The four gate-critical refusal cases are proven non-vacuous by mutation controls
(`NEW/CONTRACT/raw/negative_controls.json`): each guard is removed from the module, the
guard's own test must then FAIL, and the file is restored byte-identically.

| Control | Guard removed | Tests that must fail | Result |
|---|---|---|---|
| N1 | source-locked degradation refusal | `test_source_locked_route_refuses_t2v_i2v_substitution`, `test_operator_approval_cannot_bless_a_t2v_degradation`, `test_substitution_still_needs_explicit_approval_when_not_forbidden` | DETECTED (7 failed) |
| N2 | client path/graph refusal | `test_request_refuses_a_client_supplied_path`, `test_request_refuses_a_client_supplied_graph` | DETECTED (2 failed) |
| N3 | replay no-second-POST guard | `test_unresolved_replay_never_duplicates_the_post`, `test_a_decision_that_would_post_is_refused_by_construction` | DETECTED (2 failed) |
| N4 | reference-change invalidation | `test_reference_change_invalidates_only_the_affected_shots` | DETECTED (1 failed) |

---

## 10. Open questions this proposal puts to Codex

1. `ResourceBudget.resource_class` is a free string here; E01's authority is
   `RESOURCE_CLASSES = (cpu_light, cpu_heavy, gpu, io)` (`app/persistence/jobs.py`). Should
   the contract import that constant (creating a schema → persistence import) or keep the
   value free-form and validate at the E01 boundary? This proposal keeps it free-form.
2. `MediaEngineResult` does not carry the `OutputContract` it was requested with; the
   publish allow-list is therefore enforced at publication
   (`assert_publishable_set`) rather than at result construction. Confirm that split.
3. Should `pose_sheet` ever be publishable? This proposal says no
   (`PUBLISHABLE_ARTIFACT_KINDS = image, video, audio`) because the legacy pose-sheet pack
   path publishes through its own authority (`PackVersion` + `CORE_POSE_SLOTS`), not through
   the media engine.
