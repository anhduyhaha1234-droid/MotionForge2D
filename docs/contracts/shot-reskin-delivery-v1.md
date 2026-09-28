# Shot-reskin delivery contract v1 (MF-END-01)

Status: **contract + DTO + fixtures + tests only — no render was run** (packet
boundary).  `QUALITY_ACCEPTED=0`; not APPROVED/CLOSED.  Owner session
`20260928_111952_919c4e`; branch `codex/mf-end-01-0928`; base PRODUCT
`2c405f3e7643d42b387352643c89c8690976314`.  Implementation:
`app/schemas/shot_reskin.py`; tests: `tests/product_delivery/test_mf_end_01.py`;
evidence:
`mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-01/REPORT.md`.

This contract is the shot-level execution plan the app builds BEFORE an engine
call and records AFTER one, plus the evidence binding that keeps SOURCE facts
and OUTPUT observations apart.  It composes the accepted media-engine DTO
(`mf.media_engine.contract.v1`, MF-TOOL-CONTRACT NR05/NR06) by reuse — it never
redefines it, never modifies it and never stubs it.

## 1. What the contract owns

| Type | Owns |
|---|---|
| `ShotPlan` | source artifact + half-open span + timebase, declared elements (roles/props/background), interaction refs, reference manifest, source evidence, output observation binding |
| `ElementUnit` | role id, kind (person/prop/background/source_frame), source track, visible spans, occlusion, confidence |
| `InteractionRef` | subject role, relation, object role, one or more spans, evidence ids, measured/confirmed state |
| `ReferenceManifest` / `RoleReferenceSet` / `ReferenceItem` | per-role reference artifacts (managed ids + sha256 + key + view), style version, props, background |
| `SourceEvidenceFact` | a SOURCE fact (domain=source) measured on the locked source artifact |
| `OutputObservation` / `OutputObservationBinding` | OUTPUT facts (domain=output) measured on the rendered artifact; refuses when the output IS the source |
| `EngineInputBinding` | the engine-call input: capability, identity, source lock, cast+references, anchor, graph/model pins, output contract, budget — projected EXACTLY onto the accepted `MediaEngineRequest` field sets |
| `EngineOutputBinding` | what the engine returned: `prompt_id`, server graph hash, artifacts, decoded facts, audio handoff, wall time, VRAM peak |
| `ShotEngineError` | the error field: code, message, retryable, optional refusal-code link |
| `ShotExecutionRecord` | schema_version + execution backend (orthogonal axis) + capability + input/output/error + outcome |

## 2. Laws (binary; every refusal carries exactly one typed code)

| Law | Refusal code |
|---|---|
| intervals are half-open `[start, end)`; `end > start`, `start >= 0`; element visibility inside the shot span; interaction spans intersect it | `invalid_interval_refused` |
| frame rate and stream time_base are different quantities (pair-or-nothing); multi-frame span may not have a zero PTS span; declared time_base must hold `(frames-1)` frame intervals | `timebase_invalid` |
| a client path at any artifact position is refused (never resolved) | `client_artifact_path_refused` |
| roles declared by `elements`; interactions/manifest/evidence/observations may not name a role the shot does not declare | `foreign_role_refused` |
| element roles are unique in a shot | `duplicate_role_refused` |
| every interacting person carries references in the manifest (and the engine minima mirror `CAPABILITY_REFERENCE_REQUIREMENTS`) | `cast_reference_required` |
| source facts are measured on the locked source artifact; output observations on the rendered artifact; an output binding must name THIS shot's source | `evidence_domain_mismatch` |
| the output artifact may not be byte-identical to the source ("source returned as output") | `output_binds_source_artifact` |
| interaction evidence ids must exist in `source_evidence` | `unknown_evidence_refused` |
| a legacy renderer ROUTE is never an execution backend (`RENDERER_ROUTES` untouched) | `legacy_route_as_backend_refused` |
| backend vocabulary is closed; a comfy record carries no legacy route; a legacy record carries no capability/engine input/output | `backend_unknown_refused` / `backend_binding_invalid` |
| comfy backend requires a capability from the accepted vocabulary | `engine_capability_required` / `engine_capability_unknown` |
| a model pin handed to the engine needs the full-file sha256 (the DTO requires 64 hex) | `full_file_hash_required` |
| a `mask`/`graph`/`pose_sheet` artifact is never publishable; `publishable_types` may only narrow the server set | `artifact_not_publishable` |
| unknown contract version refuses | `schema_version_unsupported` |
| outcome/input/output/error consistency (completed ⇒ input+output, no error, …) | `record_inconsistent` |
| an engine RESULT needs a recorded decoded frame map — record it, do not invent it | `engine_result_incomplete` |
| the accepted DTO is not in this tree yet (INT transport pending) | `media_engine_dto_unavailable` |

