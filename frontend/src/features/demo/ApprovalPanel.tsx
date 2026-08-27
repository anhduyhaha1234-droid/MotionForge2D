"use client";

/**
 * ApprovalPanel — S09-T06B immutable approval surface (explicit-confirm UX).
 *
 * Data flow (NO mock data anywhere — every value comes from the REAL APIs):
 *   1. Load durable projects -> videos -> ReskinConfigs of the project ->
 *      the video's FULL correction history (read-only listings).
 *   2. The approval summary shows exactly what will be FROZEN into the
 *      immutable checkpoint: reskin config id + revision, pinned pack
 *      version(s), compatibility policy (policy version + structural-lock
 *      manifest ref + per-segment renderer routes served from the stored
 *      checkpoint after approval), accepted warnings, overrides and the
 *      referenced correction history.
 *   3. BLOCKERS FAIL CLOSED (mirror of app/services/s09_approval.py):
 *        - any referenced correction whose status != "applied"
 *          (pending/cancelled) blocks the approval;
 *        - any override string without a match inside the reasons /
 *          provenance.reasons of an APPLIED referenced correction blocks.
 *      While ANY blocker exists the Approve button stays DISABLED — the
 *      backend refuses with 409 anyway (zero mutation), the UI never even
 *      lets the request fire.
 *   4. Warnings and overrides are EXPLICIT OPT-IN: the approver types each
 *      one and must tick its individual checkbox before Approve enables.
 *      Nothing implicit anywhere.
 *   5. Approve POSTs /api/v2/s09-approvals (201 created / 200 replayed),
 *      renders the frozen checkpoint_hash and immediately re-verifies it
 *      via POST {id}/verify.  Existing checkpoints of the project stay
 *      listed below — reloading the page still shows them (durability).
 *
 * Dark-theme contract: every interactive control carries Vietnamese helper
 * text DIRECTLY beneath it (text-gray-400+, >=11px).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
	ApiError,
	type ApprovalCheckpointOut,
	type CorrectionOut,
	type ProjectInfo,
	type ReskinConfigInfo,
	type VideoItemInfo,
	listApprovals,
	listCorrections,
	listDurableProjects,
	listProjectVideos,
	listReskinConfigs,
	submitApproval,
	verifyApproval,
} from "./index";

type PanelPhase = "idle" | "loading" | "ready" | "approving";

interface ExplicitItem {
	text: string;
	accepted: boolean;
}

interface LastApproval {
	id: string;
	replayed: boolean;
	hash: string;
	verified: boolean | null;
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

/**
 * Every reason string recorded on a correction (request + provenance).
 *
 * F5 (C2 review): route-override corrections store their audit evidence in
 * `request.override_reason` and `request.provenance.evidence` (NOT in the
 * generic reasons arrays), so a legitimate override must match approval
 * overrides too — previously a valid override could never satisfy the
 * fail-closed blocker check.
 */
function reasonsOf(correction: CorrectionOut): string[] {
	const request = correction.request as {
		reasons?: unknown;
		override_reason?: unknown;
		provenance?: unknown;
	};
	const out: string[] = [];
	if (Array.isArray(request.reasons)) {
		for (const r of request.reasons) if (typeof r === "string") out.push(r);
	}
	// Route override evidence lives at the TOP LEVEL of the request payload
	// (RouteOverrideCorrectionRequest.override_reason).
	if (typeof request.override_reason === "string" && request.override_reason) {
		out.push(request.override_reason);
	}
	if (request.provenance && typeof request.provenance === "object") {
		const prov = request.provenance as {
			reasons?: unknown;
			evidence?: unknown;
		};
		if (Array.isArray(prov.reasons)) {
			for (const r of prov.reasons) {
				if (typeof r === "string") out.push(r);
			}
		}
		// RouteOverrideProvenance.evidence mirrors override_reason inside
		// the provenance object — match it explicitly as well.
		if (typeof prov.evidence === "string" && prov.evidence) {
			out.push(prov.evidence);
		}
	}
	return out;
}

