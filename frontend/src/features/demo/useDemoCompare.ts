"use client";

/**
 * useDemoCompare — orchestration hook for the demo comparison flow.
 *
 * Owns the full lifecycle: load capabilities + loops from the REAL API,
 * submit the demo-loop batch (idempotent), poll the durable job until a
 * terminal state, then expose published artifacts for the viewer.  Every
 * state transition is driven by backend responses; there is NO mock data
 * and no optimistic fabrication: loading/error/empty states render what
 * the server actually said.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
	ApiError,
	getDemoCompareStatus,
	getDemoCapabilities,
	listDemoLoops,
	submitDemoCompareJob,
	type CapabilitiesResponse,
	type JobStatus,
	type LoopInfo,
} from "./index";

export type Phase =
	| "idle"
	| "loading-meta"
	| "ready"
	| "submitting"
	| "running"
	| "completed"
	| "failed"
	| "error";

export interface DemoCompareState {
	phase: Phase;
	errorText: string | null;
	capabilities: CapabilitiesResponse | null;
	loops: LoopInfo[];
	jobId: string | null;
	jobStatus: JobStatus | null;
}

const TERMINAL_STATES = new Set(["completed", "failed", "cancelled"]);

/**
 * Default fixture location relative to the backend project root.
 *
 * S09-T04-C2 FINAL binding: the benchmark evidence path AND its exact
 * content SHA have NO default here.  The frozen I05-C2 decision identity
 * must arrive via NEXT_PUBLIC_S09_BENCHMARK_RESULTS +
 * NEXT_PUBLIC_S09_BENCHMARK_CONTENT_SHA256; without BOTH the panel renders
 * a configuration error instead of silently reading stale evidence.
 */
export const DEFAULT_FIXTURES_DIR = "tests/fixtures/s09_demo";

/** Read the explicitly configured benchmark evidence from the environment. */
function configuredBenchmark(): { path: string; sha256: string } {
	const path = process.env.NEXT_PUBLIC_S09_BENCHMARK_RESULTS;
	const sha256 = process.env.NEXT_PUBLIC_S09_BENCHMARK_CONTENT_SHA256;
	if (!path || !sha256) {
		throw new Error(
			"Cấu hình bằng chứng benchmark bị thiếu: đặt NEXT_PUBLIC_S09_BENCHMARK_RESULTS " +
				"và NEXT_PUBLIC_S09_BENCHMARK_CONTENT_SHA256 (SHA-256 của đúng file đó) — " +
				"S09-T04-C2 cấm fallback ngầm tới artifact cũ hoặc đoán SHA.",
		);
	}
	if (!/^[0-9a-f]{64}$/.test(sha256)) {
		throw new Error(
			"NEXT_PUBLIC_S09_BENCHMARK_CONTENT_SHA256 phải là SHA-256 hex64 của file benchmark " +
				`(nhận được: ${sha256.slice(0, 16)}…).`,
		);
	}
	return { path, sha256 };
}

export interface DemoCompareConfig {
	/** Backend-relative path of the frozen benchmark results document. */
	benchmarkResults: string;
	/** Pinned file-content SHA-256 (REQUIRED — mismatch → fail closed). */
	expectContentSha256: string;
	fixturesDir: string;
}

export function resolveDemoCompareConfig(
	fixturesDir?: string,
	benchmarkResults?: string,
): DemoCompareConfig {
	const env = configuredBenchmark();
	return {
		benchmarkResults: benchmarkResults ?? env.path,
		expectContentSha256: env.sha256,
		fixturesDir: fixturesDir ?? DEFAULT_FIXTURES_DIR,
	};
}

export function useDemoCompare(config: DemoCompareConfig) {
	const { fixturesDir, benchmarkResults, expectContentSha256 } = config;
	const [state, setState] = useState<DemoCompareState>({
		phase: "loading-meta",
		errorText: null,
		capabilities: null,
		loops: [],
		jobId: null,
		jobStatus: null,
	});
	const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

	const stopPolling = useCallback(() => {
		if (pollRef.current !== null) {
			clearInterval(pollRef.current);
			pollRef.current = null;
		}
	}, []);

	useEffect(() => stopPolling, [stopPolling]);

	const refreshMeta = useCallback(async () => {
		setState((s) => ({ ...s, phase: "loading-meta", errorText: null }));
		try {
			const [capabilities, loopList] = await Promise.all([
				getDemoCapabilities(benchmarkResults, expectContentSha256),
				listDemoLoops(fixturesDir, benchmarkResults, expectContentSha256),
			]);
			setState((s) => ({
				...s,
				phase: "ready",
				capabilities,
				loops: loopList.loops,
			}));
		} catch (err) {
			setState((s) => ({
				...s,
				phase: "error",
				errorText:
					err instanceof ApiError
						? err.detailText() || err.message
						: String(err),
			}));
		}
	}, [fixturesDir, benchmarkResults, expectContentSha256]);

	useEffect(() => {
		void refreshMeta();
	}, [refreshMeta]);

	const startPolling = useCallback(
		(jobId: string) => {
			stopPolling();
			pollRef.current = setInterval(async () => {
				try {
					const st = await getDemoCompareStatus(jobId);
					setState((s) => ({
						...s,
						jobStatus: st,
						phase: TERMINAL_STATES.has(st.state)
							? st.state === "completed"
								? "completed"
								: "failed"
							: "running",
						errorText:
							st.state === "failed"
								? (st.error?.message ?? "Job thất bại không rõ nguyên nhân")
								: null,
					}));
					if (TERMINAL_STATES.has(st.state)) stopPolling();
				} catch (err) {
					stopPolling();
					setState((s) => ({
						...s,
						phase: "error",
						errorText:
							err instanceof ApiError
								? `API ${err.status}: ${err.detailText()}`
								: String(err),
					}));
				}
			}, 1500);
		},
		[stopPolling],
	);

	const runComparison = useCallback(async () => {
		setState((s) => ({ ...s, phase: "submitting", errorText: null }));
		try {
			const res = await submitDemoCompareJob({
				requested_loops: state.loops.map((lp) => lp.loop_id),
				benchmark_results: benchmarkResults,
				fixtures_dir: fixturesDir,
				expect_content_sha256: expectContentSha256,
			});
			setState((s) => ({
				...s,
				phase: "running",
				jobId: res.job_id,
				jobStatus: null,
			}));
			startPolling(res.job_id);
		} catch (err) {
			setState((s) => ({
				...s,
				phase: "error",
				errorText:
					err instanceof ApiError
						? `API ${err.status}: ${err.detailText()}`
						: String(err),
			}));
		}
	},
	[state.loops, benchmarkResults, fixturesDir, expectContentSha256, startPolling]);

/**
 * S09-C3-PREP (T05B): adopt an EXTERNALLY created durable job (e.g. the
 * targeted-regeneration job opened by CorrectionPanel) and poll it exactly
 * like a job this hook submitted itself.  The viewer then re-renders from
 * the regeneration's published artifacts — no full-video rerun anywhere.
 */
const trackExternalJob = useCallback(
	(jobId: string) => {
		setState((s) => ({
			...s,
			jobId,
			jobStatus: null,
			phase: "running",
			errorText: null,
		}));
		startPolling(jobId);
	},
	[startPolling],
);

	return { ...state, refreshMeta, runComparison, trackExternalJob };
}