## 3. Composition with the accepted media-engine contract v1

* Accepted bytes: `app/schemas/media_engine.py`, git blob
  `9e4586a1b2cbc8aeb6d35a75c038327533b81b2a` at `f0b918b` (CONTRACT branch of
  MF-TOOL-CONTRACT).  Blob id re-verified by `git hash-object` in the evidence
  probe; the file's sha256 is `5900c911aed68f586f0a17f8f1b5ae439aa0e8c540d3987b8d979095bc6e6bbe`.
* `EngineInputBinding.to_request_payload()` emits EXACTLY the
  `MediaEngineRequest` field sets (`workspace_id…budget`; nested models by their
  own field names).  The DTO's two refusal-only fields (`client_path`,
  `client_graph`) are deliberately NOT emitted — they exist so client input can
  be refused, and `ENGINE_REQUEST_TOP_LEVEL_FIELDS` therefore excludes them.
* `to_engine_request()` constructs the REAL DTO when it is importable;
  otherwise it refuses with `media_engine_dto_unavailable` (fail closed — no
  stub, no re-implementation, no silent degradation).  The transport itself is
  an INT job (EXECUTION_CONTRACT §3); MF-END-01 neither performs nor blocks it.
* Pinned vocabulary (cross-checked against the real DTO by the evidence probe):
  capabilities, artifact kinds, publishable kinds, server output types,
  `CAPABILITY_REFERENCE_REQUIREMENTS` minima.
* The `ShotRange` boundary is explicit: this contract's span is half-open
  `[start, end)`, the DTO's is INCLUSIVE — `to_engine_shot_range()` subtracts 1
  and `from_engine_shot_range()` adds 1 back; both are test rows.
* Model pin gap (open item O1): the P0 inventory recorded only 16-hex head-hashes
  (first 1 MiB).  MF-END-01 MEASURED the full-file sha256 of the five pinned
  Wan Animate 2 profile files (probe `probe_model_full_hashes.py`, 17.65 s,
  read-only) and re-derived every head-hash to prove provenance; the frozen
  example uses the full digests.  `revision` stays `null` because no
  provisioning revision was ever recorded — the projection refuses a null
  revision with a typed code (open item O1) instead of inventing one.

## 4. Frozen example — shot plan (BOOK unit, PROOF_GATE candidate)

Values come from the measured Phase-A evidence: `P1_UNIT_MANIFESTS.json`
(BOOK-UNIT-001 span/window/elements/interactions), `P3B_RECEIPT.json` (graph,
seed, outputs), and the MF-END-01 probes (PTS span `0..60928` = `119 × 512`
ticks at `30/1` fps and `1/15360` time_base, both on the source window and on
the rendered clip; packet storage order zigzags (B-frames) while the display
span is complete: 120 distinct PTS, all multiples of 512).  App-side identity
labels (project/series/artifact/cast/evidence ids) are placeholders by design —
the cast registry is created by MF-END-02+; every hash/byte/span is measured.

