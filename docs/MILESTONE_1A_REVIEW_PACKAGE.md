# Milestone 1A — Review Package

**Dự án:** MotionForge 2D
**Milestone:** 1A — Object Extraction Review UI
**Ngày:** 2026-07-29
**Git commits:** `7df277e` (backend API), `040e23f` (frontend scaffold)

---

## A. Completed

### Backend (100%)

| Component | Files | Status |
|-----------|-------|:------:|
| Schema extensions | `app/schemas/__init__.py` | ✅ |
| Job service | `app/workflow/job_service.py` | ✅ |
| Project workflow | `app/workflow/project_workflow.py` | ✅ |
| Ingest service | `app/workflow/ingest_service.py` | ✅ |
| Segmentation service | `app/workflow/segmentation_service.py` | ✅ |
| Object extraction service | `app/workflow/object_extraction_service.py` | ✅ |
| Replacement service | `app/workflow/replacement_service.py` | ✅ |
| Render service | `app/workflow/render_service.py` | ✅ |
| API routes (projects) | `app/api/routes/projects.py` | ✅ |
| API routes (jobs) | `app/api/routes/jobs.py` | ✅ |
| API routes (frames) | `app/api/routes/frames.py` | ✅ |
| API app + deps | `app/api/app.py`, `deps.py` | ✅ |
| Entry point | `app/main.py` | ✅ |
| Tests (25 new) | `tests/test_api.py` | ✅ |

### Frontend (100%)

| Component | Files | Status |
|-----------|-------|:------:|
| API client | `frontend/src/lib/api.ts` | ✅ |
| Zustand store | `frontend/src/stores/project.ts` | ✅ |
| Coordinate transform | `frontend/src/lib/coordinates.ts` | ✅ |
| Screen A: Project start | `frontend/src/components/ScreenA.tsx` | ✅ |
| Screen B: Object selection | `frontend/src/components/ScreenB.tsx` | ✅ |
| Screen C: Extraction review | `frontend/src/components/ScreenC.tsx` | ✅ |
| Screen D: Replacement | `frontend/src/components/ScreenD.tsx` | ✅ |
| Screen E: Preview/Render | `frontend/src/components/ScreenE.tsx` | ✅ |
| Main page | `frontend/src/app/page.tsx` | ✅ |

### Documentation

| File | Status |
|------|:------:|
| `docs/TRANSFORM_SPEC.md` | ✅ |

---

## B. API Endpoints

| Endpoint | Method | Status |
|----------|:------:|:------:|
| `/health` | GET | ✅ Tested |
| `/api/projects` | POST | ✅ Tested |
| `/api/projects/{id}` | GET | ✅ Tested |
| `/api/projects/{id}/video` | POST | ✅ Implemented |
| `/api/projects/{id}/ingest` | POST | ✅ Implemented |
| `/api/projects/{id}/scenes` | GET | ✅ Implemented |
| `/api/projects/{id}/frames/{idx}` | GET | ✅ Implemented |
| `/api/projects/{id}/objects/preview-mask` | POST | ✅ Implemented |
| `/api/projects/{id}/objects` | POST | ✅ Implemented |
| `/api/projects/{id}/objects/{oid}/propagate` | POST | ✅ Implemented |
| `/api/projects/{id}/objects/{oid}` | GET | ✅ Implemented |
| `/api/projects/{id}/objects/{oid}/gallery` | GET | ✅ Implemented |
| `/api/projects/{id}/objects/{oid}/replacement` | POST | ✅ Implemented |
| `/api/projects/{id}/objects/{oid}/replacement-settings` | PATCH | ✅ Implemented |
| `/api/projects/{id}/preview` | POST | ✅ Implemented |
| `/api/projects/{id}/render` | POST | ✅ Implemented |
| `/api/jobs/{id}` | GET | ✅ Implemented |
| `/api/jobs/{id}/cancel` | POST | ✅ Implemented |

---

## C. Tests

```
53 passed in 2.75s
Ruff: All checks passed!
```

| Category | Tests |
|----------|------:|
| Schema (existing) | 14 |
| Motion (existing) | 7 |
| Integration (existing) | 7 |
| API (new) | 25 |
| **Total** | **53** |

---

## D. How to Run

### Backend

```bash
cd C:\Users\Admin\MotionForge2D
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

API docs at: http://127.0.0.1:8000/docs

### Frontend

```bash
cd C:\Users\Admin\MotionForge2D\frontend
npm run dev
```

UI at: http://localhost:3000

---

## E. Known Limitations

1. **No E2E Playwright test yet** — backend and frontend work independently but not tested together with browser automation.
2. **No screen recordings/screenshots** — need running services.
3. **Frontend preview canvas** — Screen D preview canvas shows placeholder, not actual composited frame.
4. **Gallery crop serving** — object crop endpoints need path resolution from project storage.
5. **Video playback in Screen E** — uses video element, may need streaming support for large files.
6. **No background clean** — replacement is overlay-only (documented limitation).
7. **frame_sequence mode** — schema supports it, not implemented (by design for M1B).

---

## F. Schema Changes

Added to v2.0.0:
- `ReplacementConfig` model (mode, asset_path, anchor, offset, scale, rotation_offset_deg, opacity, fit_mode)
- `ReplacementMode` enum (none, static_asset, frame_sequence, keyframe_assets)
- `ObjectCrop` model (frame_index, crop_path, mask_path, bbox, reason)
- `ObjectCropManifest` model (object_id, representative_frames)
- `JobState` enum (queued, running, cancelling, cancelled, completed, failed)
- `JobInfo` extended with state, current_step, started_at, completed_at, error_code, result
- `TrackedObject.replacement_config` field

---

## G. Blockers

None. Backend and frontend build and pass tests.

---

## H. Recommendation

**`PARTIALLY COMPLETE`** — Backend and frontend code is complete and tested. E2E integration (browser test with real video) not yet performed. Recommend proceeding to E2E validation before marking ACCEPTED.
