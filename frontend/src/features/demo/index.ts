/**
 * S09 Demo comparison feature — typed API client (S09-T04).
 *
 * Thin typed exports over the backend /api/v2/s09-demo-compare contract
 * (additive; mirrors the envelope-unwrapping semantics of the reskin
 * feature client).  Every number the UI renders comes from these typed
 * responses — there is NO fabricated fallback data: absent evidence stays
 * null / empty and the UI shows its empty state.
 */
import { ApiError } from "@/lib/api";

/** Re-exported so demo UI components can branch on HTTP status without
 *  importing client internals. */
export { ApiError };

async function demoFetch<T>(path: string, options?: RequestInit): Promise<T> {
	const rawApiUrl =
		process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8888";
	const API_BASE = rawApiUrl.replace(/\/+$/, "");
	const url = `${API_BASE}${path}`;
	const res = await fetch(url, {
		...options,
		headers: { ...options?.headers },
	});
	if (!res.ok) {
		const text = await res.text().catch(() => "");
		let detail: unknown = text;
		if (text) {
			try {
				const body: unknown = JSON.parse(text);
				detail =
					typeof body === "object" && body !== null && "detail" in body
						? (body as { detail: unknown }).detail
						: body;
			} catch {
				detail = text;
			}
		}
		throw new ApiError(res.status, detail);
	}
	if (res.status === 204) return undefined as T;
	return (await res.json()) as T;
}

// ── Response shapes (mirror app/schemas/s09_demo_compare.py) ───────────────

export interface BenchmarkRouteRow {
	fixture_id: string;
	risk_class: string;
	route: string;
	overall_pass: boolean;
	checks: Record<string, unknown>[];
}

export interface BenchmarkClassSummary {
	risk_class: string;
	measured_routes: BenchmarkRouteRow[];
	smallest_passing_route: string | null;
}

export interface CapabilitiesResponse {
	benchmark_results: string;
	/** File-content SHA-256 of the benchmark document bytes actually read. */
	content_sha256: string;
	frozen_content_sha256: string;
	thresholds_policy: string | null;
	routes_measured: string[];
	classes: BenchmarkClassSummary[];
}

export interface LoopSegment {
	shot_id: string;
	start_frame: number;
	end_frame: number;
}

export interface LoopInfo {
	loop_id: string;
	frame_count: number;
	fps: number;
	width: number;
	height: number;
	segments: LoopSegment[];
	risk_classes: string[];
	replacement_ops: string[];
	routes_by_risk_class: Record<string, string> | null;
	plan_error: string | null;
}

export interface LoopListResponse {
	loops: LoopInfo[];
}

export interface SubmitJobRequest {
	requested_loops: string[];
	benchmark_results: string;
	fixtures_dir: string;
	/** Pinned benchmark file-content SHA; mismatch → 409 fail closed. */
	expect_content_sha256?: string | null;
	pinned_routes?: Record<string, string> | null;
}

export interface SubmitJobResponse {
	job_id: string;
	status: string;
	reused: boolean;
	detail_url: string;
}

export interface PublishedArtifact {
	loop_id: string;
	relative_path: string;
	content_url: string;
	artifact_id: string;
	sha256: string;
	size_bytes: number;
	frame_count: number | null;
	reused_existing_file: boolean | null;
}

/**
 * S09-C4 §4.5 — mirrors app/schemas/s09_demo_compare.py PublicationIdentity
 * EXACTLY: the base publication identity an unaffected loop is bound from
 * (verbatim base row; handler re-verified its hash before binding).
 */
export interface PublicationIdentity {
	artifact_id: string;
	relative_path: string;
	sha256: string;
	size_bytes: number;
}

/**
 * S09-C4 §4.5 — mirrors app/schemas/s09_demo_compare.py PublicationStatus
 * EXACTLY: per-loop regeneration split of ONE regen job result.
 * ``regenerated`` is copied IMMUTABLY from the attempt result by the API —
 * NEVER inferred from hash equality; the UI only displays what the backend
 * sent.  ``render_ms`` exists ONLY for affected renders; unaffected loops
 * carry ``base_publication`` instead.
 */
