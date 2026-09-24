"""Case registry for the product-P1 public chain (step -> case -> status).

Pure data + pure helpers: imported by the tests, by the evidence emitter and
by the report.  No pytest fixtures, no product imports, no I/O.
"""

from __future__ import annotations

from typing import Any

RUNNABLE_NOW = "RUNNABLE_NOW"
PENDING_FROZEN_CANDIDATE = "PENDING_FROZEN_CANDIDATE"

PKG = "tests/product_p1/public_chain"

#: The full public path this suite must cover (packet §2), in chain order.
CHAIN_STEPS: tuple[dict[str, Any], ...] = (
    {
        "order": 1,
        "step": "public_upload",
        "title": "public upload (project + media through public HTTP only)",
        "routes": (("POST", "/api/projects"), ("POST", "/api/projects/{project_id}/video")),
        "pending_reason": "the upload leg is only meaningful against the frozen candidate's "
        "real source media; the fixture upload is a FIXTURE, not product media evidence",
    },
    {
        "order": 2,
        "step": "analyze",
        "title": "analyze / import / proxy / scene partition",
        "routes": (("POST", "/api/projects/{project_id}/analyze"),),
        "pending_reason": "analyze needs the frozen candidate source media + durable worker "
        "claim; runnable-now coverage is the route/authority contract only",
    },
    {
        "order": 3,
        "step": "library_roles",
        "title": "object library + current roles/segments (DISCOVER_OBJECTS output)",
        "routes": (
            ("POST", "/api/v2/object-intelligence/extraction"),
            ("GET", "/api/v2/object-intelligence/extraction/current"),
            ("GET", "/api/v2/object-intelligence/extraction/{job_id}/segments"),
        ),
        "pending_reason": "real extraction output requires the frozen candidate; no seeding of "
        "roles/segments is permitted, so the executed case waits for the freeze",
    },
    {
        "order": 4,
        "step": "producer",
        "title": "structural-lock producer (public POST, owner authority)",
        "routes": (("POST", "/api/v2/projects/{project_id}/videos/{video_item_id}/structural-lock"),),
        "pending_reason": "producer needs a real analyzed video item; the executed case waits "
        "for the freeze",
    },
    {
        "order": 5,
        "step": "approval",
        "title": "S09 approval / reapproval + server-owned full-apply authority",
        "routes": (
            ("POST", "/api/v2/s09-approvals/reapprove"),
            ("GET", "/api/v2/s09-approvals/{checkpoint_id}/full-apply-authority"),
        ),
        "pending_reason": "the executed reapproval must freeze the real manifest/roles; the "
        "points-only denial and boxed positive controls run now in "
        "tests/test_s09_t06_backend_authority.py",
    },
    {
        "order": 6,
        "step": "s10_full_apply",
        "title": "S10 Full Apply (durable run -> completed publication)",
        "routes": (
            ("POST", "/api/v2/projects/{project_id}/full-apply"),
            ("GET", "/api/v2/full-apply/{run_id}"),
        ),
        "pending_reason": "Full Apply renders; it is a frozen-candidate step and was BLOCKED at "
        "this node in the R6 round (evidence on record)",
    },
    {
        "order": 7,
        "step": "audio",
        "title": "original-audio attach (durable job)",
        "routes": (("POST", "/api/v2/projects/{project_id}/original-audio-attach"),),
        "pending_reason": "needs a completed S10 publication to attach to; waits for the freeze",
    },
    {
        "order": 8,
        "step": "qc_full",
        "title": "full QC check run + items + navigation + readiness",
        "routes": (
            ("POST", "/api/v2/projects/{project_id}/qc-check-runs"),
            ("GET", "/api/v2/projects/{project_id}/qc-check-runs/{video_item_id}"),
            ("GET", "/api/v2/projects/{project_id}/qc-check-runs/{video_item_id}/readiness"),
            ("GET", "/api/v2/projects/{project_id}/qc-items"),
            ("GET", "/api/v2/qc-navigation/{item_id}"),
        ),
        "pending_reason": "QC eligibility + QC results must be EARNED by the chain; seeding them "
        "is forbidden, so the executed full-QC case waits for the QC freeze",
    },
    {
        "order": 9,
        "step": "s12_api",
        "title": "S12 export context / preflight / submit / run state",
        "routes": (
            ("GET", "/api/v2/projects/{project_id}/export/context"),
            ("POST", "/api/v2/projects/{project_id}/export/preflight"),
            ("POST", "/s12-exports/submit"),
            ("GET", "/s12-exports/{run_id}"),
        ),
        "pending_reason": "a real submit needs a completed Full Apply + pinned checkpoint on the "
        "frozen candidate",
    },
    {
        "order": 10,
        "step": "worker",
        "title": "durable s12_export worker (claim -> render -> stitch)",
        "routes": (("GET", "/s12-exports/{run_id}"), ("POST", "/s12-exports/{run_id}/retry")),
        "pending_reason": "worker claims/render require the frozen candidate and real encode",
    },
    {
        "order": 11,
        "step": "publisher",
        "title": "production publisher (lease-fenced atomic publication + result identity)",
        "routes": (("GET", "/s12-exports/{run_id}/result"),),
        "pending_reason": "publication happens only after a real render+validation on the "
        "frozen candidate",
    },
    {
        "order": 12,
        "step": "download",
        "title": "download the published media through the public route",
        "routes": (("GET", "/s12-exports/{run_id}/media"),),
        "pending_reason": "there is no published media to download until the full chain has run "
        "on the frozen candidate",
    },
    {
        "order": 13,
        "step": "ui_reload",
        "title": "UI submit + reload (client contract against the same public routes)",
        "routes": (("GET", "/api/v2/projects/{project_id}/export/context"),),
        "pending_reason": "the live UI/BFF reload is executed after MF-P1-UI-BUILD and QC are "
        "terminal; only the client contract is pinned now",
    },
)

