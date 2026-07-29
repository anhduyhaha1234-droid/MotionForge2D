# MotionForge 2D — Milestones

## Milestone 0: Technical Discovery & Vertical Spike

**Goal:** Prove the end-to-end pipeline works from MP4 input to MP4 output.

**Status:** `CONDITIONALLY ACCEPTED` (2026-07-29)

**Reason:** Pipeline runs end-to-end but contour mask propagation fails (only 1/90 frames tracked). SAM2 backend was not tested in M0 due to missing checkpoint. See M0 review package for details.

**Resolution:** Milestone 0.5 validated SAM2 backend with100% tracking on all fixtures.

**Deliverables:**
- [x] Project scaffold with all service modules
- [x] Video probe (FFmpeg metadata extraction)
- [x] Scene detection (PySceneDetect)
- [x] Frame extraction
- [x] Segmentation adapter interface
- [x] SAM 2.1 adapter (GPU) + OpenCV fallback (CPU)
- [x] Mask propagation across scene frames
- [x] Motion extraction (centroid, bbox, scale, rotation)
- [x] Compositing service (PNG replacement)
- [x] Render service (MP4 with audio)
- [x] Project JSON schema v1.0
- [x] Unit tests (schema, motion calculation)
- [x] Integration tests (probe, render)
- [x] Debug mask overlay output
- [x] Benchmark logging (time, RAM, VRAM)
- [x] README, ARCHITECTURE, SPIKE_REPORT, THIRD_PARTY

**Acceptance Criteria:**
1. Input: MP4 → probe metadata → detect scenes → extract frames
2. User selects object via point or bbox → SAM generates mask
3. Mask propagates through scene → motion extracted
4. Replacement PNG composited → new MP4 rendered with original audio
5. All tests pass

**Status:** ✅ Complete

---

## Milestone 0.5: Core Tracking Validation ⬅ CURRENT

**Goal:** Validate SAM2 end-to-end: segmentation, propagation, compositing on real GPU.

**Status:** ✅ Complete (2026-07-29)

**Key results:**
- SAM2 runs on RTX 5070 (2.7GB VRAM, 3.1 fps at 640×360)
- All 3 fixtures:100% tracked,100% composited
- Schema upgraded to v2.0.0 (confidence, occlusion, mask_path)
- Occlusion limitation documented (SAM2 tracks occluder, not hidden object)

**Deliverables:**
- [x] SAM2 checkpoint downloaded and validated
- [x] SAM2 adapter rewritten (temp dir, forward+backward propagation)
- [x] FFmpeg PATH utility (cross-platform binary discovery)
- [x] 3 test fixtures (synthetic, animation, occlusion)
- [x] Tracking metrics for all fixtures
- [x] Schema v2.0.0 with migration from v1.0.0
- [x] .gitignore, LICENSE, pinned dependencies
- [x] Review packages (5 documents)

---

## Milestone 1: Backend API & Project Management

**Goal:** FastAPI backend serving project CRUD and processing jobs.

**Deliverables:**
- [ ] FastAPI application with CORS
- [ ] Project CRUD endpoints (create, read, update, delete)
- [ ] Video upload endpoint
- [ ] Probe endpoint returning metadata
- [ ] Scene detection endpoint
- [ ] Frame extraction endpoint
- [ ] Segmentation endpoint (accept point/bbox, return masks)
- [ ] Motion extraction endpoint
- [ ] Job queue for long-running tasks
- [ ] SQLite database with migrations
- [ ] API documentation (auto-generated)
- [ ] Unit + integration tests for all endpoints

**Acceptance Criteria:**
1. All endpoints return proper HTTP status codes
2. Background jobs track progress (0-100%)
3. Project state persisted to SQLite
4. OpenAPI docs auto-generated

---

## Milestone 2: Frontend Video Editor

**Goal:** Interactive video editor with canvas annotation.

**Deliverables:**
- [ ] Next.js app with TypeScript strict mode
- [ ] Video player component (HTML5 video)
- [ ] Canvas overlay (Konva.js) for annotation
- [ ] Point click selection on canvas
- [ ] Bounding box selection with drag
- [ ] Object list panel
- [ ] Property panel (position, scale, rotation)
- [ ] Timeline component
- [ ] Mask visualization overlay
- [ ] Zustand stores for state management
- [ ] TanStack Query for API communication

**Acceptance Criteria:**
1. User can click on video frame to select object
2. Masks visualized as colored overlay
3. Properties update in real-time
4. Responsive layout

---

## Milestone 3: Multi-Object Tracking & Motion Editor

**Goal:** Track multiple objects with motion path editing.

**Deliverables:**
- [ ] Multi-object tracking in a scene
- [ ] Object assignment across scenes
- [ ] Motion path visualization
- [ ] Keyframe editing
- [ ] Motion smoothing controls
- [ ] Rotation/scale adjustment per frame
- [ ] Visibility toggle per frame

**Acceptance Criteria:**
1. Multiple objects tracked independently
2. Motion paths visible on canvas
3. Keyframes editable via property panel

---

## Milestone 4: Rendering & Export

**Goal:** Full render pipeline with preview.

**Deliverables:**
- [ ] Preview mode (low-res fast render)
- [ ] Full quality render
- [ ] Progress tracking
- [ ] Format options (MP4, WebM, GIF)
- [ ] Resolution options
- [ ] Batch scene rendering
- [ ] Audio mixing controls

**Acceptance Criteria:**
1. Preview renders in <10s for 5s video
2. Full quality matches original FPS and duration
3. Audio preserved correctly

---

## Milestone 5: Polish & Distribution

**Goal:** Production-ready application.

**Deliverables:**
- [ ] Error handling and recovery
- [ ] Undo/redo system
- [ ] Keyboard shortcuts
- [ ] Project save/load
- [ ] Import/export presets
- [ ] Performance optimization
- [ ] Docker Compose setup
- [ ] Installation guide
- [ ] User documentation
