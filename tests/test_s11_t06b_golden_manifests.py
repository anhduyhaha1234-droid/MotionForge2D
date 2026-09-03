"""S11-T06B — golden expected-outcome manifest validation (W9).

Binary gates (production plan W9 · T06B):

1. Every golden scenario has a manifest: expected QCItems
   (reason_code / severity / status-at-create), expected readiness
   before/after (T03G read-authority semantics), rerun scope where
   applicable — sufficient for Scenario D + E2E-01 + E2E-02.
2. Manifests carry NO threshold boundary numbers — only the policy
   id/hash reference (binary scan against the frozen policy).
3. ``policy_content_hash`` equals the CURRENT frozen T03A policy hash —
   any drift makes the suite red (stale-manifest guard).
4. Every media reference is by NAME (T06A1 builders), never inlined
   media parameters; T03F orchestrator and T03G read-authority entries
   resolve to real, importable callables.

Isolation (same discipline as T06A1 harness): run with a SHORT
Windows-native ``--basetemp`` + ``-p no:cacheprovider`` +
``env -u MOTIONFORGE_DATABASE_URL`` (this suite touches no DB at all —
pure JSON schema + import resolution).
"""

from __future__ import annotations

import importlib
import json

from app.persistence.models import (
    QC_ITEM_SEVERITIES,
    QC_ITEM_STATUSES,
    QC_REASON_CODES,
)

from s11_qc_golden import (
    GOLDEN_DIR,
    GOLDEN_MANIFESTS,
    collect_numbers,
    iter_manifests,
    load_manifest,
    load_policy,
    policy_boundary_numbers,
    policy_ref_matches,
    validate_all,
)

#: Importable entry points of consumed T03F / T03G authorities.
_CONSUME_ENTRIES: tuple[tuple[str, str], ...] = (
    ("app.services.qc_checks.orchestrator", "run_full_check_set"),
    ("app.persistence.qc_check_runs", "check_run_readiness"),
)


def test_manifest_directory_matches_canonical_list() -> None:
    """Golden dir content == canonical GOLDEN_MANIFESTS (nothing more/less)."""
    assert GOLDEN_DIR.is_dir(), f"golden manifest dir missing: {GOLDEN_DIR}"
    on_disk = sorted(path.stem for path in GOLDEN_DIR.glob("*.json"))
    assert on_disk == sorted(GOLDEN_MANIFESTS)


def test_manifest_id_matches_filename_stem() -> None:
    for manifest_id in GOLDEN_MANIFESTS:
        manifest = load_manifest(manifest_id)
        assert manifest["manifest_id"] == manifest_id


def test_every_manifest_passes_schema_validation() -> None:
    """AC1: schema valid — items per reason_code/severity/status, policy ref,
    readiness before/after, consumes-by-name."""
    assert validate_all() == [], "schema violations:\n" + "\n".join(validate_all())


def test_expected_items_use_binding_enums_and_counts() -> None:
    """Every expected QCItem uses the binding 10-code enum + severity/status
    enums (T02A-C1) and a positive integer count."""
    for manifest in iter_manifests():
        for item in manifest["expected_qc_items"]:
            assert item["reason_code"] in QC_REASON_CODES, (
                f"{manifest['manifest_id']}: reason_code {item['reason_code']!r} "
                f"not in binding enum"
            )
            assert item["severity"] in QC_ITEM_SEVERITIES, (
                f"{manifest['manifest_id']}: severity {item['severity']!r} invalid"
            )
            assert item["status_at_create"] in QC_ITEM_STATUSES, (
                f"{manifest['manifest_id']}: status_at_create "
                f"{item['status_at_create']!r} invalid"
            )
            assert isinstance(item["expected_count"], int) and item["expected_count"] >= 1


def test_policy_ref_matches_frozen_policy_for_every_manifest() -> None:
    """AC3: manifest.policy_content_hash == frozen T03A policy content_hash.
    A stale manifest (old policy) fails immediately here."""
    policy = load_policy()
    assert policy["policy_id"] == "s11-qc-thresholds-v1"
    digest = policy["content_hash"]
    assert len(digest) == 64
    int(digest, 16)  # hex — raises ValueError if not
    for manifest in iter_manifests():
        ok, reason = policy_ref_matches(manifest)
        assert ok, f"{manifest['manifest_id']}: {reason}"


def test_no_threshold_boundary_numbers_in_any_manifest() -> None:
    """AC2 (binary scan): zero numeric literals equal to any policy boundary
    (warning/blocker/sanity min/max) anywhere in the manifest JSON —
    threshold numbers live ONLY in the frozen policy, never here."""
    boundaries = policy_boundary_numbers()
    assert boundaries, "policy boundary set must not be empty"
    for manifest in iter_manifests():
        numbers = collect_numbers(manifest)
        collisions = sorted(n for n in numbers if n in boundaries)
        assert not collisions, (
            f"{manifest['manifest_id']}: threshold boundary number(s) present: "
            f"{collisions} — manifests may only reference policy by id/hash"
        )