export interface PublicationStatus {
	loop_id: string;
	regenerated?: boolean | null;
	render_ms?: number | null;
	base_publication?: PublicationIdentity | null;
}

/**
 * S09-C4 §4.5 frozen contract — mirrors app/schemas/s09_demo_compare.py
 * GenerationEvidence EXACTLY (``generation`` is the backend's opaque
 * generation LABEL string, not a client-side counter).  Immutable
 * generation identity exposed read-only by GET /jobs/{job_id} AFTER T04
 * binds it (PREP: typed ahead, absent until join).  Machine authority for
 * what the UI displays about a targeted regeneration; the UI NEVER infers
 * or fabricates these values.
 */
export interface GenerationEvidence {
	generation: string;
	base_job_id: string;
	correction_id: string;
	correction_context_sha256: string;
	frozen_evidence_sha256: string;
}

export interface RouteEvidenceEntry {
	occurrence_segment_id: string;
	route: string;
	anchor_x: number;
	anchor_y: number;
	start_frame: number;
	end_frame: number;
	confidence: number;
	confidence_source: string;
	reasons: string[];
	provenance: Record<string, unknown> | null;
}

export interface JobStatus {
	job_id: string;
	state: string;
	progress: number;
	error: { message: string } | null;
	requested_loops: string[];
	covered_risk_classes: string[];
	frozen_content_sha256: string | null;
	thresholds_policy: string | null;
	published: PublishedArtifact[];
	route_evidence: RouteEvidenceEntry[];
	/**
	 * §4.5 frozen contract (S09-C4): exact affected scope của generation
	 * này khi job là targeted regeneration; absent/null với base job
	 * thường.  UI hiển thị ĐÚNG giá trị backend — không suy luận.
	 */
	affected_loop_ids?: string[] | null;
	generation_evidence?: GenerationEvidence | null;
	/**
	 * §4.5 per-loop regeneration split (mirrors DemoCompareStatus
	 * ``publications``): populated ONLY for targeted-regeneration jobs;
	 * empty for plain demo-loop jobs — never fabricated.
	 */
	publications?: PublicationStatus[];
}

// ── Client functions ───────────────────────────────────────────────────────

/** Measured route evidence from one frozen benchmark document.
 *
 * S09-T04-C2: pass `expectContentSha256` (from the frozen C2 decision /
 * explicit configuration) to fail closed when the on-disk bytes changed. */
export function getDemoCapabilities(
	benchmarkResults: string,
	expectContentSha256?: string,
): Promise<CapabilitiesResponse> {
	const q = new URLSearchParams({ benchmark_results: benchmarkResults });
	if (expectContentSha256) q.set("expect_content_sha256", expectContentSha256);
	return demoFetch<CapabilitiesResponse>(
		`/api/v2/s09-demo-compare/capabilities?${q.toString()}`,
	);
}

/** All fixture loops with locked structure + planned renderer routes. */
export function listDemoLoops(
	fixturesDir: string,
	benchmarkResults: string,
	expectContentSha256?: string,
): Promise<LoopListResponse> {
	const q = new URLSearchParams({
		fixtures_dir: fixturesDir,
		benchmark_results: benchmarkResults,
	});
	if (expectContentSha256) q.set("expect_content_sha256", expectContentSha256);
	return demoFetch<LoopListResponse>(`/api/v2/s09-demo-compare/loops?${q.toString()}`);
}

/** Submit one risk-selected batch (idempotent replay → same durable Job). */
export function submitDemoCompareJob(
	req: SubmitJobRequest,
): Promise<SubmitJobResponse> {
	return demoFetch<SubmitJobResponse>("/api/v2/s09-demo-compare/jobs", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(req),
	});
}

/** Durable job status + published artifacts + route evidence. */
export function getDemoCompareStatus(jobId: string): Promise<JobStatus> {
	return demoFetch<JobStatus>(
		`/api/v2/s09-demo-compare/jobs/${jobId}`,
	);
}