#: step -> pytest node id -> status.  Every case is either runnable now or
#: explicitly pending the frozen candidate; there is no third state.
CHAIN_CASES: tuple[dict[str, Any], ...] = (
    # ── contract surface (runnable now; no product state) ─────────────────
    {
        "id": "C-ALL-01",
        "step": "all",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_contract.py::test_every_step_route_exists_in_production_openapi",
        "asserts": "every registry route exists in the production OpenAPI surface with the "
        "declared method, exactly once, with a unique operationId",
    },
    {
        "id": "C-ALL-02",
        "step": "all",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_contract.py::test_registry_step_order_and_coverage",
        "asserts": "13 steps in chain order, each with routes and a declared disposition",
    },
    {
        "id": "C-ALL-03",
        "step": "all",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_contract.py::test_case_nodes_resolve_to_real_functions",
        "asserts": "every case node id resolves to a real file + function in this tree (no "
        "phantom coverage)",
    },
    {
        "id": "C-ALL-04",
        "step": "all",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_contract.py::test_pending_cases_declare_reason_and_freeze_dependency",
        "asserts": "every PENDING_FROZEN_CANDIDATE case names the freeze dependency; the pending "
        "list is exact",
    },
    {
        "id": "C-ALL-05",
        "step": "all",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_contract.py::test_new_suite_never_seeds_state",
        "asserts": "the new suite contains no session.add / INSERT / QC seeding — the public "
        "chain must earn its own state",
    },
    {
        "id": "C-ALL-06",
        "step": "all",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_contract.py::test_new_suite_hardcodes_no_evidence_root",
        "asserts": "no absolute evidence/product path is hardcoded in the suite (the frozen "
        "driver takes its evidence root from env)",
    },
    {
        "id": "C-UI-01",
        "step": "ui_reload",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_contract.py::test_ui_client_calls_only_public_routes",
        "asserts": "the frontend client for the export flow references the same public routes "
        "the registry declares (contract pin, not a live UI run)",
    },
    # ── typed denials, zero mutation (runnable now; no product state) ─────
    {
        "id": "C-UP-01",
        "step": "public_upload",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_denials.py::test_upload_step_unknown_project_typed_denial_zero_mutation",
        "asserts": "upload against an unknown project fails closed (typed 4xx) with zero rows "
        "created",
    },
    {
        "id": "C-QC-01",
        "step": "qc_full",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_denials.py::test_qc_step_implementation_picking_payload_denied_zero_mutation",
        "asserts": "a QC payload that tries to pick an implementation (handler/provider/"
        "detector) is rejected 422 by the strict schema with zero Job/QC rows created",
    },
    {
        "id": "C-QC-02",
        "step": "qc_full",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_denials.py::test_qc_step_unknown_video_typed_denial_zero_mutation",
        "asserts": "QC submit for an unknown video fails closed (404) with zero rows created",
    },
    {
        "id": "C-QC-03",
        "step": "qc_full",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_denials.py::test_qc_read_surfaces_fail_closed_without_state",
        "asserts": "QC read surfaces (items/navigation/readiness) answer deterministically on an "
        "empty chain and never fabricate state",
    },
    {
        "id": "C-QC-04",
        "step": "qc_full",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_denials.py::test_no_qc_state_was_seeded_or_earned",
        "asserts": "after every denial case: QC item/run counts are still 0 (nothing was seeded "
        "to make a green)",
    },
    {
        "id": "C-S12-01",
        "step": "s12_api",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_denials.py::test_s12_unknown_run_reads_and_media_denied",
        "asserts": "unknown S12 run: state/result/media reads fail closed 404",
    },
    {
        "id": "C-S12-02",
        "step": "worker",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_denials.py::test_s12_retry_and_cancel_unknown_run_denied",
        "asserts": "retry/cancel on an unknown run fail closed 404 with zero rows created",
    },
    # ── retained R6/R7 controls (runnable now) ───────────────────────────
    {
        "id": "C-CTL-01",
        "step": "all",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_media_controls.py::test_decoded_pts_monotonic_and_frame_count",
        "asserts": "decoded PTS monotonic + exact frame count on a labelled FIXTURE",
    },
    {
        "id": "C-CTL-02",
        "step": "audio",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_media_controls.py::test_audio_contract_and_absence_detected",
        "asserts": "audio presence/absence + audio contract on a labelled FIXTURE",
    },
    {
        "id": "C-CTL-03",
        "step": "download",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_media_controls.py::test_partial_output_rejected_by_product_validator",
        "asserts": "the product validator rejects a .partial / truncated output (real "
        "app.services.s12_export.validation.validate)",
    },
    {
        "id": "C-CTL-04",
        "step": "download",
        "status": RUNNABLE_NOW,
        "node": f"{PKG}/test_public_chain_media_controls.py::test_corrupt_output_fails_closed",
        "asserts": "corrupt (non-container) bytes fail the product validator, never a fake PASS",
    },
    {
        "id": "C-CTL-05",
        "step": "all",
        "status": RUNNABLE_NOW,
        "node": "tests/s12/s12-lc3-qa-r6/test_r6_controls_retained.py::test_r6_r7_control_nodes_pinned_and_present",
        "asserts": "the owned R6/R7 control nodes (partial/corrupt, stale lease, restart/retry/"
        "cancel, PTS/audio) still exist in this tree",
    },
    {
        "id": "C-CTL-06",
        "step": "all",
        "status": RUNNABLE_NOW,
        "node": "tests/s12/s12-lc3-qa-r6/test_r6_controls_retained.py::test_owned_controls_recorded_in_registry",
        "asserts": "registry control ids and the retention test agree (no silently dropped "
        "control)",
    },
    # ── executed chain: waits for the freeze ─────────────────────────────
    {
        "id": "C-E2E-01",
        "step": "all",
        "status": PENDING_FROZEN_CANDIDATE,
        "node": f"{PKG}/test_public_chain_frozen_candidate.py::test_public_chain_end_to_end_on_frozen_candidate",
        "asserts": "one bounded real chain: upload -> analyze -> library/roles -> producer -> "
        "approval -> S10 -> audio -> full QC -> S12 -> worker -> publisher -> download -> UI "
        "reload, with decoded-PTS/audio checks, partial/corrupt, stale lease, restart/retry/"
        "cancel",
        "await": "QC writers terminal + UI writers terminal + candidate SHA frozen",
    },
    {
        "id": "C-E2E-02",
        "step": "all",
        "status": PENDING_FROZEN_CANDIDATE,
        "node": f"{PKG}/test_public_chain_frozen_candidate.py::test_pending_freeze_manifest_is_exact",
        "asserts": "the pending list equals the set of steps whose contract depends on the "
        "freeze (differences fail loudly)",
        "await": "same freeze; the manifest itself is reviewable now",
    },
)

