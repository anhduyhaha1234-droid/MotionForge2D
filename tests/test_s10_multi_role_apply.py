"""S10-T02 — Multi-role independent apply (binary acceptance).

Five bullets:
1. Group fixture has 2+ chars, 1 prop with contact anchor, 1 fg occluder — no flattening.
2. Every role uses its own pinned mapping/pack/route + attempt evidence.
3. Role A failure/retry never mutates role B artifacts/route.
4. Contact + z-order edges survive chunk overlap/stitch; zero unexplained visibility events.
5. Scheduling order invariance — permuting dispatch order yields same canonical identity.
"""

from __future__ import annotations

import itertools
from typing import Any

from pathlib import Path
import pytest

from app.services.s10_multi_role_apply import (
    GROUP_FIXTURE_SPEC,
    MultiRoleApplyError,
    S10MultiRoleService,
    build_group_fixture,
)
from app.workflow.s10_full_apply_jobs import dispatch_per_role_via_worker

# ── Helpers ───────────────────────────────────────────────────────────────

def _default_roles() -> list[dict[str, Any]]:
    return [dict(r) for r in GROUP_FIXTURE_SPEC["roles"]]


def _default_contacts() -> list[dict[str, Any]]:
    return [dict(e) for e in GROUP_FIXTURE_SPEC["contact_edges"]]


def _default_z() -> list[dict[str, Any]]:
    return [dict(e) for e in GROUP_FIXTURE_SPEC["z_order_edges"]]


def _shots_two() -> list[dict[str, Any]]:
    return [
        {"shot_id": "shot_A", "start_frame": 0, "end_frame": 47},
        {"shot_id": "shot_B", "start_frame": 48, "end_frame": 95},
    ]


def _vis_events_for_roles(role_ids: list[str]) -> list[dict[str, Any]]:
    return []


# ═══════════════════════════════════════════════════════════════════════════
# 1. Group fixture
# ═══════════════════════════════════════════════════════════════════════════

class TestGroupFixture:

    def test_default_fixture_has_required_diversity(self) -> None:
        fx = build_group_fixture()
        assert fx["char_count"] >= 2, "need at least 2 characters"
        assert fx["prop_count"] >= 1, "need at least 1 prop"
        assert fx["fg_count"] >= 1, "need at least 1 foreground occluder"
        assert fx["not_flattened"] is True
        assert len(fx["roles"]) == 4
        assert len(fx["layer_ids"]) == 4
        assert len(set(fx["layer_ids"])) == 4

    def test_default_fixture_roles_have_expected_kinds(self) -> None:
        fx = build_group_fixture()
        kinds = [r.get("kind") for r in fx["roles"]]
        assert kinds.count("character") >= 2
        assert "prop" in kinds
        assert "foreground_occluder" in kinds

    def test_prop_has_contact_anchor(self) -> None:
        fx = build_group_fixture()
        prop_roles = [r for r in fx["roles"] if r.get("kind") == "prop"]
        assert len(prop_roles) >= 1
        for pr in prop_roles:
            assert isinstance(pr.get("contact_anchor"), dict), f"prop {pr.get('role_id')} missing contact_anchor"
            anchor = pr["contact_anchor"]
            assert "x" in anchor and "y" in anchor

    def test_distinct_layers_not_flattened(self) -> None:
        fx = build_group_fixture()
        layer_ids = fx["layer_ids"]
        assert len(layer_ids) == len(set(layer_ids)), "layers must be distinct (no flattening)"
        assert fx["not_flattened"] is True

    def test_rejects_insufficient_characters(self) -> None:
        roles = [dict(r) for r in _default_roles() if r.get("kind") != "character"]
        one_char = [r for r in _default_roles() if r.get("kind") == "character"][:1]
        attempt = one_char + roles
        with pytest.raises(MultiRoleApplyError, match="at least 2 character"):
            build_group_fixture(roles=attempt)

    def test_rejects_missing_prop(self) -> None:
        roles = [r for r in _default_roles() if r.get("kind") != "prop"]
        with pytest.raises(MultiRoleApplyError, match="at least 1 prop"):
            build_group_fixture(roles=roles)

    def test_rejects_missing_fg(self) -> None:
        roles = [r for r in _default_roles() if r.get("kind") != "foreground_occluder"]
        with pytest.raises(MultiRoleApplyError, match="foreground occluder"):
            build_group_fixture(roles=roles)

    def test_rejects_duplicate_layer(self) -> None:
        roles = _default_roles()
        dup = dict(roles[0])
        dup["role_id"] = "role_dup"
        dup["layer_id"] = roles[0]["layer_id"]
        roles_dup = roles + [dup]
        with pytest.raises(MultiRoleApplyError, match="distinct layer_ids|duplicate layer"):
            build_group_fixture(roles=roles_dup)

    def test_rejects_prop_without_anchor(self) -> None:
        roles = _default_roles()
        for r in roles:
            if r.get("kind") == "prop":
                r2 = dict(r)
                r2.pop("contact_anchor", None)
                bad_roles = [x if x.get("role_id") != r2["role_id"] else r2 for x in roles]
                with pytest.raises(MultiRoleApplyError, match="contact_anchor"):
                    build_group_fixture(roles=bad_roles)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Per-role pinned mapping/pack/route + attempt evidence
# ═══════════════════════════════════════════════════════════════════════════

