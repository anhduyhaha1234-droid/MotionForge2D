"""MF-END-25 C25 — real-path journey probe (NO SQL, HTTP only) against isolated backend.

Usage: python -B probe_journey_real.py <base_url> <fixture_mp4> [out_json]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8041"
FIXTURE = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("frontend/e2e/fixtures/s05t05-import-4s.mp4")
OUT = Path(sys.argv[3]) if len(sys.argv) > 3 else None


def req(method: str, path: str, body: dict | None = None, timeout: int = 120):
    url = BASE + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw.decode())
            except Exception:
                return resp.status, {"_raw_bytes": len(raw)}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode())
        except Exception:
            return e.code, {"_raw": raw[:200].decode(errors="replace")}


def upload(path: str, file: Path):
    boundary = "----mf25" + uuid.uuid4().hex
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{file.name}"\r\n'.encode(),
            b"Content-Type: video/mp4\r\n\r\n",
            file.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    r = urllib.request.Request(
        BASE + path,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(r, timeout=300) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode())
        except Exception:
            return e.code, {"_raw": raw[:300].decode(errors="replace")}


steps: list[dict] = []


def log(name: str, status: int, payload) -> None:
    steps.append({"step": name, "status": status, "payload": payload})
    print(f"{name:38s} -> {status} {json.dumps(payload)[:180] if payload else ''}", flush=True)


st, health = req("GET", "/health")
log("health", st, health)

name = f"MF-END-25 C25 real-path {uuid.uuid4().hex[:6]}"
st, proj = req("POST", "/api/projects", {"name": name})
log("POST /api/projects (legacy create)", st, proj)
pid = proj.get("project_id") if st < 300 else None
if not pid:
    print("CANNOT CREATE PROJECT", st, proj)
    sys.exit(2)

st, up = upload(f"/api/projects/{pid}/video", FIXTURE)
log("POST /api/projects/{id}/video", st, up)

st, chain = req("POST", f"/api/projects/{pid}/analyze", {"title": FIXTURE.name})
log("POST /api/projects/{id}/analyze", st, chain)

deadline = time.time() + 300
last = None
while time.time() < deadline:
    st, c = req("GET", f"/api/projects/{pid}/analyze?generation=1")
    if st != 200:
        log("GET /api/projects/{id}/analyze", st, c)
        break
    snap = {
        "chain_status": c.get("chain_status"),
        "active_step": c.get("active_step"),
        "progress": c.get("progress"),
        "video_item_id": c.get("video_item_id"),
        "scenes_count": c.get("scenes_count"),
        "steps": {k: v.get("status") for k, v in (c.get("steps") or {}).items()},
    }
    if snap != last:
        log("GET /api/projects/{id}/analyze", st, snap)
        last = snap
    if c.get("chain_status") in ("completed", "failed", "cancelled"):
        break
    time.sleep(5)

vid = (last or {}).get("video_item_id")
st, dv = req("GET", f"/api/v2/projects/{pid}")
log("GET /api/v2/projects/{id} (durable)", st, dv if st < 300 else {"detail": str(dv)[:80]})
st, vids = req("GET", f"/api/v2/projects/{pid}/videos")
log("GET /api/v2/projects/{id}/videos", st, vids if st < 300 else {"detail": str(vids)[:80]})
if vid:
    st, ctx = req("GET", f"/api/v2/projects/{pid}/export/context?video_item_id={vid}")
    log("GET export/context", st, {
        "full_apply_run_id": (ctx or {}).get("full_apply_run_id"),
        "reasons": (ctx or {}).get("reasons"),
        "video_title": (ctx or {}).get("video_title"),
    })
    st, cast = req("GET", f"/api/v2/project-cast?project_id={pid}&limit=50&offset=0")
    log("GET /api/v2/project-cast", st, {"total": (cast or {}).get("total")})

result = {"base": BASE, "project_id": pid, "video_item_id": vid, "steps": steps}
if OUT:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("wrote", OUT)
print("PROBE_DONE")
