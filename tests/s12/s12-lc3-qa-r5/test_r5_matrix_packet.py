"""QA packet assertions only; never product acceptance evidence."""

from __future__ import annotations

import ast
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MATRIX_PATH = REPO_ROOT / "docs/pm/sessions/S12-LC3-QA/R5_MATRIX.md"

C10 = "tests/s12/s12-t03b/test_s12_t03b_c1_closure.py"
F4K = "tests/s12/s12-t06b/test_scenario_f_4k.py"
E2E = "frontend/e2e/s12-export.spec.ts"
UI_CONTRACT = "tests/s12/s12-lc3-ui/test_export_context_contract.py"
AUDIO = "tests/s12/s12-t06b/test_c28_audio_mapping.py"
VALIDATOR_AUDIO = "tests/s12/s12-t04a/test_c2_source_locked.py"
T01 = "tests/s12/s12-t01/test_s12_t01_c1_closure.py"
T04A = "tests/s12/s12-t04a/test_s12_t04a_c1_closure.py"
VAL_AUDIO = "tests/s12/s12-lc3-val/test_r1_correction_boundaries.py"
MIGRATION = "tests/s12/s12-t03a/test_s12_export_migration.py"
RETRY_MIGRATION = "tests/s12/s12-lc3-retry/test_retry_migration.py"
DOMAIN = "tests/s12/s12-t03a/test_s12_export_domain.py"
T03A_CLOSURE = "tests/s12/s12-t03a/test_s12_export_c1_closure.py"
R3_HARNESS = "tests/s12/s12-lc3-qa-r3/r3_public_producer_chain_harness.py"
R4_AUDIT = "tests/s12/s12-lc3-qa-r4/r4_readonly_audit.py"
R4_PACKET = "tests/s12/s12-lc3-qa-r4/test_r4_review_packet.py"


def _nodes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith(
            "test_"
        ):
            found.add(item.name)
        if isinstance(item, ast.ClassDef):
            for child in item.body:
                if (
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name.startswith("test_")
                ):
                    found.add(child.name)
    return found


def _candidate() -> Path:
    raw = os.environ.get("S12_R5_CANDIDATE_ROOT")
    expected = os.environ.get("S12_R5_EXPECTED_CANDIDATE_SHA")
    assert raw, "S12_R5_CANDIDATE_ROOT must identify the audited integration checkout"
    assert expected, "S12_R5_EXPECTED_CANDIDATE_SHA must be the full pinned SHA"
    root = Path(raw).resolve()
    assert root.is_dir(), root
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    assert actual == expected, (actual, expected)
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=root,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    assert branch == "codex/s12-lc3-luna-integration", branch
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    assert not status.strip(), f"candidate is not clean: {status}"
    return root