class TestPerRolePinnedEvidence:

    def test_per_role_pinned_mapping_pack_route_and_attempt_evidence(self) -> None:
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=_shots_two(),
            chunk_config={"chunk_frames": 24, "overlap_frames": 2},
        )
        result = svc.dispatch_per_role(plan)
        assert set(result["roles"].keys()) == {r["role_id"] for r in _default_roles()}
        for role_id, rd in result["roles"].items():
            assert rd["mapping_id"], f"{role_id} missing mapping_id"
            assert rd["pack_version"], f"{role_id} missing pack_version"
            assert rd["route"] in {"pose_swap", "sprite_affine", "controlled_redraw", "mesh_warp", "part_rig"}
            assert len(rd["attempts"]) > 0, f"{role_id} has no attempts"
            for at in rd["attempts"]:
                assert at["mapping_id"] == rd["mapping_id"]
                assert at["pack_version"] == rd["pack_version"]
                assert at["route"] == rd["route"]
                assert at["attempt"] == 1
                assert at["content_hash"]
                assert at["chunk_id"]
                assert at["state"] == "completed"
            for art in rd["artifacts"]:
                assert art["mapping_id"] == rd["mapping_id"]
                assert art["pack_version"] == rd["pack_version"]
                assert art["route"] == rd["route"]
                assert art["artifact_sha256"] and len(art["artifact_sha256"]) == 64
                assert art["artifact_id"].startswith("art_")
        all_chunk_ids: list[str] = []
        for rd in result["roles"].values():
            for ch in rd["chunks"]:
                all_chunk_ids.append(ch["chunk_id"])
        assert len(all_chunk_ids) == len(set(all_chunk_ids)), "chunk_ids must be unique across roles (no flattening)"

    def test_per_role_chunks_have_distinct_content_hashes(self) -> None:
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=[{"shot_id": "shot_0", "start_frame": 0, "end_frame": 95}],
            chunk_config={"chunk_frames": 24, "overlap_frames": 2},
        )
        result = svc.dispatch_per_role(plan)
        by_index: dict[int, list[str]] = {}
        for rd in result["roles"].values():
            for ch in rd["chunks"]:
                by_index.setdefault(int(ch["chunk_index"]), []).append(ch["content_hash_input"])
        for ci, hashes in by_index.items():
            assert len(set(hashes)) == len(hashes), f"chunk_index {ci} content hashes collide across roles"

    def test_every_role_has_distinct_route_pack_mapping(self) -> None:
        roles = _default_roles()
        tuples = [(r["route"], r["pack_version"], r["mapping_id"]) for r in roles]
        assert len(tuples) == len(set(tuples)), "each role must have distinct (route, pack, mapping)"

    def test_worker_layer_per_role_dispatch_has_route_per_role(self) -> None:
        res = dispatch_per_role_via_worker(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=_shots_two(),
            chunk_config={"chunk_frames": 24, "overlap_frames": 2},
        )
        for _role_id, rd in res["roles"].items():
            assert rd["route"]
            assert rd["mapping_id"]
            assert rd["pack_version"]
            assert len(rd["attempts"]) > 0
            assert res["plan_hash"]


# ═══════════════════════════════════════════════════════════════════════════
# 3. Isolation: role A failure/retry never mutates role B
# ═══════════════════════════════════════════════════════════════════════════

class TestIsolationOnFailure:

    def test_role_a_failure_does_not_mutate_role_b_artifacts(self) -> None:
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=_shots_two(),
            chunk_config={"chunk_frames": 24, "overlap_frames": 2},
        )
        baseline = svc.dispatch_per_role(plan)
        role_ids = sorted(baseline["roles"].keys())
        role_a = role_ids[0]
        role_b = role_ids[1]
        baseline_b_artifacts = baseline["roles"][role_b]["artifacts"]
        baseline_b_hashes = [a["artifact_sha256"] for a in baseline_b_artifacts]
        baseline_b_ids = [a["artifact_id"] for a in baseline_b_artifacts]
        baseline_b_routes = [a["route"] for a in baseline_b_artifacts]
        failed = svc.dispatch_per_role(plan, fail_role_id=role_a, fail_chunk_index=0)
        after_b = failed["roles"][role_b]["artifacts"]
        after_hashes = [a["artifact_sha256"] for a in after_b]
        after_ids = [a["artifact_id"] for a in after_b]
        after_routes = [a["route"] for a in after_b]
        assert after_hashes == baseline_b_hashes, "role B hashes must not change when role A fails"
        assert after_ids == baseline_b_ids, "role B artifact IDs must not change when role A fails"
        assert after_routes == baseline_b_routes, "role B routes must not change when role A fails"
        assert failed["roles"][role_a]["failed"] is True
        assert any(a["state"] == "failed" for a in failed["roles"][role_a]["attempts"])
        failed2 = dispatch_per_role_via_worker(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=_shots_two(),
            chunk_config={"chunk_frames": 24, "overlap_frames": 2},
            fail_role_id=role_a,
            fail_chunk_index=0,
        )
        after2 = failed2["roles"][role_b]["artifacts"]
        assert [a["artifact_sha256"] for a in after2] == baseline_b_hashes

    def test_retry_only_mutates_target_role(self) -> None:
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=_shots_two(),
            chunk_config={"chunk_frames": 24, "overlap_frames": 2},
        )
        baseline = svc.dispatch_per_role(plan)
        role_ids = sorted(baseline["roles"].keys())
        target = role_ids[0]
        other = role_ids[1]
        other_before = [a["artifact_sha256"] for a in baseline["roles"][other]["artifacts"]]
        retry = svc.retry_role(plan, target, new_pack_version="pack_char_a_v2")
        assert retry["pack_version"] == "pack_char_a_v2"
        assert retry["attempts"][0]["attempt"] == 2
        assert [a["artifact_sha256"] for a in baseline["roles"][other]["artifacts"]] == other_before
        target_before = [a["artifact_sha256"] for a in baseline["roles"][target]["artifacts"]]
        target_after = [a["artifact_sha256"] for a in retry["artifacts"]]
        assert target_before != target_after, "retry with new pack must change artifact hashes"

    def test_failed_role_has_no_artifact_for_failed_chunk_but_other_roles_complete(self) -> None:
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=[{"shot_id": "shot_0", "start_frame": 0, "end_frame": 47}],
            chunk_config={"chunk_frames": 24, "overlap_frames": 2},
        )
        result = svc.dispatch_per_role(plan, fail_role_id="role_char_a", fail_chunk_index=0)
        char_a = result["roles"]["role_char_a"]
        assert char_a["failed"] is True
        failed_attempts = [a for a in char_a["attempts"] if a["state"] == "failed"]
        assert len(failed_attempts) == 1
        assert failed_attempts[0]["artifact_id"] is None
        for rid, rd in result["roles"].items():
            if rid == "role_char_a":
                continue
            assert rd["failed"] is False
            assert len(rd["artifacts"]) == len(rd["chunks"])


