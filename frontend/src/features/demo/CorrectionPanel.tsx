"use client";

/**
 * CorrectionPanel — S09-T05B targeted correction surface.
 *
 * Data flow (NO mock data anywhere):
 *   1. Load REAL durable projects -> video items -> CURRENT segments /
 *      contacts / motions from the structural-evidence API.
 *   2. Submit any of the five typed corrections (mask, z_order, contact,
 *      mesh_parts, route_override) with EXACT T05A payload shapes
 *      (app/schemas/s09_correction.py).
 *   3. CAS confirm applies the mutation; a stale revision or an
 *      idempotency-key replay with a materially different payload
 *      surfaces as an explicit conflict state (HTTP 409).
 *   4. After confirm the panel renders the backend impact (affected
 *      layers) and the persisted route_override provenance — regeneration
 *      touches ONLY the affected scope; this UI never shows a full-video
 *      rerun indicator because targeted corrections never rerun the whole
 *      video.
 *   5. S09-C4 §4.1 (F1 fix): the correction scope is EXACTLY the loop
 *      currently selected/active in the compare viewer ([selectedLoopId])
 *      — NEVER the whole published list, no frame-range fabrication, no
 *      "all" fallback.  Without an exact selected loop on a COMPLETED base
 *      job, submit/confirm stay disabled with an explicit Vietnamese
 *      reason and no empty scope is ever archived.
 *
 * State-shape note: per-target fields (revision / end_frame / transform /
 * generation) are DERIVED from the currently selected REAL row at render
 * time; text inputs hold raw strings and only override the derived value
 * when non-empty.  This keeps the component pure (no setState-in-effect
 * synchronization cascades) and guarantees submitted values always match
 * what the backend actually owns.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
	ApiError,
	RENDERER_ROUTES,
	type ContactInfo,
	type CorrectionKind,
	type CorrectionPayload,
	type MotionInfo,
	type RendererRoute,
	type SegmentInfo,
	submitCorrection,
	confirmCorrection,
	cancelCorrection,
	getAppliedCorrectionCounts,
	getDemoCompareStatus,
	listContacts,
	listCurrentSegments,
	listDurableProjects,
	listMotions,
	listProjectVideos,
	regenerateDemoCompareJob,
} from "./index";

type PanelPhase = "idle" | "loading" | "ready" | "submitting" | "applied";

/** Lifecycle of the post-confirm targeted regeneration (C3-PREP). */
type RegenPhase =
	| "idle"
	| "opening"
	| "running"
	| "completed"
	| "failed"
	| "error";

export interface CorrectionPanelProps {
	/** Completed base demo-compare job this correction targets (if any). */
	baseJobId?: string | null;
	/** Live state of the base job ("completed" required to regenerate). */
	baseJobState?: string | null;
	/**
	 * S09-C4 §4.1: the EXACT loop the compare viewer currently shows
	 * (user-selected/expanded).  The submitted correction scope is exactly
	 * `[selectedLoopId]` — NEVER the whole published list, never a
	 * fabricated frame-range, never an "all" fallback.
	 */
	selectedLoopId?: string | null;
	/** Adopt + poll the regeneration job in the compare viewer. */
	onRegenerationJob?: (jobId: string) => void;
}

const REGEN_TERMINAL = new Set(["completed", "failed", "cancelled"]);

interface LastResult {
	correctionId: string;
	kind: CorrectionKind;
	status: string;
	/** Revision snapshot used for the CAS confirm/cancel of THIS record. */
	pendingRevision: number;
	affectedLayers: string[];
	provenance: string | null;
}

const HELPER_TEXT =
	"text-[11px] leading-snug text-gray-400"; // VN dark-theme contract: >= gray-400, >= 11px

function errText(err: unknown): string {
	if (err instanceof ApiError) {
		const detail = err.detailText();
		return detail ? `API ${err.status}: ${detail}` : `API ${err.status}`;
	}
	return String(err);
}

/** Parse a raw input string; null when blank/invalid (= keep derived value). */
function parseNum(raw: string): number | null {
	if (raw.trim() === "") return null;
	const n = Number(raw);
	return Number.isFinite(n) ? n : null;
}