<!-- FROZEN_EXAMPLE: shot_plan_book -->
```json
{
  "schema_version": "mf.shot_reskin.contract.v1",
  "project_id": "demo-project-r28",
  "series_id": "demo-series-r28",
  "video_id": "demo-video-book",
  "unit_id": "BOOK-UNIT-001",
  "shot_id": "BOOK",
  "source": {
    "artifact_id": "artifact.book.source_window",
    "kind": "video",
    "sha256": "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
    "store_relative_path": "inputs/BOOK_src.mp4",
    "size_bytes": 141833
  },
  "span": {
    "start_frame": 0,
    "end_frame_exclusive": 120
  },
  "timebase": {
    "fps_num": 30,
    "fps_den": 1,
    "stream_timebase_num": 1,
    "stream_timebase_den": 15360,
    "pts_start_ticks": 0,
    "pts_end_ticks": 60928,
    "decoded_frame_count": 120
  },
  "elements": [
    {
      "role": "source_frame",
      "kind": "source_frame",
      "visible_spans": [
        {
          "start_frame": 0,
          "end_frame_exclusive": 120
        }
      ],
      "occlusion": "visible"
    },
    {
      "role": "BOOK-P1",
      "kind": "person",
      "visible_spans": [
        {
          "start_frame": 0,
          "end_frame_exclusive": 120
        }
      ],
      "occlusion": "visible"
    },
    {
      "role": "BOOK-P2",
      "kind": "person",
      "visible_spans": [
        {
          "start_frame": 0,
          "end_frame_exclusive": 120
        }
      ],
      "occlusion": "visible"
    },
    {
      "role": "BOOK-P3",
      "kind": "person",
      "visible_spans": [
        {
          "start_frame": 0,
          "end_frame_exclusive": 120
        }
      ],
      "occlusion": "visible"
    },
    {
      "role": "BOOK-P4",
      "kind": "person",
      "visible_spans": [
        {
          "start_frame": 0,
          "end_frame_exclusive": 120
        }
      ],
      "occlusion": "visible"
    },
    {
      "role": "book",
      "kind": "prop",
      "visible_spans": [
        {
          "start_frame": 0,
          "end_frame_exclusive": 120
        }
      ],
      "occlusion": "visible"
    },
    {
      "role": "yellow_part",
      "kind": "prop",
      "visible_spans": [
        {
          "start_frame": 0,
          "end_frame_exclusive": 72
        },
        {
          "start_frame": 105,
          "end_frame_exclusive": 120
        }
      ],
      "occlusion": "visible"
    },
    {
      "role": "table",
      "kind": "prop",
      "visible_spans": [
        {
          "start_frame": 0,
          "end_frame_exclusive": 120
        }
      ],
      "occlusion": "visible"
    }
  ],
  "interactions": [
    {
      "subject_role": "BOOK-P1",
      "relation": "holds",
      "object_role": "book",
      "spans": [
        {
          "start_frame": 0,
          "end_frame_exclusive": 72
        }
      ],
      "evidence_ids": [
        "EV-BOOK-P1-HOLDS-BOOK"
      ],
      "state": "measured"
    },
    {
      "subject_role": "BOOK-P1",
      "relation": "holds",
      "object_role": "book",
      "spans": [
        {
          "start_frame": 72,
          "end_frame_exclusive": 120
        }
      ],
      "evidence_ids": [
        "EV-BOOK-BOOKSTATE-OPEN-72"
      ],
      "state": "measured"
    },
    {
      "subject_role": "BOOK-P1",
      "relation": "holds",
      "object_role": "yellow_part",
      "spans": [
        {
          "start_frame": 0,
          "end_frame_exclusive": 72
        },
        {
          "start_frame": 105,
          "end_frame_exclusive": 120
        }
      ],
      "evidence_ids": [
        "EV-BOOK-P1-HOLDS-BOOK"
      ],
      "state": "measured"
    },
    {
      "subject_role": "BOOK-P3",
      "relation": "sits_behind",
      "object_role": "table",
      "spans": [
        {
          "start_frame": 0,
          "end_frame_exclusive": 120
        }
      ],
      "evidence_ids": [
        "EV-BOOK-P3-BACK-TO-CAMERA"
      ],
      "state": "measured"
    }
  ],
  "reference_manifest": {
    "style_version": "roundD-style-1",
    "roles": [
      {
        "role": "BOOK-P1",
        "character_id": "cast-boy-hacker",
        "pack_version_id": "demo-packversion-r28",
        "items": [
          {
            "key": "identity_anchor",
            "artifact": {
              "artifact_id": "artifact.book.ref.BOOK-P1",
              "kind": "image",
              "sha256": "a60969452f904e5e7249db1ff43d7b552f8d7105fa6bff84c6bc32b9273d02c4",
              "store_relative_path": "inputs/i1d_cast_boy_hacker_sitting_on_neutral_bg.png",
              "size_bytes": 3586
            }
          }
        ]
      },
      {
        "role": "BOOK-P2",
        "character_id": "cast-dan-choi",
        "pack_version_id": "demo-packversion-r28",
        "items": [
          {
            "key": "identity_anchor",
            "artifact": {
              "artifact_id": "artifact.book.ref.BOOK-P2",
              "kind": "image",
              "sha256": "271f1c5789ee8fb9022ab402d834c8f2d4e862f972a105060e457b68b0282496",
              "store_relative_path": "inputs/i1d_cast_dan_choi_standing_on_neutral_bg.png"
            }
          }
        ]
      },
      {
        "role": "BOOK-P3",
        "character_id": "cast-gau-nau",
        "pack_version_id": "demo-packversion-r28",
        "items": [
          {
            "key": "identity_anchor",
            "artifact": {
              "artifact_id": "artifact.book.ref.BOOK-P3",
              "kind": "image",
              "sha256": "9658aa3a947ffbf3c062757380438c36eb05bd2959444dddc659afbc60bffd11",
              "store_relative_path": "inputs/i1d_cast_gau_nau_back_on_neutral_bg.png"
            }
          }
        ]
      }
    ]
  },
  "source_evidence": [
    {
      "evidence_id": "EV-BOOK-P1-HOLDS-BOOK",
      "subject_role": "BOOK-P1",
      "kind": "holder",
      "span": {
        "start_frame": 0,
        "end_frame_exclusive": 120
      },
      "artifact": {
        "artifact_id": "artifact.book.source_window",
        "kind": "video",
        "sha256": "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
        "store_relative_path": "inputs/BOOK_src.mp4",
        "size_bytes": 141833
      },
      "state": "measured"
    },
    {
      "evidence_id": "EV-BOOK-BOOKSTATE-OPEN-72",
      "subject_role": "BOOK-P1",
      "kind": "event",
      "span": {
        "start_frame": 72,
        "end_frame_exclusive": 120
      },
      "artifact": {
        "artifact_id": "artifact.book.source_window",
        "kind": "video",
        "sha256": "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
        "store_relative_path": "inputs/BOOK_src.mp4",
        "size_bytes": 141833
      },
      "state": "measured"
    },
    {
      "evidence_id": "EV-BOOK-P3-BACK-TO-CAMERA",
      "subject_role": "BOOK-P3",
      "kind": "presence",
      "span": {
        "start_frame": 0,
        "end_frame_exclusive": 120
      },
      "artifact": {
        "artifact_id": "artifact.book.source_window",
        "kind": "video",
        "sha256": "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
        "store_relative_path": "inputs/BOOK_src.mp4",
        "size_bytes": 141833
      },
      "state": "measured"
    }
  ],
  "output_observations": {
    "state": "unmeasured",
    "source_artifact": {
      "artifact_id": "artifact.book.source_window",
      "kind": "video",
      "sha256": "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
      "store_relative_path": "inputs/BOOK_src.mp4",
      "size_bytes": 141833
    },
    "output_artifact": {
      "artifact_id": "artifact.book.p3b.clip",
      "kind": "video",
      "sha256": "dfc4e37b81ba4252635581a6f75fef1084324dcd7af9015e3ea3e2c86b90d77f",
      "store_relative_path": "p3b/animate2_book_p3b_00001_.mp4",
      "size_bytes": 208053
    }
  }
}
```
<!-- /FROZEN_EXAMPLE: shot_plan_book -->

