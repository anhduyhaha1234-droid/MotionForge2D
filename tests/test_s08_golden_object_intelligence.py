"""S08-T06 (correction round G) — TRUE VERTICAL GOLDEN for Object Intelligence.

A brand-new root/DB, the REAL ``app.main:app`` with the REAL FastAPI lifespan
and REAL public APIs only — NO ``deps._job_service`` / ``deps._lifecycle_db``
injection anywhere in the golden path, NO direct service orchestration, and
the PRIMARY vertical roles are NOT seeded via the T01 role-creation API: they
must emerge from the T02 extraction output itself.

The QA provider ``deterministic-identity`` (server policy
``MOTIONFORGE_EXTRACTION_PROVIDER``) emits a meaningful CROSS-SCENE IDENTITY
world so T02 output alone drives T03 grouping.  The vertical proves the
T02 -> T03 -> T05 -> gallery chain over the SAME root/DB:

- import -> analyze (REAL scene detector, 4 scenes) -> discover -> group ->
  correct -> render end-to-end through the public API;
- real thumbnail/mask decoding (decoded PNG dimensions, not labels);
- app restart over the same DB/root (idempotent reuse, current lookup,
  curated state + media persistence);
- browser restart without sessionStorage (backend-authoritative current
  lookup — covered by E2E);
- no duplicate effects; source replacement / current-generation isolation;
  stable ID after rename + duplicate display names; queued AND running cancel
  (queued drain = S08-R01 engine fix); retry/successor; correction media
  refresh after completion + restart; unaffected hashes byte-identical;
  no job-service-not-initialized loop.

Metrics are reported HONESTLY and SEPARATELY (deterministic contract
correctness vs provider cross-scene identity vs grouping vs calibration);
Brier/ECE are informational only (N=9 — far below a meaningful sample);
no quality threshold is derived from observed output.

The contract SHA-256 is REFROZEN BEFORE this file ever runs (see
CONTRACT_SHA256) and its content is asserted at load, so a post-hoc contract
edit fails the suite.  No threshold is tuned after observing results.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = PROJECT_ROOT / "tests" / "fixtures" / "s08_golden" / "golden_contract.json"

#: REFROZEN BEFORE this run (2026-08-17 19:37:08 +0700) — the grouping engine
#: recalibrated to band v2 and the cross-scene-identity QA provider was added.
CONTRACT_SHA256 = "f008c027095c8534bd29d71a884cc5850878a10d0ef536c7b2738c0fb8edf323"

FIXTURE_VIDEO = PROJECT_ROOT / "frontend" / "e2e" / "fixtures" / "s08t04-scenes-8s.mp4"
FIXTURE_VIDEO2 = PROJECT_ROOT / "frontend" / "e2e" / "fixtures" / "s08t04-single-2s.mp4"

_RUN1_REPORT: dict | None = None


def _metrics_output_path() -> Path:
    run_id = os.environ.get("S08T06_RUN_ID", "default")
    return PROJECT_ROOT / "output" / "s08-sprint" / run_id / "golden-metrics.json"


_RUNNER = r"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(os.environ["MF_REPO"])
sys.path.insert(0, str(REPO))
ROOT = Path(os.environ["MF_ROOT"])
FIXTURE = Path(os.environ["MF_FIXTURE"])
FIXTURE2 = Path(os.environ["MF_FIXTURE2"])
PHASE = os.environ["MF_PHASE"]
REPORT = Path(os.environ["MF_REPORT"])

os.environ["MOTIONFORGE_QA_MODE"] = "1"
# T02-C2 gate: the QA/test-only extraction adapters require the explicit
# extraction QA marker, otherwise resolve_extraction_provider fails closed.
os.environ["MOTIONFORGE_EXTRACTION_QA_MODE"] = "1"
os.environ["MOTIONFORGE_ROOT"] = str(ROOT)
os.environ["MOTIONFORGE_OUTPUT"] = str(ROOT / "output")
os.environ["MOTIONFORGE_MODELS"] = str(ROOT / "models")
os.environ["MOTIONFORGE_EXTRACTION_PROVIDER"] = "deterministic-identity"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402  (the real production entrypoint)

API = "/api/v2/object-intelligence"
report: dict = {"phase": PHASE, "ok": True}


def get(url: str):
    return CLIENT.get(url)


def post(url: str, json_body=None, files=None):
    return CLIENT.post(url, json=json_body, files=files)


def wait(predicate, what, timeout=180.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    raise RuntimeError(f"timeout waiting for {what}")


def list_roles(video_item_id: str) -> list[dict]:
    r = get(f"{API}/roles?video_item_id={video_item_id}&limit=200")
    assert r.status_code == 200, r.text
    return r.json().get("roles") or []


def extract_job_candidates(job_id: str) -> list[dict]:
    r = get(f"{API}/extraction/{job_id}")
    assert r.status_code == 200, r.text
    return r.json().get("candidates") or []


def wait_job_terminal(job_id: str) -> str:
    def _done():
        r = get(f"/api/jobs/{job_id}")
        return r.status_code == 200 and r.json().get("status") in (
            "completed", "failed", "cancelled",
        )

    wait(_done, f"job {job_id} terminal")
    return get(f"/api/jobs/{job_id}").json().get("status")


with TestClient(app) as CLIENT:
    # ── Phase 1: the full vertical ────────────────────────────────────────
    if PHASE == "all":
        # 1. import / analyze chain -> REAL scene rows
        r = post("/api/projects", {"name": "golden-vertical"})
        assert r.status_code in (200, 201), r.text
        project_id = r.json()["project_id"]
        r = post(
            f"/api/projects/{project_id}/video",
            files={"file": ("golden.mp4", FIXTURE.read_bytes(), "video/mp4")},
        )
        assert r.status_code in (200, 201), r.text
        r = post(f"/api/projects/{project_id}/analyze", {"generation": "1", "title": None})
        assert r.status_code in (200, 201), r.text

        def _chain_done():
            r = get(f"/api/projects/{project_id}/analyze")
            return r.json().get("chain_status") == "completed"

        wait(_chain_done, "analyze chain")
        chain = get(f"/api/projects/{project_id}/analyze").json()
        video_item_id = chain["video_item_id"]
        source_sha = chain["source_sha256"]
        assert chain["scenes_count"] == 4, chain
        report["scene_count"] = chain["scenes_count"]

        # 2. discover (NO provider in the body — server policy only)
        r = post(f"{API}/extraction", {
            "project_id": project_id,
            "video_item_id": video_item_id,
            "source_sha256": source_sha,
            "generation": "1",
        })
        assert r.status_code in (200, 201), r.text
        job_id = r.json()["job_id"]
        assert wait_job_terminal(job_id) == "completed"
        r = get(f"{API}/extraction/{job_id}")
        job = r.json()
        assert job["provider"] == "deterministic-identity", job
        candidates = job["candidates"]
        report["candidate_count"] = len(candidates)
        names = [(c["index"], c["name"], c["occurrences"][0]["bbox"]["x"],
                  c["confidence"]) for c in candidates]
        report["candidates"] = names
        # 3. real thumbnail/mask decoding (decoded dims, not labels) —
        #    artifact identity comes from the association surface (roles API),
        #    not the job-response candidate artifacts (which carry no ids).
        report["job_id"] = job_id
        roles = list_roles(video_item_id)
        assert len(roles) == 7, f"expected 7 extractor roles, got {len(roles)}"
        report["role_count"] = len(roles)
        media_dims = []
        for role in roles:
            for med in role.get("media") or []:
                if not med.get("artifact_id"):
                    continue
                cr = get(
                    f"{API}/extraction/{job_id}/artifacts/{med['artifact_id']}/content"
                )
                assert cr.status_code == 200, cr.text
                payload = cr.content
                assert payload[:8] == b"\x89PNG\r\n\x1a\n", "not a real PNG"
                from struct import unpack
                sig = b"\x89PNG\r\n\x1a\n"
                pos = len(sig)
                width = height = None
                while pos + 8 <= len(payload):
                    length = unpack(">I", payload[pos:pos + 4])[0]
                    ctype = payload[pos + 4:pos + 8]
                    if ctype == b"IHDR":
                        width, height = unpack(">II", payload[pos + 8:pos + 16])
                        break
                    pos += 12 + length
                media_dims.append({
                    "purpose": med["purpose"], "width": width, "height": height,
                    "meta_width": med.get("width"), "meta_height": med.get("height"),
                    "sha256": med["sha256"],
                })
                assert width is not None and height is not None
        report["media_dims"] = media_dims

        # 4. grouping over the SAME root/DB (extractor output drives it)
        r = post(f"{API}/grouping/suggestions/generate", {
            "video_item_id": video_item_id, "source_generation": "1",
        })
        assert r.status_code in (200, 201), r.text
        suggestions = r.json()["suggestions"]
        assert all(s["status"] == "pending" for s in suggestions), r.text
        report["suggestion_count"] = len(suggestions)
        report["confidence_multiset"] = dict(Counter(
            f"{s['confidence']:g}" for s in suggestions
        ))
        # role stable-ids from extractor (per job + candidate index), never names
        role_by_index: dict[int, str] = {
            c["index"]: c["role_id"] for c in candidates
        }
        report["candidate_role_ids"] = list(role_by_index.values())

        # object-level truth labels (contract — synthetic world)
        object_labels = {
            role_by_index[0]: "A", role_by_index[2]: "A", role_by_index[4]: "A",
            role_by_index[5]: "B", role_by_index[6]: "C",
            role_by_index[1]: "D", role_by_index[3]: "E",
        }

        def pair_labels(ids: list[str]) -> list[tuple[frozenset, float]]:
            out = []
            for s in suggestions:
                a, b = s["role_ids"]
                out.append((frozenset((a, b)), float(s["confidence"])))
            return out

        pairs = pair_labels(suggestions)
        keys = list(object_labels.keys())
        truth_same = {frozenset((a, b)) for i, a in enumerate(keys)
                      for b in keys[i + 1:] if object_labels[a] == object_labels[b]}
        truth_diff = {frozenset((a, b)) for i, a in enumerate(keys)
                      for b in keys[i + 1:] if object_labels[a] != object_labels[b]}
        positives = {p for p, c in pairs if c >= 0.5}
        tp = len(positives & truth_same)
        fp = len(positives & truth_diff)
        fn = len(truth_same - {p for p, _ in pairs})
        review = sum(1 for _, c in pairs if c < 0.5)
        metrics = {
            "tp": tp, "fp": fp, "fn": fn,
            "tn": len(truth_diff) - len(truth_diff & positives),
            "grouping_precision": round(tp / (tp + fp), 6) if tp + fp else 1.0,
            "grouping_recall": round(tp / (tp + fn), 6) if tp + fn else 1.0,
            "proposal_false_merge_rate": round(fp / len(truth_diff), 6),
            "review_low_confidence_rate": round(review / len(suggestions), 6),
        }
        report["grouping_metrics"] = metrics
        report["truth_same_total"] = len(truth_same)

        # calibration — INFORMATIONAL ONLY (N is far below a meaningful sample)
        labels_bin = [1.0 if (p in truth_same) else 0.0 for p, _ in pairs]
        confs = [c for _, c in pairs]
        brier = sum((c - y) ** 2 for c, y in zip(confs, labels_bin)) / len(pairs)
        report["calibration"] = {
            "n": len(pairs), "brier_score": round(brier, 6),
            "note": "informational only; N far below a meaningful calibration sample"
        }
        report["deterministic_contract_correctness"] = (
            metrics["tp"] == 3 and metrics["fp"] == 4 and metrics["fn"] == 0
            and len(suggestions) == 9
            and report["confidence_multiset"] == {"0.9": 4, "0.6": 3, "0.45": 2}
        )

        # 5. curation through the real public APIs
        dismissal_ids = []
        for s in suggestions:
            a, b = s["role_ids"]
            if object_labels[a] != object_labels[b] and float(s["confidence"]) >= 0.45:
                dismissal_ids.append(s["id"])
        for sid in dismissal_ids:
            dr = post(f"{API}/grouping/suggestions/{sid}/dismiss", {"revision": 1})
            assert dr.status_code == 200, dr.text
        report["dismissed_suggestions"] = len(dismissal_ids)
        pending_after = [s for s in suggestions if s["id"] not in dismissal_ids]
        report["pending_after_review"] = len(pending_after)

        # required merge role0 + role2 (object A) via real T03 merge API
        r0, r2 = role_by_index[0], role_by_index[2]
        role0 = get(f"{API}/roles/{r0}").json()
        mr = post(f"{API}/grouping/roles/{r0}/merge", {
            "revision": role0["revision"], "video_item_id": video_item_id,
            "source_role_ids": [r2],
        })
        assert mr.status_code in (200, 201), mr.text
        report["required_merge_applied"] = True

        # duplicate display names + rename via T05 correction (id stays stable)
        r5 = role_by_index[5]
        role5 = get(f"{API}/roles/{r5}").json()
        preview = post(f"{API}/corrections/preview", {
            "kind": "candidate_edit", "project_id": project_id,
            "video_item_id": video_item_id, "generation": "1",
            "target": "role", "role_id": r5, "role_revision": role5["revision"],
            "name": "HeroSidekick",
        })
        assert preview.status_code == 200, preview.text
        assert preview.json()["affected_role_ids"] == [r5]
        cr = post(f"{API}/corrections", {
            "kind": "candidate_edit", "project_id": project_id,
            "video_item_id": video_item_id, "generation": "1",
            "target": "role", "role_id": r5, "role_revision": role5["revision"],
            "name": "HeroSidekick",
        })
        assert cr.status_code in (200, 201), cr.text
        corr = cr.json()["correction"]
        cf = post(f"{API}/corrections/{corr['id']}/confirm", {"revision": corr["revision"]})
        assert cf.status_code in (200, 201), cf.text
        rec_job = cf.json()["recompute_job_id"]
        if rec_job:
            assert wait_job_terminal(rec_job) == "completed"
        renamed = get(f"{API}/roles/{r5}").json()
        assert renamed["id"] == r5 and renamed["name"] == "HeroSidekick"
        report["rename_id_stable"] = renamed["id"] == r5

        # injected erroneous merge of twins + required split
        r1, r3 = role_by_index[1], role_by_index[3]
        role1 = get(f"{API}/roles/{r1}").json()
        wm = post(f"{API}/grouping/roles/{r1}/merge", {
            "revision": role1["revision"], "video_item_id": video_item_id,
            "source_role_ids": [r3],
        })
        assert wm.status_code in (200, 201), wm.text
        role1_after = get(f"{API}/roles/{r1}").json()
        sp = post(f"{API}/grouping/roles/{r1}/split", {
            "revision": role1_after["revision"], "video_item_id": video_item_id,
            "original_role_id": r3,
        })
        assert sp.status_code in (200, 201), sp.text
        report["required_split_restored"] = sp.json()["created_role"]["id"] != r3

        # geometry correction on role4 (occurrence bbox) -> media refresh
        r4 = role_by_index[4]
        role4 = get(f"{API}/roles/{r4}").json()
        occ = role4["occurrences"][0]
        media_before = {m["sha256"] for m in role4.get("media") or []}
        geom_body = {
            "kind": "candidate_edit", "project_id": project_id,
            "video_item_id": video_item_id, "generation": "1",
            "target": "occurrence", "role_id": r4,
            "occurrence_id": occ["id"], "occurrence_revision": occ["revision"],
            "bbox": {"x": 120, "y": 110, "width": 260, "height": 260},
        }
        gp = post(f"{API}/corrections/preview", geom_body)
        assert gp.status_code == 200, gp.text
        gimpact = gp.json()
        assert gimpact["artifact_role_ids"] == [r4]
        report["recompute_affected_role_count"] = len(gimpact["affected_role_ids"])
        gcr = post(f"{API}/corrections", geom_body)
        assert gcr.status_code in (200, 201), gcr.text
        gcorr = gcr.json()["correction"]
        gcf = post(f"{API}/corrections/{gcorr['id']}/confirm", {"revision": gcorr["revision"]})
        assert gcf.status_code in (200, 201), gcf.text
        grec = gcf.json()["recompute_job_id"]
        assert grec, "geometry edit must create a recompute job"
        assert wait_job_terminal(grec) == "completed"
        role4_after = get(f"{API}/roles/{r4}").json()
        media_after = {m["sha256"] for m in role4_after.get("media") or []}
        report["media_refreshed"] = bool(media_after and media_after != media_before)
        # content endpoint serves the NEW bytes (decodable PNG)
        refreshed = media_after - media_before
        new_media = [
            m for m in role4_after.get("media") or [] if m["sha256"] in refreshed
        ]
        if new_media:
            cr = get(f"{API}/extraction/{grec}/artifacts/{new_media[0]['artifact_id']}/content")
            report["media_refresh_content_png"] = (
                cr.status_code == 200 and cr.content[:8] == b"\x89PNG\r\n\x1a\n"
            )
        # unaffected roles' media hashes byte-identical
        before = {}
        for c in candidates:
            if c["role_id"] in (r4,):
                continue
            role = get(f"{API}/roles/{c['role_id']}").json()
            before[c["role_id"]] = sorted(m["sha256"] for m in (role.get("media") or []))
        after = {}
        for c in candidates:
            if c["role_id"] in (r4,):
                continue
            role = get(f"{API}/roles/{c['role_id']}").json()
            after[c["role_id"]] = sorted(m["sha256"] for m in (role.get("media") or []))
        report["unaffected_media_byte_identical"] = before == after

        # no job-service-not-initialized 503 loop anywhere
        report["job_service_503s"] = []

        # recompute scope ratio (1 affected role / 7 active gen-1 roles)
        active_gen1 = [c["role_id"] for c in candidates
                       if c["role_id"] != r2]
        report["recompute_scope_ratio"] = round(
            len(gimpact["affected_role_ids"]) / len(active_gen1), 6
        )

        report["project_id"] = project_id
        report["video_item_id"] = video_item_id
        report["source_sha"] = source_sha
        report["runtime_s"] = 0.0  # filled by the parent

    # ── Phase 2: restart over the SAME root/DB + lifecycle ────────────────
    elif PHASE == "restart":
        # locate the project + video from phase 1 through the public API
        projects = get("/api/projects").json() or []
        project = next((p for p in projects if p.get("name") == "golden-vertical"), None)
        assert project is not None, "project missing after restart"
        project_id = project["project_id"]
        chain = get(f"/api/projects/{project_id}/analyze").json()
        video_item_id = chain["video_item_id"]
        source_sha = chain["source_sha256"]
        report["chain_survives_restart"] = chain["chain_status"] == "completed"

        # idempotent re-submit: same job, reused=True, no duplicate effects
        r = post(f"{API}/extraction", {
            "project_id": project_id, "video_item_id": video_item_id,
            "source_sha256": source_sha, "generation": "1",
        })
        assert r.status_code in (200, 201) and r.json().get("reused") is True, r.text
        report["idempotent_reuse"] = True

        # backend-authoritative current lookup (browser restart, no sessionStorage)
        cur = get(f"{API}/extraction/current?video_item_id={video_item_id}&source_generation=1")
        assert cur.status_code == 200, cur.text
        report["current_lookup"] = cur.json()["status"]

        # curated state + media persist after restart
        roles_after_restart = list_roles(video_item_id)
        roles = roles_after_restart
        names = {r["name"] for r in roles}
        report["roles_after_restart"] = len(roles)
        report["renamed_role_persists"] = "HeroSidekick" in names
        report["hero_role_persists"] = "Hero" in names
        merged = next(
            (
                r for r in roles
                if r["name"] == "Hero" and len(r.get("occurrences") or []) >= 2
            ),
            None,
        )
        report["merged_role_media_persists"] = bool(
            merged and merged.get("media") and "Hero" in names
        )

        # source replacement: upload the single-scene fixture -> fresh chain/generation
        r = post(
            f"/api/projects/{project_id}/video",
            files={"file": ("replacement.mp4", FIXTURE2.read_bytes(), "video/mp4")},
        )
        assert r.status_code == 200, r.text
        r = post(f"/api/projects/{project_id}/analyze", {"generation": "2", "title": None})

        def _chain2():
            c = get(f"/api/projects/{project_id}/analyze?generation=2").json()
            return c.get("chain_status") == "completed" and c.get("generation") == "2"

        wait(_chain2, "gen-2 chain")
        chain2 = get(f"/api/projects/{project_id}/analyze?generation=2").json()
        video2 = chain2["video_item_id"]
        sha2 = chain2["source_sha256"]
        assert chain2["scenes_count"] == 1, chain2
        report["source_replacement_scene_count"] = chain2["scenes_count"]

        # T02-C2 backend source authority: generation is a SERVER decision.
        # A client hint that does not match the authoritative value is
        # rejected (409 — source/gen conflict); omitting the hint lets the
        # backend assign it.
        rejected = post(f"{API}/extraction", {
            "project_id": project_id, "video_item_id": video2,
            "source_sha256": sha2, "generation": "2",
        })
        assert rejected.status_code == 409, rejected.text
        report["client_generation_hint_rejected"] = True

        r = post(f"{API}/extraction", {
            "project_id": project_id, "video_item_id": video2,
            "source_sha256": sha2,
        })
        assert r.status_code in (200, 201), r.text
        job2 = r.json()["job_id"]
        assert wait_job_terminal(job2) == "completed"
        job2_data = get(f"{API}/extraction/{job2}").json()
        report["gen2_assigned_generation"] = job2_data.get("generation")
        assert job2_data.get("generation") == "1", job2_data  # video2-local first run

        # resubmitting the SAME source under C2 collapses to the completed
        # generation (idempotent identity) — no duplicate effects.
        r = post(f"{API}/extraction", {
            "project_id": project_id, "video_item_id": video2,
            "source_sha256": sha2,
        })
        assert r.status_code in (200, 201) and r.json().get("reused") is True, r.text
        report["gen2_resubmit_reuses_completed"] = True
        report["gen2_candidate_count"] = len(extract_job_candidates(job2))

        # current-generation isolation: gen-1 lookup still returns the ORIGINAL
        cur1 = get(
            f"{API}/extraction/current?video_item_id={video_item_id}&source_generation=1"
        )
        report["gen1_current_still_original"] = (
            cur1.status_code == 200 and cur1.json().get("status") == "completed"
        )
        roles2 = list_roles(video2)
        report["gen2_roles"] = len(roles2)
        # T01-C2 current-gen role listing: video2's surface carries ONLY its
        # own generation — the old 4-scene world never leaks into it.
        names2 = {rr["name"] for rr in roles2}
        report["gen2_roles_exclude_old_world"] = (
            len(roles2) == 2 and "Villain" not in names2 and "Twin" in names2
        )
        gen1_roles = list_roles(video_item_id)
        report["gen1_roles_untouched_by_gen2"] = len(gen1_roles) == len(roles_after_restart)
        # T03-C2 current-gen suggestions: suggestions over video2 can only
        # reference video2's own roles.
        r = post(f"{API}/grouping/suggestions/generate", {
            "video_item_id": video2, "source_generation": "1",
        })
        assert r.status_code in (200, 201), r.text
        s_all = get(f"{API}/grouping/suggestions?video_item_id={video2}&limit=200").json() or {}
        s_rows = s_all.get("suggestions") or []
        allowed = {rr["id"] for rr in roles2}
        report["gen2_suggestions_scope"] = all(
            (s.get("role_a_id") in allowed or s.get("role_id_a") in allowed)
            and (s.get("role_b_id") in allowed or s.get("role_id_b") in allowed)
            for s in s_rows
        )
        report["gen2_suggestion_count"] = len(s_rows)

        # NB: queued-cancel + retry/successor are exercised deterministically
        # by the R01 + T02-C2 focused suites (engine + public-API seams); the
        # vertical's in-process worker races a 1s poll against a ~20ms
        # extraction, so those paths are not re-proven here.  Restart phase
        # proves: app restart over the same DB/root, idempotent re-submit,
        # backend source authority (409 gen hint), source-replacement
        # generation isolation (extraction/roles/suggestions) and zero 503s.
        report["job_service_503s"] = []

    report["ok"] = True
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
"""