# ═══════════════════════════════════════════════════════════════════════════
# 4. Contact + z-order survive chunk overlap/stitch; zero unexplained visibility
# ═══════════════════════════════════════════════════════════════════════════

class TestContactZOrderSurvival:

    def test_contact_and_zorder_survive_overlap_stitch_boundaries(self) -> None:
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=_shots_two(),
            chunk_config={"chunk_frames": 24, "overlap_frames": 4},
        )
        result = svc.dispatch_per_role(plan)
        assert result["contact_survival"]["all_survive"] is True, f"contact edges must survive: {result['contact_survival']}"
        assert result["z_order_survival"]["all_survive"] is True, f"z-order edges must survive: {result['z_order_survival']}"
        cs = svc._check_edge_survival(plan, overlap_context=True, edge_kind="contact")
        zs = svc._check_edge_survival(plan, overlap_context=True, edge_kind="z_order")
        assert cs["all_survive"] is True
        assert zs["all_survive"] is True
        for e in cs["edges"]:
            assert e["survives"] is True
        for e in zs["edges"]:
            assert e["survives"] is True

    def test_zero_unexplained_visibility_events(self) -> None:
        svc = S10MultiRoleService()
        vis = [
            {"event_id": "vis_0", "role_id": "role_char_a", "segment_id": "seg_a", "from_visibility": "visible", "to_visibility": "occluded", "frame": 24, "reason": "occluded_by:layer_fg_table", "related_edge_id": "z_char_a_behind_table"},
            {"event_id": "vis_1", "role_id": "role_char_b", "segment_id": "seg_b", "from_visibility": "visible", "to_visibility": "occluded", "frame": 48, "reason": "contact:hand_to_phone", "related_edge_id": "contact_char_a_phone"},
        ]
        plan = svc.build_plan(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            visibility_events=vis,
            shots=_shots_two(),
            chunk_config={"chunk_frames": 24, "overlap_frames": 2},
        )
        result = svc.dispatch_per_role(plan)
        assert result["unexplained_visibility_count"] == 0
        for ev in plan.visibility_events:
            assert ev.reason, "every visibility event must have explicit reason"

    def test_missing_visibility_reason_fails_closed(self) -> None:
        svc = S10MultiRoleService()
        vis = [
            {"event_id": "vis_bad", "role_id": "role_char_a", "segment_id": "seg_a", "from_visibility": "visible", "to_visibility": "occluded", "frame": 10, "reason": ""},
        ]
        with pytest.raises(MultiRoleApplyError, match="reason is required"):
            svc.build_plan(
                roles=_default_roles(),
                contact_edges=_default_contacts(),
                z_order_edges=_default_z(),
                visibility_events=vis,
                shots=_shots_two(),
            )

    def test_edge_spanning_chunk_boundary_still_survives_with_overlap(self) -> None:
        svc = S10MultiRoleService()
        contacts = [
            {"edge_id": "contact_straddle", "source_role_id": "role_char_a", "target_role_id": "role_prop_phone", "contact_kind": "hand_to_phone", "anchor": {"x": 0.5, "y": 0.5}, "start_frame": 22, "end_frame": 26},
        ]
        plan = svc.build_plan(
            roles=_default_roles(),
            contact_edges=contacts,
            z_order_edges=_default_z(),
            shots=[{"shot_id": "shot_0", "start_frame": 0, "end_frame": 95}],
            chunk_config={"chunk_frames": 24, "overlap_frames": 4},
        )
        cs = svc._check_edge_survival(plan, overlap_context=True, edge_kind="contact")
        assert cs["all_survive"] is True, "straddling edge must survive via overlap context"
        result = svc.dispatch_per_role(plan)
        assert result["contact_survival"]["all_survive"] is True

    def test_no_visibility_events_also_zero_unexplained(self) -> None:
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            visibility_events=[],
            shots=_shots_two(),
            chunk_config={"chunk_frames": 24, "overlap_frames": 2},
        )
        result = svc.dispatch_per_role(plan)
        assert result["unexplained_visibility_count"] == 0
        assert len(plan.visibility_events) == 0


# ═══════════════════════════════════════════════════════════════════════════
# 5. Scheduling order invariance
# ═══════════════════════════════════════════════════════════════════════════