## 5. Frozen example — execution record (P3B BOOK, comfy backend)

`prompt_id`, output file names/bytes/sha256, wall time `154.67 s` and
VRAM peak `10973 MiB` are the P3B receipt values; the graph hash is the
submitted graph; `config_hash` is sha256 of the canonical `declared_params`
JSON from the receipt (recomputed in `raw/probe_dto_composition.json` payload
evidence).  `server_output_type` is `unclassified` on every artifact because
the receipts record no server classification — and an unclassified node output
is never publishable (NR05.4); the contract mirrors that instead of claiming
`output`.  Budget numbers are the demo POLICY caps: wall 900 s (cold BOOK run
measured 596.95 s), VRAM cap = the device total 12,227 MiB, output cap 512 MiB.
The engine-request payload built from this record (with the provisioning
revision label supplied) has canonical sha256
`a81db36912ec6b20389d4cf205703b05dbb28de1ca693b9812b1e600d87bb3bd`.

<!-- FROZEN_EXAMPLE: execution_record_book_p3b -->
```json
{
  "schema_version": "mf.shot_reskin.contract.v1",
  "execution_backend": "comfy_shot_engine",
  "legacy_route": null,
  "capability": "source_video_motion_transfer",
  "outcome": "completed",
  "input": {
    "capability": "source_video_motion_transfer",
    "identity": {
      "workspace_id": "demo-workspace",
      "project_id": "demo-project-r28",
      "series_id": "demo-series-r28",
      "video_id": "demo-video-book",
      "stage": "shot_render",
      "attempt_id": "attempt-book-p3b-1",
      "job_id": null
    },
    "source": {
      "source_artifact_id": "artifact.book.source_window",
      "source_sha256": "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
      "span": {
        "start_frame": 0,
        "end_frame_exclusive": 120
      },
      "timebase": {
        "fps_num": 30,
        "fps_den": 1,
        "stream_timebase_num": 1,
        "stream_timebase_den": 15360,
        "pts_start_ticks": 0,
        "pts_end_ticks": 60928,
        "decoded_frame_count": 120
      },
      "decoded_frame_count": 120
    },
    "cast": [
      {
        "role": "BOOK-P1",
        "character_id": "cast-boy-hacker",
        "pack_version_id": "demo-packversion-r28",
        "references": [
          {
            "key": "identity_anchor",
            "artifact": {
              "artifact_id": "artifact.book.ref.BOOK-P1",
              "kind": "image",
              "sha256": "a60969452f904e5e7249db1ff43d7b552f8d7105fa6bff84c6bc32b9273d02c4",
              "store_relative_path": "inputs/i1d_cast_boy_hacker_sitting_on_neutral_bg.png",
              "size_bytes": 3586
            }
          }
        ]
      },
      {
        "role": "BOOK-P2",
        "character_id": "cast-dan-choi",
        "pack_version_id": "demo-packversion-r28",
        "references": [
          {
            "key": "identity_anchor",
            "artifact": {
              "artifact_id": "artifact.book.ref.BOOK-P2",
              "kind": "image",
              "sha256": "271f1c5789ee8fb9022ab402d834c8f2d4e862f972a105060e457b68b0282496",
              "store_relative_path": "inputs/i1d_cast_dan_choi_standing_on_neutral_bg.png"
            }
          }
        ]
      },
      {
        "role": "BOOK-P3",
        "character_id": "cast-gau-nau",
        "pack_version_id": "demo-packversion-r28",
        "references": [
          {
            "key": "identity_anchor",
            "artifact": {
              "artifact_id": "artifact.book.ref.BOOK-P3",
              "kind": "image",
              "sha256": "9658aa3a947ffbf3c062757380438c36eb05bd2959444dddc659afbc60bffd11",
              "store_relative_path": "inputs/i1d_cast_gau_nau_back_on_neutral_bg.png"
            }
          }
        ]
      }
    ],
    "anchor": {
      "artifact_id": "artifact.book.anchor_p2",
      "kind": "image",
      "sha256": "aa08747048c42af56c9e5109b7a041d2f8d95bf7c79544017ef38b98bbb6455e",
      "store_relative_path": "inputs/anchor_book_p2_00001_.png"
    },
    "source_window": {
      "artifact_id": "artifact.book.source_window",
      "kind": "video",
      "sha256": "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
      "store_relative_path": "inputs/BOOK_src.mp4",
      "size_bytes": 141833
    },
    "graph": {
      "workflow_id": "mf.comfy.wan_animate2.motion_transfer",
      "workflow_version": "p3b",
      "workflow_hash": "b2ab500748d5163797ccef71e6ed9e078682440a656afd6ae4ab4cf43234a36d",
      "model": {
        "model_id": "wan_animate_2_int8_convrot",
        "revision": null,
        "file": {
          "algorithm": "sha256",
          "scope": "full_file",
          "value": "0580ecdd65e47e97c30df9670d13a6c4a131d26de5a1faf2ccc78392d5167584"
        },
        "precision": "int8",
        "size_bytes": 16653175528
      },
      "nodes": [],
      "config_hash": "932454b6b5c4a33a5bffe10b3e67a042cab0471acdab7e4219ce3d5d20fca532",
      "seed": 582699151003550
    },
    "auxiliary_models": [
      {
        "model_id": "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16",
        "revision": null,
        "file": {
          "algorithm": "sha256",
          "scope": "full_file",
          "value": "85c4a61c30e0497aa44b91d93a893b624708461a56fe5485183b28fa07e2dfb3"
        },
        "precision": "bf16",
        "size_bytes": 738005744
      },
      {
        "model_id": "umt5_xxl_fp8_e4m3fn_scaled",
        "revision": null,
        "file": {
          "algorithm": "sha256",
          "scope": "full_file",
          "value": "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68"
        },
        "precision": "fp8_e4m3fn",
        "size_bytes": 6735906897
      },
      {
        "model_id": "clip_vision_h",
        "revision": null,
        "file": {
          "algorithm": "sha256",
          "scope": "full_file",
          "value": "64a7ef761bfccbadbaa3da77366aac4185a6c58fa5de5f589b42a65bcc21f161"
        },
        "precision": "not_recorded",
        "size_bytes": 1264219396
      },
      {
        "model_id": "Wan2_1_VAE_bf16",
        "revision": null,
        "file": {
          "algorithm": "sha256",
          "scope": "full_file",
          "value": "1ab9a32cc2c740f6e39d80d367ce5dcc28db8c71b79b28670546b8973e9d75f9"
        },
        "precision": "bf16",
        "size_bytes": 253806278
      }
    ],
    "output_contract": {
      "width": 640,
      "height": 368,
      "fps_num": 30,
      "fps_den": 1,
      "frame_count": 120,
      "container": "mp4",
      "video_codec": "h264",
      "audio": {
        "mode": "source_remux",
        "source_artifact_id": "artifact.book.source_window",
        "sample_rate": 44100,
        "channels": 2,
        "codec": "aac"
      },
      "stream_timebase_num": 1,
      "stream_timebase_den": 15360,
      "publishable_types": [
        "output"
      ]
    },
    "budget": {
      "resource_class": "gpu_12gb",
      "max_wall_seconds": 900.0,
      "max_vram_bytes": 12821706752,
      "max_output_bytes": 536870912
    }
  },
  "output": {
    "prompt_id": "d1f4e097-458d-4bd4-8049-fe6da26f91c1",
    "owner_session": null,
    "graph_sha256_server": "b2ab500748d5163797ccef71e6ed9e078682440a656afd6ae4ab4cf43234a36d",
    "artifacts": [
      {
        "artifact_id": "artifact.book.p3b.clip",
        "kind": "video",
        "media_type": "video/mp4",
        "sha256": "dfc4e37b81ba4252635581a6f75fef1084324dcd7af9015e3ea3e2c86b90d77f",
        "store_relative_path": "p3b/animate2_book_p3b_00001_.mp4",
        "size_bytes": 208053
      },
      {
        "artifact_id": "artifact.book.p3b.still_first",
        "kind": "video",
        "media_type": "video/mp4",
        "sha256": "a0eb2577607aec9408e4ca8d418ed222fd5c9b9ce941340c10483fc6a2785588",
        "store_relative_path": "p3b/animate2_book_p3b_00002_.mp4",
        "size_bytes": 26407
      },
      {
        "artifact_id": "artifact.book.p3b.composite",
        "kind": "video",
        "media_type": "video/mp4",
        "sha256": "d1939c5aae91be6190215935f371c719c8d6f1f420cda06c21c74c969e139276",
        "store_relative_path": "p3b/animate2_book_p3b_00003_.mp4",
        "size_bytes": 238389
      },
      {
        "artifact_id": "artifact.book.p3b.still_second",
        "kind": "video",
        "media_type": "video/mp4",
        "sha256": "3570d93eb155999d146fa84c978f1c5877b5f01ed6cba39b21da9852309bbead",
        "store_relative_path": "p3b/animate2_book_p3b_00004_.mp4",
        "size_bytes": 36543
      }
    ],
    "decoded": {
      "decoded_frames": 120,
      "first_pts_ticks": 0,
      "timebase": "1/15360"
    },
    "audio": {
      "mode": "source_remux",
      "source_artifact_id": "artifact.book.source_window",
      "sample_rate": 44100,
      "channels": 2,
      "codec": "aac"
    },
    "server_side_wall_s": 154.67,
    "vram_peak_mib": 10973
  },
  "error": null
}
```
<!-- /FROZEN_EXAMPLE: execution_record_book_p3b -->