EXPECTED_PROBES = tuple(
    ("C10", C10, node)
    for node in (
        "test_c10_runner_scales_320x180_to_real_3840x2160",
        "test_c10_hevc_eligible_only_when_measured",
        "test_c10_unknown_profile_fails_explicit",
    )
) + tuple(
    ("C10", F4K, node)
    for node in (
        "test_f1_upscale_1080p_to_2160_labeled",
        "test_f2_native_4k_control",
        "test_f3_provenance_decides_not_filesize",
        "test_f4_aspect_fail_closed_and_letterbox",
    )
) + (
    (
        "C20/C21",
        E2E,
        "title: C20/C21: project-video entry point -> context -> submit updates scoped run pointer",
    ),
    (
        "C21",
        E2E,
        "title: C21: refresh giu nguyen run dang active, khong tao run moi",
    ),
) + tuple(
    ("C20", UI_CONTRACT, node)
    for node in (
        "test_context_revision_changes_when_server_authority_changes",
        "test_context_response_rejects_client_filesystem_fields",
        "test_context_response_contains_no_filesystem_paths",
    )
) + tuple(
    ("C28", AUDIO, node)
    for node in (
        "test_c28_audio_content_mapping_and_transcode_explicit",
        "test_c28_start_end_drift_pin_and_fail_closed",
        "test_c28_f01_publication_audio_reference_is_explicit",
    )
) + tuple(
    ("C28", VALIDATOR_AUDIO, node)
    for node in (
        "test_c28_remux_matching_audio_passes",
        "test_c28_transcode_explicit_content_comparison_passes",
        "test_c28_audio_start_drift_fails",
    )
) + tuple(
    ("R08-provenance", T01, node)
    for node in (
        "test_c03_native_only_when_proved",
        "test_c03_already_upscaled_4k_never_native",
        "test_c03_1080p_upscale_honesty",
        "test_c03_missing_provenance_below_4k",
    )
) + tuple(
    ("R08-timing", path, node)
    for path, node in (
        (C10, "test_c12_source_order_cuts_rational_and_cfr"),
        (C10, "test_c12_vfr_rejected_before_any_work"),
        (T04A, "test_c12_seam_stitch_correct_order_passes"),
        (T04A, "test_c12_vfr_rejected_pre_work"),
        (T04A, "test_c12_cfr_control_matches_manifest"),
    )
) + tuple(
    ("R08-geometry", path, node)
    for path, node in (
        (C10, "test_c11_portrait_pixels_letterboxed_no_stretch"),
        (C10, "test_c11_unsupported_profile_rejected"),
        (F4K, "test_f4_aspect_fail_closed_and_letterbox"),
    )
) + tuple(
    ("R08-audio", path, node)
    for path, node in (
        (AUDIO, "test_c28_audio_content_mapping_and_transcode_explicit"),
        (VAL_AUDIO, "test_r01_multicomponent_aac_transcode_passes_source_referenced_check"),
        (VAL_AUDIO, "test_r03_audio_cancel_mid_read_reaps_both_children"),
        (VAL_AUDIO, "test_r03_audio_deadline_interrupts_blocked_decoder_pipe"),
        (VAL_AUDIO, "test_r03_stderr_pressure_and_nonzero_decoder_are_bounded"),
    )
) + tuple(
    ("R08-migration", path, node)
    for path, node in (
        (RETRY_MIGRATION, "test_upgrade_retains_terminal_rows_hashes_and_binds_existing_job"),
        (MIGRATION, "test_single_head_is_new_revision"),
        (MIGRATION, "test_fresh_upgrade_creates_tables"),
        (MIGRATION, "test_upgrade_from_parent_retains_data"),
        (MIGRATION, "test_downgrade_with_rows_refuses"),
        (MIGRATION, "test_history_links_parent"),
        (MIGRATION, "test_empty_downgrade_drops_only_new_tables"),
    )
) + tuple(
    ("R08-stale-readiness", path, node)
    for path, node in (
        (DOMAIN, "test_create_stale_checkpoint_hash_fails_closed"),
        (DOMAIN, "test_create_stale_checkpoint_revision_fails_closed"),
        (DOMAIN, "test_create_stale_manifest_hash_fails_closed"),
        (DOMAIN, "test_create_stale_manifest_generation_fails_closed"),
        (DOMAIN, "test_create_cross_project_checkpoint_fails_closed"),
        (T03A_CLOSURE, "test_c09_expired_lease_old_token_zero_mutations"),
        (UI_CONTRACT, "test_context_revision_changes_when_server_authority_changes"),
    )
) + (
    ("R10", R3_HARNESS, "script"),
    ("R10", R4_AUDIT, "script"),
    ("R10", R4_PACKET, "test_r4_report_keeps_product_and_mechanism_separate"),
)
MISSING_PROBES = (
    (
        "R08-timing-mapping-correction",
        T04A,
        "test_c12_rational_cuts_placement_passes",
        "C12_WRONG_MODULE_MAPPING_RETAINED_AS_MISSING",
    ),
    (
        "R10",
        R4_PACKET,
        "test_missing_authority_is_typed_and_zero_mutation",
        "R3_PROPOSED_ONLY_NODE_NOT_PRESENT_B01_REMAINS_BLOCKED",
    ),
)


def _matrix_rows(text: str) -> list[list[str]]:
    main = text.split("## C01-C32", maxsplit=1)[1].split(
        "## Immutable probe inventory", maxsplit=1
    )[0]
    rows: list[list[str]] = []
    for line in main.splitlines():
        if re.match(r"^\|\s*(?:C|S|P|R)\d{2}\s*\|", line):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def _inventory_rows(text: str) -> list[list[str]]:
    inventory = text.split("## Immutable probe inventory", maxsplit=1)[1].split(
        "## R4 semantic corrections", maxsplit=1
    )[0]
    result: list[list[str]] = []
    for line in inventory.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0] not in {"Case", "---"}:
            result.append(cells)
    return result


def test_r5_matrix_has_exactly_the_original_62_row_ids() -> None:
    text = MATRIX_PATH.read_text(encoding="utf-8")
    rows = _matrix_rows(text)
    ids = [row[0] for row in rows]
    expected = [f"C{number:02}" for number in range(1, 33)]
    expected += [f"S{number:02}" for number in range(1, 11)]
    expected += [f"P{number:02}" for number in range(1, 11)]
    expected += [f"R{number:02}" for number in range(1, 11)]
    assert len(ids) == 62
    assert len(set(ids)) == 62, ids
    assert ids == expected
    assert all(len(row) == 4 for row in rows)
    assert "The 62 tracked rows are scope rows, not 62 passes" in text
    assert "No row is APPROVED or CLOSED" in text