class TestSchedulingInvariance:

    def test_scheduling_order_does_not_change_canonical_output_identity(self) -> None:
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=_shots_two(),
            chunk_config={"chunk_frames": 24, "overlap_frames": 2},
        )
        order_a = sorted([r["role_id"] for r in _default_roles()])
        order_b = list(reversed(order_a))
        res_a = svc.dispatch_per_role(plan, role_order=order_a)
        res_b = svc.dispatch_per_role(plan, role_order=order_b)
        id_a = svc.canonical_output_identity(res_a)
        id_b = svc.canonical_output_identity(res_b)
        assert id_a == id_b, f"scheduling invariance violated: {id_a!r} != {id_b!r}"
        res_wa = dispatch_per_role_via_worker(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=_shots_two(),
            chunk_config={"chunk_frames": 24, "overlap_frames": 2},
            role_order=order_a,
        )
        res_wb = dispatch_per_role_via_worker(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=_shots_two(),
            chunk_config={"chunk_frames": 24, "overlap_frames": 2},
            role_order=order_b,
        )
        assert svc.canonical_output_identity(res_wa) == svc.canonical_output_identity(res_wb)

    def test_plan_hash_invariant_to_schedule_order(self) -> None:
        svc = S10MultiRoleService()
        roles = _default_roles()
        order_a = [r["role_id"] for r in roles]
        order_b = list(reversed(order_a))
        plan_a = svc.build_plan(roles=roles, contact_edges=_default_contacts(), z_order_edges=_default_z(), shots=_shots_two(), schedule_order=order_a)
        plan_b = svc.build_plan(roles=roles, contact_edges=_default_contacts(), z_order_edges=_default_z(), shots=_shots_two(), schedule_order=order_b)
        assert plan_a.plan_hash == plan_b.plan_hash
        assert plan_a.plan_id == plan_b.plan_id
        assert plan_a.canonical_inputs_hash == plan_b.canonical_inputs_hash

    def test_per_role_artifacts_identical_across_permutations(self) -> None:
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=[{"shot_id": "shot_0", "start_frame": 0, "end_frame": 95}],
            chunk_config={"chunk_frames": 24, "overlap_frames": 2},
        )
        perms = list(itertools.permutations(sorted([r["role_id"] for r in _default_roles()])))
        sample = [perms[0], perms[5], perms[11], perms[23]]
        identities = []
        artifact_sets = []
        for perm in sample:
            res = svc.dispatch_per_role(plan, role_order=list(perm))
            identities.append(svc.canonical_output_identity(res))
            per_role = {rid: sorted(a["artifact_sha256"] for a in rd["artifacts"]) for rid, rd in res["roles"].items()}
            artifact_sets.append(per_role)
        assert len(set(identities)) == 1, f"all permutations must yield same identity, got {identities}"
        for i in range(1, len(artifact_sets)):
            assert artifact_sets[i] == artifact_sets[0], f"permutation {sample[i]} artifacts differ"

    def test_canonical_identity_independent_of_roles_input_order(self) -> None:
        svc = S10MultiRoleService()
        roles_fwd = _default_roles()
        roles_rev = list(reversed(roles_fwd))
        plan_fwd = svc.build_plan(roles=roles_fwd, contact_edges=_default_contacts(), z_order_edges=_default_z(), shots=_shots_two())
        plan_rev = svc.build_plan(roles=roles_rev, contact_edges=_default_contacts(), z_order_edges=_default_z(), shots=_shots_two())
        assert plan_fwd.plan_hash == plan_rev.plan_hash
        res_fwd = svc.dispatch_per_role(plan_fwd)
        res_rev = svc.dispatch_per_role(plan_rev)
        assert svc.canonical_output_identity(res_fwd) == svc.canonical_output_identity(res_rev)


# ── Negative / edge cases ────────────────────────────────────────────────

class TestValidation:

    def test_rejects_unknown_route(self) -> None:
        svc = S10MultiRoleService()
        roles = _default_roles()
        roles[0] = dict(roles[0])
        roles[0]["route"] = "nonexistent_route"
        with pytest.raises(MultiRoleApplyError, match="route must be one of"):
            svc.build_plan(roles=roles)

    def test_rejects_duplicate_role_id(self) -> None:
        svc = S10MultiRoleService()
        roles = _default_roles()
        dup = dict(roles[0])
        dup["layer_id"] = "layer_dup_unique"
        dup["role_id"] = roles[0]["role_id"]
        roles_dup = roles + [dup]
        roles_dup = roles_dup[:4]
        roles_dup[-1] = dup
        with pytest.raises(MultiRoleApplyError, match="duplicate role_id"):
            svc.build_plan(roles=roles_dup)

    def test_rejects_non_finite(self) -> None:
        svc = S10MultiRoleService()
        roles = _default_roles()
        roles[0] = dict(roles[0])
        roles[0]["contact_anchor"] = {"x": float("inf"), "y": 0.5}
        with pytest.raises(MultiRoleApplyError, match="non-finite"):
            svc.build_plan(roles=roles)

    def test_rejects_empty_roles(self) -> None:
        svc = S10MultiRoleService()
        with pytest.raises(MultiRoleApplyError, match="non-empty"):
            svc.build_plan(roles=[])

    def test_rejects_too_many_roles(self) -> None:
        svc = S10MultiRoleService()
        roles = _default_roles() + [
            {"role_id": "role_extra", "layer_id": "layer_extra", "route": "pose_swap", "pack_version": "pack_extra_v1", "mapping_id": "mapping_extra_v1"}
        ]
        with pytest.raises(MultiRoleApplyError, match="at most 4"):
            svc.build_plan(roles=roles)


# ═══════════════════════════════════════════════════════════════════════════
# 6. Real adapter execution (S10-T02-C1 correction)
# ═══════════════════════════════════════════════════════════════════════════