// ── S09-T05B: targeted corrections (typed client additions, additive) ──────
//
// Mirrors app/schemas/s09_correction.py EXACTLY (extra=forbid upstream, so
// every field here is contract-checked) plus READ-ONLY structural-evidence
// listings used to pick REAL correction targets.  The five renderer routes
// are DERIVED from the single authority RENDERER_ROUTES in
// app/persistence/models.py — never a second taxonomy.

/** Single-authority route enum (models.py:214-220), frozen order. */
export const RENDERER_ROUTES = [
	"pose_swap",
	"sprite_affine",
	"mesh_warp",
	"part_rig",
	"controlled_redraw",
] as const;

export type RendererRoute = (typeof RENDERER_ROUTES)[number];

/** Exact correction kinds accepted by POST /api/v2/s09-corrections. */
export const CORRECTION_KINDS = [
	"mask",
	"z_order",
	"contact",
	"mesh_parts",
	"route_override",
] as const;

export type CorrectionKind = (typeof CORRECTION_KINDS)[number];

// ── structural-evidence read models (mirror app/schemas/structural_evidence.py)

export interface EvidencePoint {
	x: number;
	y: number;
	label?: string | null;
}

export interface SegmentEvidence {
	points?: EvidencePoint[];
	boxes?: unknown[];
}

export interface SegmentInfo {
	id: string;
	logical_id: string;
	lineage_version: number;
	project_id: string;
	video_item_id: string;
	name: string;
	kind: string;
	start_frame: number;
	end_frame: number;
	source_generation: string;
	mask_artifact_id: string | null;
	z_order: number;
	revision: number;
	state: string;
	segmentation: SegmentEvidence | null;
}

export interface SegmentListResponseDto {
	workspace_id: string;
	total: number;
	scope: string;
	current_generation: string | null;
	segments: SegmentInfo[];
}

export interface ContactInfo {
	id: string;
	source_segment_id: string;
	target_segment_id: string;
	contact_kind: string;
	start_frame: number;
	end_frame: number;
	end_time_ms: number;
	confidence: number;
	revision: number;
}

export interface MotionInfo {
	id: string;
	occurrence_segment_id: string;
	transform_type: string;
	transform: Record<string, number>;
	revision: number;
}

/** Current-generation segments scoped to one video (READ-ONLY listing). */
export function listCurrentSegments(
	videoItemId: string,
): Promise<SegmentListResponseDto> {
	const q = new URLSearchParams({ video_item_id: videoItemId });
	return demoFetch<SegmentListResponseDto>(
		`/api/v2/structural-evidence/segments?${q.toString()}`,
	);
}

/** All contacts (optionally scoped by segment) — READ-ONLY listing. */
export function listContacts(segmentId?: string): Promise<ContactInfo[]> {
	const q = new URLSearchParams();
	if (segmentId) q.set("segment_id", segmentId);
	const suffix = q.toString();
	return demoFetch<ContactInfo[]>(
		`/api/v2/structural-evidence/contacts${suffix ? `?${suffix}` : ""}`,
	);
}

/** Motions of one segment — READ-ONLY listing. */
export function listMotions(segmentId: string): Promise<MotionInfo[]> {
	const q = new URLSearchParams({ segment_id: segmentId });
	return demoFetch<MotionInfo[]>(
		`/api/v2/structural-evidence/motions?${q.toString()}`,
	);
}

// ── durable project/video pickers (READ-ONLY listings) ────────────────────

export interface ProjectInfo {
	project_id: string;
	name: string;
	status: string;
}

export interface VideoItemInfo {
	video_item_id: string;
	title: string;
	status: string;
}

export function listDurableProjects(): Promise<{ projects: ProjectInfo[] }> {
	return demoFetch<{ projects: ProjectInfo[] }>(
		"/api/v2/projects?active_only=true",
	);
}

export function listProjectVideos(projectId: string): Promise<{
	videos: VideoItemInfo[];
}> {
	return demoFetch<{ videos: VideoItemInfo[] }>(
		`/api/v2/projects/${projectId}/videos`,
	);
}

// ── correction payloads (EXACT shapes of app/schemas/s09_correction.py) ────