export function ApprovalPanel() {
	const [phase, setPhase] = useState<PanelPhase>("idle");
	const [errorText, setErrorText] = useState<string | null>(null);
	const [conflictText, setConflictText] = useState<string | null>(null);
	const [projects, setProjects] = useState<ProjectInfo[]>([]);
	const [videos, setVideos] = useState<VideoItemInfo[]>([]);
	const [configs, setConfigs] = useState<ReskinConfigInfo[]>([]);
	const [projectId, setProjectId] = useState<string>("");
	const [videoId, setVideoId] = useState<string>("");
	const [configId, setConfigId] = useState<string>("");

	const [corrections, setCorrections] = useState<CorrectionOut[]>([]);
	const [checkpoints, setCheckpoints] = useState<ApprovalCheckpointOut[]>([]);
	const [checkpointsVerified, setCheckpointsVerified] = useState<
		Record<string, boolean>
	>({});

	const [warnings, setWarnings] = useState<ExplicitItem[]>([]);
	const [overrides, setOverrides] = useState<ExplicitItem[]>([]);
	const [warningInput, setWarningInput] = useState<string>("");
	const [overrideInput, setOverrideInput] = useState<string>("");

	const [revisionInput, setRevisionInput] = useState<string>("");
	const [noteInput, setNoteInput] = useState<string>("");
	const [idempotencyInput, setIdempotencyInput] = useState<string>("");
	const [last, setLast] = useState<LastApproval | null>(null);

	const selectedConfig = useMemo(
		() => configs.find((c) => c.id === configId) ?? null,
		[configs, configId],
	);

	// ── blockers (fail-closed, mirrors the backend service semantics) ─────
	const unresolvedCorrections = useMemo(
		() => corrections.filter((c) => c.status !== "applied"),
		[corrections],
	);
	const unmatchedOverrides = useMemo(
		() =>
			overrides.filter(
				(o) =>
					!corrections.some(
						(c) =>
							c.status === "applied" && reasonsOf(c).includes(o.text),
					),
			),
		[corrections, overrides],
	);
	const hasBlockers =
		unresolvedCorrections.length > 0 || unmatchedOverrides.length > 0;

	const allExplicitAccepted =
		warnings.every((w) => w.accepted) && overrides.every((o) => o.accepted);

	const effectiveRevision =
		revisionInput.trim() !== ""
			? Number(revisionInput)
			: (selectedConfig?.revision ?? 0);

	const approveDisabled =
		phase === "loading" ||
		phase === "approving" ||
		!configId ||
		hasBlockers ||
		!allExplicitAccepted ||
		!(effectiveRevision >= 1);

	const loadCheckpoints = useCallback(async (pid: string) => {
		try {
			const doc = await listApprovals({ projectId: pid });
			setCheckpoints(doc.items);
			const verdicts: Record<string, boolean> = {};
			await Promise.all(
				doc.items.map(async (cp) => {
					try {
						const v = await verifyApproval(cp.id);
						verdicts[cp.id] = v.verified;
					} catch {
						verdicts[cp.id] = false; // fail-closed display
					}
				}),
			);
			setCheckpointsVerified(verdicts);
		} catch {
			setCheckpoints([]); // honest empty state; never fabricated rows
		}
	}, []);

	const loadTargets = useCallback(async (pid: string, vid: string) => {
		setPhase("loading");
		setErrorText(null);
		setConflictText(null);
		try {
			const [cfgDoc, corrDoc] = await Promise.all([
				listReskinConfigs(pid),
				listCorrections(vid),
			]);
			setConfigs(cfgDoc.configs);
			setConfigId(cfgDoc.configs[0]?.id ?? "");
			setRevisionInput("");
			setCorrections(corrDoc.items);
			setPhase("ready");
		} catch (err) {
			setErrorText(errText(err));
			setPhase("idle");
		}
	}, []);

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
				void loadCheckpoints(first.project_id);
			} else {
				setPhase("idle");
			}
		} catch (err) {
			setErrorText(errText(err));
			setPhase("idle");
		}
	}, [loadCheckpoints, loadTargets]);

	const loadedOnce = useRef(false);
	useEffect(() => {
		if (loadedOnce.current) return;
		loadedOnce.current = true;
		void loadProjects();
	}, [loadProjects]);

	const onProjectChange = useCallback(
		async (nextPid: string) => {
			setProjectId(nextPid);
			setLast(null);
			try {
				const vdoc = await listProjectVideos(nextPid);
				setVideos(vdoc.videos);
				const firstVideo = vdoc.videos[0];
				setVideoId(firstVideo?.video_item_id ?? "");
				if (firstVideo) {
					await loadTargets(nextPid, firstVideo.video_item_id);
				}
				void loadCheckpoints(nextPid);
			} catch (err) {
				setErrorText(errText(err));
			}
		},
		[loadCheckpoints, loadTargets],
	);

	const onVideoChange = useCallback(
		async (nextVid: string) => {
			setVideoId(nextVid);
			await loadTargets(projectId, nextVid);
		},
		[loadTargets, projectId],
	);

	const onReload = useCallback(() => {
		if (!projectId) return;
		void loadTargets(projectId, videoId);
		void loadCheckpoints(projectId);
	}, [loadCheckpoints, loadTargets, projectId, videoId]);

	const addWarning = useCallback(() => {
		const text = warningInput.trim();
		if (!text) return;
		setWarnings((prev) =>
			prev.some((w) => w.text === text) ? prev : [...prev, { text, accepted: false }],
		);
		setWarningInput("");
	}, [warningInput]);

	const addOverride = useCallback(() => {
		const text = overrideInput.trim();
		if (!text) return;
		setOverrides((prev) =>
			prev.some((o) => o.text === text)
				? prev
				: [...prev, { text, accepted: false }],
		);
		setOverrideInput("");
	}, [overrideInput]);

	const toggleWarning = useCallback((index: number) => {
		setWarnings((prev) =>
			prev.map((w, i) => (i === index ? { ...w, accepted: !w.accepted } : w)),
		);
	}, []);

	const toggleOverride = useCallback((index: number) => {
		setOverrides((prev) =>
			prev.map((o, i) => (i === index ? { ...o, accepted: !o.accepted } : o)),
		);
	}, []);

	const removeWarning = useCallback((index: number) => {
		setWarnings((prev) => prev.filter((_, i) => i !== index));
	}, []);

	const removeOverride = useCallback((index: number) => {
		setOverrides((prev) => prev.filter((_, i) => i !== index));
	}, []);

	const onApprove = useCallback(async () => {
		if (!selectedConfig || approveDisabled) return;
		setConflictText(null);
		setErrorText(null);
		setPhase("approving");
		try {
			const submitted = await submitApproval({
				reskin_config_id: selectedConfig.id,
				expected_reskin_revision: effectiveRevision,
				pack_version_ids: [selectedConfig.pack_version_id],
				correction_ids: corrections.map((c) => c.id),
				accepted_warnings: warnings.map((w) => w.text),
				overrides: overrides.map((o) => o.text),
				note: noteInput.trim() ? noteInput.trim() : null,
				idempotency_key:
					idempotencyInput.trim() ||
					`t06b-ui-${crypto.randomUUID()}`,
			});
			setLast({
				id: submitted.id,
				replayed: submitted.replayed,
				hash: submitted.checkpoint_hash,
				verified: null,
			});
			try {
				const verdict = await verifyApproval(submitted.id);
				setLast((prev) =>
					prev && prev.id === submitted.id
						? { ...prev, verified: verdict.verified }
						: prev,
				);
			} catch {
				setLast((prev) =>
					prev && prev.id === submitted.id ? { ...prev, verified: false } : prev,
				);
			}
			void loadCheckpoints(projectId);
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
		approveDisabled,
		corrections,
		effectiveRevision,
		idempotencyInput,
		loadCheckpoints,
		noteInput,
		overrides,
		projectId,
		selectedConfig,
		warnings,
	]);

	const onVerify = useCallback(async () => {
		if (!last) return;
		try {
			const verdict = await verifyApproval(last.id);
			setLast((prev) =>
				prev && prev.id === last.id ? { ...prev, verified: verdict.verified } : prev,
			);
		} catch (err) {
			setErrorText(errText(err));
		}
	}, [last]);

	return (
		<section
			className="flex flex-col gap-3 rounded border border-gray-700 bg-gray-900/60 p-3"
			data-testid="approval-panel"
			aria-label="Duyệt áp dụng bất biến theo checkpoint"
		>
			<header className="flex flex-col gap-1">
				<h2 className="text-sm font-semibold text-gray-100">
					Duyệt áp dụng (approval checkpoint)
				</h2>
				<p className={HELPER_TEXT}>
					Tạo bản ghi duyệt BẤT BIẾN: đóng băng pack/policy/route/warning/override — không thể sửa hay xoá sau khi duyệt.
				</p>
			</header>

			{phase === "loading" && (
				<div
					className="rounded border border-gray-700 p-3"
					aria-busy="true"
					data-testid="approval-loading"
				>
					<p className="text-sm text-gray-300">
						Đang tải project / video / reskin config / correction…
					</p>
					<p className={`mt-1 ${HELPER_TEXT}`}>
						Dữ liệu đọc trực tiếp từ API backend, không dùng dữ liệu giả.
					</p>
				</div>
			)}

			{errorText && (
				<div
					className="rounded border border-red-700 bg-red-900/20 p-3"
					role="alert"
					data-testid="approval-error"
				>
					<p className="text-sm text-red-300">{errorText}</p>
					<button
						onClick={() => void loadProjects()}
						className="mt-2 rounded bg-red-700 px-3 py-1.5 text-sm text-white hover:bg-red-600 focus:outline-none focus:ring-2 focus:ring-red-400"
						data-testid="approval-error-retry"
					>
						Thử lại
					</button>
					<p className={`mt-1 ${HELPER_TEXT}`}>
						Tải lại toàn bộ dữ liệu duyệt từ backend.
					</p>
				</div>
			)}

			{conflictText && (
				<div
					className="rounded border border-amber-600 bg-amber-900/20 p-3"
					role="alert"
					data-testid="approval-conflict"
				>
					<p className="text-sm text-amber-300">
						Xung đột (HTTP 409): {conflictText}
					</p>
					<p className={`mt-1 ${HELPER_TEXT}`}>
						Revision đã cũ hoặc nội dung đụng idempotency key đã có — kiểm tra rồi gửi lại với key mới.
					</p>
				</div>
			)}

			{/* ── target pickers ─────────────────────────────────────────── */}
			<div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
				<div className="flex flex-col gap-1">
					<label htmlFor="appr-project" className="text-xs text-gray-300">
						Project
					</label>
					<select
						id="appr-project"
						value={projectId}
						onChange={(e) => void onProjectChange(e.target.value)}
						className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
						data-testid="approval-project-select"
					>
						{projects.length === 0 && <option value="">(không có project)</option>}
						{projects.map((p) => (
							<option key={p.project_id} value={p.project_id}>
								{p.name}
							</option>
						))}
					</select>
					<p className={HELPER_TEXT}>Project chứa hợp đồng reskin cần duyệt.</p>
				</div>
				<div className="flex flex-col gap-1">
					<label htmlFor="appr-video" className="text-xs text-gray-300">
						Video item
					</label>
					<select
						id="appr-video"
						value={videoId}
						onChange={(e) => void onVideoChange(e.target.value)}
						className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
						data-testid="approval-video-select"
					>
						{videos.length === 0 && <option value="">(không có video)</option>}
						{videos.map((v) => (
							<option key={v.video_item_id} value={v.video_item_id}>
								{v.title}
							</option>
						))}
					</select>
					<p className={HELPER_TEXT}>
						Lịch sử correction của video này sẽ được tham chiếu trong lệnh duyệt.
					</p>
				</div>
				<div className="flex flex-col gap-1">
					<label htmlFor="appr-config" className="text-xs text-gray-300">
						Reskin config
					</label>
					<select
						id="appr-config"
						value={configId}
						onChange={(e) => setConfigId(e.target.value)}
						className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
						data-testid="approval-config-select"
					>
						{configs.length === 0 && <option value="">(không có reskin config)</option>}
						{configs.map((c) => (
							<option key={c.id} value={c.id}>
								rev {c.revision} · pack {c.pack_version_id.slice(0, 8)} ·{" "}
								{c.lock_policy_version ?? "không khoá manifest"}
							</option>
						))}
					</select>
					<p className={HELPER_TEXT}>
						Hợp đồng bị đóng băng đúng revision bạn thấy — đổi sau khi duyệt sẽ tạo config mới, không sửa bản ghi cũ.
					</p>
				</div>
				<div className="flex flex-col gap-1">
					<label htmlFor="appr-rev" className="text-xs text-gray-300">
						Revision mong đợi (CAS)
					</label>
					<input
						id="appr-rev"
						type="number"
						min={1}
						value={revisionInput !== "" ? revisionInput : String(selectedConfig?.revision ?? "")}
						onChange={(e) => setRevisionInput(e.target.value)}
						className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
						data-testid="approval-revision-input"
					/>
					<p className={HELPER_TEXT}>
						Sai revision → máy chủ từ chối 409 trước mọi ghi (fail-closed).
					</p>
				</div>
			</div>

			{/* ── summary of what will be frozen ─────────────────────────── */}
			<div className="rounded border border-gray-700 p-3" data-testid="approval-summary">
				<p className="text-xs font-semibold text-gray-200">
					Sẽ bị đóng băng vào checkpoint:
				</p>
				<ul className="mt-1 space-y-0.5 text-[11px] leading-snug text-gray-400">
					<li data-testid="approval-summary-config">
						config: <span className="font-mono">{configId || "(chưa chọn)"}</span>
						· rev {Number.isFinite(effectiveRevision) ? effectiveRevision : "?"}
					</li>
					<li data-testid="approval-summary-pack">
						pack version:{" "}
						<span className="font-mono">
							{selectedConfig?.pack_version_id ?? "(không có)"}
						</span>
					</li>
					<li data-testid="approval-summary-policy">
						policy/manifest:{" "}
						<span className="font-mono">
							{selectedConfig?.structural_lock_manifest_id ?? "(không khoá)"}
						</span>
						· {selectedConfig?.lock_policy_version ?? "policy: (không có)"}
					</li>
					<li data-testid="approval-summary-warnings">
						warnings chấp nhận: {warnings.length > 0 ? warnings.map((w) => w.text).join("; ") : "(không)"}
					</li>
					<li data-testid="approval-summary-overrides">
						overrides: {overrides.length > 0 ? overrides.map((o) => o.text).join("; ") : "(không)"}
					</li>
					<li data-testid="approval-summary-corrections">
						correction refs: {corrections.length > 0 ? `${corrections.length} bản ghi (${corrections.filter((c) => c.status === "applied").length} applied)` : "(không có)"}
					</li>
				</ul>
				<p className={`mt-1 ${HELPER_TEXT}`}>
					Bản ghi duyệt lưu toàn bộ mục trên dưới dạng snapshot băm SHA-256 — đọc lại không join bảng sống.
				</p>
			</div>

			{/* ── corrections referenced ─────────────────────────────────── */}
			<div className="flex flex-col gap-1" data-testid="approval-corrections">
				<p className="text-xs text-gray-300">Lịch sử correction của video:</p>
				{corrections.length === 0 ? (
					<p className={`text-[11px] ${HELPER_TEXT}`}>(chưa có correction nào)</p>
				) : (
					corrections.map((c) => (
						<p
							key={c.id}
							className={`text-[11px] ${c.status === "applied" ? "text-emerald-300" : "text-red-300"}`}
							data-testid={`approval-correction-${c.id}`}
						>
							<span className="font-mono">{c.correction_kind}</span> ·{" "}
							<span className="font-mono">{c.id}</span> · trạng thái{" "}
							<span data-testid={`approval-correction-status-${c.id}`}>{c.status}</span>
						</p>
					))
				)}
				<p className={HELPER_TEXT}>
					Chỉ correction ở trạng thái applied mới được phép nằm dưới một lệnh duyệt.
				</p>
			</div>

			{/* ── blockers (fail-closed) ─────────────────────────────────── */}
			<div
				className={`rounded border p-3 ${
					hasBlockers
						? "border-red-700 bg-red-900/20"
						: "border-emerald-700 bg-emerald-900/10"
				}`}
				data-testid="approval-blockers"
			>
				{hasBlockers ? (
					<>
						<p className="text-sm font-medium text-red-300">
							Còn blocker — nút Duyệt bị khoá cho đến khi xử lý hết:
						</p>
						<ul className="mt-1 space-y-0.5 text-[11px] text-red-200">
							{unresolvedCorrections.map((c) => (
								<li key={`blk-${c.id}`} data-testid="approval-blocker-item">
									Blocker: correction <span className="font-mono">{c.id}</span> đang{" "}
									<span className="font-mono">{c.status}</span> — cần chuyển sang applied (hoặc bỏ khỏi phạm vi duyệt).
								</li>
							))}
							{unmatchedOverrides.map((o) => (
								<li key={`blk-ov-${o.text}`} data-testid="approval-blocker-override">
									Blocker: override “{o.text}” chưa có bằng chứng trong reasons của correction applied nào — override không bao giờ tự động được chấp nhận.
								</li>
							))}
						</ul>
					</>
				) : (
					<p className="text-sm text-emerald-300" data-testid="approval-no-blockers">
						Không còn blocker — có thể duyệt sau khi tick chấp nhận từng mục bên dưới.
					</p>
				)}
				<p className={`mt-1 ${HELPER_TEXT}`}>
					Fail-closed: backend cũng từ chối 409 nếu còn blocker — UI không gửi lệnh duyệt khi danh sách này chưa sạch.
				</p>
			</div>

			{/* ── explicit warnings ──────────────────────────────────────── */}
			<fieldset className="rounded border border-gray-700 p-3" data-testid="approval-warnings-box">
				<legend className="px-1 text-xs text-gray-300">Cảnh báo đã biết (warnings)</legend>
				<div className="flex items-end gap-2">
					<div className="flex grow flex-col gap-1">
						<label htmlFor="appr-warn-in" className="text-xs text-gray-300">
							Thêm cảnh báo
						</label>
						<input
							id="appr-warn-in"
							type="text"
							value={warningInput}
							onChange={(e) => setWarningInput(e.target.value)}
							placeholder="VD: benchmark route mesh_warp chưa đo ở fps 60"
							className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
							data-testid="approval-warning-input"
						/>
						<p className={HELPER_TEXT}>Gõ đúng nội dung cảnh báo bạn hiểu và chấp nhận.</p>
					</div>
					<div className="flex flex-col gap-1 pb-0.5">
						<button
							onClick={addWarning}
							className="rounded bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
							data-testid="approval-warning-add"
						>
							Thêm cảnh báo
						</button>
						<p className={HELPER_TEXT}>Thêm chuỗi cảnh báo vào danh sách sẽ đóng băng trong checkpoint.</p>
					</div>
				</div>
				<p className={`mt-1 ${HELPER_TEXT}`}>
					Mỗi cảnh báo phải được tick chấp nhận rõ ràng thì nút Duyệt mới bật — không có chấp nhận ngầm.
				</p>
				{warnings.length > 0 && (
					<ul className="mt-2 space-y-1">
						{warnings.map((w, i) => (
							<li key={w.text} className="flex items-start gap-2" data-testid={`approval-warning-row-${i}`}>
								<input
									id={`appr-warn-chk-${i}`}
									type="checkbox"
									checked={w.accepted}
									onChange={() => toggleWarning(i)}
									className="mt-0.5 h-4 w-4 accent-emerald-600"
									data-testid={`approval-warning-check-${i}`}
								/>
								<label htmlFor={`appr-warn-chk-${i}`} className="text-xs text-gray-200">
									Tôi đã đọc và chấp nhận: {w.text}
								</label>
								<div className="flex flex-col gap-0.5">
									<button
										onClick={() => removeWarning(i)}
										className="rounded border border-gray-600 px-2 py-1 text-xs text-gray-300 hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-400"
										data-testid={`approval-warning-remove-${i}`}
									>
										Xóa
									</button>
									<p className={HELPER_TEXT}>Gỡ cảnh báo này khỏi bản duyệt (không gửi nữa).</p>
								</div>
							</li>
						))}
					</ul>
				)}
				<p className={`mt-1 ${HELPER_TEXT}`}>
					Mỗi cảnh báo phải được tick chấp nhận rõ ràng thì nút Duyệt mới bật — không có chấp nhận ngầm.
				</p>
			</fieldset>

			{/* ── explicit overrides ─────────────────────────────────────── */}
			<fieldset className="rounded border border-gray-700 p-3" data-testid="approval-overrides-box">
				<legend className="px-1 text-xs text-gray-300">Ghi đè có chủ đích (overrides)</legend>
				<div className="flex items-end gap-2">
					<div className="flex grow flex-col gap-1">
						<label htmlFor="appr-ovr-in" className="text-xs text-gray-300">
							Thêm override
						</label>
						<input
							id="appr-ovr-in"
							type="text"
							value={overrideInput}
							onChange={(e) => setOverrideInput(e.target.value)}
							placeholder="Phải trùng reasons/provenance của một correction applied"
							className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
							data-testid="approval-override-input"
						/>
						<p className={HELPER_TEXT}>Ví dụ: “UI z-order correction” nếu correction applied có reason đó.</p>
					</div>
					<div className="flex flex-col gap-1 pb-0.5">
						<button
							onClick={addOverride}
							className="rounded bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
							data-testid="approval-override-add"
						>
							Thêm override
						</button>
						<p className={HELPER_TEXT}>Thêm override vào danh sách duyệt (phải khớp bằng chứng correction applied).</p>
					</div>
				</div>
				{overrides.length > 0 && (
					<ul className="mt-2 space-y-1">
						{overrides.map((o, i) => {
							const matched = corrections.some(
								(c) => c.status === "applied" && reasonsOf(c).includes(o.text),
							);
							return (
								<li key={o.text} className="flex items-start gap-2" data-testid={`approval-override-row-${i}`}>
									<input
										id={`appr-ovr-chk-${i}`}
										type="checkbox"
										checked={o.accepted}
										onChange={() => toggleOverride(i)}
										className="mt-0.5 h-4 w-4 accent-emerald-600"
										data-testid={`approval-override-check-${i}`}
									/>
									<label htmlFor={`appr-ovr-chk-${i}`} className="text-xs text-gray-200">
										Tôi chủ đích ghi đè: {o.text}
										{matched ? (
											<span className="ml-1 text-emerald-300" data-testid={`approval-override-evidence-${i}`}>
												(đã có bằng chứng applied)
											</span>
										) : (
											<span className="ml-1 text-red-300" data-testid={`approval-override-no-evidence-${i}`}>
												(chưa có bằng chứng — sẽ là blocker)
											</span>
										)}
									</label>
									<div className="flex flex-col gap-0.5">
										<button
											onClick={() => removeOverride(i)}
											className="rounded border border-gray-600 px-2 py-1 text-xs text-gray-300 hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-400"
											data-testid={`approval-override-remove-${i}`}
										>
											Xóa
										</button>
										<p className={HELPER_TEXT}>Gỡ override này khỏi bản duyệt.</p>
									</div>
								</li>
							);
						})}
					</ul>
				)}
				<p className={`mt-1 ${HELPER_TEXT}`}>
					Mỗi override phải được tick xác nhận chủ đích; thiếu bằng chứng applied sẽ khoá nút Duyệt.
				</p>
			</fieldset>

			{/* ── note + idempotency ─────────────────────────────────────── */}
			<div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
				<div className="flex flex-col gap-1">
					<label htmlFor="appr-note" className="text-xs text-gray-300">
						Ghi chú (tuỳ chọn)
					</label>
					<input
						id="appr-note"
						type="text"
						maxLength={500}
						value={noteInput}
						onChange={(e) => setNoteInput(e.target.value)}
						placeholder="Ghi chú nằm trong nội dung băm của checkpoint"
						className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
						data-testid="approval-note-input"
					/>
					<p className={HELPER_TEXT}>Đổi ghi chú = đổi nội dung → key cũ sẽ thành xung đột 409 (đúng thiết kế).</p>
				</div>
				<div className="flex flex-col gap-1">
					<label htmlFor="appr-idem" className="text-xs text-gray-300">
						Idempotency key
					</label>
					<input
						id="appr-idem"
						type="text"
						maxLength={255}
						value={idempotencyInput}
						onChange={(e) => setIdempotencyInput(e.target.value)}
						placeholder="(bỏ trống để tự sinh)"
						className="rounded border border-gray-600 bg-gray-800 px-2 py-1.5 font-mono text-sm text-gray-100 placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
						data-testid="approval-idempotency-input"
					/>
					<p className={HELPER_TEXT}>Gửi lại cùng key + cùng nội dung → trả lại checkpoint cũ, không nhân bản.</p>
				</div>
			</div>

			{/* ── actions ────────────────────────────────────────────────── */}
			<div className="flex flex-wrap items-start gap-4" data-testid="approval-actions">
				<div className="flex flex-col gap-1">
					<button
						onClick={() => void onApprove()}
						disabled={approveDisabled}
						aria-disabled={approveDisabled}
						title={
							hasBlockers
								? "Còn blocker — không thể duyệt"
								: !allExplicitAccepted
									? "Còn warning/override chưa được tick chấp nhận"
									: "Tạo checkpoint duyệt"
						}
						className={`rounded px-4 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-emerald-500 ${
							approveDisabled
								? "cursor-not-allowed bg-gray-700 text-gray-400"
								: "bg-emerald-600 text-white hover:bg-emerald-500"
						}`}
						data-testid="approval-approve-btn"
					>
						Duyệt áp dụng
					</button>
					<p className={HELPER_TEXT} data-testid="approval-approve-helper">
						{hasBlockers
							? "Đang khoá: còn blocker chưa xử lý hết."
							: !allExplicitAccepted
								? "Đang khoá: tick chấp nhận TỪNG warning/override trước."
								: "Tạo bản ghi duyệt bất biến kèm toàn bộ snapshot đã liệt kê."}
					</p>
				</div>
				<div className="flex flex-col gap-1">
					<button
						onClick={() => void onVerify()}
						disabled={!last}
						aria-disabled={!last}
						className={`rounded px-4 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-sky-500 ${
							last
								? "bg-sky-700 text-white hover:bg-sky-600"
								: "cursor-not-allowed bg-gray-700 text-gray-400"
						}`}
						data-testid="approval-verify-btn"
					>
						Kiểm tra hash
					</button>
					<p className={HELPER_TEXT}>Tính lại SHA-256 từ bản ghi đã lưu và đối chiếu — phát hiện sửa trái phép.</p>
				</div>
				<div className="flex flex-col gap-1">
					<button
						onClick={onReload}
						className="rounded bg-gray-700 px-4 py-2 text-sm font-medium text-gray-100 hover:bg-gray-600 focus:outline-none focus:ring-2 focus:ring-gray-400"
						data-testid="approval-reload-btn"
					>
						Nạp lại dữ liệu
					</button>
					<p className={HELPER_TEXT}>Đọc lại correction/checkpoint mới nhất từ backend sau khi có thay đổi.</p>
				</div>
			</div>

			{/* ── last result ────────────────────────────────────────────── */}
			{last && (
				<div
					className="rounded border border-emerald-700 bg-emerald-900/10 p-3"
					data-testid="approval-last-result"
				>
					<p className="text-xs text-emerald-200">
						Checkpoint{" "}
						<span data-testid="approval-last-replayed">
							{last.replayed ? "replayed (bản ghi đã có)" : "created (mới)"}
						</span>{" "}
						· id <span className="font-mono" data-testid="approval-last-id">{last.id}</span>
					</p>
					<p className="mt-1 break-all font-mono text-[11px] text-gray-300" data-testid="approval-hash">
						{last.hash}
					</p>
					<p
						className={`mt-1 text-[11px] ${
							last.verified === null
								? "text-gray-400"
								: last.verified
									? "text-emerald-300"
									: "text-red-300"
						}`}
						data-testid="approval-hash-status"
					>
						{last.verified === null
							? "Chưa kiểm tra hash."
							: last.verified
								? "Hash hợp lệ (verified=true) — bản ghi nguyên vẹn."
								: "Hash KHÔNG khớp — bản ghi có thể bị can thiệp!"}
					</p>
					<p className={`mt-1 ${HELPER_TEXT}`}>
						Hash băm toàn bộ nội dung duyệt; reload trang vẫn tra cứu được từ danh sách dưới đây.
					</p>
				</div>
			)}

			{/* ── existing checkpoints ───────────────────────────────────── */}
			<div className="flex flex-col gap-1" data-testid="approval-checkpoints">
				<p className="text-xs text-gray-300">
					Checkpoint đã duyệt của project ({checkpoints.length}):
				</p>
				{checkpoints.length === 0 ? (
					<p className={HELPER_TEXT}>(chưa có checkpoint nào)</p>
				) : (
					checkpoints.map((cp) => (
						<div
							key={cp.id}
							className="rounded border border-gray-700 px-2 py-1"
							data-testid={`approval-checkpoint-${cp.id}`}
						>
							<p className="break-all text-[11px] text-gray-300">
								<span className="font-mono" data-testid="approval-checkpoint-id">{cp.id}</span>
								{" · rev "}
								{cp.reskin_config_revision}
								{" · "}
								<span className="font-mono" data-testid="approval-checkpoint-hash">
									{cp.checkpoint_hash.slice(0, 16)}…
								</span>
								{" · "}
								<span
									data-testid="approval-checkpoint-verified"
									className={
										checkpointsVerified[cp.id]
											? "text-emerald-300"
											: "text-red-300"
									}
								>
									{checkpointsVerified[cp.id] ? "verified" : "NOT verified"}
								</span>
							</p>
						</div>
					))
				)}
				<p className={HELPER_TEXT}>
					Danh sách đọc từ bảng apply_checkpoint — bản ghi bất biến, tồn tại qua mọi lần tải lại trang.
				</p>
			</div>

			<footer className={HELPER_TEXT}>
				Duyệt là hành động một chiều: checkpoint đã tạo không thể sửa/xoá; mọi thay đổi sau này tạo bản ghi mới.
			</footer>
		</section>
	);
}