class TestRealAdapterExecution:

    def _make_workspace(self, tmp_path: Path):
        import cv2
        import numpy as np
        from app.services.renderer_routes.composite import write_frames_mp4

        ws = tmp_path / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        h, w = 120, 160
        src_frames = []
        for i in range(12):
            f = np.zeros((h, w, 3), dtype=np.uint8)
            f[:, :, 0] = int(30 + i * 6)
            f[:, :, 1] = 80
            f[:, :, 2] = 20
            src_frames.append(f)
        source = ws / "source.mp4"
        write_frames_mp4(src_frames, source, fps=24.0)
        assets = ws / "assets"
        assets.mkdir(exist_ok=True)
        palette = {
            "layer_char_a": (0, 0, 255),
            "layer_char_b": (0, 255, 0),
            "layer_prop_phone": (255, 0, 0),
            "layer_fg_table": (128, 128, 64),
        }
        for layer_id, color in palette.items():
            img = np.zeros((40, 40, 4), dtype=np.uint8)
            img[:, :, 0], img[:, :, 1], img[:, :, 2] = color
            img[:, :, 3] = 255
            cv2.imwrite(str(assets / f"{layer_id}.png"), img)
        outputs = ws / "outputs"
        outputs.mkdir(exist_ok=True)
        return ws, source, assets, outputs

    def test_real_executor_produces_decodable_media_per_role_chunk(self, tmp_path: Path) -> None:
        from app.services.renderer_routes.composite import decode_rgb_frames

        ws, source, assets, outputs = self._make_workspace(tmp_path)
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=[{"shot_id": "shot_0", "start_frame": 0, "end_frame": 11}],
            chunk_config={"chunk_frames": 6, "overlap_frames": 0},
        )
        result = svc.execute_plan_via_renderer(
            plan, workspace_root=ws, source_media=source, assets_dir=assets,
            outputs_dir=outputs,
            workspace_id="ws_test", project_id="proj_test", video_item_id="vid_test",
        )
        assert set(result["roles"].keys()) == {r["role_id"] for r in _default_roles()}
        for role_id, rd in result["roles"].items():
            assert rd["failed"] is False
            assert len(rd["artifacts"]) == 2
            for art in rd["artifacts"]:
                ev = art["evidence"]
                assert ev["decoded_frame_count"] in (6, 6)
                assert len(ev["decoded_sha256"]) == 64
                out_path = Path(ev["output_media"])
                assert out_path.is_file()
                decoded = decode_rgb_frames(out_path)
                assert len(decoded) == ev["decoded_frame_count"]
                assert decoded[0].shape[0] > 0

    def test_real_executor_exact_frame_count_and_route_evidence(self, tmp_path: Path) -> None:
        ws, source, assets, outputs = self._make_workspace(tmp_path)
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=[
                {"shot_id": "shot_A", "start_frame": 0, "end_frame": 5},
                {"shot_id": "shot_B", "start_frame": 6, "end_frame": 11},
            ],
            chunk_config={"chunk_frames": 6, "overlap_frames": 2},
        )
        result = svc.execute_plan_via_renderer(
            plan, workspace_root=ws, source_media=source, assets_dir=assets, outputs_dir=outputs,
            workspace_id="ws_test", project_id="proj_test", video_item_id="vid_test",
        )
        for role_id, rd in result["roles"].items():
            for art in rd["artifacts"]:
                ev = art["evidence"]
                assert ev["start_frame"] <= ev["end_frame"]
                expected = ev["end_frame"] - ev["start_frame"] + 1
                assert ev["decoded_frame_count"] == expected
                assert ev["frames_rendered"] == expected
                assert ev["route"] in {"pose_swap", "sprite_affine", "controlled_redraw"}
                assert ev["backend_id"].startswith("ffmpeg-nvenc-")
                assert art["route"] == ev["route"]
                assert art["artifact_sha256"] == ev["decoded_sha256"]

    def test_real_executor_visible_replacement_region_change(self, tmp_path: Path) -> None:
        import numpy as np
        from app.services.renderer_routes.composite import decode_rgb_frames

        ws, source, assets, outputs = self._make_workspace(tmp_path)
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=_default_roles()[:2],
            shots=[{"shot_id": "shot_0", "start_frame": 0, "end_frame": 5}],
            chunk_config={"chunk_frames": 6, "overlap_frames": 0},
        )
        result = svc.execute_plan_via_renderer(
            plan, workspace_root=ws, source_media=source, assets_dir=assets, outputs_dir=outputs,
            workspace_id="ws_test", project_id="proj_test", video_item_id="vid_test",
        )
        src_frames = decode_rgb_frames(source)
        for role_id, rd in result["roles"].items():
            for art in rd["artifacts"]:
                ev = art["evidence"]
                out_frames = decode_rgb_frames(Path(ev["output_media"]))
                diffs = [
                    float(np.abs(out.astype(int) - src.astype(int)).mean())
                    for out, src in zip(out_frames, src_frames[ev["start_frame"] : ev["end_frame"] + 1])
                ]
                assert max(diffs) > 2.0, f"{role_id} not visibly different (max diff {max(diffs):.3f})"

    def test_real_executor_no_source_only_reencode(self, tmp_path: Path) -> None:
        import cv2
        import shutil
        import numpy as np

        ws, source, assets, outputs = self._make_workspace(tmp_path)
        svc = S10MultiRoleService()
        plan = svc.build_plan(
                    roles=[
                        {"role_id": "role_char_a", "layer_id": "layer_char_a", "route": "pose_swap", "pack_version": "pack_char_a_v1", "mapping_id": "mapping_char_a_v1", "affected_region": [0.10, 0.10, 0.45, 0.45]},
                        {"role_id": "role_char_b", "layer_id": "layer_char_b", "route": "sprite_affine", "pack_version": "pack_char_b_v1", "mapping_id": "mapping_char_b_v1", "affected_region": [0.30, 0.30, 0.50, 0.50]},
                    ],
            shots=[{"shot_id": "shot_0", "start_frame": 0, "end_frame": 5}],
            chunk_config={"chunk_frames": 6, "overlap_frames": 0},
        )
        result = svc.execute_plan_via_renderer(
            plan, workspace_root=ws, source_media=source, assets_dir=assets, outputs_dir=outputs,
            workspace_id="ws_test", project_id="proj_test", video_item_id="vid_test",
        )
        hashes = [art["artifact_sha256"] for rd in result["roles"].values() for art in rd["artifacts"]]
        assert len(set(hashes)) > 1
        alt_assets = ws / "assets_alt"
        alt_assets.mkdir()
        for p in assets.glob("*.png"):
            shutil.copy(str(p), str(alt_assets / p.name))
        alt_img = np.zeros((40, 40, 4), dtype=np.uint8)
        alt_img[:, :, 0] = 200
        alt_img[:, :, 1] = 200
        alt_img[:, :, 3] = 255
        cv2.imwrite(str(alt_assets / "layer_char_a.png"), alt_img)
        alt_outputs = ws / "outputs_alt"
        alt_outputs.mkdir()
        alt_result = svc.execute_plan_via_renderer(
            plan, workspace_root=ws, source_media=source, assets_dir=alt_assets, outputs_dir=alt_outputs,
            workspace_id="ws_test", project_id="proj_test", video_item_id="vid_test",
        )
        assert result["roles"]["role_char_a"]["artifacts"][0]["artifact_sha256"] != alt_result["roles"]["role_char_a"]["artifacts"][0]["artifact_sha256"]

    def test_real_executor_contact_and_zorder_preservation(self, tmp_path: Path) -> None:
        ws, source, assets, outputs = self._make_workspace(tmp_path)
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=[{"shot_id": "shot_0", "start_frame": 0, "end_frame": 11}],
            chunk_config={"chunk_frames": 6, "overlap_frames": 2},
        )
        result = svc.execute_plan_via_renderer(
            plan, workspace_root=ws, source_media=source, assets_dir=assets, outputs_dir=outputs,
            workspace_id="ws_test", project_id="proj_test", video_item_id="vid_test",
        )
        assert result["contact_survival"]["all_survive"] is True
        assert result["z_order_survival"]["all_survive"] is True
        for e in result["contact_survival"]["edges"]:
            assert e["survives"] is True
        for e in result["z_order_survival"]["edges"]:
            assert e["survives"] is True

    def test_real_executor_isolation_one_role_failure(self, tmp_path: Path) -> None:
        ws, source, assets, outputs = self._make_workspace(tmp_path)
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=[{"shot_id": "shot_0", "start_frame": 0, "end_frame": 11}],
            chunk_config={"chunk_frames": 6, "overlap_frames": 0},
        )
        baseline = svc.execute_plan_via_renderer(
            plan, workspace_root=ws, source_media=source, assets_dir=assets, outputs_dir=outputs,
            workspace_id="ws_test", project_id="proj_test", video_item_id="vid_test",
        )
        role_ids = sorted(baseline["roles"].keys())
        role_a, role_b = role_ids[0], role_ids[1]
        baseline_b_hashes = [a["artifact_sha256"] for a in baseline["roles"][role_b]["artifacts"]]
        outputs2 = ws / "outputs2"
        outputs2.mkdir()
        failed = svc.execute_plan_via_renderer(
            plan,
            workspace_root=ws,
            source_media=source,
            assets_dir=assets,
            outputs_dir=outputs2,
            workspace_id="ws_test", project_id="proj_test", video_item_id="vid_test",
            fail_role_id=role_a,
            fail_chunk_index=0,
        )
        assert failed["roles"][role_a]["failed"] is True
        assert any(a["state"] == "failed" for a in failed["roles"][role_a]["attempts"])
        after_hashes = [a["artifact_sha256"] for a in failed["roles"][role_b]["artifacts"]]
        assert after_hashes == baseline_b_hashes
        failed_attempts = [a for a in failed["roles"][role_a]["attempts"] if a["state"] == "failed"]
        assert len(failed_attempts) == 1
        assert failed_attempts[0]["artifact_id"] is None
        for rid, rd in failed["roles"].items():
            if rid == role_a:
                continue
            assert rd["failed"] is False
            assert len(rd["artifacts"]) == len(rd["chunks"])

    def test_real_executor_scheduling_invariance(self, tmp_path: Path) -> None:
        ws, source, assets, outputs = self._make_workspace(tmp_path)
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=_default_roles(),
            contact_edges=_default_contacts(),
            z_order_edges=_default_z(),
            shots=[{"shot_id": "shot_0", "start_frame": 0, "end_frame": 11}],
            chunk_config={"chunk_frames": 6, "overlap_frames": 0},
        )
        out1 = ws / "out1"
        out2 = ws / "out2"
        out1.mkdir()
        out2.mkdir()
        r1 = svc.execute_plan_via_renderer(plan, workspace_root=ws, source_media=source, assets_dir=assets, outputs_dir=out1, workspace_id="ws_test", project_id="proj_test", video_item_id="vid_test")
        r2 = svc.execute_plan_via_renderer(plan, workspace_root=ws, source_media=source, assets_dir=assets, outputs_dir=out2, workspace_id="ws_test", project_id="proj_test", video_item_id="vid_test")
        order_a = sorted([r["role_id"] for r in _default_roles()])
        order_b = list(reversed(order_a))
        legacy_a = svc.dispatch_per_role(plan, role_order=order_a)
        legacy_b = svc.dispatch_per_role(plan, role_order=order_b)
        assert svc.canonical_output_identity(legacy_a) == svc.canonical_output_identity(legacy_b)
        for rid in r1["roles"]:
            h1 = [a["artifact_sha256"] for a in r1["roles"][rid]["artifacts"]]
            h2 = [a["artifact_sha256"] for a in r2["roles"][rid]["artifacts"]]
            assert h1 == h2

    def test_real_executor_direct_execute_role_chunk(self, tmp_path: Path) -> None:
        from app.services.renderer_routes.composite import decode_rgb_frames

        ws, source, assets, _ = self._make_workspace(tmp_path)
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=[{"role_id": "role_char_b", "layer_id": "layer_char_b", "route": "sprite_affine", "pack_version": "p1", "mapping_id": "m1", "affected_region": [0.30, 0.30, 0.50, 0.50]}],
            shots=[{"shot_id": "shot_0", "start_frame": 0, "end_frame": 5}],
            chunk_config={"chunk_frames": 6, "overlap_frames": 0},
        )
        role = next(r for r in plan.roles if r.role_id == "role_char_b")
        chunk = plan.per_role_chunks["role_char_b"][0]
        out_media = ws / "single_chunk.mp4"
        result = svc.execute_role_chunk(
            role=role,
            chunk=chunk,
            workspace_root=ws,
            source_media=source,
            assets_dir=assets,
            output_media=out_media,
            workspace_id="ws_test", project_id="proj_test", video_item_id="vid_test",
        )
        assert result["role_id"] == "role_char_b"
        assert result["chunk_id"] == chunk["chunk_id"]
        assert result["route"] == "sprite_affine"
        ev = result["evidence"]
        assert ev["decoded_frame_count"] == 6
        assert ev["start_frame"] == 0 and ev["end_frame"] == 5
        assert ev["route"] == "sprite_affine"
        assert ev["requested_route"] == "sprite_affine"
        assert ev["effective_adapter"] == "SpriteAffineAdapter"
        assert Path(ev["output_media"]).is_file()
        frames = decode_rgb_frames(Path(ev["output_media"]))
        assert len(frames) == 6
        assert result["render_request"].route == "sprite_affine"