## 6. Negative fixtures (machine-readable, used by the tests)

Each fixture patches one of the frozen examples (`set` = dotted path → value,
`append` = append to the list at the path) and MUST refuse with the listed code.
The test file parametrizes over this array, so the doc block, the module
constant and the test rows are one source.  Every `set` on `sha256` uses a REAL
hash from the proof evidence as the "foreign" value — no invented digests.

<!-- FROZEN_EXAMPLE: negative_fixtures -->
```json
[
  {
    "id": "N01_client_path_on_reference",
    "base": "shot_plan_book",
    "set": [
      [
        "reference_manifest.roles.0.items.0.artifact.path",
        "C:/tmp/cast.png"
      ]
    ],
    "expected_refusal_code": "client_artifact_path_refused",
    "note": "a client path is refused by the contract, never resolved"
  },
  {
    "id": "N02_foreign_role_in_interaction",
    "base": "shot_plan_book",
    "set": [
      [
        "interactions.0.subject_role",
        "BOOK-P9"
      ]
    ],
    "expected_refusal_code": "foreign_role_refused",
    "note": "interaction may only name declared element roles"
  },
  {
    "id": "N03_foreign_role_in_manifest",
    "base": "shot_plan_book",
    "set": [
      [
        "reference_manifest.roles.0.role",
        "BOOK-P9"
      ]
    ],
    "expected_refusal_code": "foreign_role_refused",
    "note": "manifest may only carry declared roles"
  },
  {
    "id": "N04_invalid_interval_span",
    "base": "shot_plan_book",
    "set": [
      [
        "span.end_frame_exclusive",
        0
      ]
    ],
    "expected_refusal_code": "invalid_interval_refused",
    "note": "empty/negative half-open interval"
  },
  {
    "id": "N05_invalid_interval_element_outside",
    "base": "shot_plan_book",
    "set": [
      [
        "elements.0.visible_spans.0.end_frame_exclusive",
        500
      ]
    ],
    "expected_refusal_code": "invalid_interval_refused",
    "note": "element visibility must stay inside the shot span"
  },
  {
    "id": "N06_timebase_half_pair",
    "base": "shot_plan_book",
    "set": [
      [
        "timebase.stream_timebase_den",
        null
      ]
    ],
    "expected_refusal_code": "timebase_invalid",
    "note": "time_base is declared as a pair or not at all"
  },
  {
    "id": "N07_timebase_zero_span_multiframe",
    "base": "shot_plan_book",
    "set": [
      [
        "timebase.pts_start_ticks",
        0
      ],
      [
        "timebase.pts_end_ticks",
        0
      ]
    ],
    "expected_refusal_code": "timebase_invalid",
    "note": "a 120-frame span cannot be a point in time"
  },
  {
    "id": "N08_timebase_pts_capacity",
    "base": "shot_plan_book",
    "set": [
      [
        "timebase.pts_end_ticks",
        4096
      ]
    ],
    "expected_refusal_code": "timebase_invalid",
    "note": "119 frame intervals need >= 60928 ticks at 30/1 and 1/15360"
  },
  {
    "id": "N09_legacy_route_as_backend",
    "base": "execution_record_book_p3b",
    "set": [
      [
        "execution_backend",
        "sprite_affine"
      ]
    ],
    "expected_refusal_code": "legacy_route_as_backend_refused",
    "note": "a legacy renderer route is never an execution backend"
  },
  {
    "id": "N10_comfy_with_legacy_route",
    "base": "execution_record_book_p3b",
    "set": [
      [
        "legacy_route",
        "pose_swap"
      ]
    ],
    "expected_refusal_code": "backend_binding_invalid",
    "note": "Comfy does not alias a legacy route"
  },
  {
    "id": "N11_backend_unknown",
    "base": "execution_record_book_p3b",
    "set": [
      [
        "execution_backend",
        "comfy_engine2"
      ]
    ],
    "expected_refusal_code": "backend_unknown_refused",
    "note": "backend vocabulary is closed"
  },
  {
    "id": "N12_capability_missing",
    "base": "execution_record_book_p3b",
    "set": [
      [
        "capability",
        null
      ]
    ],
    "expected_refusal_code": "engine_capability_required",
    "note": "comfy backend without a capability is refused"
  },
  {
    "id": "N13_schema_version_unsupported",
    "base": "execution_record_book_p3b",
    "set": [
      [
        "schema_version",
        "mf.shot_reskin.contract.v0"
      ]
    ],
    "expected_refusal_code": "schema_version_unsupported",
    "note": "versioned contract; unknown version refuses"
  },
  {
    "id": "N14_output_binds_source_artifact",
    "base": "shot_plan_book",
    "set": [
      [
        "output_observations.output_artifact.sha256",
        "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc"
      ]
    ],
    "expected_refusal_code": "output_binds_source_artifact",
    "note": "the source returned as output is refused (MF-END-19 acceptance)"
  },
  {
    "id": "N15_source_fact_measured_on_foreign_artifact",
    "base": "shot_plan_book",
    "set": [
      [
        "source_evidence.0.artifact.sha256",
        "aa08747048c42af56c9e5109b7a041d2f8d95bf7c79544017ef38b98bbb6455e"
      ]
    ],
    "expected_refusal_code": "evidence_domain_mismatch",
    "note": "source facts are measured on the locked source"
  },
  {
    "id": "N16_output_binding_names_foreign_source",
    "base": "shot_plan_book",
    "set": [
      [
        "output_observations.source_artifact.sha256",
        "aa08747048c42af56c9e5109b7a041d2f8d95bf7c79544017ef38b98bbb6455e"
      ]
    ],
    "expected_refusal_code": "evidence_domain_mismatch",
    "note": "the output binding must name THIS shot's locked source"
  },
  {
    "id": "N17_unknown_evidence_ref",
    "base": "shot_plan_book",
    "set": [
      [
        "interactions.0.evidence_ids.0",
        "EV-NOPE"
      ]
    ],
    "expected_refusal_code": "unknown_evidence_refused",
    "note": "interaction evidence must exist in source_evidence"
  },
  {
    "id": "N18_duplicate_role",
    "base": "shot_plan_book",
    "append": [
      [
        "elements",
        {
          "role": "BOOK-P1",
          "kind": "person"
        }
      ]
    ],
    "expected_refusal_code": "duplicate_role_refused",
    "note": "element roles are unique within a shot"
  },
  {
    "id": "N19_model_pin_head_hash_only",
    "base": "execution_record_book_p3b",
    "set": [
      [
        "input.graph.model.file",
        {
          "algorithm": "sha256",
          "scope": "head_1mib",
          "value": "f7ba70b820aa441f"
        }
      ]
    ],
    "expected_refusal_code": "full_file_hash_required",
    "note": "the engine pin needs the full-file sha256, not a head-hash"
  },
  {
    "id": "N20_mask_publishable",
    "base": "execution_record_book_p3b",
    "set": [
      [
        "output.artifacts.0.kind",
        "mask"
      ],
      [
        "output.artifacts.0.publishable",
        true
      ]
    ],
    "expected_refusal_code": "artifact_not_publishable",
    "note": "a mask is managed but never publishable"
  },
  {
    "id": "N21_artifact_path_escape",
    "base": "execution_record_book_p3b",
    "set": [
      [
        "output.artifacts.0.store_relative_path",
        "../escape.mp4"
      ]
    ],
    "expected_refusal_code": "client_artifact_path_refused",
    "note": "store-relative only; traversal refuses"
  },
  {
    "id": "N22_cast_reference_required",
    "base": "execution_record_book_p3b",
    "set": [
      [
        "input.cast.0.references",
        []
      ]
    ],
    "expected_refusal_code": "cast_reference_required",
    "note": "motion transfer needs reference pixels per bound role"
  },
  {
    "id": "N23_completed_without_output",
    "base": "execution_record_book_p3b",
    "set": [
      [
        "output",
        null
      ]
    ],
    "expected_refusal_code": "record_inconsistent",
    "note": "outcome=completed requires the output binding"
  }
]
```
<!-- /FROZEN_EXAMPLE: negative_fixtures -->