def test_r5_matrix_preserves_corrected_semantics_and_b01() -> None:
    text = MATRIX_PATH.read_text(encoding="utf-8")
    rows = {row[0]: row for row in _matrix_rows(text)}
    assert all(len(row) == 4 for row in rows.values())
    c10, c20, c21 = rows["C10"][1], rows["C20"][1], rows["C21"][1]
    assert "3840x2160" in c10 and "1080p-to-4K" in c10 and "native 4K" in c10
    assert "duplicate Job" not in c10
    assert "Export UI" in c20 and "preflight" in c20 and "submit" in c20
    assert "reload/reopen/recovery" in c21 and "same server-owned active run" in c21
    assert c20 != c21 and "lease/expiry" not in c20 and "lease/expiry" not in c21
    c24 = rows["C24"][1].lower()
    assert c24.startswith("package-hash")
    assert "declared dependencies" in c24
    assert "fresh-process" not in c24
    c28 = rows["C28"][1]
    for term in ("440 Hz", "880 Hz", "start/end sync", "AudioReference"):
        assert term in c28
    assert "Export UI" not in c28
    r08 = rows["R08"][1]
    for family in (
        "source identity/timing/provenance",
        "audio content/start-end",
        "audio deadline/error/cancel (separate)",
        "geometry",
        "migration/hash/Job binding",
        "stale/readiness/ownership",
    ):
        assert family in r08
    assert "StructuralLock producer/activation" in rows["R10"][1]
    assert "BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY" in rows["R10"][1]
    assert rows["R10"][3] == "BLOCKED_DEPENDENCY"
    assert rows["P07"][2] == "BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY"
    assert rows["P07"][3] == "NOT_EXECUTED; no public route/manifest."
    assert "b6d7187 audit does not prove b6d620e" in text
    assert "NOT_DEMONSTRATED" in text and "NOT_RUN" in text


def test_r5_probe_inventory_is_static_and_exactly_mapped() -> None:
    candidate = _candidate()
    text = MATRIX_PATH.read_text(encoding="utf-8")
    actual_rows = _inventory_rows(text)
    expected_rows = [
        [case, f"{path}::{probe}", "PRESENT", "STATIC_INVENTORY"]
        for case, path, probe in EXPECTED_PROBES
    ]
    expected_rows.extend(
        [case, f"{path}::{probe}", "MISSING", evidence_class]
        for case, path, probe, evidence_class in MISSING_PROBES
    )
    # The detailed evidence classes are checked below, independently of node presence.
    actual_keys = [(row[0], row[1], row[2]) for row in actual_rows]
    expected_keys = [(row[0], row[1], row[2]) for row in expected_rows]
    assert len(actual_keys) == len(expected_keys)
    assert Counter(actual_keys) == Counter(expected_keys)
    assert len(actual_rows) == len(expected_rows)

    for case, relative_path, probe in EXPECTED_PROBES:
        row = next(
            item for item in actual_rows
            if item[0] == case and item[1] == f"{relative_path}::{probe}"
        )
        assert row[2] == "PRESENT"
        source = candidate / relative_path
        assert source.is_file(), relative_path
        if probe.startswith("title: "):
            found = probe.removeprefix("title: ") in source.read_text(encoding="utf-8")
        elif probe == "script":
            found = True
        else:
            found = probe in _nodes(source)
        assert found, (relative_path, probe)

    missing_rows = []
    for case, relative_path, probe, evidence_class in MISSING_PROBES:
        missing = next(
            item for item in actual_rows
            if item[0] == case and item[1] == f"{relative_path}::{probe}"
        )
        assert missing[2] == "MISSING"
        assert missing[3] == evidence_class
        assert probe not in _nodes(candidate / relative_path)
        missing_rows.append(missing)
    classes = {row[3] for row in actual_rows}
    for marker in (
        "MECHANISM_ONLY_NOT_PRODUCT",
        "SEEDED_E2E_FIXTURE_NOT_EQUIVALENT_TO_PUBLIC_PRODUCT",
        "ENGINEERING_MEDIA_MECHANISM_NOT_PUBLIC_S12_AUDIO",
        "INHERITED_COMPATIBILITY_FAILURE_RETAINED",
        "R3_PROPOSED_ONLY_NODE_NOT_PRESENT_B01_REMAINS_BLOCKED",
        "C12_WRONG_MODULE_MAPPING_RETAINED_AS_MISSING",
    ):
        assert marker in classes

    def inventory_row(case: str, path: str, probe: str) -> list[str]:
        reference = f"{path}::{probe}"
        return next(row for row in actual_rows if row[0] == case and row[1] == reference)

    for _, path, probe in EXPECTED_PROBES:
        row = inventory_row(_, path, probe)
        if row[0] == "C10":
            assert row[3] == "MECHANISM_ONLY_NOT_PRODUCT"
        elif row[0] in {"C20/C21", "C21"}:
            assert row[3] == "SEEDED_E2E_FIXTURE_NOT_EQUIVALENT_TO_PUBLIC_PRODUCT"
        elif row[0] == "C28":
            assert row[3] in {
                "ENGINEERING_MEDIA_MECHANISM_NOT_PUBLIC_S12_AUDIO",
                "VALIDATOR_MECHANISM_NOT_PUBLIC_S12_AUDIO",
            }
    assert any(
        row[3] == "R3_PROPOSED_ONLY_NODE_NOT_PRESENT_B01_REMAINS_BLOCKED"
        for row in missing_rows
    )