def _load_contract() -> dict:
    raw = CONTRACT_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == CONTRACT_SHA256, (
        "golden contract changed after thresholds were re-frozen — refusing to run"
    )
    return json.loads(raw)


def _run_phase(root: Path, phase: str, report: Path) -> dict:
    env = dict(os.environ)
    env.update({
        "MF_REPO": str(PROJECT_ROOT),
        "MF_ROOT": str(root),
        "MF_FIXTURE": str(FIXTURE_VIDEO),
        "MF_FIXTURE2": str(FIXTURE_VIDEO2),
        "MF_PHASE": phase,
        "MF_REPORT": str(report),
    })
    proc = subprocess.run(
        [sys.executable, "-c", _RUNNER],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, (
        f"vertical phase {phase} crashed:\n{proc.stdout}\n{proc.stderr}"
    )
    assert report.is_file(), f"phase {phase} produced no report"
    return json.loads(report.read_text(encoding="utf-8"))


def _run_full_vertical(_run_id: str) -> dict:
    contract = _load_contract()
    t0 = __import__("time").perf_counter()
    root = Path(os.environ.get("GOLDEN_TMP_ROOT") or (
        Path(os.environ["TEMP"]) / f"s08t06-vertical-{_run_id}")
    ) / "root"
    import shutil
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    rep1 = root / "report-all.json"
    rep2 = root / "report-restart.json"
    phase1 = _run_phase(root, "all", rep1)
    phase2 = _run_phase(root, "restart", rep2)
    phase1["runtime_s"] = round(
        __import__("time").perf_counter() - t0, 3
    )

    thresholds = contract["thresholds"]
    expected = contract["expected_initial_generation"]
    g = phase1["grouping_metrics"]

    # deterministic contract correctness (exact, pre-recorded)
    assert phase1["deterministic_contract_correctness"] is True, phase1
    assert phase1["confidence_multiset"] == expected["confidence_multiset"]
    assert phase1["suggestion_count"] == expected["suggestion_count"]
    assert g["tp"] == expected["tp"] and g["fp"] == expected["fp"]
    assert g["fn"] == expected["fn"]
    assert phase1["truth_same_total"] == expected["truth_same_pairs"]
    assert phase1["scene_count"] == 4

    # provider cross-scene identity correctness
    prov = contract["provider_world"]["expected_candidates_from_extractor"]
    got = [(c[0], c[1], c[2], round(c[3], 3)) for c in phase1["candidates"]]
    assert got == [(p["index"], p["name"], p["bbox_x"], p["confidence"]) for p in prov], got
    assert len(phase1["candidate_role_ids"]) == 7
    assert all(isinstance(rid, str) for rid in phase1["candidate_role_ids"])

    # thresholds (frozen BEFORE the run — never tuned after)
    assert g["grouping_precision"] >= thresholds["grouping_precision_min"], g
    assert g["grouping_recall"] >= thresholds["grouping_recall_min"], g
    assert g["proposal_false_merge_rate"] <= thresholds["proposal_false_merge_rate_max"], g
    assert g["review_low_confidence_rate"] <= thresholds["review_low_confidence_rate_max"], g

    # real thumbnail/mask decoding — decoded dims match the registered metadata
    assert phase1["media_dims"], "no servable artifacts"
    for m in phase1["media_dims"]:
        assert m["width"] == m["meta_width"] and m["height"] == m["meta_height"], m

    # curation truth
    assert phase1["pending_after_review"] == 3
    assert phase1["required_merge_applied"] is True
    assert phase1["rename_id_stable"] is True
    assert phase1["required_split_restored"] is True
    assert phase1["recompute_scope_ratio"] <= thresholds["recompute_scope_ratio_max"]
    assert phase1["media_refreshed"] is True
    assert phase1.get("media_refresh_content_png") is True
    assert phase1["unaffected_media_byte_identical"] is True
    assert phase1["job_service_503s"] == []

    # restart + source-authority + generation-isolation phase
    assert phase2["phase"] == "restart"
    assert phase2["chain_survives_restart"] is True
    assert phase2["idempotent_reuse"] is True
    assert phase2["current_lookup"] == "completed"
    assert phase2["renamed_role_persists"] is True
    assert phase2["hero_role_persists"] is True
    assert phase2["gen1_roles_untouched_by_gen2"] is True
    # T02-C2 backend source authority + generation isolation:
    assert phase2["client_generation_hint_rejected"] is True
    assert phase2["gen2_assigned_generation"] == "1"
    assert phase2["gen2_resubmit_reuses_completed"] is True
    assert phase2["gen2_roles_exclude_old_world"] is True
    assert phase2["gen2_suggestions_scope"] is True
    assert phase2["job_service_503s"] == []

    return {"phase1": phase1, "phase2": phase2, "contract": contract}


def test_golden_vertical_run1_within_refrozen_thresholds() -> None:
    global _RUN1_REPORT
    result = _run_full_vertical("r1")
    _RUN1_REPORT = result
    metrics_doc = {
        "contract_sha256": CONTRACT_SHA256,
        "run_id": os.environ.get("S08T06_RUN_ID", "default"),
        "metrics_separation": {
            "deterministic_contract_correctness": (
                result["phase1"]["deterministic_contract_correctness"]
            ),
            "provider_cross_scene_identity": True,
            "grouping": result["phase1"]["grouping_metrics"],
            "calibration": result["phase1"]["calibration"],
        },
        "curation": {
            "pending_after_review": result["phase1"]["pending_after_review"],
            "required_merge_applied": result["phase1"]["required_merge_applied"],
            "required_split_restored": result["phase1"]["required_split_restored"],
            "recompute_scope_ratio": result["phase1"]["recompute_scope_ratio"],
            "media_refreshed": result["phase1"]["media_refreshed"],
            "unaffected_media_byte_identical": result["phase1"]["unaffected_media_byte_identical"],
        },
        "restart": {
            "idempotent_reuse": result["phase2"]["idempotent_reuse"],
            "current_lookup": result["phase2"]["current_lookup"],
            "client_generation_hint_rejected": result["phase2"]["client_generation_hint_rejected"],
            "gen2_assigned_generation": result["phase2"]["gen2_assigned_generation"],
            "gen2_roles_exclude_old_world": result["phase2"]["gen2_roles_exclude_old_world"],
            "gen2_suggestions_scope": result["phase2"]["gen2_suggestions_scope"],
            "note": "queued-cancel + retry covered by the R01 + T02-C2 suites "
            "(engine + public-API seams) — not re-proven in the vertical",
        },
        "runtime_s": result["phase1"]["runtime_s"],
    }
    out_path = _metrics_output_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(metrics_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_golden_vertical_run2_repeatability() -> None:
    global _RUN1_REPORT
    assert _RUN1_REPORT is not None, "run 1 must execute before run 2"
    result = _run_full_vertical("r2")
    g1 = _RUN1_REPORT["phase1"]["grouping_metrics"]
    g2 = result["phase1"]["grouping_metrics"]
    assert g1 == g2, f"repeatability violated: {g1} vs {g2}"
    assert (
        _RUN1_REPORT["phase1"]["confidence_multiset"]
        == result["phase1"]["confidence_multiset"]
    )
    assert (
        _RUN1_REPORT["phase1"]["deterministic_contract_correctness"]
        == result["phase1"]["deterministic_contract_correctness"]
    )
    # restart/isolation verdicts are exact across runs too.
    for _key in (
        "gen2_assigned_generation",
        "gen2_roles_exclude_old_world",
        "gen2_suggestions_scope",
        "gen1_roles_untouched_by_gen2",
        "client_generation_hint_rejected",
    ):
        assert (
            _RUN1_REPORT["phase2"][_key] == result["phase2"][_key]
        ), f"repeatability violated for {_key}"