## 7. Source vs output evidence (U08 / U21)

* A `SourceEvidenceFact` (domain `source`) must be measured on the locked source
  artifact; a foreign artifact refuses (`evidence_domain_mismatch`).
* An `OutputObservation` (domain `output`) must be measured on the rendered
  artifact the binding names; anything else refuses.
* `OutputObservationBinding` refuses an output whose sha equals the source
  (`output_binds_source_artifact`) — the "source returned as output" case the
  MF-END-19 acceptance names.
* `state=unmeasured` must carry no observations: absence of data is visible as
  UNKNOWN, never as an empty list that reads like a pass.
* The frozen output binding is `unmeasured` on purpose: role-level output
  observations are produced by MF-END-21; the binding freezes the artifact
  identity today so those observations are domain-pinned the moment they exist.

## 8. Legacy route orthogonality

`app/persistence/models.py::RENDERER_ROUTES` = (`pose_swap`, `sprite_affine`,
`mesh_warp`, `part_rig`, `controlled_redraw`) is untouched; the values are
PINNED in this module (`LEGACY_RENDERER_ROUTES_PIN`) so a legacy route used as
an `execution_backend` refuses with `legacy_route_as_backend_refused`, a comfy
record carrying a `legacy_route` refuses, and a legacy record carrying engine
capability/input/output refuses.  Comfy is a backend, not a route alias.