#: R6/R7 controls this lane owns and RETAINS (packet §2).  The keys MUST
#: match the pins in tests/s12/s12-lc3-qa-r6/test_r6_controls_retained.py.
RETAINED_CONTROLS: tuple[dict[str, str], ...] = (
    {
        "control": "decoded_pts",
        "where": "tests/s12/s12-lc3-qa-r6/test_r6_b01i_public_chain.py",
        "how": "ffprobe-decoded frame facts + frame-count/sequence equality on the exported media",
    },
    {
        "control": "audio_checks",
        "where": "tests/s12/s12-lc3-qa-r6/test_r6_b01i_public_chain.py",
        "how": "source vs export audio stream facts (codec/channels/sample_rate/duration)",
    },
    {
        "control": "partial_or_corrupt_output",
        "where": "tests/s12/s12-lc3-retry/test_r4_retry_execution.py",
        "how": "malformed/partial lineage and output fail closed; product validator completeness "
        "(app/services/s12_export/validation.py) rejects .partial and undecodable containers",
    },
    {
        "control": "stale_lease",
        "where": "tests/s12/s12-lc3-val/test_r7_lease_serialization.py",
        "how": "a claim-first stale lease entry is denied while the live owner completes",
    },
    {
        "control": "stale_lease_expired_reclaim",
        "where": "tests/s12/s12-lc3-val/test_r7_lease_serialization.py",
        "how": "expired/released leases are re-claimed through a guarded CAS with a fresh fence",
    },
    {
        "control": "restart_retry_cancel",
        "where": "tests/s12/s12-lc3-qa-r6/test_r6_b01i_public_chain.py",
        "how": "worker stop/restart with zero duplicate rows; public cancel leg; retry identity",
    },
    {
        "control": "r6_prep_dispatch_guard",
        "where": "tests/s12/s12-lc3-qa-r6/test_r6_b01i_prep.py",
        "how": "the B01-I dispatch stays gated until every dependency is recorded satisfied",
    },
    {
        "control": "r6_prep_exclusive_output_policy",
        "where": "tests/s12/s12-lc3-qa-r6/test_r6_b01i_prep.py",
        "how": "every run gets a NEW exclusive evidence directory (old evidence never reused)",
    },
    {
        "control": "r7_prep_inventory",
        "where": "tests/s12/s12-lc3-qa-r6/test_r7_prep_inventory.py",
        "how": "the R7 additions table freezes every case id with owner + outcome",
    },
)