export interface MaskCorrectionPayload {
	occurrence_segment_id: string;
	revision: number;
	source_generation: string;
	segmentation: SegmentEvidence;
	mask_artifact_id: string;
	confidence_source?: "user" | "manual";
	reasons?: string[];
	provenance: Record<string, unknown>;
	mutation_idempotency_key?: string | null;
}

export interface ZOrderCorrectionPayload {
	occurrence_segment_id: string;
	revision: number;
	source_generation: string;
	z_order: number;
	confidence_source?: "user" | "manual";
	reasons?: string[];
	provenance: Record<string, unknown>;
	mutation_idempotency_key?: string | null;
}

export interface ContactCorrectionPayload {
	contact_id: string;
	revision: number;
	end_frame?: number | null;
	end_time_ms?: number | null;
	confidence?: number | null;
	reasons?: string[];
	provenance?: Record<string, unknown> | null;
}

export interface MeshPartsCorrectionPayload {
	motion_id: string;
	revision: number;
	transform: Record<string, number>;
	confidence?: number | null;
	reasons?: string[];
	provenance?: Record<string, unknown> | null;
}

export interface RouteOverrideProvenanceDto {
	route_from: RendererRoute;
	route_to: RendererRoute;
	reason?: string | null;
	evidence: string;
}

export interface RouteOverrideCorrectionPayload {
	occurrence_segment_id: string;
	route_from: RendererRoute;
	route_to: RendererRoute;
	anchor_x: number;
	anchor_y: number;
	start_frame: number;
	end_frame: number;
	override_reason: string;
	algorithm?: string | null;
	algorithm_version?: string | null;
	confidence?: number;
	structural_lock_manifest_id?: string | null;
	mutation_idempotency_key?: string | null;
	provenance: RouteOverrideProvenanceDto;
}

export type CorrectionPayload =
	| MaskCorrectionPayload
	| ZOrderCorrectionPayload
	| ContactCorrectionPayload
	| MeshPartsCorrectionPayload
	| RouteOverrideCorrectionPayload;

export interface SubmitCorrectionRequest {
	workspace_id: string;
	project_id: string;
	video_item_id: string;
	idempotency_key?: string | null;
	affected_loop_ids?: string[] | null;
	payload: CorrectionPayload;
}

export interface CorrectionImpactOut {
	correction_kind: string;
	affected_occurrence_segment_ids: string[];
	affected_contact_ids: string[];
	affected_motion_ids: string[];
	affected_loop_ids: string[];
	affected_layer_ids: string[];
	route_override: boolean;
	counts: Record<string, number>;
}

export interface CorrectionOut {
	id: string;
	workspace_id: string;
	project_id: string;
	video_item_id: string;
	occurrence_segment_id: string | null;
	correction_kind: string;
	status: string;
	request: Record<string, unknown>;
	impact: CorrectionImpactOut;
	result: Record<string, unknown> | null;
	applied_at: string | null;
	cancelled_at: string | null;
	idempotency_key: string | null;
	natural_key: string | null;
	revision: number;
	created_at: string;
	updated_at: string;
}

export interface SubmittedCorrectionOut {
	correction: CorrectionOut;
	created: boolean;
	replayed: boolean;
}

export interface ConfirmCorrectionRequest {
	workspace_id: string;
	revision: number;
}

export interface AppliedCorrectionCounts {
	total: number;
	by_kind: Record<string, number>;
}

/** Submit one targeted correction (201 created / 200 idempotent replay). */
export function submitCorrection(
	req: SubmitCorrectionRequest,
): Promise<SubmittedCorrectionOut> {
	return demoFetch<SubmittedCorrectionOut>("/api/v2/s09-corrections", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(req),
	});
}

/** CAS confirm pending -> applied (stale revision -> ApiError 409). */
export function confirmCorrection(
	correctionId: string,
	req: ConfirmCorrectionRequest,
): Promise<CorrectionOut> {
	return demoFetch<CorrectionOut>(
		`/api/v2/s09-corrections/${correctionId}/confirm`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(req),
		},
	);
}

/** CAS cancel pending -> cancelled (applied -> ApiError 409). */
export function cancelCorrection(
	correctionId: string,
	req: ConfirmCorrectionRequest,
): Promise<CorrectionOut> {
	return demoFetch<CorrectionOut>(
		`/api/v2/s09-corrections/${correctionId}/cancel`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(req),
		},
	);
}