# ═══════════════════════════════════════════════════════════════════════════
# 7. C2 — hard-coded identity removal, authority fail-closed, determinism,
#    route evidence correctness
# ═══════════════════════════════════════════════════════════════════════════

ADAPTER_BY_ROUTE = {
    "sprite_affine": "SpriteAffineAdapter",
    "controlled_redraw": "SpriteAffineAdapter",
    "pose_swap": "PoseSwapAdapter",
}


def _make_real_workspace(tmp_path: Path):
    import cv2
    import numpy as np
    from app.services.renderer_routes.composite import write_frames_mp4

    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    h, w = 120, 160
    src_frames = []
    for i in range(6):
        f = np.zeros((h, w, 3), dtype=np.uint8)
        f[:, :, 0] = 30
        f[:, :, 1] = 80
        f[:, :, 2] = 20
        src_frames.append(f)
    source = ws / "source.mp4"
    write_frames_mp4(src_frames, source, fps=24.0)
    assets = ws / "assets"
    assets.mkdir(exist_ok=True)
    for layer_id, color in [("layer_char_a", (0, 0, 255)),
                             ("layer_char_b", (0, 255, 0)),
                             ("layer_prop_phone", (255, 0, 0)),
                             ("layer_fg_table", (128, 128, 64))]:
        img = np.zeros((40, 40, 4), dtype=np.uint8)
        img[:, :, 0], img[:, :, 1], img[:, :, 2] = color
        img[:, :, 3] = 255
        cv2.imwrite(str(assets / f"{layer_id}.png"), img)
    outputs = ws / "outputs"
    outputs.mkdir(exist_ok=True)
    return ws, source, assets, outputs