export function CorrectionPanel({
	baseJobId = null,
	baseJobState = null,
	selectedLoopId = null,
	onRegenerationJob,
}: CorrectionPanelProps) {
	const [phase, setPhase] = useState<PanelPhase>("idle");
	const [errorText, setErrorText] = useState<string | null>(null);
	const [conflictText, setConflictText] = useState<string | null>(null);
	const [projects, setProjects] = useState<
		Awaited<ReturnType<typeof listDurableProjects>>["projects"]
	>([]);
	const [videos, setVideos] = useState<
		Awaited<ReturnType<typeof listProjectVideos>>["videos"]
	>([]);
	const [projectId, setProjectId] = useState<string>("");
	const [videoId, setVideoId] = useState<string>("");
	const [segments, setSegments] = useState<SegmentInfo[]>([]);
	const [contacts, setContacts] = useState<ContactInfo[]>([]);
	const [motions, setMotions] = useState<MotionInfo[]>([]);
	const [kind, setKind] = useState<CorrectionKind>("z_order");
	const [segmentId, setSegmentId] = useState<string>("");
	const [contactId, setContactId] = useState<string>("");
	const [motionId, setMotionId] = useState<string>("");

	// Raw string inputs; "" = derive from the currently selected REAL row.
	const [revisionInput, setRevisionInput] = useState<string>("");
	const [zOrderInput, setZOrderInput] = useState<string>("0");
	const [contactEndFrameInput, setContactEndFrameInput] =
		useState<string>("");
	const [dxInput, setDxInput] = useState<string>("");
	const [dyInput, setDyInput] = useState<string>("");
	const [routeFrom, setRouteFrom] = useState<RendererRoute>("pose_swap");
	const [routeTo, setRouteTo] = useState<RendererRoute>("sprite_affine");
	const [anchorXInput, setAnchorXInput] = useState<string>("0.25");
	const [anchorYInput, setAnchorYInput] = useState<string>("0.75");
	const [startFrameInput, setStartFrameInput] = useState<string>("0");
	const [endFrameInput, setEndFrameInput] = useState<string>("90");
	const [overrideReason, setOverrideReason] = useState<string>("");
	const [idempotencyKey, setIdempotencyKey] = useState<string>("");
	const [last, setLast] = useState<LastResult | null>(null);
	const [counts, setCounts] = useState<{
		total: number;
		by_kind: Record<string, number>;
	} | null>(null);

	const selectedSegment = useMemo(
		() => segments.find((s) => s.id === segmentId) ?? null,
		[segments, segmentId],
	);
	const selectedContact = useMemo(
		() => contacts.find((c) => c.id === contactId) ?? null,
		[contacts, contactId],
	);
	const selectedMotion = useMemo(
		() => motions.find((m) => m.id === motionId) ?? null,
		[motions, motionId],
	);

	// ── C3-PREP: targeted-regeneration state (post-confirm flow) ──────────
	const [regenPhase, setRegenPhase] = useState<RegenPhase>("idle");
	const [regenJobId, setRegenJobId] = useState<string | null>(null);
	const [regenError, setRegenError] = useState<string | null>(null);
	const [regenScope, setRegenScope] = useState<string[]>([]);
	const regenPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

	useEffect(
		() => () => {
			if (regenPollRef.current !== null) clearInterval(regenPollRef.current);
		},
		[],
	);

	/**
	 * S09-C4 §4.1 — EXACT selected-loop scope.  The affected scope is the
	 * ONE loop currently shown/selected in the compare viewer, and only
	 * when a completed base job exists.  There is deliberately NO overlap
	 * heuristic, NO whole-completed-list expansion, NO "all" fallback and
	 * no fabricated frame-range: without an exact selection this stays
	 * empty and every regeneration action is blocked below.
	 */
	const affectedLoopIds = useMemo<string[]>(() => {
		if (!baseJobId || !selectedLoopId) return [];
		return [selectedLoopId];
	}, [baseJobId, selectedLoopId]);

	const baseJobReady = Boolean(baseJobId && baseJobState === "completed");

	/**
	 * §4.1 gate: submit/confirm regeneration requires BOTH an exact
	 * selected loop AND a completed base job.  When blocked, the action
	 * buttons stay disabled with an explicit Vietnamese helper (no empty
	 * scope is ever archived and no job call is made).
	 */
	const regenBlocked =
		!baseJobReady || affectedLoopIds.length !== 1 || !selectedLoopId;

	/**
	 * §4.1: explicit machine-readable reason WHY regeneration actions are
	 * blocked — rendered as the Vietnamese helper text under the disabled
	 * buttons so the user always knows what is missing.
	 */
	const regenBlockedReason: string | null = !baseJobId
		? "Chưa có base job so sánh nào — hãy chạy “Tạo job so sánh” trước khi sửa lỗi."
		: !baseJobReady
			? "Base job chưa hoàn tất (trạng thái không phải completed) — không thể gửi correction có scope tái tạo."
			: !selectedLoopId
				? "Chưa chọn loop cụ thể trong trình so sánh — hãy chọn đúng loop cần sửa ở danh sách loop phía trên."
				: null;

	/** Poll ONE durable job id to its terminal state (regeneration). */
	const pollRegenJob = useCallback(
		(jobId: string) => {
			if (regenPollRef.current !== null) clearInterval(regenPollRef.current);
			regenPollRef.current = setInterval(async () => {
				try {
					const st = await getDemoCompareStatus(jobId);
					if (REGEN_TERMINAL.has(st.state)) {
						if (regenPollRef.current !== null) {
							clearInterval(regenPollRef.current);
							regenPollRef.current = null;
						}
						if (st.state === "completed") {
							setRegenPhase("completed");
							onRegenerationJob?.(jobId); // viewer re-renders from new artifacts
						} else {
							setRegenPhase("failed");
							setRegenError(st.error?.message ?? `job kết thúc: ${st.state}`);
						}
					}
				} catch (err) {
					if (regenPollRef.current !== null) {
						clearInterval(regenPollRef.current);
						regenPollRef.current = null;
					}
					setRegenPhase("error");
					setRegenError(errText(err));
				}
			}, 1500);
		},
		[onRegenerationJob],
	);

	/**
	 * Open the TARGETED regeneration for an APPLIED correction through the
	 * completed base job — body carries ONLY correction_id per contract;
	 * the EXACT scope is loaded server-side from the applied context and
	 * returned in `affected_loop_ids` (§4.5), which this panel displays as
	 * evidence.  Fail-closed: without an exact selected loop on a completed
	 * base job this refuses BEFORE any HTTP call.
	 */
	const openRegeneration = useCallback(
		async (correctionId: string) => {
			if (regenBlocked || !baseJobId) {
				setRegenError(
					regenBlockedReason ??
						"Không thể tạo lại: thiếu loop được chọn hoặc base job chưa hoàn tất.",
				);
				setRegenPhase("error");
				return;
			}
			setConflictText(null);
			setErrorText(null);
			setRegenError(null);
			setRegenPhase("opening");
			try {
				const res = await regenerateDemoCompareJob(baseJobId, {
					correction_id: correctionId,
				});
				setRegenJobId(res.job_id);
				// §4.5 evidence: display the SERVER-loaded exact scope, never a
				// client-side memory of what we think it should be.
				setRegenScope(res.affected_loop_ids);
				setRegenPhase("running");
				pollRegenJob(res.job_id);
			} catch (err) {
				setRegenPhase("error");
				setRegenError(errText(err));
			}
		},
		[baseJobId, pollRegenJob, regenBlocked, regenBlockedReason],
	);

	// ── derived per-kind values (always reflect the REAL backend rows) ────
	const effectiveRevision = useMemo(() => {
		const overridden = parseNum(revisionInput);
		if (overridden !== null && overridden >= 1) return overridden;
		if (kind === "contact") return selectedContact?.revision ?? 1;
		if (kind === "mesh_parts") return selectedMotion?.revision ?? 1;
		return selectedSegment?.revision ?? 1;
	}, [revisionInput, kind, selectedContact, selectedMotion, selectedSegment]);

	const effectiveGeneration = selectedSegment?.source_generation ?? "";

	const effectiveZOrder = parseNum(zOrderInput) ?? 0;

	const effectiveContactEndFrame =
		parseNum(contactEndFrameInput) ?? selectedContact?.end_frame ?? null;

	const effectiveDx =
		parseNum(dxInput) ?? Number(selectedMotion?.transform.dx ?? 0);
	const effectiveDy =
		parseNum(dyInput) ?? Number(selectedMotion?.transform.dy ?? 0);

	const refreshCounts = useCallback(async (vid: string) => {
		try {
			setCounts(await getAppliedCorrectionCounts(vid));
		} catch {
			setCounts(null); // honest empty state; not fabricated zeroes
		}
	}, []);

	const loadTargets = useCallback(
		async (pid: string, vid: string) => {
			setPhase("loading");
			setErrorText(null);
			setConflictText(null);
			setRevisionInput("");
			setContactEndFrameInput("");
			setDxInput("");
			setDyInput("");
			try {
				const [segList, contactList] = await Promise.all([
					listCurrentSegments(vid),
					listContacts(),
				]);
				let motionList: MotionInfo[] = [];
				if (segList.segments.length > 0) {
					motionList = await listMotions(segList.segments[0].id);
				}
				setSegments(segList.segments);
				setContacts(contactList);
				setMotions(motionList);
				setSegmentId(segList.segments[0]?.id ?? "");
				setContactId(contactList[0]?.id ?? "");
				setMotionId(motionList[0]?.id ?? "");
				setPhase("ready");
				void refreshCounts(vid);
			} catch (err) {
				setErrorText(errText(err));
				setPhase("idle");
			}
		},
		[refreshCounts],
	);

	const loadProjects = useCallback(async () => {
		setPhase("loading");
		setErrorText(null);
		setConflictText(null);
		try {
			const doc = await listDurableProjects();
			setProjects(doc.projects);
			const first = doc.projects[0];
			if (!first) {
				setPhase("idle");
				return;
			}
			setProjectId(first.project_id);
			const vdoc = await listProjectVideos(first.project_id);
			setVideos(vdoc.videos);
			const firstVideo = vdoc.videos[0];
			if (firstVideo) {
				setVideoId(firstVideo.video_item_id);
				await loadTargets(first.project_id, firstVideo.video_item_id);
			} else {
				setPhase("idle");
			}
		} catch (err) {
			setErrorText(errText(err));
			setPhase("idle");
		}
	}, [loadTargets]);

	const loadedOnce = useRef(false);
	useEffect(() => {
		if (loadedOnce.current) return;
		loadedOnce.current = true;
		void loadProjects();
	}, [loadProjects]);

	const onProjectChange = useCallback(
		async (nextPid: string) => {
			setProjectId(nextPid);
			try {
				const vdoc = await listProjectVideos(nextPid);
				setVideos(vdoc.videos);
				const firstVideo = vdoc.videos[0];
				setVideoId(firstVideo?.video_item_id ?? "");
				if (firstVideo) {
					await loadTargets(nextPid, firstVideo.video_item_id);
				}
			} catch (err) {
				setErrorText(errText(err));
			}
		},
		[loadTargets],
	);

	const onVideoChange = useCallback(
		async (nextVid: string) => {
			setVideoId(nextVid);
			await loadTargets(projectId, nextVid);
		},
		[projectId, loadTargets],
	);

	/** Refresh motions when the picked segment changes (mesh_parts target). */
	useEffect(() => {
		if (!segmentId || kind !== "mesh_parts") return;
		let cancelled = false;
		void (async () => {
			try {
				const list = await listMotions(segmentId);
				if (!cancelled) {
					setMotions(list);
					setMotionId(list[0]?.id ?? "");
				}
			} catch {
				if (!cancelled) setMotions([]);
			}
		})();
		return () => {
			cancelled = true;
		};
	}, [segmentId, kind]);

	const reasonMissing = kind === "route_override" && overrideReason.trim().length === 0;

	/**
	 * S09-C4 §4.1: submission is blocked when there is no exact selected
	 * loop on a completed base job — an empty scope must NEVER be archived.
	 */
	const submitDisabled =
		regenBlocked ||
		phase === "submitting" ||
		phase === "loading" ||
		!projectId ||
		!videoId ||
		reasonMissing ||
		((kind === "mask" || kind === "z_order" || kind === "route_override") &&
			!segmentId) ||
		(kind === "contact" && !contactId) ||
		(kind === "mesh_parts" && !motionId);

	const onSubmit = useCallback(async () => {
		setConflictText(null);
		setErrorText(null);
		setLast(null);
		setPhase("submitting");
		let payload: CorrectionPayload;
		switch (kind) {
			case "mask":
				payload = {
					occurrence_segment_id: segmentId,
					revision: effectiveRevision,
					source_generation: effectiveGeneration,
					segmentation: selectedSegment?.segmentation ?? {
						points: [{ x: 12, y: 22 }],
					},
					mask_artifact_id: selectedSegment?.mask_artifact_id ?? "",
					confidence_source: "user",
					reasons: ["UI mask correction"],
					provenance: { user: "demo-reviewer", surface: "t05b-ui" },
				};
				break;
			case "z_order":
				payload = {
					occurrence_segment_id: segmentId,
					revision: effectiveRevision,
					source_generation: effectiveGeneration,
					z_order: effectiveZOrder,
					confidence_source: "user",
					reasons: ["UI z-order correction"],
					provenance: { user: "demo-reviewer", surface: "t05b-ui" },
				};
				break;
			case "contact":
				payload = {
					contact_id: contactId,
					revision: effectiveRevision,
					end_frame: effectiveContactEndFrame,
					reasons: ["UI contact correction"],
					provenance: { user: "demo-reviewer", surface: "t05b-ui" },
				};
				break;
			case "mesh_parts":
				payload = {
					motion_id: motionId,
					revision: effectiveRevision,
					transform: { dx: effectiveDx, dy: effectiveDy },
					reasons: ["UI mesh/parts correction"],
					provenance: { user: "demo-reviewer", surface: "t05b-ui" },
				};
				break;
			case "route_override":
				payload = {
					occurrence_segment_id: segmentId,
					route_from: routeFrom,
					route_to: routeTo,
					anchor_x: parseNum(anchorXInput) ?? 0.25,
					anchor_y: parseNum(anchorYInput) ?? 0.75,
					start_frame: parseNum(startFrameInput) ?? 0,
					end_frame: parseNum(endFrameInput) ?? 90,
					override_reason: overrideReason.trim(),
					algorithm: "user_override",
					algorithm_version: "s09-t05b",
					provenance: {
						route_from: routeFrom,
						route_to: routeTo,
						evidence: overrideReason.trim(),
					},
				};
				break;
		}
		try {
			const res = await submitCorrection({
				workspace_id: "default",
				project_id: projectId,
				video_item_id: videoId,
				idempotency_key:
					idempotencyKey.trim() ||
					`t05b-ui-${crypto.randomUUID()}`,
				// S09-C4 §4.1: the archived correction carries the EXACT
				// non-empty selected-loop scope — never the whole completed
				// list, never null/[] (the button is disabled in that case).
				affected_loop_ids: affectedLoopIds,
				payload,
			});
			setLast({
				correctionId: res.correction.id,
				kind,
				status: res.correction.status,
				pendingRevision: effectiveRevision,
				affectedLayers: res.correction.impact.affected_layer_ids,
				provenance: res.replayed ? "replay: dùng lại bản ghi đã có" : null,
			});
			setPhase("ready");
		} catch (err) {
			if (err instanceof ApiError && err.status === 409) {
				setConflictText(errText(err));
			} else {
				setErrorText(errText(err));
			}
			setPhase("ready");
		}
	}, [
		anchorXInput,
		anchorYInput,
		affectedLoopIds,
		contactId,
		effectiveContactEndFrame,
		effectiveDx,
		effectiveDy,
		effectiveGeneration,
		effectiveRevision,
		effectiveZOrder,
		endFrameInput,
		idempotencyKey,
		kind,
		motionId,
		overrideReason,
		projectId,
		routeFrom,
		routeTo,
		selectedSegment,
		segmentId,
		startFrameInput,
		videoId,
	]);

	const onConfirm = useCallback(
		async (result: LastResult) => {
			setConflictText(null);
			setErrorText(null);
			setPhase("submitting");
			try {
				const applied = await confirmCorrection(result.correctionId, {
					workspace_id: "default",
					revision: result.pendingRevision,
				});
				let provenance: string | null = null;
				if (applied.result && typeof applied.result === "object") {
					const routeOverride = (
						applied.result as {
							route_override?: {
								route_from?: string;
								route_to?: string;
								provenance?: { evidence?: string };
							};
						}
					).route_override;
					if (routeOverride?.provenance?.evidence) {
						provenance = `${routeOverride.route_from} → ${routeOverride.route_to} · bằng chứng: ${routeOverride.provenance.evidence}`;
					}
				}
				setLast({
					...result,
					status: applied.status,
					affectedLayers: applied.impact.affected_layer_ids,
					provenance: provenance ?? result.provenance,
				});
				setPhase("ready");
				void refreshCounts(videoId);
				// S09-C4 §4.1: a CONFIRMED correction immediately opens the
				// targeted regeneration of ONLY the exact selected loop — and
				// ONLY when the §4.1 gate passes (exact loop + completed base).
				// Blocked state never archives an empty scope nor calls the job.
				if (applied.status === "applied" && !regenBlocked) {
					setRegenScope(affectedLoopIds);
					void openRegeneration(applied.id);
				}
			} catch (err) {
				if (err instanceof ApiError && err.status === 409) {
					setConflictText(errText(err));
				} else {
					setErrorText(errText(err));
				}
				setPhase("ready");
			}
		},
		[
			refreshCounts,
			videoId,
			regenBlocked,
			affectedLoopIds,
			openRegeneration,
		],
	);

	const onCancelCorrection = useCallback(
		async (result: LastResult) => {
			setConflictText(null);
			setErrorText(null);
			setPhase("submitting");
			try {
				const cancelled = await cancelCorrection(result.correctionId, {
					workspace_id: "default",
					revision: result.pendingRevision,
				});
				setLast({
					...result,
					status: cancelled.status,
				});
				setPhase("ready");
			} catch (err) {
				if (err instanceof ApiError && err.status === 409) {
					setConflictText(errText(err));
				} else {
					setErrorText(errText(err));
				}
				setPhase("ready");
			}
		},
		[],
	);

	const canCas =
		last !== null && phase !== "submitting" && last.status === "pending";

	return (
		<section
			className="flex flex-col gap-3 rounded border border-gray-700 bg-gray-900/60 p-3"
			data-testid="correction-panel"
			aria-label="Sửa lỗi có chủ đích theo segment"
		>
			<header className="flex flex-col gap-1">
				<h2 className="text-sm font-semibold text-gray-100">
					Sửa lỗi có chủ đích (targeted correction)
				</h2>
				<p className={HELPER_TEXT}>
					Chỉ tác động đúng layer/segment được chọn sau khi duyệt — không chạy lại toàn bộ video.
				</p>
			</header>

			{phase === "loading" && (
				<div className="rounded border border-gray-700 p-3" aria-busy="true" data-testid="correction-loading">
					<p className="text-sm text-gray-300">Đang tải danh sách project / video / segment…</p>
					<p className={`mt-1 ${HELPER_TEXT}`}>Dữ liệu đọc trực tiếp từ API backend.</p>
				</div>
			)}

			{errorText && (
				<div className="rounded border border-red-700 bg-red-900/20 p-3" role="alert" data-testid="correction-error">
					<p className="text-sm text-red-300">{errorText}</p>
					<button
						onClick={() => void loadProjects()}
						className="mt-2 rounded bg-red-700 px-3 py-1.5 text-sm text-white hover:bg-red-600 focus:outline-none focus:ring-2 focus:ring-red-400"
						data-testid="correction-error-retry"
					>
						Thử lại
					</button>
					<p className={`mt-1 ${HELPER_TEXT}`}>Tải lại toàn bộ dữ liệu sửa lỗi từ backend.</p>
				</div>
			)}

			{conflictText && (
				<div className="rounded border border-amber-600 bg-amber-900/20 p-3" role="alert" data-testid="correction-conflict">
					<p className="text-sm text-amber-300">
						Xung đột (HTTP 409): {conflictText}
					</p>
					<p className={`mt-1 ${HELPER_TEXT}`}>
						Dữ liệu đã đổi trên máy chủ (CAS/idempotency). Kiểm tra revision hoặc dùng idempotency key khác rồi gửi lại.
					</p>
				</div>
			)}

			{last && (
				<div className="rounded border border-emerald-700 bg-emerald-900/10 p-3" data-testid="correction-last-result">
					<p className="text-xs text-emerald-300">
						Cập nhật cuối: <span className="font-mono">{last.kind}</span> · trạng thái{" "}
						<span data-testid="correction-last-status">{last.status}</span> · id{" "}
						<span className="font-mono" data-testid="correction-last-id">{last.correctionId}</span>
					</p>
					<p className={`mt-1 ${HELPER_TEXT}`} data-testid="correction-affected-layers">
						Affected layers sau regenerate: {last.affectedLayers.length > 0 ? last.affectedLayers.join(", ") : "(không đổi layer nào)"}
					</p>
					{last.provenance && (
						<p className={`mt-1 ${HELPER_TEXT}`} data-testid="correction-provenance">
							Provenance đã lưu: {last.provenance}
						</p>
					)}
				</div>
			)}

			{baseJobId && (
				<p className={HELPER_TEXT} data-testid="correction-base-job">
					Base job: <span className="font-mono">{baseJobId}</span>
					{baseJobState ? ` · trạng thái ${baseJobState}` : ""}
					{baseJobReady && regenScope.length > 0
						? ` · scope tái tạo: ${regenScope.length} loop`
						: ""}
				</p>
			)}

			{/* ── S09-C4 §4.1 selected-loop scope + block reason ─────────── */}
			<p className={HELPER_TEXT} data-testid="correction-selected-loop-scope">
				{regenBlocked
					? (regenBlockedReason ?? "Correction bị chặn: thiếu loop được chọn/base job hoàn tất.")
					: `Loop đang sửa: ${selectedLoopId} — correction này chỉ tác động đúng loop đã chọn.`}
			</p>

			{/* ── C3-PREP targeted-generation status ──────────────────────── */}
			{regenPhase !== "idle" && (
				<div
					className={`rounded border p-3 ${
						regenPhase === "completed"
							? "border-emerald-700 bg-emerald-900/10"
							: regenPhase === "failed" || regenPhase === "error"
								? "border-red-700 bg-red-900/20"
								: "border-indigo-700 bg-indigo-900/20"
					}`}
					role="status"
					data-testid="correction-regeneration"
				>
					<p className="text-xs text-gray-200" data-testid="correction-regeneration-phase">
						Tạo lại có chủ đích (targeted generation):{" "}
						<span className="font-semibold">{regenPhase}</span>
						{regenJobId && (
							<>
								{" "}· job <span className="font-mono">{regenJobId}</span>
							</>
						)}
					</p>
					<p className={`mt-1 ${HELPER_TEXT}`} data-testid="correction-regeneration-scope">
						Scope thật của job (từ máy chủ):{" "}
						{regenScope.length > 0 ? regenScope.join(", ") : "—"} —
						chỉ các loop này được render lại, phần còn lại của video giữ nguyên
						artifact gốc.
					</p>
					{(regenPhase === "failed" || regenPhase === "error") &&
						regenError && (
							<>
								<p
									className="mt-1 text-xs text-red-300"
									data-testid="correction-regeneration-error"
								>
									{regenError}
								</p>
								{last && baseJobReady && (
									<>
										<button
											onClick={() => void openRegeneration(last.correctionId)}
											className="mt-2 rounded bg-red-700 px-3 py-1.5 text-sm text-white hover:bg-red-600 focus:outline-none focus:ring-2 focus:ring-red-400"
											data-testid="correction-regeneration-retry"
										>
											Thử tạo lại
										</button>
										<p className={`mt-1 ${HELPER_TEXT}`}>
											Gửi lại yêu cầu tạo lại đúng correction đã áp dụng.
										</p>
									</>
								)}
							</>
						)}
				</div>
			)}

			{counts && (
				<p className={HELPER_TEXT} data-testid="correction-counts">
					Tổng correction đã áp dụng cho video này: {counts.total}
					{Object.keys(counts.by_kind).length > 0
						? ` · ${Object.entries(counts.by_kind).map(([k, v]) => `${k}=${v}`).join(", ")}`
						: ""}
				</p>
			)}

			{/* ── target pickers ──────────────────────────────────────────── */}
			<div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
				<div className="flex flex-col gap-1">
					<label htmlFor="corr-project" className="text-xs text-gray-300">Project</label>
					<select
						id="corr-project"
						value={projectId}
						onChange={(e) => void onProjectChange(e.target.value)}
						className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
						data-testid="correction-project-select"
					>
						{projects.length === 0 && <option value="">(không có project)</option>}
						{projects.map((p) => (
							<option key={p.project_id} value={p.project_id}>{p.name}</option>
						))}
					</select>
					<p className={HELPER_TEXT}>Chọn project chứa video cần sửa lỗi.</p>
				</div>
				<div className="flex flex-col gap-1">
					<label htmlFor="corr-video" className="text-xs text-gray-300">Video item</label>
					<select
						id="corr-video"
						value={videoId}
						onChange={(e) => void onVideoChange(e.target.value)}
						className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
						data-testid="correction-video-select"
					>
						{videos.length === 0 && <option value="">(không có video)</option>}
						{videos.map((v) => (
							<option key={v.video_item_id} value={v.video_item_id}>{v.title}</option>
						))}
					</select>
					<p className={HELPER_TEXT}>Chọn video để liệt kê segment/contact/motion thật.</p>
				</div>
				<div className="flex flex-col gap-1">
					<label htmlFor="corr-kind" className="text-xs text-gray-300">Loại correction</label>
					<select
						id="corr-kind"
						value={kind}
						onChange={(e) => setKind(e.target.value as CorrectionKind)}
						className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
						data-testid="correction-kind-select"
					>
						<option value="mask">Mask (đường viền vùng giữ)</option>
						<option value="z_order">Z-order (thứ tự lớp)</option>
						<option value="contact">Contact (tiếp xúc)</option>
						<option value="mesh_parts">Mesh/parts (biến dạng)</option>
						<option value="route_override">Route override (đổi route render)</option>
					</select>
					<p className={HELPER_TEXT}>Chỉ một trong năm loại sửa lỗi có chủ đích.</p>
				</div>
			</div>

			<div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
				{(kind === "mask" || kind === "z_order" || kind === "route_override") && (
					<div className="flex flex-col gap-1">
						<label htmlFor="corr-segment" className="text-xs text-gray-300">Segment (layer hiện tại)</label>
						<select
							id="corr-segment"
							value={segmentId}
							onChange={(e) => setSegmentId(e.target.value)}
							className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
							data-testid="correction-segment-select"
						>
							{segments.length === 0 && <option value="">(không có segment)</option>}
							{segments.map((s) => (
								<option key={s.id} value={s.id}>
									{s.name} · gen {s.source_generation} · rev {s.revision} ({s.start_frame}–{s.end_frame})
								</option>
							))}
						</select>
						<p className={HELPER_TEXT}>Layer sẽ bị ảnh hưởng bởi correction này.</p>
					</div>
				)}

				{(kind === "mask" || kind === "z_order") && (
					<div className="flex flex-col gap-1">
						<label htmlFor="corr-rev" className="text-xs text-gray-300">Revision (CAS)</label>
						<input
							id="corr-rev"
							type="number"
							min={1}
							value={revisionInput !== "" ? revisionInput : String(effectiveRevision)}
							onChange={(e) => setRevisionInput(e.target.value)}
							className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
							data-testid="correction-revision-input"
						/>
						<p className={HELPER_TEXT}>Số bản ghi hiện tại của đối tượng — sai sẽ bị từ chối 409.</p>
					</div>
				)}

				{kind === "contact" && (
					<>
						<div className="flex flex-col gap-1">
							<label htmlFor="corr-contact" className="text-xs text-gray-300">Contact</label>
							<select
								id="corr-contact"
								value={contactId}
								onChange={(e) => setContactId(e.target.value)}
								className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
								data-testid="correction-contact-select"
							>
								{contacts.length === 0 && <option value="">(không có contact)</option>}
								{contacts.map((c) => (
									<option key={c.id} value={c.id}>
										{c.contact_kind} · frames {c.start_frame}–{c.end_frame} · rev {c.revision}
									</option>
								))}
							</select>
							<p className={HELPER_TEXT}>Cạnh tiếp xúc giữa hai segment cần điều chỉnh.</p>
						</div>
						<div className="flex flex-col gap-1">
							<label htmlFor="corr-contact-end" className="text-xs text-gray-300">End frame mới</label>
							<input
								id="corr-contact-end"
								type="number"
								value={contactEndFrameInput !== "" ? contactEndFrameInput : String(selectedContact?.end_frame ?? "")}
								onChange={(e) => setContactEndFrameInput(e.target.value)}
								className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
								data-testid="correction-contact-endframe-input"
							/>
							<p className={HELPER_TEXT}>Giá trị hiện tại được điền sẵn từ contact thật.</p>
						</div>
					</>
				)}

				{kind === "mesh_parts" && (
					<>
						<div className="flex flex-col gap-1">
							<label htmlFor="corr-motion" className="text-xs text-gray-300">Motion (mesh/parts)</label>
							<select
								id="corr-motion"
								value={motionId}
								onChange={(e) => setMotionId(e.target.value)}
								className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
								data-testid="correction-motion-select"
							>
								{motions.length === 0 && <option value="">(không có motion)</option>}
								{motions.map((m) => (
									<option key={m.id} value={m.id}>
										{m.transform_type} · rev {m.revision}
									</option>
								))}
							</select>
							<p className={HELPER_TEXT}>Bản ghi biến dạng của segment đang chọn.</p>
						</div>
						<div className="flex flex-col gap-1">
							<label htmlFor="corr-dx" className="text-xs text-gray-300">dx</label>
							<input
								id="corr-dx"
								type="number"
								step="any"
								value={dxInput !== "" ? dxInput : String(effectiveDx)}
								onChange={(e) => setDxInput(e.target.value)}
								className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
								data-testid="correction-transform-dx-input"
							/>
							<p className={HELPER_TEXT}>Thành phần dịch ngang của transform hiện tại.</p>
						</div>
						<div className="flex flex-col gap-1">
							<label htmlFor="corr-dy" className="text-xs text-gray-300">dy</label>
							<input
								id="corr-dy"
								type="number"
								step="any"
								value={dyInput !== "" ? dyInput : String(effectiveDy)}
								onChange={(e) => setDyInput(e.target.value)}
								className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
								data-testid="correction-transform-dy-input"
							/>
							<p className={HELPER_TEXT}>Thành phần dịch dọc của transform hiện tại.</p>
						</div>
					</>
				)}

				{kind === "z_order" && (
					<div className="flex flex-col gap-1">
						<label htmlFor="corr-z" className="text-xs text-gray-300">Z-order mới</label>
						<input
							id="corr-z"
							type="number"
							value={zOrderInput}
							onChange={(e) => setZOrderInput(e.target.value)}
							className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
							data-testid="correction-zorder-input"
						/>
						<p className={HELPER_TEXT}>Giá trị lớp −1.000.000 … 1.000.000.</p>
					</div>
				)}
			</div>

			{kind === "route_override" && (
				<fieldset className="rounded border border-gray-700 p-3" data-testid="correction-route-form">
					<legend className="px-1 text-xs text-gray-300">Ghi đè route render</legend>
					<div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
						<div className="flex flex-col gap-1">
							<label htmlFor="corr-route-from" className="text-xs text-gray-300">Route hiện tại</label>
							<select
								id="corr-route-from"
								value={routeFrom}
								onChange={(e) => setRouteFrom(e.target.value as RendererRoute)}
								className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
								data-testid="correction-route-from-select"
							>
								{RENDERER_ROUTES.map((r) => (
									<option key={`from-${r}`} value={r}>{r}</option>
								))}
							</select>
							<p className={HELPER_TEXT}>Route đang ghi trong bằng chứng benchmark.</p>
						</div>
						<div className="flex flex-col gap-1">
							<label htmlFor="corr-route-to" className="text-xs text-gray-300">Route mới</label>
							<select
								id="corr-route-to"
								value={routeTo}
								onChange={(e) => setRouteTo(e.target.value as RendererRoute)}
								className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
								data-testid="correction-route-to-select"
							>
								{RENDERER_ROUTES.map((r) => (
									<option key={`to-${r}`} value={r}>{r}</option>
								))}
							</select>
							<p className={HELPER_TEXT}>Chỉ một trong 5 route enum chuẩn của hệ thống.</p>
						</div>
						<div className="flex flex-col gap-1">
							<label htmlFor="corr-anchor-x" className="text-xs text-gray-300">Anchor X (0–1)</label>
							<input
								id="corr-anchor-x"
								type="number"
								step="any"
								min={0}
								max={1}
								value={anchorXInput}
								onChange={(e) => setAnchorXInput(e.target.value)}
								className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
								data-testid="correction-anchor-x-input"
							/>
							<p className={HELPER_TEXT}>Điểm neo tiếp xúc theo toạ độ chuẩn hoá.</p>
						</div>
						<div className="flex flex-col gap-1">
							<label htmlFor="corr-anchor-y" className="text-xs text-gray-300">Anchor Y (0–1)</label>
							<input
								id="corr-anchor-y"
								type="number"
								step="any"
								min={0}
								max={1}
								value={anchorYInput}
								onChange={(e) => setAnchorYInput(e.target.value)}
								className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
								data-testid="correction-anchor-y-input"
							/>
							<p className={HELPER_TEXT}>Điểm neo dọc theo toạ độ chuẩn hoá.</p>
						</div>
						<div className="flex flex-col gap-1">
							<label htmlFor="corr-start-frame" className="text-xs text-gray-300">Start frame</label>
							<input
								id="corr-start-frame"
								type="number"
								value={startFrameInput}
								onChange={(e) => setStartFrameInput(e.target.value)}
								className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
								data-testid="correction-start-frame-input"
							/>
							<p className={HELPER_TEXT}>Khung đầu đoạn route áp dụng.</p>
						</div>
						<div className="flex flex-col gap-1">
							<label htmlFor="corr-end-frame" className="text-xs text-gray-300">End frame</label>
							<input
								id="corr-end-frame"
								type="number"
								value={endFrameInput}
								onChange={(e) => setEndFrameInput(e.target.value)}
								className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
								data-testid="correction-end-frame-input"
							/>
							<p className={HELPER_TEXT}>Khung cuối đoạn route áp dụng.</p>
						</div>
						<div className="flex flex-col gap-1 sm:col-span-2">
							<label htmlFor="corr-reason" className="text-xs text-gray-300">Lý do ghi đè (bắt buộc)</label>
							<input
								id="corr-reason"
								type="text"
								required
								value={overrideReason}
								onChange={(e) => setOverrideReason(e.target.value)}
								placeholder="VD: benchmark FAIL pose_swap ở loop này"
								className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 aria-[invalid=true]:border-red-600"
								aria-invalid={reasonMissing}
								data-testid="correction-reason-input"
							/>
							<p className={HELPER_TEXT}>
								Bắt buộc — lưu vào provenance làm bằng chứng kiểm toán, không được xoá sau khi ghi.
							</p>
						</div>
					</div>
				</fieldset>
			)}

			{/* ── idempotency + actions ───────────────────────────────────── */}
			<div className="flex flex-col gap-1">
				<label htmlFor="corr-idem" className="text-xs text-gray-300">Idempotency key</label>
				<input
					id="corr-idem"
					type="text"
					value={idempotencyKey}
					onChange={(e) => setIdempotencyKey(e.target.value)}
					placeholder="(bỏ trống để tự sinh)"
					className="w-full rounded border border-gray-600 bg-gray-800 px-2 py-1.5 font-mono text-sm text-gray-100 placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 sm:w-fit"
					data-testid="correction-idempotency-input"
				/>
				<p className={HELPER_TEXT}>
					Gửi lại cùng key với nội dung KHÁC → máy chủ từ chối 409 (chống trùng lặp).
				</p>
			</div>

			<div className="flex flex-wrap items-center gap-2" data-testid="correction-actions">
				<button
					onClick={() => void onSubmit()}
					disabled={submitDisabled}
					aria-disabled={submitDisabled}
					className={`rounded px-4 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
						submitDisabled
							? "cursor-not-allowed bg-gray-700 text-gray-400"
							: "bg-indigo-600 text-white hover:bg-indigo-500"
					}`}
					data-testid="correction-submit"
				>
					Gửi correction
				</button>
				<p className={HELPER_TEXT}>
					Lưu correction vào hàng chờ duyệt (pending) — chỉ khả dụng khi đã
					chọn loop cụ thể và base job hoàn tất.
				</p>

				<button
					onClick={() => {
						if (last) void onConfirm(last);
					}}
					disabled={!canCas}
					aria-disabled={!canCas}
					className={`rounded px-4 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-emerald-500 ${
						canCas
							? "bg-emerald-600 text-white hover:bg-emerald-500"
							: "cursor-not-allowed bg-gray-700 text-gray-400"
					}`}
					data-testid="correction-confirm"
				>
					Xác nhận áp dụng
				</button>
				<p className={HELPER_TEXT}>
					Áp dụng thay đổi đúng scope đã báo (CAS revision){regenBlocked ? " — đang bị chặn vì chưa đủ điều kiện tái tạo (xem ghi chú scope ở trên)." : "."}
				</p>

				<button
					onClick={() => {
						if (last) void onCancelCorrection(last);
					}}
					disabled={!canCas}
					aria-disabled={!canCas}
					className={`rounded px-4 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-red-500 ${
						canCas
							? "bg-red-700 text-white hover:bg-red-600"
							: "cursor-not-allowed bg-gray-700 text-gray-400"
					}`}
					data-testid="correction-cancel-btn"
				>
					Hủy correction
				</button>
				<p className={HELPER_TEXT}>Hủy bản ghi pending mà không đụng dữ liệu gốc.</p>
			</div>

			<footer className={HELPER_TEXT}>
				Mọi thao tác chỉ tác động đúng loop/segment đã chọn; trạng thái
				loading/lỗi/xung đột hiển thị ngay tại đây.
			</footer>
		</section>
	);
}
