"""MF-END-05 negative-control probe — the series-pin call path must exist.

Run against the BASE tree (fda3df1): FAILS (no /series-cast route, no
series_cast_snapshot tables).  Run against the patched tree: PASSES.
This is the PRE_FIX / POST_FIX flip proof for the acceptance call path.
"""

from __future__ import annotations

import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.api import deps


def test_series_pin_call_path_exists(client: TestClient) -> None:
    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200, openapi.text
    paths = openapi.json()["paths"]
    assert "/api/v2/project-cast/series-cast/snapshots" in paths
    assert "/api/v2/project-cast/series-cast/snapshots/{snapshot_id}/apply" in paths

    service = deps._job_service
    assert service is not None
    with service.session_factory() as session:
        tables = {
            row[0]
            for row in session.connection()
            .exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")
            .fetchall()
        }
    assert {"series_cast_snapshot", "series_cast_snapshot_entry"} <= tables

    # the freeze route answers as a real endpoint (validation refusal for an
    # unknown project — NOT the framework's "Not Found" for a missing route)
    resp = client.post(
        "/api/v2/project-cast/series-cast/snapshots",
        json={
            "project_id": "no-such-project",
            "entries": [
                {
                    "role_key": "ROLE-HERO",
                    "character_id": "no-such-character",
                    "pack_version_id": "no-such-version",
                }
            ],
        },
    )
    assert resp.status_code == 404, resp.text
    assert "Not Found" != resp.json().get("detail"), resp.text
    assert "ownership mismatch" in resp.json()["detail"], resp.text