## 9. Open items (recorded, not fixed here)

* **O1** — the P0 model inventory records no provisioning `revision`; engine
  pin projection refuses a null revision (typed).  Owner: MF-END-16 (model
  profiles) / provisioning.
* **O2** — the partial person `BOOK-P4` (right-edge sliver, visible all 120
  frames) has NO reference artwork yet; the plan freezes its element and the
  demo coverage finding F2 (DEMO_PROOF_REVIEW) tracks it.  Owner: MF-END-12/14.
* **O3** — book-state policy (Wan keeps the book closed while the source opens
  it at frame 72) is a product decision; the contract can express the change
  (two interaction spans) but does not decide it.  Owner: Codex (F3).
* **O4** — the receipts record no per-node pins and no decoded frame map;
  `nodes: []` and `mapping: null` in the examples are the measured truth, and
  `assert_result_ready()` refuses a result without a map.  Owner: MF-END-18/19.
* **O5** — server output classification (`server_output_type`) is absent from
  the receipts; every frozen artifact is `unclassified` (never publishable).

## 10. Verification

* Frozen examples validate; 23/23 negative fixtures refuse with their exact
  codes; payload key sets equal the accepted DTO field sets; payload digest is
  frozen (`a81db36912ec6b20389d4cf205703b05dbb28de1ca693b9812b1e600d87bb3bd`); `to_engine_request` fails closed without the
  transported DTO; the composition probe builds a REAL `MediaEngineRequest`
  from the pinned blob (22 rows) including four DTO-side negatives.
* Raw evidence: `MF-END-01/raw/probe_selfcheck.json`,
  `MF-END-01/raw/probe_dto_composition.json`, `MF-END-01/commands.jsonl`,
  `MF-END-01/REPORT.md`.