#: QA3 (packet §2): engine availability is a HOST fact, never a product result.
#: When the real engine is unavailable the two things stay SEPARATE:
#:   * ``engineering_case`` -- a QA/host row: what could not be executed, why, and
#:     the measured probe that backs it.  It claims no product result at all.
#:   * ``typed_real_case`` -- a PRODUCT row for an engine-dependent chain leg, typed
#:     with its real disposition.  Never reported as "product complete".
#: They are disjoint by construction; the split is asserted in
#: test_public_chain_engine_cases.py.
ENGINE_PRODUCT_LEGS: tuple[str, ...] = ("s10_full_apply", "worker")

#: dispositions a typed real-case row may carry (never a pass).
TYPED_ENGINE_DISPOSITIONS: tuple[str, ...] = (
    "NOT_EXECUTED_ENGINE_UNAVAILABLE",
    "PENDING_FROZEN_CANDIDATE",
    "BLOCKED_DEPENDENCY",
)

ENGINE_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "E-ENG-01",
        "kind": "engineering_case",
        "title": "real render/encode engine unavailable on the CPU prep host",
        "claimed_product_result": None,
        "blocked_node": PKG + "/test_public_chain_frozen_candidate.py::"
        "test_public_chain_end_to_end_on_frozen_candidate",
        "why": "the executed chain renders (S10 Full Apply) and encodes (durable"
        " s12_export worker); without a reachable engine those legs cannot produce"
        " real media, so the chain cannot complete and no product row may be typed"
        " from it",
        "probe_env": "S12QA_EVIDENCE_OUT",
        "probe_artifact": "raw/qa3_engine_probe.json",
        "probe_command": "the QA evidence driver probes the engine endpoint/binaries"
        " and records the artifact",
        "cannot_claim": "product complete; chain green; engine render verified",
    },
    {
        "id": "E-REAL-01",
        "kind": "typed_real_case",
        "step": "s10_full_apply",
        "disposition": "NOT_EXECUTED_ENGINE_UNAVAILABLE",
        "title": "S10 Full Apply render on the frozen integrated candidate",
        "why": "renders source frames through the real engine; with the engine"
        " unavailable this leg is UNTESTED",
        "must_not_claim": "rendered output; quality acceptance",
    },
    {
        "id": "E-REAL-02",
        "kind": "typed_real_case",
        "step": "worker",
        "disposition": "NOT_EXECUTED_ENGINE_UNAVAILABLE",
        "title": "durable s12_export worker render/stitch",
        "why": "the worker encodes the export; without the engine the encode leg"
        " is UNTESTED",
        "must_not_claim": "encoded media; publisher result",
    },
)