def test_media_references_by_name_and_resolve_to_builders() -> None:
    """W9: scenario references T06A1 builder by NAME (never inline media
    params); every referenced builder is a real callable in
    s11_qc_media_builders."""
    media_builders = importlib.import_module("s11_qc_media_builders")
    builders = {
        name
        for name in dir(media_builders)
        if callable(getattr(media_builders, name))
    }
    for manifest in iter_manifests():
        for entry in manifest["consumes"]["media"]:
            assert entry["scenario"] in media_builders.MEDIA_SCENARIOS, (
                f"{manifest['manifest_id']}: unknown media scenario "
                f"{entry['scenario']!r}"
            )
            assert entry["builder"] in builders, (
                f"{manifest['manifest_id']}: unknown builder {entry['builder']!r}"
            )
            assert entry["manifest"].endswith(f"{entry['scenario']}.json")


def test_consumed_authorities_resolve() -> None:
    """T03F orchestrator + T03G read authority entries in every manifest are
    importable callables (consume by name, verified)."""
    for module_name, entry_name in _CONSUME_ENTRIES:
        module = importlib.import_module(module_name)
        assert callable(getattr(module, entry_name)), (
            f"{module_name}.{entry_name} must be callable"
        )
    for manifest in iter_manifests():
        for key in ("orchestrator", "read_authority"):
            ref = manifest["consumes"][key]
            module = importlib.import_module(ref["module"])
            assert callable(getattr(module, ref["entry"])), (
                f"{manifest['manifest_id']}: consumes.{key} "
                f"{ref['module']}.{ref['entry']} does not resolve"
            )


def test_scenario_d_manifest_carries_targeted_rerun_truth() -> None:
    """AC1 Scenario D: rerun scope present — good scenes remain ready,
    only the affected segment reruns, recheck fails closed."""
    manifest = load_manifest("scenario_d_targeted_rerun")
    rerun = manifest.get("expected_rerun_scope")
    assert isinstance(rerun, dict), "scenario_d must declare expected_rerun_scope"
    assert rerun.get("rerun_target") == "affected_segment_only"
    assert "ready_scenes" in str(rerun.get("unchanged", ""))
    assert "fresh evidence" in str(rerun.get("recheck_flow", ""))
    after_rerun = manifest["expected_readiness"].get("after_rerun")
    assert isinstance(after_rerun, dict), (
        "scenario_d must declare expected_readiness.after_rerun"
    )
    assert after_rerun["status"] == "ready"


def test_e2e_02_manifest_carries_blocker_readiness_truth() -> None:
    """AC1 E2E-02: readiness flips blocked -> ready once the blocker is
    resolved through the recheck-with-fresh-evidence flow."""
    manifest = load_manifest("e2e_02_blocker_readiness")
    blockers = [i for i in manifest["expected_qc_items"] if i["severity"] == "blocker"]
    assert blockers, "e2e_02 must expect at least one blocker-severity item"
    blocker_codes = {b["reason_code"] for b in blockers}
    after = manifest["expected_readiness"]["after"]
    assert after["status"] == "blocked"
    assert set(after["expected_blocker_codes"]) == blocker_codes
    after_resolve = manifest["expected_readiness"].get("after_resolve")
    assert isinstance(after_resolve, dict) and after_resolve["status"] == "ready"
    assert after_resolve.get("expected_blocker_codes") == []
    resolution = manifest.get("expected_resolution")
    assert resolution is not None and resolution.get("method") == "recheck_fresh_evidence"


def test_e2e_01_vertical_review_covers_full_envelope() -> None:
    """E2E-01 vertical review: the full 10-code binding envelope is
    represented in expected items."""
    manifest = load_manifest("e2e_01_vertical_review")
    codes = {i["reason_code"] for i in manifest["expected_qc_items"]}
    assert codes == set(QC_REASON_CODES)
    assert manifest.get("expected_total_count") == len(QC_REASON_CODES)


def test_e2e_04_mobile_a11y_manifest_declares_viewport_and_contrast() -> None:
    """E2E-04: mobile viewport + touch-first interaction + readable badge
    contrast (dark theme) are part of the golden expectation."""
    manifest = load_manifest("e2e_04_a11y_mobile")
    viewport = manifest.get("viewport")
    assert isinstance(viewport, dict) and viewport.get("width") == 390
    assert viewport.get("height") == 844
    rendering = manifest.get("expected_rendering")
    assert rendering is not None
    assert rendering.get("touch_first_no_hover") is True
    assert rendering.get("helper_text_under_buttons") is True
    assert rendering.get("contrast") == "readable_on_dark_theme"
    assert rendering.get("severity_badges") == ["blocker", "warning", "info"]


def test_helper_consistency() -> None:
    """Helper invariants: policy fixture sane, boundary set derived, all
    manifests readable, seed refs non-empty."""
    policy = load_policy()
    assert isinstance(policy["content_hash"], str)
    assert set(policy["thresholds"]) == set(QC_REASON_CODES).difference(
        {"audio_missing"}
    ).union({"no_audio_source_fact"})
    assert len(policy_boundary_numbers()) >= 16
    manifests = iter_manifests()
    assert len(manifests) == len(GOLDEN_MANIFESTS)
    for manifest in manifests:
        assert manifest["consumes"]["seed"]


def test_stale_manifest_fails_fast() -> None:
    """Hash guard proven: an old hash is REJECTED by the same check the
    suite runs — stale manifests cannot pass silently."""
    manifest = load_manifest(GOLDEN_MANIFESTS[0])
    stale = json.loads(json.dumps(manifest))
    stale["policy_ref"]["policy_content_hash"] = "0" * 64
    ok, _ = policy_ref_matches(stale)
    assert ok is False