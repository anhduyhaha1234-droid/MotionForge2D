"use client";

/**
 * CompareViewer — renders one loop's original vs rendered result with the
 * five comparison modes (original / result / split / wipe / blink).
 *
 * Both videos are REAL published bytes served by the backend content
 * endpoint (the source fixture is streamed through the same managed-root
 * containment contract).  The wipe mode clips the RESULT layer with a
 * draggable/keyboard-accessible divider; blink alternates visibility on a
 * fixed cadence; split shows them side-by-side.  No canvas, no synthetic
 * frames: two <video> elements kept frame-locked by currentTime sync.
 */
import { useCallback, useEffect, useRef, useState } from "react";

export type CompareMode = "original" | "result" | "split" | "wipe" | "blink";

export const COMPARE_MODES: { value: CompareMode; label: string; helper: string }[] = [
	{ value: "original", label: "Original", helper: "Chỉ xem video gốc chưa chỉnh sửa." },
	{ value: "result", label: "Result", helper: "Chỉ xem video kết quả sau khi render." },
	{ value: "split", label: "Split", helper: "Xem hai video song song để đối chiếu trực tiếp." },
	{ value: "wipe", label: "Wipe", helper: "Kéo vạch chia để so dọc theo khung hình." },
	{ value: "blink", label: "Blink", helper: "Tự động nhấp nháy giữa gốc và kết quả." },
];

interface CompareViewerProps {
	loopId: string;
	/** Managed-root URL of the ORIGINAL fixture media (backend-served). */
	originalUrl: string;
	/** Backend-relative content_url of the RENDERED artifact. */
	resultUrl: string;
	mode: CompareMode;
}

function absolute(url: string): string {
	if (/^https?:\/\//i.test(url)) return url;
	const base = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8888").replace(
		/\/+$/,
		"",
	);
	return url.startsWith("/") ? `${base}${url}` : `${base}/${url}`;
}