/** List corrections of one video (READ-ONLY; mirrors CorrectionListOut). */
export function listCorrections(
	videoItemId: string,
	workspaceId = "default",
): Promise<{ items: CorrectionOut[]; total: number }> {
	const q = new URLSearchParams({
		workspace_id: workspaceId,
		video_item_id: videoItemId,
	});
	return demoFetch<{ items: CorrectionOut[]; total: number }>(
		`/api/v2/s09-corrections?${q.toString()}`,
	);
}

// ── S09-T06B: immutable approval surface (typed client additions, additive) ─
//
// Mirrors app/schemas/s09_approval.py EXACTLY (extra=forbid upstream, so
// every field here is contract-checked).  Read models expose the FROZEN
// snapshot (pack versions, policy, per-segment routes, manifest ref,
// warnings/overrides, correction history) straight from the durable
// checkpoint row — never recomputed client-side.

export interface ApprovalRouteEvidence {
	occurrence_segment_id: string;
	route: string;
	anchor_x: number;
	anchor_y: number;
	start_frame: number;
	end_frame: number;
	confidence: number;
	confidence_source: string;
	reasons: string[];
	provenance: Record<string, unknown> | null;
	structural_lock_manifest_id: string | null;
}

export interface ApprovalCompatibilityPolicy {
	policy_version?: string | null;
	structural_lock_manifest_id?: string | null;
	renderer_routes_per_segment?: ApprovalRouteEvidence[];
}

export interface ApprovalSnapshot {
	schema?: string;
	note?: string | null;
	compatibility_policy?: ApprovalCompatibilityPolicy;
	warnings_accepted?: string[];
	overrides?: string[];
	demo_artifact_refs?: string[];
	correction_history_refs?: string[];
}

/** Mirror of CheckpointOut — one frozen approval checkpoint. */
export interface ApprovalCheckpointOut {
	id: string;
	workspace_id: string;
	project_id: string;
	reskin_config_id: string;
	reskin_config_revision: number;
	structural_lock_manifest_id: string | null;
	lock_policy_version: string | null;
	pack_version_ids: string[];
	loop_hashes: Record<string, unknown>[];
	timebase_fingerprint: string;
	snapshot: ApprovalSnapshot;
	checkpoint_hash: string;
	note: string | null;
	created_at: string;
	updated_at: string;
}

/** Mirror of SubmittedCheckpointOut (201 created / 200 replayed). */
export interface ApprovalSubmittedOut extends ApprovalCheckpointOut {
	replayed: boolean;
}

export interface ApprovalVerifyOut {
	checkpoint_id: string;
	verified: boolean;
	reason: string;
}

/** Exact SubmitCheckpointRequest shape (extra=forbid upstream). */
export interface SubmitApprovalRequest {
	reskin_config_id: string;
	expected_reskin_revision: number;
	pack_version_ids: string[];
	demo_artifact_ids?: string[];
	correction_ids?: string[];
	accepted_warnings?: string[];
	overrides?: string[];
	note?: string | null;
	idempotency_key?: string | null;
}

/** Submit one immutable approval checkpoint (201 created / 200 replayed). */
export function submitApproval(
	req: SubmitApprovalRequest,
	workspaceId = "default",
): Promise<ApprovalSubmittedOut> {
	const q = new URLSearchParams({ workspace_id: workspaceId });
	return demoFetch<ApprovalSubmittedOut>(`/api/v2/s09-approvals?${q.toString()}`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(req),
	});
}

/** Get one checkpoint hash-verified from the STORED row. */
export function getApproval(
	checkpointId: string,
	workspaceId = "default",
): Promise<ApprovalCheckpointOut> {
	const q = new URLSearchParams({ workspace_id: workspaceId });
	return demoFetch<ApprovalCheckpointOut>(
		`/api/v2/s09-approvals/${checkpointId}?${q.toString()}`,
	);
}