class TestC2HardCodedIdentity:
    """C2: workspace_id/project_id/video_item_id are REQUIRED — no hard-coded defaults."""

    def test_missing_workspace_id_fails_closed(self, tmp_path: Path) -> None:
        from app.services.s10_multi_role_apply import (
            S10MultiRoleService, GROUP_FIXTURE_SPEC,
        )

        ws, source, assets, outputs = _make_real_workspace(tmp_path)
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=GROUP_FIXTURE_SPEC["roles"],
            contact_edges=GROUP_FIXTURE_SPEC.get("contact_edges", []),
            z_order_edges=GROUP_FIXTURE_SPEC.get("z_order_edges", []),
            shots=[{"shot_id": "shot_0", "start_frame": 0, "end_frame": 5}],
            chunk_config={"chunk_frames": 6, "overlap_frames": 0},
        )
        with pytest.raises((ValueError, Exception), match="workspace_id/project_id/video_item_id are REQUIRED"):
            svc.execute_plan_via_renderer(
                plan, workspace_root=ws, source_media=source, assets_dir=assets,
                outputs_dir=outputs,
                workspace_id="", project_id="proj_test", video_item_id="vid_test",
            )

    def test_missing_project_id_fails_closed(self, tmp_path: Path) -> None:
        from app.services.s10_multi_role_apply import (
            S10MultiRoleService, GROUP_FIXTURE_SPEC,
        )

        ws, source, assets, outputs = _make_real_workspace(tmp_path)
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=GROUP_FIXTURE_SPEC["roles"],
            contact_edges=GROUP_FIXTURE_SPEC.get("contact_edges", []),
            z_order_edges=GROUP_FIXTURE_SPEC.get("z_order_edges", []),
            shots=[{"shot_id": "shot_0", "start_frame": 0, "end_frame": 5}],
            chunk_config={"chunk_frames": 6, "overlap_frames": 0},
        )
        with pytest.raises((ValueError, Exception), match="workspace_id/project_id/video_item_id are REQUIRED"):
            svc.execute_plan_via_renderer(
                plan, workspace_root=ws, source_media=source, assets_dir=assets,
                outputs_dir=outputs,
                workspace_id="ws_test", project_id="", video_item_id="vid_test",
            )

    def test_missing_video_item_id_fails_closed(self, tmp_path: Path) -> None:
        from app.services.s10_multi_role_apply import (
            S10MultiRoleService, GROUP_FIXTURE_SPEC,
        )

        ws, source, assets, outputs = _make_real_workspace(tmp_path)
        svc = S10MultiRoleService()
        plan = svc.build_plan(
            roles=GROUP_FIXTURE_SPEC["roles"],
            contact_edges=GROUP_FIXTURE_SPEC.get("contact_edges", []),
            z_order_edges=GROUP_FIXTURE_SPEC.get("z_order_edges", []),
            shots=[{"shot_id": "shot_0", "start_frame": 0, "end_frame": 5}],
            chunk_config={"chunk_frames": 6, "overlap_frames": 0},
        )
        with pytest.raises((ValueError, Exception), match="workspace_id/project_id/video_item_id are REQUIRED"):
            svc.execute_plan_via_renderer(
                plan, workspace_root=ws, source_media=source, assets_dir=assets,
                outputs_dir=outputs,
                workspace_id="ws_test", project_id="proj_test", video_item_id="",
            )

    def test_no_hard_coded_s10_t02_identities_in_service(self) -> None:
        import pathlib
        svc_path = pathlib.Path(__file__).resolve().parent.parent / "app" / "services" / "s10_multi_role_apply.py"
        text = svc_path.read_text(encoding="utf-8")
        for bad in ["s10_t02_ws", "s10_t02_proj", "s10_t02_item"]:
            assert bad not in text, f"hard-coded {bad} found in service — C2 violation"

    def test_no_hash_layer_id_fabrication_in_service(self) -> None:
        import pathlib
        svc_path = pathlib.Path(__file__).resolve().parent.parent / "app" / "services" / "s10_multi_role_apply.py"
        text = svc_path.read_text(encoding="utf-8")
        assert "hashlib.sha256(layer_id.encode()).hexdigest()" not in text
        assert "int(h[0:2], 16)" not in text