def steps() -> list[dict[str, Any]]:
    return [dict(step) for step in CHAIN_STEPS]


def step(step_id: str) -> dict[str, Any]:
    for entry in CHAIN_STEPS:
        if entry["step"] == step_id:
            return dict(entry)
    raise KeyError(step_id)


def cases(status: str | None = None) -> list[dict[str, Any]]:
    return [
        dict(case)
        for case in CHAIN_CASES
        if status is None or case["status"] == status
    ]


def cases_for_step(step_id: str) -> list[dict[str, Any]]:
    return [dict(case) for case in CHAIN_CASES if case["step"] == step_id]


def engine_cases(kind: str | None = None) -> list[dict[str, Any]]:
    """QA3 blocks: ``engineering_case`` rows and ``typed_real_case`` rows."""
    return [dict(row) for row in ENGINE_CASES if kind is None or row["kind"] == kind]


def pending_steps() -> list[str]:
    """Steps whose EXECUTED case is pending the freeze (declared, not implied).

    A case declared with ``step == "all"`` (the executed end-to-end chain)
    makes EVERY step pending, because the chain runs top to bottom.
    """
    pending: set[str] = set()
    all_steps = False
    for case in CHAIN_CASES:
        if case["status"] != PENDING_FROZEN_CANDIDATE:
            continue
        if case["step"] == "all":
            all_steps = True
        else:
            pending.add(case["step"])
    if all_steps:
        pending |= {entry["step"] for entry in CHAIN_STEPS}
    return [entry["step"] for entry in CHAIN_STEPS if entry["step"] in pending]


def document() -> dict[str, Any]:
    """Evidence document: step -> case -> status, plus the pending table."""
    return {
        "lane": "S12-LC3-QA",
        "wave": "A (CPU) — preparation only",
        "suite_root": PKG,
        "status_legend": {
            RUNNABLE_NOW: "runs on this tree now; no frozen pin, no seeded state",
            PENDING_FROZEN_CANDIDATE: "written against the contract; execution waits for the "
            "QC/UI freeze — reported, never stubbed",
        },
        "steps": [
            {
                "order": entry["order"],
                "step": entry["step"],
                "title": entry["title"],
                "public_routes": [f"{m} {p}" for m, p in entry["routes"]],
                "pending_reason": entry["pending_reason"],
                "cases": [
                    {
                        "id": case["id"],
                        "status": case["status"],
                        "node": case["node"],
                        "asserts": case["asserts"],
                    }
                    for case in CHAIN_CASES
                    if case["step"] in {entry["step"], "all"}
                ],
            }
            for entry in CHAIN_STEPS
        ],
        "totals": {
            "steps": len(CHAIN_STEPS),
            "cases": len(CHAIN_CASES),
            "runnable_now": len(cases(RUNNABLE_NOW)),
            "pending_frozen_candidate": len(cases(PENDING_FROZEN_CANDIDATE)),
            "engine_engineering_cases": len(engine_cases("engineering_case")),
            "engine_typed_real_cases": len(engine_cases("typed_real_case")),
        },
        "engine_legend": {
            "engineering_case": "a QA/host row: what the unavailable engine blocked, and"
            " the measured probe that backs it; carries no product claim",
            "typed_real_case": "a PRODUCT row for an engine-dependent leg, typed with its"
            " real disposition; never a product-complete claim",
        },
        "engine_cases": [dict(row) for row in ENGINE_CASES],
        "engine_product_legs": list(ENGINE_PRODUCT_LEGS),
        "pending_freeze_steps": pending_steps(),
        "retained_controls": [dict(control) for control in RETAINED_CONTROLS],
    }