/** List checkpoints scoped by workspace (+ optional project). */
export function listApprovals(
	options: { workspaceId?: string; projectId?: string } = {},
): Promise<{ total: number; items: ApprovalCheckpointOut[] }> {
	const q = new URLSearchParams({
		workspace_id: options.workspaceId ?? "default",
	});
	if (options.projectId) q.set("project_id", options.projectId);
	return demoFetch<{ total: number; items: ApprovalCheckpointOut[] }>(
		`/api/v2/s09-approvals?${q.toString()}`,
	);
}

/** Recompute the stored hash; verified=false means tampered/fail-closed. */
export function verifyApproval(
	checkpointId: string,
	workspaceId = "default",
): Promise<ApprovalVerifyOut> {
	const q = new URLSearchParams({ workspace_id: workspaceId });
	return demoFetch<ApprovalVerifyOut>(
		`/api/v2/s09-approvals/${checkpointId}/verify?${q.toString()}`,
		{ method: "POST" },
	);
}

// ── reskin-config read model (READ-ONLY listing for approval targets) ──────

/** Mirror of ReskinConfigData (app/schemas/reskin_config.py). */
export interface ReskinConfigInfo {
	id: string;
	workspace_id: string;
	project_id: string;
	object_role_id: string;
	cast_mapping_id: string | null;
	character_id: string;
	pack_version_id: string;
	params: Record<string, unknown>;
	idempotency_key: string | null;
	structural_lock_manifest_id: string | null;
	lock_policy_version: string | null;
	revision: number;
	created_at: string;
	updated_at: string;
}

/** List reskin configs of one project (READ-ONLY listing). */
export function listReskinConfigs(
	projectId: string,
): Promise<{ total: number; configs: ReskinConfigInfo[] }> {
	const q = new URLSearchParams({ project_id: projectId });
	return demoFetch<{ total: number; configs: ReskinConfigInfo[] }>(
		`/api/v2/reskin-configs?${q.toString()}`,
	);
}

/** Applied-correction counts per kind — the benchmark-results feed. */
export function getAppliedCorrectionCounts(
	videoItemId: string,
): Promise<AppliedCorrectionCounts> {
	return demoFetch<AppliedCorrectionCounts>(
		`/api/v2/videos/${videoItemId}/s09-correction-counts`,
	);
}

// ── S09-C3-PREP (T05B): targeted regeneration surface (additive) ───────────
//
// Contract per the C3 correction prompt: after a correction is CONFIRMED
// APPLIED, the UI opens a targeted regeneration of ONLY the affected loops
// through the base demo-compare job.  The endpoint is owned by T04's F1
// correction (production wiring pending); the client ships the exact
// planned contract so the C3-PREP E2E can probe it honestly and skip with
// a REAL precondition failure while the endpoint is not yet deployed.

export interface RegenerateJobRequest {
	/** The one applied correction that justifies this targeted rerun. */
	correction_id: string;
}

/**
 * S09-C4 §4.5: mirrors app/schemas/s09_demo_compare.py RegenerateJobCreated
 * EXACTLY (extra=forbid upstream).  `affected_loop_ids` here is the
 * SERVER-LOADED exact scope from the applied correction's context — the
 * client NEVER supplies or re-derives it; the UI displays this value
 * verbatim as the regeneration scope evidence.
 */
export interface RegenerateJobResponse {
	job_id: string;
	state: string;
	reused: boolean;
	base_job_id: string;
	correction_id: string;
	correction_context_sha256: string;
	/** §4.4/§4.5: SERVER-side frozen-evidence identity this generation is bound to. */
	frozen_evidence_sha256: string;
	affected_loop_ids: string[];
	detail_url: string;
}

/**
 * Open a TARGETED regeneration job for `base_job_id`, re-rendering only the
 * loops affected by the applied correction (`correction_id`).
 *
 * POST /api/v2/s09-demo-compare/jobs/{base_job_id}/regenerate
 */
export function regenerateDemoCompareJob(
	baseJobId: string,
	req: RegenerateJobRequest,
): Promise<RegenerateJobResponse> {
	return demoFetch<RegenerateJobResponse>(
		`/api/v2/s09-demo-compare/jobs/${baseJobId}/regenerate`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(req),
		},
	);
}

