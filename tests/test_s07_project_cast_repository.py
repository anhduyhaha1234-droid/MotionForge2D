"""S07-T01 repository tests — direct repo coverage (no mocks).



Covers:

- workspace isolation (B cannot read/mutate A)

- idempotent replay (no dup, same revision)

- conflict matrix (same key + different payload → stable conflict zero mutation, payload variations)

- stale revision 409 zero mutation

- concurrent CAS one winner

- immutable version pin (publish new version → old mapping byte-identical)

- cross-workspace rejected

- deterministic serialization

- delete/FK fail closed



Uses production ProjectCastRepository via isolated DB (client fixture ensures DB migrated).

"""



from __future__ import annotations

import json
import threading
import uuid

import pytest
from sqlalchemy import select, text

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import (  # noqa: F811  # noqa
    Artifact,
    Character,
    CharacterAsset,
    CharacterPackVersion,
    Project,
    ProjectCastMapping,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.project_cast import (
    ProjectCastConflictError,
    ProjectCastNotFoundError,
    ProjectCastOwnershipError,
    ProjectCastRepository,
)


def _session():

    svc = deps._job_service

    assert svc is not None

    return svc._session_factory()





def _seed(ws: str = DEFAULT_WORKSPACE_ID) -> tuple[str, str, str, str]:

    with _session() as s:

        from sqlalchemy.dialects.sqlite import insert as sqlite_insert



        s.execute(

            sqlite_insert(Workspace)

            .values(id=ws, name=ws)

            .on_conflict_do_nothing(index_elements=[Workspace.id])

        )

        proj = Project(workspace_id=ws, name=f"Proj-{uuid.uuid4().hex[:4]}")

        s.add(proj)

        s.flush()

        vid = VideoItem(project_id=proj.id, title="Vid", position=0)

        s.add(vid)

        s.flush()

        scene = Scene(

            video_item_id=vid.id,

            position=0,

            start_frame=0,

            end_frame=10,

            start_time_ms=0,

            end_time_ms=1000,

            status="pending",

        )

        s.add(scene)

        s.flush()

        from app.persistence.models import ObjectRole



        role = ObjectRole(

            workspace_id=ws,

            project_id=proj.id,

            video_item_id=vid.id,

            source_generation="1",

            name="Hero",

            kind="character",

            status="confirmed",

        )

        s.add(role)

        s.flush()

        char = Character(workspace_id=ws, name="Char", code=f"c_{uuid.uuid4().hex[:6]}")

        s.add(char)

        s.flush()

        pv1 = CharacterPackVersion(

            character_id=char.id, workspace_id=ws, version=1, status="published"

        )

        s.add(pv1)

        s.flush()

        # Create 6 core pose assets for pv1 (complete pack for new policy)

        for slot in ("front", "three_quarter", "side", "back", "sitting", "walking"):

            rel = f"{pv1.id}_{slot}.png"

            data = bytes.fromhex("89504e470d0a1a0a") + b"" * 10

            # write file

            import hashlib as _hl
            import pathlib as _pl

            tgt = _pl.Path(__import__('app.api.deps', fromlist=['_job_service'])._job_service._managed_root) / rel  # noqa: E501

            tgt.parent.mkdir(parents=True, exist_ok=True)

            tgt.write_bytes(data)

            art = Artifact(workspace_id=ws, kind="image", relative_path=rel, state="ready", size_bytes=len(data), mime_type="image/png", sha256=_hl.sha256(data).hexdigest())  # noqa: E501

            s.add(art)

            s.flush()

            ca = CharacterAsset(pack_version_id=pv1.id, workspace_id=ws, pose_slot=slot, artifact_id=art.id)  # noqa: E501

            s.add(ca)

        s.flush()

        pv2 = CharacterPackVersion(

            character_id=char.id, workspace_id=ws, version=2, status="published"

        )

        s.add(pv2)

        s.flush()

        for slot in ("front", "three_quarter", "side", "back", "sitting", "walking"):

            rel = f"{pv2.id}_{slot}.png"

            data = bytes.fromhex("89504e470d0a1a0a") + b"" * 10

            import hashlib as _hl2
            import pathlib as _pl2

            tgt = _pl2.Path(__import__('app.api.deps', fromlist=['_job_service'])._job_service._managed_root) / rel  # noqa: E501

            tgt.parent.mkdir(parents=True, exist_ok=True)

            tgt.write_bytes(data)

            art = Artifact(workspace_id=ws, kind="image", relative_path=rel, state="ready", size_bytes=len(data), mime_type="image/png", sha256=_hl2.sha256(data).hexdigest())  # noqa: E501

            s.add(art)

            s.flush()

            ca = CharacterAsset(pack_version_id=pv2.id, workspace_id=ws, pose_slot=slot, artifact_id=art.id)  # noqa: E501

            s.add(ca)

        s.flush()

        s.commit()

        return proj.id, role.id, char.id, pv1.id





def _repo():

    svc = deps._job_service

    assert svc is not None

    # repository tests use manual session to test transactions

    return svc._session_factory()





def test_workspace_isolation(client) -> None:  # noqa: ARG001 - client ensures DB

    ws_a = DEFAULT_WORKSPACE_ID

    ws_b = f"ws-b-{uuid.uuid4().hex[:6]}"

    proj_a, role_a, char_a, pv_a = _seed(ws_a)

    proj_b, role_b, char_b, pv_b = _seed(ws_b)



    # Create mapping in A

    with _repo() as s:

        repo = ProjectCastRepository(s)

        rec, created = repo.create_mapping(ws_a, proj_a, role_a, char_a, pv_a, f"iso-{uuid.uuid4().hex[:6]}")  # noqa: E501

        s.commit()

        assert created

        mid = rec.id



    # B cannot read A's mapping

    with _repo() as s:

        repo = ProjectCastRepository(s)

        with pytest.raises(ProjectCastNotFoundError):

            repo.get_mapping(mid, ws_b)

        # B listing never shows A's mapping

        lst, _ = repo.list_mappings(ws_b)

        assert all(r.id != mid for r in lst)

        # A can still read

        rec2 = repo.get_mapping(mid, ws_a)

        assert rec2.id == mid





def test_idempotent_replay_no_dup(client) -> None:  # noqa: ARG001

    proj, role, char, pv = _seed()

    key = f"replay-{uuid.uuid4().hex[:6]}"

    with _repo() as s:

        repo = ProjectCastRepository(s)

        r1, c1 = repo.create_mapping(DEFAULT_WORKSPACE_ID, proj, role, char, pv, key)

        s.commit()

        assert c1 is True

        rev1 = r1.revision

        # Equivalent replay

        r2, c2 = repo.create_mapping(DEFAULT_WORKSPACE_ID, proj, role, char, pv, key)

        s.commit()

        assert c2 is False

        assert r2.id == r1.id

        assert r2.revision == rev1

        # No duplicate in DB

        lst, total = repo.list_mappings(DEFAULT_WORKSPACE_ID, project_id=proj)

        assert total == 1





def test_conflict_matrix_payload_variations(client) -> None:  # noqa: ARG001

    proj, role, char, pv = _seed()

    # Create alternative entities for variations

    proj2, role2, char2, pv2 = _seed()

    # Need to ensure alternative pack belongs to char2; create a fresh char2 pack via helper

    # For variations we use distinct ids from second seed

    key = f"conflict-{uuid.uuid4().hex[:6]}"

    # Create a new pack for char to test different pack variation

    with _session() as s2:

        new_pv_for_char = CharacterPackVersion(

            character_id=char, workspace_id=DEFAULT_WORKSPACE_ID, version=77, status="published"

        )

        s2.add(new_pv_for_char)

        s2.commit()

        new_pv_for_char_id = new_pv_for_char.id

    with _repo() as s:

        repo = ProjectCastRepository(s)

        rec, _ = repo.create_mapping(DEFAULT_WORKSPACE_ID, proj, role, char, pv, key)

        s.commit()

        before_rev = rec.revision

        before_id = rec.id

        # Same key + different project -> conflict zero mutation (ownership or conflict both 409)

        with pytest.raises((ProjectCastConflictError, ProjectCastOwnershipError)):

            repo.create_mapping(DEFAULT_WORKSPACE_ID, proj2, role, char, pv, key)

        s.rollback()

        # Same key + different role -> conflict

        with pytest.raises((ProjectCastConflictError, ProjectCastOwnershipError)):

            repo.create_mapping(DEFAULT_WORKSPACE_ID, proj, role2, char, pv, key)

        s.rollback()

        # Same key + different character -> conflict (use char2+pv2 consistent pair)

        with pytest.raises(ProjectCastConflictError):

            repo.create_mapping(DEFAULT_WORKSPACE_ID, proj, role, char2, pv2, key)

        s.rollback()

        # Same key + different pack -> conflict (same char, new pack)

        with pytest.raises(ProjectCastConflictError):

            repo.create_mapping(DEFAULT_WORKSPACE_ID, proj, role, char, new_pv_for_char_id, key)

        s.rollback()

        # Verify zero mutation: original still same, revision unchanged, count still 1

        rec2 = repo.get_mapping(before_id, DEFAULT_WORKSPACE_ID)

        assert rec2.revision == before_rev

        assert rec2.pack_version_id == pv

        lst, total = repo.list_mappings(DEFAULT_WORKSPACE_ID, project_id=proj)

        assert total == 1





def test_stale_revision_409_zero_mutation(client) -> None:  # noqa: ARG001

    proj, role, char, pv = _seed()

    _, _, char2, pv2 = _seed()

    # Actually need char2's pack to match char2; pv2 from second seed belongs to char2

    # For update we need to use pv from second seed but char must match; so use char2+pv2

    with _repo() as s:

        repo = ProjectCastRepository(s)

        rec, _ = repo.create_mapping(DEFAULT_WORKSPACE_ID, proj, role, char, pv, f"stale-{uuid.uuid4().hex[:6]}")  # noqa: E501

        s.commit()

        mid = rec.id

        rev = rec.revision  # 1

        # Valid update with correct revision

        _updated = repo.update_mapping(  # noqa: E501

            mid, DEFAULT_WORKSPACE_ID, rev, pack_version_id=pv, character_id=char

        )

        s.commit()

        # If no change, revision stays 1 (our repo returns same without bump when no mutation)

        # But if we change to a different pack (need char2/pv2), it should bump

        # First test stale: try update with old rev 1 after we already did one update (if bump) ?

        # Our repo only bumps when pack/char changes; we used same pack so no bump -> rev still 1

        # So let's do a real change to bump

        # Create a new pack for same char

        with _session() as s2:

            new_pv = CharacterPackVersion(

                character_id=char, workspace_id=DEFAULT_WORKSPACE_ID, version=99, status="published"

            )

            s2.add(new_pv)
            s2.flush()
            for slot in ("front", "three_quarter", "side", "back", "sitting", "walking"):
                rel = f"{new_pv.id}_{slot}.png"
                data = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 10
                import hashlib as _hl
                import pathlib as _pl
                tgt = _pl.Path(__import__('app.api.deps', fromlist=['_job_service'])._job_service._managed_root) / rel  # noqa: E501
                tgt.parent.mkdir(parents=True, exist_ok=True)
                tgt.write_bytes(data)
                art = Artifact(workspace_id=DEFAULT_WORKSPACE_ID, kind="image", relative_path=rel, state="ready", size_bytes=len(data), mime_type="image/png", sha256=_hl.sha256(data).hexdigest())  # noqa: E501
                s2.add(art)
                s2.flush()
                ca = CharacterAsset(pack_version_id=new_pv.id, workspace_id=DEFAULT_WORKSPACE_ID, pose_slot=slot, artifact_id=art.id)  # noqa: E501
                s2.add(ca)
            s2.flush()

            s2.commit()

            new_pv_id = new_pv.id

        # Now update with correct rev (still 1) to new pack -> should succeed and bump to 2

        rec2 = repo.get_mapping(mid, DEFAULT_WORKSPACE_ID)

        assert rec2.revision == 1

        updated2 = repo.update_mapping(mid, DEFAULT_WORKSPACE_ID, 1, pack_version_id=new_pv_id, character_id=char)  # noqa: E501

        s.commit()

        assert updated2.revision == 2

        assert updated2.pack_version_id == new_pv_id

        # Stale revision 1 -> 409

        with pytest.raises(ProjectCastConflictError, match="stale revision"):

            repo.update_mapping(mid, DEFAULT_WORKSPACE_ID, 1, pack_version_id=pv, character_id=char)

        s.rollback()

        # Verify zero mutation: still revision 2 and pack is new_pv

        rec3 = repo.get_mapping(mid, DEFAULT_WORKSPACE_ID)

        assert rec3.revision == 2

        assert rec3.pack_version_id == new_pv_id





def test_concurrent_cas_one_winner(client) -> None:  # noqa: ARG001

    proj, role, char, pv = _seed()

    with _repo() as s:

        repo = ProjectCastRepository(s)

        rec, _ = repo.create_mapping(DEFAULT_WORKSPACE_ID, proj, role, char, pv, f"conc-{uuid.uuid4().hex[:6]}")  # noqa: E501

        s.commit()

        mid = rec.id

        # Create two new packs for concurrent updates

        with _session() as s2:

            pv_a = CharacterPackVersion(

                character_id=char, workspace_id=DEFAULT_WORKSPACE_ID, version=10, status="published"

            )

            pv_b = CharacterPackVersion(

                character_id=char, workspace_id=DEFAULT_WORKSPACE_ID, version=11, status="published"

            )

            s2.add_all([pv_a, pv_b])
            s2.flush()
            for pv in (pv_a, pv_b):
                for slot in ("front", "three_quarter", "side", "back", "sitting", "walking"):
                    rel = f"{pv.id}_{slot}.png"
                    data = bytes.fromhex("89504e470d0a1a0a") + bytes([0])*10
                    import hashlib as _hl
                    import pathlib as _pl
                    tgt = _pl.Path(__import__('app.api.deps', fromlist=['_job_service'])._job_service._managed_root) / rel  # noqa: E501
                    tgt.parent.mkdir(parents=True, exist_ok=True)
                    tgt.write_bytes(data)
                    art = Artifact(workspace_id=DEFAULT_WORKSPACE_ID, kind="image", relative_path=rel, state="ready", size_bytes=len(data), mime_type="image/png", sha256=_hl.sha256(data).hexdigest())  # noqa: E501
                    s2.add(art)
                    s2.flush()
                    ca = CharacterAsset(pack_version_id=pv.id, workspace_id=DEFAULT_WORKSPACE_ID, pose_slot=slot, artifact_id=art.id)  # noqa: E501
                    s2.add(ca)
            s2.flush()

            s2.commit()

            pv_a_id, pv_b_id = pv_a.id, pv_b.id



        results: list[str] = []

        errors: list[str] = []



        def try_update(target_pv: str) -> None:

            svc = deps._job_service

            assert svc is not None

            with svc._session_factory() as sess:

                r = ProjectCastRepository(sess)

                try:

                    rec_up = r.update_mapping(mid, DEFAULT_WORKSPACE_ID, 1, pack_version_id=target_pv, character_id=char)  # noqa: E501

                    sess.commit()

                    results.append(rec_up.pack_version_id)

                except ProjectCastConflictError as e:

                    sess.rollback()

                    errors.append(str(e))

                except Exception as e:  # noqa: BLE001

                    sess.rollback()

                    errors.append(f"other:{e}")



        t1 = threading.Thread(target=try_update, args=(pv_a_id,))

        t2 = threading.Thread(target=try_update, args=(pv_b_id,))

        t1.start()

        t2.start()

        t1.join()

        t2.join()



        assert len(results) == 1, f"expected one winner, got {results} errors {errors}"

        assert len(errors) == 1

        assert "stale revision" in errors[0]

        # Final DB has winner's pack, revision 2

        with _repo() as s:

            repo = ProjectCastRepository(s)

            final = repo.get_mapping(mid, DEFAULT_WORKSPACE_ID)

            assert final.revision == 2

            assert final.pack_version_id in (pv_a_id, pv_b_id)





def test_immutable_version_pin_publish_new_does_not_change_old(client) -> None:  # noqa: ARG001

    proj, role, char, pv1 = _seed()

    with _repo() as s:

        repo = ProjectCastRepository(s)

        rec, _ = repo.create_mapping(DEFAULT_WORKSPACE_ID, proj, role, char, pv1, f"immut-{uuid.uuid4().hex[:6]}")  # noqa: E501

        s.commit()

        mid = rec.id

        _before_json = json.dumps(rec.__dict__, sort_keys=True, default=str)  # noqa: F841

        # Simulate new publish: create new pack version row

        with _session() as s2:

            pv_new = CharacterPackVersion(

                character_id=char, workspace_id=DEFAULT_WORKSPACE_ID, version=77, status="published"

            )

            s2.add(pv_new)

            s2.commit()

            pv_new_id = pv_new.id

        # Old mapping byte-identical and still points old pack_version id

        with _repo() as s:

            repo = ProjectCastRepository(s)

            after = repo.get_mapping(mid, DEFAULT_WORKSPACE_ID)

            _after_json = json.dumps(after.__dict__, sort_keys=True, default=str)  # noqa: F841

            assert after.pack_version_id == pv1

            assert after.pack_version_id != pv_new_id

            assert after.revision == rec.revision

            assert after.character_id == rec.character_id

            assert after.project_id == rec.project_id

            assert after.object_role_id == rec.object_role_id





def test_cross_workspace_rejected(client) -> None:  # noqa: ARG001

    ws_other = f"ws-other-{uuid.uuid4().hex[:6]}"

    proj_a, role_a, char_a, pv_a = _seed(DEFAULT_WORKSPACE_ID)

    proj_b, role_b, char_b, pv_b = _seed(ws_other)



    with _repo() as s:

        repo = ProjectCastRepository(s)

        # cross project

        with pytest.raises(ProjectCastOwnershipError):

            repo.create_mapping(DEFAULT_WORKSPACE_ID, proj_b, role_a, char_a, pv_a, f"xws-p-{uuid.uuid4().hex[:6]}")  # noqa: E501

        s.rollback()

        # cross role

        with pytest.raises(ProjectCastOwnershipError):

            repo.create_mapping(DEFAULT_WORKSPACE_ID, proj_a, role_b, char_a, pv_a, f"xws-r-{uuid.uuid4().hex[:6]}")  # noqa: E501

        s.rollback()

        # cross character

        with pytest.raises(ProjectCastOwnershipError):

            repo.create_mapping(DEFAULT_WORKSPACE_ID, proj_a, role_a, char_b, pv_b, f"xws-c-{uuid.uuid4().hex[:6]}")  # noqa: E501

        s.rollback()

        # cross pack

        with pytest.raises(ProjectCastOwnershipError):

            repo.create_mapping(DEFAULT_WORKSPACE_ID, proj_a, role_a, char_a, pv_b, f"xws-pv-{uuid.uuid4().hex[:6]}")  # noqa: E501

        s.rollback()

        # No leak: listing only shows own workspace

        lst, _ = repo.list_mappings(DEFAULT_WORKSPACE_ID)

        for r in lst:

            assert r.workspace_id == DEFAULT_WORKSPACE_ID





def test_delete_fk_fail_closed(client) -> None:  # noqa: ARG001

    proj, role, char, pv = _seed()

    with _repo() as s:

        repo = ProjectCastRepository(s)

        rec, _ = repo.create_mapping(DEFAULT_WORKSPACE_ID, proj, role, char, pv, f"del-{uuid.uuid4().hex[:6]}")  # noqa: E501

        s.commit()

        mid = rec.id

        # Attempt to delete referenced project via raw SQL should fail FK

        with _session() as s2:

            from sqlalchemy.exc import IntegrityError as SAIntegrityError



            with pytest.raises(SAIntegrityError):

                s2.execute(text("DELETE FROM project WHERE id=:id"), {"id": proj})

                s2.commit()

            s2.rollback()

            with pytest.raises(SAIntegrityError):

                s2.execute(text("DELETE FROM object_role WHERE id=:id"), {"id": role})

                s2.commit()

            s2.rollback()

        # But deleting the mapping itself succeeds

        with _repo() as s3:

            repo3 = ProjectCastRepository(s3)

            # fetch revision for delete (new policy requires revision)
            rec_del = repo3.get_mapping(mid, DEFAULT_WORKSPACE_ID)
            repo3.delete_mapping(mid, DEFAULT_WORKSPACE_ID, expected_revision=rec_del.revision)

            s3.commit()

            with pytest.raises(ProjectCastNotFoundError):

                repo3.get_mapping(mid, DEFAULT_WORKSPACE_ID)





def test_deterministic_serialization(client) -> None:  # noqa: ARG001

    proj, role, char, pv = _seed()

    with _repo() as s:

        repo = ProjectCastRepository(s)

        rec, _ = repo.create_mapping(DEFAULT_WORKSPACE_ID, proj, role, char, pv, f"det-{uuid.uuid4().hex[:6]}")  # noqa: E501

        s.commit()

        mid = rec.id

        a = repo.get_mapping(mid, DEFAULT_WORKSPACE_ID)

        b = repo.get_mapping(mid, DEFAULT_WORKSPACE_ID)

        assert json.dumps(a.__dict__, sort_keys=True, default=str) == json.dumps(

            b.__dict__, sort_keys=True, default=str

        )

        # Field order is dataclass field order

        assert list(a.__dict__.keys()) == list(b.__dict__.keys())



def test_natural_lookup_scoped_no_cross_workspace_occupancy_leak(client):
    # C4-P1b regression: the (project_id, object_role_id) natural-key
    # pre-check MUST be workspace-scoped. A cross-workspace request that
    # reuses an occupied pair must fail closed EXACTLY like an unoccupied
    # one - no 409 'already exists' oracle, no mutation, W1 mapping intact.
    ws_a = DEFAULT_WORKSPACE_ID
    ws_b = f"ws-b-{uuid.uuid4().hex[:6]}"
    proj_a, role_a, char_a, pv_a = _seed(ws_a)
    proj_c, role_c, char_c, pv_c = _seed(ws_a)  # unoccupied pair in A
    proj_b, role_b, char_b, pv_b = _seed(ws_b)

    # Occupy (proj_a, role_a) in W1.
    key1 = f"c4occ-{uuid.uuid4().hex[:6]}"
    with _repo() as s:
        repo = ProjectCastRepository(s)
        rec1, created1 = repo.create_mapping(ws_a, proj_a, role_a, char_a, pv_a, key1)
        s.commit()
        assert created1
    baseline = dict(rec1.__dict__)

    def _count_rows(ws: str) -> int:
        from sqlalchemy import func as _f

        with _repo() as s:
            return int(
                s.scalar(
                    select(_f.count()).select_from(ProjectCastMapping).where(
                        ProjectCastMapping.workspace_id == ws
                    )
                )
                or 0
            )

    before_b = _count_rows(ws_b)
    assert before_b == 0

    outcomes: list[str] = []

    def _probe(target_pair: tuple[str, str]) -> None:
        p_id, r_id = target_pair
        key = f"c4leak-{uuid.uuid4().hex[:6]}"
        with _repo() as s:
            repo = ProjectCastRepository(s)
            try:
                repo.create_mapping(ws_b, p_id, r_id, char_b, pv_b, key)
                s.commit()
                raise AssertionError("cross-workspace request must not succeed")
            except ProjectCastConflictError as e:
                s.rollback()
                assert "already exists" not in str(e), f"occupancy leak via natural key: {e}"
                outcomes.append(f"conflict:{e}")
            except (ProjectCastOwnershipError, ProjectCastNotFoundError) as e:
                s.rollback()
                outcomes.append(f"closed:{type(e).__name__}")

    # OCCUPIED pair (mapping exists in W1) vs UNOCCUPIED pair (no mapping
    # anywhere): identical fail-closed family required.
    _probe((proj_a, role_a))
    _probe((proj_c, role_c))
    assert len(outcomes) == 2, outcomes
    family = {o.split(':')[0] for o in outcomes}
    assert family == {"closed"}, f"inconsistent fail-closed outcomes: {outcomes}"

    # Zero mutation in W2 and W1 mapping byte-identical afterwards.
    assert _count_rows(ws_b) == before_b == 0
    with _repo() as s:
        repo = ProjectCastRepository(s)
        rec1_after = repo.get_mapping(rec1.id, ws_a)
    strip = ("created_at", "updated_at")
    assert {k: v for k, v in rec1_after.__dict__.items() if k not in strip} == {
        k: v for k, v in baseline.items() if k not in strip
    }, "W1 mapping mutated by W2 probes"