class TestC2AuthorityFailClosed:
    """C2: missing/fabricated authority must fail closed before render."""

    def test_missing_affected_region_fails_at_render(self) -> None:
        from app.services.s10_multi_role_apply import (
            S10MultiRoleService, MultiRoleApplyError,
        )

        svc = S10MultiRoleService()
        roles_no_ar = [
            {"role_id": "role_char_a", "layer_id": "layer_char_a",
             "route": "sprite_affine", "pack_version": "p1", "mapping_id": "m1"},
        ]
        plan = svc.build_plan(roles=roles_no_ar)
        assert plan is not None
        role = plan.roles[0]
        assert role.affected_region is None
        with pytest.raises(MultiRoleApplyError, match="affected_region is REQUIRED"):
            svc._build_render_request_for_chunk(
                rm=role,
                chunk=plan.per_role_chunks["role_char_a"][0],
                workspace_root=Path("/tmp"),
                source_media=Path("/tmp/source.mp4"),
                output_media=Path("/tmp/out.mp4"),
                assets_dir=Path("/tmp/assets"),
                workspace_id="ws_test", project_id="proj_test", video_item_id="vid_test",
            )

    def test_unknown_route_fails_closed(self) -> None:
        from app.services.s10_multi_role_apply import (
            S10MultiRoleService, MultiRoleApplyError,
        )

        svc = S10MultiRoleService()
        roles_bad = [
            {"role_id": "role_bad", "layer_id": "layer_bad",
             "route": "unsupported_route", "pack_version": "p1", "mapping_id": "m1"},
        ]
        with pytest.raises(MultiRoleApplyError, match="route must be one of"):
            svc.build_plan(roles=roles_bad)

    def test_unsupported_route_for_adapter_fails_closed(self, tmp_path: Path) -> None:
        from app.services.s10_multi_role_apply import (
            S10MultiRoleService, MultiRoleApplyError,
        )
        import numpy as np
        import cv2
        from app.services.renderer_routes.composite import write_frames_mp4

        ws = tmp_path / "ws"
        ws.mkdir()
        src = ws / "source.mp4"
        write_frames_mp4([np.zeros((120, 160, 3), dtype=np.uint8)], src, fps=24.0)
        assets = ws / "assets"
        assets.mkdir()
        img = np.zeros((40, 40, 4), dtype=np.uint8)
        img[:, :, 3] = 255
        cv2.imwrite(str(assets / "layer_bad.png"), img)

        svc = S10MultiRoleService()
        roles_bad = [
            {"role_id": "role_bad", "layer_id": "layer_bad", "route": "mesh_warp",
             "pack_version": "p1", "mapping_id": "m1",
             "affected_region": [0.1, 0.1, 0.5, 0.5]},
        ]
        plan = svc.build_plan(roles=roles_bad)
        role = plan.roles[0]
        chunk = plan.per_role_chunks["role_bad"][0]
        with pytest.raises(MultiRoleApplyError, match="only sprite_affine/pose_swap/controlled_redraw are wired for real-adapter execution"):
            svc._execute_via_adapter(
                svc._build_render_request_for_chunk(
                    rm=role, chunk=chunk,
                    workspace_root=ws, source_media=src, assets_dir=assets,
                    output_media=ws / "out.mp4",
                    workspace_id="ws_test", project_id="proj_test", video_item_id="vid_test",
                )
            )
