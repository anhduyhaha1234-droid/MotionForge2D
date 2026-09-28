"use client";

/**
 * DemoComparePanel — the S09 demo comparison surface.
 *
 * Composition: metadata (capabilities + loops) → submit/run controls →
 * per-loop comparison viewers (five modes) + renderer route per segment +
 * compatibility/QC reasons + persisted route evidence when present.  Every
 * state (loading / error / empty) renders REAL backend data or an explicit
 * empty message — no fabricated fallback numbers anywhere.
 */
import { useMemo, useState } from "react";

import {
	type JobStatus,
	type PublicationStatus,
} from "./index";
import { CompareViewer, COMPARE_MODES, type CompareMode } from "./CompareViewer";
import { DemoShotReview } from "./DemoShotReview";
import { ApprovalPanel } from "./ApprovalPanel";
import { CorrectionPanel } from "./CorrectionPanel";
import { resolveDemoCompareConfig, useDemoCompare } from "./useDemoCompare";

interface DemoComparePanelProps {
	fixturesDir?: string;
	benchmarkResults?: string;
}

export function DemoComparePanel({
	fixturesDir,
	benchmarkResults,
}: DemoComparePanelProps) {
	// S09-T04-C2: benchmark evidence comes from explicit configuration ONLY
	// (env NEXT_PUBLIC_S09_BENCHMARK_RESULTS[_CONTENT_SHA256] or page props).
	// Missing configuration THROWS here and the panel renders the error —
	// there is no default artifact path to fall back to.
	let configError: string | null = null;
	let config: ReturnType<typeof resolveDemoCompareConfig> | null = null;
	try {
		config = resolveDemoCompareConfig(fixturesDir, benchmarkResults);
	} catch (err) {
		configError = err instanceof Error ? err.message : String(err);
	}
	const {
		phase,
		errorText,
		capabilities,
		loops,
		jobId,
		jobStatus,
		refreshMeta,
		runComparison,
		trackExternalJob,
	} = useDemoCompare(
		config ?? { fixturesDir: "", benchmarkResults: "", expectContentSha256: "" },
	);
	const [mode, setMode] = useState<CompareMode>("split");
	const [activeLoop, setActiveLoop] = useState<string | null>(null);

	/**
	 * S09-C4 §4.1: the CURRENT selected/active loop of this compare viewer
	 * (the entry highlighted in the loop selector, falling back to the first
	 * listed loop).  This exact value is passed to CorrectionPanel so every
	 * correction targets ONLY the loop the reviewer is looking at — never
	 * the whole published list.
	 */
	const effectiveActiveLoop = activeLoop ?? loops[0]?.loop_id ?? null;

	const publishedByLoop = useMemo(() => {
		const map = new Map<string, JobStatus["published"][number]>();
		for (const pub of jobStatus?.published ?? []) map.set(pub.loop_id, pub);
		return map;
	}, [jobStatus]);

	/**
	 * S09-C4 §4.5: per-loop regeneration split reported by the BACKEND for
	 * targeted-regeneration jobs (``publications``).  Rendered verbatim —
	 * the UI never infers ``regenerated`` or fabricates missing entries.
	 */
	const pubStatusByLoop = useMemo(() => {
		const map = new Map<string, PublicationStatus>();
		for (const ps of jobStatus?.publications ?? []) map.set(ps.loop_id, ps);
		return map;
	}, [jobStatus]);

	const busy =
		phase === "loading-meta" || phase === "submitting" || phase === "running";

	return (
		<div className="flex flex-col gap-4 text-gray-100" data-testid="demo-compare-panel">
			<header className="flex flex-col gap-1">
				<h1 className="text-lg font-semibold">So sánh Demo — S09</h1>
				<p className="text-[11px] text-gray-400">
					So sánh video gốc và kết quả render theo từng loop; mọi số liệu lấy trực tiếp từ API backend.
				</p>
			</header>

			<CorrectionPanel
					baseJobId={jobId}
					baseJobState={jobStatus?.state ?? null}
					selectedLoopId={effectiveActiveLoop}
					onRegenerationJob={trackExternalJob}
				/>

			<ApprovalPanel />

			{configError && (
				<div className="rounded border border-red-700 bg-red-900/20 p-3" role="alert" data-testid="demo-config-error">
					<p className="text-sm text-red-300">{configError}</p>
					<p className="mt-1 text-[11px] text-gray-400">
						Bảng so sánh không có bằng chứng mặc định — cấu hình env rồi tải lại trang.
					</p>
				</div>
			)}

			{phase === "error" && (
				<div className="rounded border border-red-700 bg-red-900/20 p-3" role="alert" data-testid="demo-error">
					<p className="text-sm text-red-300">{errorText}</p>
					<button
						onClick={() => void refreshMeta()}
						className="mt-2 rounded bg-red-700 px-3 py-1.5 text-sm text-white hover:bg-red-600 focus:outline-none focus:ring-2 focus:ring-red-400"
						data-testid="demo-error-retry"
					>
						Thử lại
					</button>
					<p className="mt-1 text-[11px] text-gray-400">Nhấn Thử lại để tải lại dữ liệu từ backend.</p>
				</div>
			)}

			{phase === "loading-meta" && (
				<div className="rounded border border-gray-700 p-4" aria-busy="true" data-testid="demo-loading">
					<p className="text-sm text-gray-300">Đang tải capabilities và danh sách loop…</p>
					<p className="mt-1 text-[11px] text-gray-400">Vui lòng đợi — hệ thống đang đọc bằng chứng đo được từ backend.</p>
				</div>
			)}

			{phase !== "loading-meta" && phase !== "error" && loops.length === 0 && (
				<div className="rounded border border-gray-700 p-4" data-testid="demo-empty">
					<p className="text-sm text-gray-300">Chưa có loop demo nào khả dụng.</p>
					<p className="mt-1 text-[11px] text-gray-400">
						Không tìm thấy fixtures — kiểm tra lại đường dẫn fixtures_dir trên máy chủ.
					</p>
				</div>
			)}

			{capabilities && (
				<section className="rounded border border-gray-700 p-3" data-testid="demo-capabilities">
					<h2 className="text-sm font-medium">Bằng chứng benchmark (đo thật)</h2>
					<p className="text-[11px] text-gray-400">Tổng hợp route nhỏ nhất đạt ngưỡng theo từng lớp rủi ro.</p>
					<ul className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2 lg:grid-cols-3">
						{capabilities.classes.map((cls) => (
							<li key={cls.risk_class} className="rounded bg-gray-800 px-2 py-1 text-xs" data-testid={`cap-${cls.risk_class}`}>
								<span className="font-mono">{cls.risk_class}</span>{" "}
								→ {cls.smallest_passing_route ?? <span className="text-amber-400">không có route đạt (null)</span>}
							</li>
						))}
					</ul>
					<p className="mt-2 break-all font-mono text-[11px] text-gray-400">
						frozen_content_sha256: {capabilities.frozen_content_sha256}
						{capabilities.thresholds_policy ? ` · policy: ${capabilities.thresholds_policy}` : ""}
					</p>
				</section>
			)}

			<section className="flex flex-wrap items-center gap-2" data-testid="demo-run-controls">
				<button
					onClick={() => void runComparison()}
					disabled={busy || loops.length === 0}
					aria-disabled={busy || loops.length === 0}
					className={`rounded px-4 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
						busy || loops.length === 0
							? "cursor-not-allowed bg-gray-700 text-gray-400"
							: "bg-indigo-600 text-white hover:bg-indigo-500"
					}`}
					data-testid="demo-submit"
				>
					Tạo job so sánh
				</button>
				<p className="text-[11px] text-gray-400">
					Gửi toàn bộ loop tới API để render và xuất kết quả so sánh (job nền, không chặn trang).
				</p>
			</section>

			{(phase === "submitting" || phase === "running") && (
				<div className="rounded border border-indigo-700 bg-indigo-900/20 p-3" data-testid="demo-running">
					<p className="text-sm text-indigo-200">
						Đang chạy job {jobId ?? "…"} — tiến độ {(Math.round((jobStatus?.progress ?? 0) * 10) / 10).toFixed(1)}%
					</p>
					<p className="mt-1 text-[11px] text-gray-400">Trạng thái: {jobStatus?.state ?? "đang gửi"} — trang tự cập nhật mỗi 1.5 giây.</p>
				</div>
			)}

			{phase === "failed" && (
				<div className="rounded border border-red-700 bg-red-900/20 p-3" data-testid="demo-failed">
					<p className="text-sm text-red-300">Job thất bại: {errorText ?? "không rõ nguyên nhân"}</p>
					<p className="mt-1 text-[11px] text-gray-400">Xem chi tiết lỗi trong phản hồi của job để xử lý rồi tạo lại.</p>
				</div>
			)}

			{phase === "completed" && jobStatus && (
				<section className="rounded border border-emerald-700 bg-emerald-900/10 p-3" data-testid="demo-completed">
					<h2 className="text-sm font-medium text-emerald-300">Job hoàn tất — {jobStatus.published.length} artifact đã xuất</h2>
					<p className="mt-1 text-[11px] text-gray-400">
						Các lớp rủi ro phủ: {jobStatus.covered_risk_classes.join(", ") || "—"}
					</p>
				</section>
			)}

			{phase === "completed" && jobStatus && (
					<section className="flex flex-col gap-3" data-testid="demo-mode-picker">
						{/* ── S09-C4 §4.5 generation evidence (backend-reported ONLY) */}
						{(jobStatus.affected_loop_ids != null ||
							jobStatus.generation_evidence != null) && (
							<div
								className="rounded border border-indigo-700 bg-indigo-900/10 p-3"
								data-testid="demo-generation-evidence"
							>
								<p className="text-xs font-medium text-indigo-200">
									Bằng chứng generation có chủ đích (targeted regeneration)
								</p>
								<p
										className="mt-1 text-[11px] leading-snug text-gray-400"
										data-testid="demo-generation-scope"
									>
									Scope bị ảnh hưởng (theo máy chủ):{" "}
									<span className="font-mono">
										{jobStatus.affected_loop_ids?.length
											? jobStatus.affected_loop_ids.join(", ")
											: "—"}
									</span>
								</p>
								{jobStatus.generation_evidence && (
									<p
											className="mt-1 break-all font-mono text-[11px] leading-snug text-gray-400"
											data-testid="demo-generation-identity"
										>
										gen {jobStatus.generation_evidence.generation} · base{" "}
										{jobStatus.generation_evidence.base_job_id} · correction{" "}
										{jobStatus.generation_evidence.correction_id} · ctx{" "}
										{jobStatus.generation_evidence.correction_context_sha256.slice(0, 12)}… ·
										frozen-evidence{" "}
										{jobStatus.generation_evidence.frozen_evidence_sha256.slice(0, 12)}…
									</p>
								)}
								<p className="mt-1 text-[11px] leading-snug text-gray-400">
										Loop không nằm trong scope giữ nguyên artifact gốc
										(regenerated=false); chỉ loop trong scope mới có thời gian render.
									</p>
								</div>
								)}

						<div className="flex flex-col gap-1">
							<label htmlFor="demo-mode-select" className="text-xs text-gray-300">Chế độ so sánh</label>
							<select
								id="demo-mode-select"
								value={mode}
								onChange={(e) => setMode(e.target.value as CompareMode)}
								className="w-fit rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
								data-testid="demo-mode-select"
							>
								{COMPARE_MODES.map((m) => (
									<option key={m.value} value={m.value}>{m.label}</option>
								))}
							</select>
							<p className="text-[11px] text-gray-400" data-testid="demo-mode-helper">
								{COMPARE_MODES.find((m) => m.value === mode)?.helper}
							</p>
						</div>

						<div className="flex flex-col gap-1">
							<label htmlFor="demo-loop-select" className="text-xs text-gray-300">Loop đang mở rộng</label>
							<select
								id="demo-loop-select"
								value={activeLoop ?? loops[0]?.loop_id ?? ""}
								onChange={(e) => setActiveLoop(e.target.value)}
								className="w-fit rounded border border-gray-600 bg-gray-800 px-2 py-1.5 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
								data-testid="demo-loop-select"
							>
								{loops.map((lp) => (
									<option key={lp.loop_id} value={lp.loop_id}>{lp.loop_id}</option>
								))}
							</select>
							<p className="text-[11px] text-gray-400">
								Chọn loop để xem chi tiết route, QC và trình so sánh video tương ứng.
							</p>
						</div>

						{loops
							.filter((lp) => (activeLoop ?? loops[0]?.loop_id) === lp.loop_id)
							.map((lp) => {
								const published = publishedByLoop.get(lp.loop_id);
								const pubStatus = pubStatusByLoop.get(lp.loop_id);
								return (
							<article key={lp.loop_id} className="rounded border border-gray-700 p-3" data-testid={`demo-loop-${lp.loop_id}`}>
								<div className="mb-2 flex flex-wrap items-center gap-2">
									<h3 className="font-mono text-sm">{lp.loop_id}</h3>
									<span className="rounded bg-gray-800 px-2 py-0.5 text-[11px] text-gray-300">
										{lp.frame_count} frames · {lp.width}×{lp.height} @ {lp.fps}fps
									</span>
								</div>
								<p className="mb-2 text-[11px] text-gray-400">
									Lớp rủi ro: {lp.risk_classes.join(", ") || "—"} · Thao tác: {lp.replacement_ops.join(", ") || "—"}
								</p>

								{/* Renderer route per segment */}
								<div className="mb-2 overflow-x-auto" data-testid={`routes-${lp.loop_id}`}>
									<table className="w-full min-w-[420px] text-left text-xs">
										<thead>
											<tr className="border-b border-gray-700 text-gray-400">
												<th className="py-1 pr-3">Segment</th>
												<th className="py-1 pr-3">Frames</th>
												<th className="py-1 pr-3">Lớp rủi ro</th>
												<th className="py-1">Route render</th>
											</tr>
										</thead>
										<tbody>
											{lp.segments.length === 0 && (
												<tr>
													<td colSpan={4} className="py-1 text-gray-500">Không có segment nào trong manifest.</td>
												</tr>
											)}
											{lp.segments.map((seg) => {
												const segClasses = lp.risk_classes.filter((c) =>
													Object.keys(lp.routes_by_risk_class ?? {}).includes(c),
												);
												const routes = lp.routes_by_risk_class ?? {};
												return (
													<tr key={seg.shot_id} className="border-b border-gray-800">
														<td className="py-1 pr-3 font-mono">{seg.shot_id}</td>
														<td className="py-1 pr-3">{seg.start_frame}–{seg.end_frame}</td>
														<td className="py-1 pr-3">{segClasses.join(", ") || "—"}</td>
														<td className="py-1">
															{segClasses.map((c) => `${c}=${routes[c]}`).join(" · ") || (lp.plan_error ? "—" : "—")}
														</td>
													</tr>
												);
											})}
										</tbody>
									</table>
								</div>
								{lp.plan_error && (
									<p className="mb-2 rounded bg-amber-900/20 px-2 py-1 text-[11px] text-amber-300" data-testid={`plan-error-${lp.loop_id}`}>
										Planner từ chối lập kế hoạch: {lp.plan_error}
									</p>
								)}

								{/* Compatibility / QC reason */}
								{published ? (
									<div className="mb-2 rounded bg-gray-800 px-2 py-1.5" data-testid={`qc-${lp.loop_id}`}>
										<p className="text-[11px] text-gray-300">
											QC: sha256 khớp artifact đã publish · {published.size_bytes.toLocaleString("vi-VN")} bytes
											{published.frame_count != null ? ` · ${published.frame_count} frames` : ""}
											{published.reused_existing_file ? " · tái sử dụng artifact sẵn có (idempotent)" : ""}
										</p>
										<p className="text-[11px] text-gray-400">
											Route chọn theo bằng chứng đo được; không dùng giá trị mặc định khi thiếu measurement.
										</p>
									</div>
								) : (
									<div className="mb-2 rounded bg-gray-800 px-2 py-1.5" data-testid={`qc-pending-${lp.loop_id}`}>
										<p className="text-[11px] text-gray-400">Chưa có artifact cho loop này — chưa thể so sánh.</p>
									</div>
								)}

								{/* ── S09-C4 §4.5 per-loop regeneration split — backend-reported ONLY,
								     rendered verbatim; never inferred, never fabricated. */}
								{pubStatus && (
									<div
										className="mb-2 rounded border border-indigo-800/60 bg-indigo-900/10 px-2 py-1.5"
										data-testid={`regen-status-${lp.loop_id}`}
									>
										<p className="text-[11px] leading-snug text-gray-300">
											Tái tạo có chủ đích:{" "}
											<span className="font-medium" data-testid={`regen-flag-${lp.loop_id}`}>
												{pubStatus.regenerated == null
													? "máy chủ chưa báo cờ regenerated cho loop này"
													: pubStatus.regenerated
														? `ĐÃ render lại${pubStatus.render_ms != null ? ` · render ${pubStatus.render_ms} ms` : ""}`
														: "giữ nguyên artifact gốc (regenerated=false)"}
											</span>
										</p>
										{pubStatus.base_publication && (
											<p className="mt-0.5 break-all text-[11px] leading-snug text-gray-400">
												Bound từ publication gốc: artifact{" "}
												<span className="font-mono">{pubStatus.base_publication.artifact_id}</span> · sha256{" "}
												<span className="font-mono">{pubStatus.base_publication.sha256.slice(0, 12)}…</span> ·{" "}
												{pubStatus.base_publication.size_bytes.toLocaleString("vi-VN")} bytes
											</p>
										)}
									</div>
								)}

								{published && (
										<CompareViewer
											loopId={lp.loop_id}
											originalUrl={`/api/v2/s09-demo-compare/source-content/${lp.loop_id}?fixtures_dir=${encodeURIComponent(fixturesDir ?? "tests/fixtures/s09_demo")}`}
											resultUrl={published.content_url}
											mode={mode}
										/>
									)}
								</article>
									);
								})}
								</section>
								)}

			{/* MF-END-24: before/after sync for published loops (backend URLs only) */}
			{jobStatus?.published.map((lp) => (
				<DemoShotReview
					key={`shot-review-${lp.loop_id}`}
					loopId={lp.loop_id}
					originalUrl={`/api/v2/s09-demo-compare/source-content/${lp.loop_id}?fixtures_dir=${encodeURIComponent(fixturesDir ?? "tests/fixtures/s09_demo")}`}
					resultUrl={lp.content_url}
				/>
			))}

			{/* Persisted SegmentRenderRoute evidence (empty when none referenced) */}
			{jobStatus && jobStatus.route_evidence.length > 0 && (
				<section className="rounded border border-gray-700 p-3" data-testid="demo-route-evidence">
					<h2 className="text-sm font-medium">Bằng chứng route đã lưu (SegmentRenderRoute)</h2>
					<p className="mt-1 text-[11px] text-gray-400">Quyết định route theo từng segment kèm độ tin cậy và lý do.</p>
					<ul className="mt-2 space-y-1">
						{jobStatus.route_evidence.map((ev) => (
							<li key={`${ev.occurrence_segment_id}-${ev.start_frame}`} className="rounded bg-gray-800 px-2 py-1 text-xs">
								<span className="font-mono">{ev.occurrence_segment_id}</span> → {ev.route} (frames {ev.start_frame}–
								{ev.end_frame}, tin cậy {ev.confidence.toFixed(2)}) — {ev.reasons.join("; ") || "không ghi lý do"}
							</li>
						))}
					</ul>
				</section>
			)}

			<footer className="text-[11px] text-gray-400">
				Phím tắt: Tab di chuyển giữa các nút; Enter kích hoạt; ở chế độ Wipe dùng phím mũi tên trái/phải để kéo vạch chia.
				Giao diện hỗ trợ mobile 390px và dark theme chuẩn dự án.
			</footer>
		</div>
	);
}