export function CompareViewer({ loopId, originalUrl, resultUrl, mode }: CompareViewerProps) {
	const [progress, setProgress] = useState(50);
	const [blinkOn, setBlinkOn] = useState(true);
	const containerRef = useRef<HTMLDivElement | null>(null);
	const draggingRef = useRef(false);
	const origRef = useRef<HTMLVideoElement | null>(null);
	const resultRef = useRef<HTMLVideoElement | null>(null);

	// Blink cadence — only active in blink mode.  The reset to `true` is
	// folded into the interval tick (setState in a callback, not in the
	// effect body) so entering blink mode never triggers a cascading render;
	// the first flip happens after one cadence period.
	useEffect(() => {
		if (mode !== "blink") return;
		const t = setInterval(() => setBlinkOn((b) => !b), 600);
		return () => clearInterval(t);
	}, [mode]);

	// Frame-lock: keep both videos at the same playback position.
	useEffect(() => {
		const orig = origRef.current;
		const result = resultRef.current;
		if (!orig || !result) return;
		const onTime = () => {
			if (Math.abs(orig.currentTime - result.currentTime) > 0.15) {
				result.currentTime = orig.currentTime;
			}
		};
		orig.addEventListener("timeupdate", onTime);
		return () => orig.removeEventListener("timeupdate", onTime);
	}, []);

	const updateFromClientX = useCallback((clientX: number) => {
		const el = containerRef.current;
		if (!el) return;
		const rect = el.getBoundingClientRect();
		const pct = ((clientX - rect.left) / rect.width) * 100;
		setProgress(Math.min(100, Math.max(0, pct)));
	}, []);

	useEffect(() => {
		const move = (e: MouseEvent) => {
			if (draggingRef.current) updateFromClientX(e.clientX);
		};
		const up = () => {
			draggingRef.current = false;
		};
		window.addEventListener("mousemove", move);
		window.addEventListener("mouseup", up);
		return () => {
			window.removeEventListener("mousemove", move);
			window.removeEventListener("mouseup", up);
		};
	}, [updateFromClientX]);

	const showOriginalOnly = mode === "original" || (mode === "blink" && blinkOn);
	const showResultOnly = mode === "result" || (mode === "blink" && !blinkOn);

	return (
		<div className="flex flex-col gap-2" data-testid={`compare-viewer-${loopId}`}>
			{mode === "split" ? (
				<div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
					<figure className="overflow-hidden rounded border border-gray-700 bg-black">
						<video
							ref={origRef}
							src={absolute(originalUrl)}
							controls
							muted
							loop
							className="w-full"
							data-testid={`video-original-${loopId}`}
						/>
						<figcaption className="p-1 text-[11px] text-gray-400">Gốc — video nguồn chưa thay thế.</figcaption>
					</figure>
					<figure className="overflow-hidden rounded border border-gray-700 bg-black">
						<video
							ref={resultRef}
							src={absolute(resultUrl)}
							controls
							muted
							loop
							className="w-full"
							data-testid={`video-result-${loopId}`}
						/>
						<figcaption className="p-1 text-[11px] text-gray-400">Kết quả — video đã render thay thế.</figcaption>
					</figure>
				</div>
			) : (
				<div className="flex flex-col gap-1">
					<div
						ref={containerRef}
						className="relative overflow-hidden rounded border border-gray-700 bg-black"
						data-testid={`compare-stage-${loopId}`}
					>
						<video
							ref={origRef}
							src={absolute(originalUrl)}
							controls={showOriginalOnly || mode === "wipe"}
							muted
							loop
							autoPlay={false}
							className="w-full"
							style={{ visibility: showResultOnly ? "hidden" : undefined }}
							data-testid={`video-original-${loopId}`}
						/>
						{mode === "wipe" ? (
							<div
								className="pointer-events-none absolute inset-y-0 right-0 overflow-hidden"
								style={{ width: `${100 - progress}%` }}
							>
								<video
									ref={resultRef}
									src={absolute(resultUrl)}
									muted
									loop
									className="h-full w-full object-cover"
									data-testid={`video-result-${loopId}`}
								/>
							</div>
						) : (
							<video
								ref={resultRef}
								src={absolute(resultUrl)}
								controls={showResultOnly}
								muted
								loop
								className="absolute inset-0 h-full w-full"
								style={{ visibility: showOriginalOnly ? "hidden" : undefined }}
								data-testid={`video-result-${loopId}`}
							/>
						)}
						{mode === "wipe" && (
							<div
								className="absolute inset-y-0 z-10 w-6 -translate-x-1/2 cursor-ew-resize"
								style={{ left: `${progress}%` }}
								role="slider"
								tabIndex={0}
								aria-label="Vạch chia so sánh wipe"
								aria-valuemin={0}
								aria-valuemax={100}
								aria-valuenow={Math.round(progress)}
								onMouseDown={(e) => {
									draggingRef.current = true;
									e.preventDefault();
								}}
								onTouchStart={() => {
									draggingRef.current = true;
								}}
								onTouchMove={(e) => {
									if (draggingRef.current) updateFromClientX(e.touches[0].clientX);
								}}
								onTouchEnd={() => {
									draggingRef.current = false;
								}}
								onKeyDown={(e) => {
									if (e.key === "ArrowLeft") setProgress((p) => Math.max(0, p - 5));
									if (e.key === "ArrowRight") setProgress((p) => Math.min(100, p + 5));
								}}
								data-testid={`wipe-handle-${loopId}`}
							>
								<div className="mx-auto h-full w-0.5 bg-indigo-400" />
							</div>
						)}
					</div>
					<p className="text-[11px] text-gray-400" data-testid={`viewer-mode-note-${loopId}`}>
						{mode === "wipe"
							? `Đang ở chế độ Wipe — vạch chia tại ${Math.round(progress)}%. Dùng chuột hoặc phím mũi tên.`
							: mode === "blink"
								? "Đang ở chế độ Blink — video tự chuyển giữa gốc/kết quả mỗi 0.6 giây."
								: mode === "result"
									? "Chế độ Result — chỉ phát video kết quả."
									: mode === "original"
										? "Chế độ Original — chỉ phát video gốc."
										: "Chế độ Split — hai phát độc lập, tua riêng từng video."}
					</p>
				</div>
			)}
		</div>
	);
}
