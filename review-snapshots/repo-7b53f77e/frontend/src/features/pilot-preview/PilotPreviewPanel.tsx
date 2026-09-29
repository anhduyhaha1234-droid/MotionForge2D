"use client";

import { useEffect, useMemo, useState } from "react";
import {
  pilotAssetUrl,
  pilotMediaUrl,
  readPilotJob,
  resolvePilotContext,
  submitPilotPreview,
  type PilotContext,
  type PilotJob,
} from "@/lib/pilot-preview-api";

const PINNED_SOURCE_PROMPT =
  "Replace only the seated gray-haired source character in the selected shot with the pinned V3 seated identity; preserve the original action, camera, scene, audio, and foreground occluder.";

export function PilotPreviewPanel() {
  const [projectId, setProjectId] = useState("");
  const [generation, setGeneration] = useState("1");
  const [packId, setPackId] = useState("");
  const [cleanPlateId, setCleanPlateId] = useState("");
  const [context, setContext] = useState<PilotContext | null>(null);
  const [startFrame, setStartFrame] = useState(450);
  const [endFrame, setEndFrame] = useState(570);
  const [bbox, setBbox] = useState("0.32,0.26,0.16,0.60");
  const [anchor] = useState("0.4296875,0.7388889");
  const [scale, setScale] = useState("1.00");
  const [prompt, setPrompt] = useState(PINNED_SOURCE_PROMPT);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<PilotJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let active = true;
    const poll = async () => {
      try {
        const next = await readPilotJob(jobId);
        if (!active) return;
        setJob(next);
        if (!["completed", "failed", "cancelled"].includes(next.job.status)) {
          window.setTimeout(poll, 1000);
        }
      } catch (pollError) {
        if (active) setError(pollError instanceof Error ? pollError.message : String(pollError));
      }
    };
    void poll();
    return () => {
      active = false;
    };
  }, [jobId]);

  const parsedBbox = useMemo(() => bbox.split(",").map(Number), [bbox]);
  const parsedAnchor = useMemo(() => anchor.split(",").map(Number), [anchor]);
  const packVerdict = context?.pack_verdict_for_pinned_asset;
  const packCompatible = Boolean(context?.selected_pack_id && packVerdict?.compatible);
  const plateVerdict = context?.clean_plate_verdict;
  const cleanPlateCompatible = Boolean(context?.selected_clean_plate_id && plateVerdict?.compatible);
  const submitReady = packCompatible && cleanPlateCompatible;
  const packApprovalStatus = packVerdict?.pack?.approval_status ?? packVerdict?.approval_status ?? "UNKNOWN";
  const packSemanticStatus = packVerdict?.pack?.semantic_review_status ?? packVerdict?.semantic_review_status ?? "UNKNOWN";
  const plateApprovalStatus = plateVerdict?.approval_status ?? "UNKNOWN";

  function jobStatusLabel(status: string) {
    if (status === "completed") return "render-completed · automated QC passed · needs visual review · not approved";
    if (status === "failed") return "render failed · not approved";
    if (status === "cancelled") return "render cancelled · not approved";
    return `render in progress · ${status}`;
  }

  async function handleContext() {
    setBusy(true);
    setError(null);
    try {
      const next = await resolvePilotContext(projectId.trim(), generation.trim() || "1", packId.trim() || undefined, cleanPlateId.trim() || undefined);
      setContext(next);
      const suggestedStart = next.frame_count >= 570 ? 450 : 0;
      setStartFrame(suggestedStart);
      setEndFrame(Math.min(suggestedStart + 120, next.frame_count));
    } catch (contextError) {
      setError(contextError instanceof Error ? contextError.message : String(contextError));
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmit() {
    if (!context || !submitReady) return;
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      if (parsedBbox.length !== 4 || parsedBbox.some((part) => !Number.isFinite(part))) throw new Error("Mask bbox must be x,y,w,h in normalized coordinates.");
      if (parsedAnchor.length !== 2 || parsedAnchor.some((part) => !Number.isFinite(part))) throw new Error("Anchor must be x,y in normalized coordinates.");
      const submitted = await submitPilotPreview({
        project_id: context.legacy_project_id,
        generation: context.generation,
        start_frame: startFrame,
        end_frame: endFrame,
        role: "seated_character",
        source_prompt: prompt,
        pack_id: context.selected_pack_id,
        clean_plate_id: context.selected_clean_plate_id,
        asset_sha256: context.asset_sha256,
        mask_correction: {
          bbox_xywh_norm: parsedBbox,
          source_frame: startFrame,
          confidence: 0.94,
          note: "operator-corrected seated-character removal region",
        },
        anchor_keyframes: [
          { frame: startFrame, anchor_xy_norm: parsedAnchor, scale: Number(scale), rotation_deg: 0, operator_offset_xy_norm: [0, 0] },
          { frame: endFrame - 1, anchor_xy_norm: parsedAnchor, scale: Number(scale), rotation_deg: 0, operator_offset_xy_norm: [0, 0] },
        ],
        anchor_mode: "source_derived",
        occluder: {
          layer_id: "foreground_right",
          region_xywh_norm: [0.76, 0.34, 0.20, 0.66],
          z: -1,
        },
      });
      setJobId(submitted.job_id);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : String(submitError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-7xl flex-col gap-5 p-4 sm:p-6">
      <section className="rounded-2xl border border-primary-500/30 bg-surface-900 p-5 shadow-panel">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.18em] text-accent-300">MF-DEMO-V3-01</p>
            <h1 className="mt-2 font-display text-3xl font-semibold text-primary">Pilot Preview · V3 seated identity</h1>
            <p className="mt-2 max-w-3xl text-sm text-secondary">One real 3–5 second shot. Fresh public import/analyze context, operator-corrected mask, pinned RGBA asset, durable worker render, and before/after media. Preview-only.</p>
          </div>
          <span className="rounded-full border border-warning/40 bg-warning/10 px-3 py-1 text-xs font-medium text-warning">PREVIEW ONLY · NO FULL APPLY</span>
        </div>
        <div className="mt-5 grid gap-3 md:grid-cols-[1fr_180px_auto]">
          <label className="text-xs text-muted">Legacy or durable project id<input value={projectId} onChange={(event) => setProjectId(event.target.value)} placeholder="paste project id" className="mt-1 w-full rounded-lg border border-surface-700 bg-surface-950 px-3 py-2 text-sm text-primary" /></label>
          <label className="text-xs text-muted">Generation<input value={generation} onChange={(event) => setGeneration(event.target.value)} className="mt-1 w-full rounded-lg border border-surface-700 bg-surface-950 px-3 py-2 text-sm text-primary" /></label>
          <button type="button" onClick={() => void handleContext()} disabled={busy || !projectId.trim()} className="self-end rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50">Resolve source context</button>
        </div>
        <label className="mt-3 block text-xs text-muted">Versioned compatible pack id<input value={packId} onChange={(event) => setPackId(event.target.value)} placeholder="required; V3 is intentionally incompatible" className="mt-1 w-full rounded-lg border border-surface-700 bg-surface-950 px-3 py-2 text-sm text-primary" /></label>
        <label className="mt-3 block text-xs text-muted">Source-bound clean plate candidate id<input value={cleanPlateId} onChange={(event) => setCleanPlateId(event.target.value)} placeholder="required; full-frame candidate or approved plate" className="mt-1 w-full rounded-lg border border-surface-700 bg-surface-950 px-3 py-2 text-sm text-primary" /></label>
        {context && (
          <div className="mt-4 grid gap-3 rounded-xl border border-surface-700 bg-surface-950/60 p-4 text-sm md:grid-cols-4">
            <div><span className="text-muted">Source</span><p className="mt-1 text-primary">{context.source_name}</p></div>
            <div><span className="text-muted">Decoded</span><p className="mt-1 text-primary">{context.width}×{context.height} · {context.fps_num}/{context.fps_den}fps · {context.frame_count}f</p></div>
            <div><span className="text-muted">Chain</span><p className="mt-1 text-primary">{context.chain_status}</p></div>
            <div><span className="text-muted">Durable video</span><p className="mt-1 truncate font-mono text-xs text-primary">{context.durable_video_item_id ?? "not materialized"}</p></div>
            <div className="md:col-span-4"><span className="text-muted">Pack gate</span><p className={packCompatible ? "mt-1 text-success" : "mt-1 text-warning"}>{packCompatible ? `compatible · ${context.selected_pack_id} · approval ${packApprovalStatus} · semantic ${packSemanticStatus}` : `${packVerdict?.reason ?? "missing compatible versioned pack"}${packVerdict?.missing?.length ? ` · missing: ${packVerdict.missing.join(", ")}` : ""}`}</p></div>
            <div className="md:col-span-4"><span className="text-muted">Clean plate gate</span><p className={cleanPlateCompatible ? "mt-1 text-success" : "mt-1 text-warning"}>{cleanPlateCompatible ? `compatible · ${context.selected_clean_plate_id} · approval ${plateApprovalStatus}` : `${plateVerdict?.reason ?? "missing source-bound full-frame clean plate"}${plateVerdict?.missing?.length ? ` · missing: ${plateVerdict.missing.join(", ")}` : ""}`}</p></div>
          </div>
        )}
      </section>

      <section className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-2xl border border-surface-700 bg-surface-900 p-5">
          <div className="flex items-center justify-between"><h2 className="font-display text-xl font-semibold text-primary">Bounded shot contract</h2><span className="text-xs text-muted">90–150 frames</span></div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-muted">Start frame<input type="number" value={startFrame} readOnly className="mt-1 w-full rounded-lg border border-surface-700 bg-surface-950 px-3 py-2 text-sm text-primary" /></label>
            <label className="text-xs text-muted">End frame (exclusive)<input type="number" value={endFrame} readOnly className="mt-1 w-full rounded-lg border border-surface-700 bg-surface-950 px-3 py-2 text-sm text-primary" /></label>
            <label className="text-xs text-muted">Removal bbox · normalized x,y,w,h<input value={bbox} onChange={(event) => setBbox(event.target.value)} className="mt-1 w-full rounded-lg border border-surface-700 bg-surface-950 px-3 py-2 text-sm text-primary" /></label>
            <label className="text-xs text-muted">Measured source seat anchor · normalized x,y<input value={anchor} readOnly className="mt-1 w-full rounded-lg border border-surface-700 bg-surface-950 px-3 py-2 text-sm text-primary" /></label>
            <label className="text-xs text-muted">Asset scale<input value={scale} onChange={(event) => setScale(event.target.value)} className="mt-1 w-full rounded-lg border border-surface-700 bg-surface-950 px-3 py-2 text-sm text-primary" /></label>
          </div>
          <label className="mt-3 block text-xs text-muted">Operator prompt<textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={3} className="mt-1 w-full rounded-lg border border-surface-700 bg-surface-950 px-3 py-2 text-sm text-primary" /></label>
          <div className="mt-4 flex flex-wrap items-center gap-3"><button type="button" onClick={() => void handleSubmit()} disabled={busy || !submitReady} className="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-surface-950 disabled:cursor-not-allowed disabled:opacity-50">Submit durable pilot render</button><span className="text-xs text-muted">Submit requires server-verified pack/plate compatibility; approval status remains visible and separate.</span></div>
          {context && !submitReady && <p className="mt-3 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">Artwork readiness: {packCompatible ? `pack ready (${packApprovalStatus})` : "compatible closed/open pack missing"}; {cleanPlateCompatible ? `clean plate ready (${plateApprovalStatus})` : "full-frame source-bound clean plate missing"}. Submit remains disabled until both gates pass.</p>}
          {error && <p role="alert" className="mt-4 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
        </div>
        <div className="rounded-2xl border border-surface-700 bg-surface-900 p-5"><h2 className="font-display text-xl font-semibold text-primary">Immutable V3 negative sample</h2><div className="mt-4 flex min-h-72 items-center justify-center rounded-xl bg-white p-4"><img src={pilotAssetUrl()} alt="Immutable V3 negative sample; not compatible for this window" className="max-h-80 w-full object-contain" /></div><p className="mt-3 text-xs text-warning">Hands-on-knees/no two-state book coverage · preserved for comparison only.</p>{context && <p className="mt-3 break-all font-mono text-[11px] text-muted">selected asset/pack sha256 · {context.asset_sha256}</p>}</div>
      </section>

      {job && <section className="rounded-2xl border border-surface-700 bg-surface-900 p-5"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="font-mono text-xs text-muted">{job.job.job_id}</p><h2 className="mt-1 font-display text-xl font-semibold text-primary">{jobStatusLabel(job.job.status)}</h2></div><span className="text-sm text-secondary">{Math.round(job.job.progress)}%</span></div><div className="mt-4 h-2 overflow-hidden rounded-full bg-surface-700"><div className="h-full rounded-full bg-accent-400 transition-all" style={{ width: `${Math.max(0, Math.min(100, job.job.progress))}%` }} /></div><p className="mt-2 text-sm text-secondary">{job.job.message || "Durable worker is processing the bounded shot."}</p>{job.job.error && <p className="mt-3 text-sm text-danger">{job.job.error}</p>}{job.media.after && <div className="mt-5 grid gap-4 lg:grid-cols-2"><div><p className="mb-2 text-xs uppercase tracking-wide text-muted">Before · source action/audio</p><video controls src={pilotMediaUrl(job.media.before)} className="w-full rounded-xl border border-surface-700" /></div><div><p className="mb-2 text-xs uppercase tracking-wide text-muted">After · replacement/audio remux</p><video controls src={pilotMediaUrl(job.media.after)} className="w-full rounded-xl border border-accent-500/50" /></div><a href={pilotMediaUrl(job.media.evidence)} className="text-sm text-accent-300 underline">Download per-frame evidence JSON</a></div>}</section>}
    </main>
  );
}
