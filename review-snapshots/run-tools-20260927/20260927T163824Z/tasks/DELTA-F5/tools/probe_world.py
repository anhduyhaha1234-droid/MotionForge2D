"""DELTA-F5 probe v4: QC submit composition on a real world, base bytes vs fixed bytes."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F5")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.persistence import create_engine_for_path, create_session_factory  # noqa: E402
from app.services.qc_evidence import compose as qc_compose  # noqa: E402
from app.services.qc_evidence import sources as qc_sources  # noqa: E402
from app.workflow import qc_checks_handler as handler  # noqa: E402

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F5")
R3 = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/"
    "tasks/MF-DEMO-E2E-R3"
)
BASE_PUB = R3 / "raw/runtime_harvest/s10_full_apply/a94d76d9-8156-4ed2-a717-dd5fb2d733ad/stitch_shot_chunks.mp4"
FIXED_PUB = Path(
    "C:/Users/Admin/AppData/Local/Temp/deltaf5_probe/managed/s10_full_apply/"
    "a94d76d9-8156-4ed2-a717-dd5fb2d733ad/stitch_shot_chunks.mp4"
)
SRC = R3 / "raw/source_12s.mp4"

WS = "default"
PROJECT = "proj-f5"
VIDEO = "vid-f5"
ROLE = "role-f5"
SEGMENT = "seg-f5"
ROUTE = "route-f5"
LOCK = "lock-f5"


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build(tmp: Path, pub_bytes: bytes, tag: str) -> dict:
    db = tmp / f"{tag}.db"
    cfg = Config(str(WT / "alembic.ini"))
    cfg.set_main_option("script_location", str(WT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    command.upgrade(cfg, "head")
    sf = create_session_factory(create_engine_for_path(db))
    managed = tmp / f"managed_{tag}"
    managed.mkdir(parents=True, exist_ok=True)
    src_rel = f"{tag}/src/source.mp4"
    pub_rel = f"{tag}/render/publication.mp4"
    (managed / src_rel).parent.mkdir(parents=True, exist_ok=True)
    (managed / pub_rel).parent.mkdir(parents=True, exist_ok=True)
    (managed / src_rel).write_bytes(SRC.read_bytes())
    (managed / pub_rel).write_bytes(pub_bytes)
    with sf() as s:
        s.execute(text("INSERT OR IGNORE INTO workspace(id,name) VALUES (:w,'default')"), {"w": WS})
        s.execute(
            text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'F5')"),
            {"p": PROJECT, "w": WS},
        )
        for aid, rel, sha, kind in (
            ("art-src-f5", src_rel, sha_file(managed / src_rel), "video"),
            ("art-pub-f5", pub_rel, sha_file(managed / pub_rel), "video"),
        ):
            s.execute(
                text(
                    "INSERT INTO artifact(id, workspace_id, kind, relative_path, state,"
                    " sha256, size_bytes, revision, created_at, updated_at) VALUES"
                    " (:id,:ws,:kind,:rel,'ready',:sha,:size,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                ),
                {
                    "id": aid,
                    "ws": WS,
                    "kind": kind,
                    "rel": rel,
                    "sha": sha,
                    "size": (managed / rel).stat().st_size,
                },
            )
        s.execute(
            text(
                "INSERT INTO artifact_owner(artifact_id, owner_type, owner_id, purpose)"
                " VALUES ('art-src-f5','video_item',:v,'source')"
            ),
            {"v": VIDEO},
        )
        s.execute(
            text(
                "INSERT INTO artifact_owner(artifact_id, owner_type, owner_id, purpose)"
                " VALUES ('art-pub-f5','video_item',:v,'result')"
            ),
            {"v": VIDEO},
        )
        s.execute(
            text(
                "INSERT INTO video_item(id, project_id, title, position, source_artifact_id,"
                " width, height, fps_num, fps_den, duration_ms) VALUES"
                " (:v,:p,'12s demo',0,'art-src-f5',640,360,30,1,12000)"
            ),
            {"v": VIDEO, "p": PROJECT},
        )
        s.execute(
            text(
                "INSERT INTO scene(id, video_item_id, position, start_frame, end_frame,"
                " start_time_ms, end_time_ms, status, revision, created_at, updated_at)"
                " VALUES ('sc-f5',:v,0,0,359,0,12000,'pending',1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"v": VIDEO},
        )
        s.execute(
            text(
                "INSERT INTO object_role(id, workspace_id, project_id, video_item_id,"
                " source_generation, name, kind, status, revision, created_at, updated_at)"
                " VALUES (:r,:w,:p,:v,'1','BOOK-P1','character','confirmed',1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"r": ROLE, "w": WS, "p": PROJECT, "v": VIDEO},
        )
        # structural-lock manifest + occurrence segment + render route (real shapes)
        s.execute(
            text(
                "INSERT INTO structural_lock_manifest(id, workspace_id, project_id,"
                " video_item_id, source_generation, version, status, policy_version,"
                " manifest_hash, manifest_json, idempotency_key, revision,"
                " created_at, updated_at) VALUES (:i,:w,:p,:v,'1',1,'active',"
                " 'structural-thresholds-v1',:h,'{}','demo-lock-f5',1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"i": LOCK, "w": WS, "p": PROJECT, "v": VIDEO, "h": "f" * 64},
        )
        s.execute(
            text(
                "INSERT INTO occurrence_segment(id, logical_id, lineage_version, workspace_id,"
                " project_id, video_item_id, role_id, scene_id, name, kind, start_frame,"
                " end_frame, start_time_ms, end_time_ms, source_generation, prompt_json,"
                " segmentation_json, mask_artifact_id, confidence, confidence_source,"
                " reasons_json, visibility, z_order, revision, created_at, updated_at) VALUES"
                " (:i,:l,1,:w,:p,:v,:r,'sc-f5','BOOK-P1','character',0,359,0,12000,'1',"
                " :pj, :sg, NULL,1.0,'user','[]','visible',0,1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "i": SEGMENT,
                "l": "log-f5",
                "w": WS,
                "p": PROJECT,
                "v": VIDEO,
                "r": ROLE,
                "pj": json.dumps({"boxes": [{"h": 0.4, "w": 0.3, "x": 0.05, "y": 0.05}]}),
                "sg": json.dumps({"boxes": [{"h": 0.3, "w": 0.2, "x": 0.1, "y": 0.1}]}),
            },
        )
        s.execute(
            text(
                "INSERT INTO segment_render_route(id, workspace_id, project_id, video_item_id,"
                " occurrence_segment_id, structural_lock_manifest_id, route, anchor_x, anchor_y,"
                " start_frame, end_frame, algorithm, algorithm_version, confidence,"
                " confidence_source, provenance_json, reasons_json, idempotency_key, revision,"
                " created_at, updated_at) VALUES"
                " (:i,:w,:p,:v,:s,:m,'sprite_affine',0.5,0.5,0,359,'structural-lock-producer',"
                " '1',1.0,'derived','{}','[]','structural-lock-produce:f5',1,"
                " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"i": ROUTE, "w": WS, "p": PROJECT, "v": VIDEO, "s": SEGMENT, "m": LOCK},
        )
        s.commit()
    return {"sf": sf, "managed": managed}


def run_case(tmp: Path, pub: Path, tag: str) -> None:
    world = build(tmp, pub.read_bytes(), tag)
    sf, managed = world["sf"], world["managed"]
    import app.api.deps as deps

    deps.get_managed_root = lambda: managed  # type: ignore[assignment]
    print(f"===== {tag}: publication sha {sha_file(pub)[:16]} =====")
    with sf() as s:
        try:
            args = handler.compose_check_run_args(
                s, workspace_id=WS, project_id=PROJECT, video_item_id=VIDEO, scope="full"
            )
            print("  compose_check_run_args OK ->", sorted(args))
        except Exception as exc:
            detail = getattr(exc, "details", None) or {}
            print("  compose REFUSED:", getattr(exc, "code", type(exc).__name__))
            print("   message:", str(exc)[:220])
            if isinstance(detail, dict):
                print("   failed_detectors:", json.dumps(detail.get("failed_detectors", {}))[:300])
        try:
            band = qc_compose.compose_visual_band(
                s, managed_root=managed, workspace_id=WS, project_id=PROJECT, video_item_id=VIDEO
            )
            print("  visual band OK ->", sorted(band))
        except Exception as exc:
            print("  visual band REFUSED:", getattr(exc, "code", type(exc).__name__))
            det = getattr(exc, "details", None) or {}
            print("   refusals:", json.dumps(det.get("refusals", {}))[:300])
        scope = qc_sources.load_scope(
            s, workspace_id=WS, project_id=PROJECT, video_item_id=VIDEO
        )
        ctx = qc_compose._Context(session=s, managed_root=managed, scope=scope)
        try:
            args = qc_compose._BUILDERS["trajectory_drift"](ctx)
            print(
                "  trajectory_drift OK: observed_x n=",
                len(args["observed_x"]),
                "frames:",
                args.get("frame_start"),
                "render_observation role:",
                args["render_observation"].get("role") if isinstance(args.get("render_observation"), dict) else None,
            )
        except Exception as exc:
            print("  trajectory_drift REFUSED:", getattr(exc, "code", type(exc).__name__), "|", str(exc)[:200])


def main() -> int:
    tmp = Path("C:/Users/Admin/AppData/Local/Temp/deltaf5_world")
    if tmp.exists():
        import shutil

        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    run_case(tmp, BASE_PUB, "base")
    run_case(tmp, FIXED_PUB, "fixed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
