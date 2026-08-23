/**
 * S08-H01 shared E2E helpers — backend lifecycle + honest suite setup.
 *
 * The API failure tests exercise a REAL error path: the spec kills the real
 * QA backend (identity-verified taskkill on the run-qa-backend.sh tree bound
 * to port 8026) so the browser gets a genuine connection-refused, then
 * restarts it and proves the retry button recovers. No page.route()
 * interception, no mocks.
 */

import { execSync, spawn } from "child_process";
import path from "path";
import {
  API,
  apiJson,
  setupProjectWithVideo,
  uploadVideo,
  postAnalyze,
  waitChainCompleted,
  runExtraction,
  VIDEO_PATH,
  VIDEO_PATH_2,
} from "./s08-t04-helpers";

export const RUN_ID = "20260817-s08h01-r1";
export const RUN_ROOT = path.resolve(__dirname, "../../output/s08-sprint", RUN_ID);
export const BACKEND_SH = path.join(RUN_ROOT, "run-qa-backend.sh");
export const SHOT_DIR = path.join(RUN_ROOT, "screenshots");

export interface Suite {
  legacy: { projectId: string; videoA: string; videoB: string };
  durable: { projectId: string; videoA: string; videoB: string; name: string };
}

async function waitHealth(timeoutMs = 180_000): Promise<void> {
  const start = Date.now();
  for (;;) {
    try {
      const res = await fetch(`${API}/health`);
      if (res.ok) return;
    } catch {
      /* keep waiting for the real server */
    }
    if (Date.now() - start > timeoutMs) {
      throw new Error(`QA backend not healthy after ${timeoutMs}ms`);
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
}

/**
 * Locate the QA backend that owns port 8026 — identity-verified via the
 * CommandLine (uvicorn + port + this worktree) so we NEVER kill an unrelated
 * process that happens to listen on the port.
 */
function findBackendPid(): number | null {
  try {
    const out = execSync('netstat -ano | findstr ":8026" | findstr "LISTENING"', {
      encoding: "utf8",
    });
    for (const line of out.trim().split(/\r?\n/)) {
      const parts = line.trim().split(/\s+/);
      const pid = Number(parts[parts.length - 1]);
      if (!Number.isFinite(pid) || pid <= 0) continue;
      try {
        const cl = execSync(`wmic process where "ProcessId=${pid}" get CommandLine /value`, {
          encoding: "utf8",
        });
        if (cl.includes("uvicorn") && cl.includes("8026") && cl.includes("s08-integration")) {
          return pid;
        }
      } catch {
        /* try next listener on the port */
      }
    }
    return null;
  } catch {
    return null;
  }
}

export async function startBackend(): Promise<void> {
  // Reuse an already-healthy QA backend on the port (leftover from a previous
  // run or another worker) instead of double-binding.
  try {
    await waitHealth(8_000);
    return;
  } catch {
    /* not up — spawn below */
  }
  spawn("bash", [BACKEND_SH], { detached: true, stdio: "ignore" });
  await waitHealth();
}

/** Kill the QA backend on port 8026 by verified identity (works across workers). */
export function killBackend(): void {
  const pid = findBackendPid();
  if (pid !== null) {
    try {
      // cmd.exe (Node's default shell on win32) — no MSYS path mangling here.
      execSync(`taskkill /PID ${pid} /T /F`, { stdio: "ignore" });
    } catch {
      /* already gone */
    }
  }
}

export async function ensureBackendUp(): Promise<void> {
  try {
    await waitHealth(5_000);
  } catch {
    await startBackend();
  }
}

/**
 * Build a fresh isolated suite on the REAL QA backend:
 *  - legacy multi-video project (video A = 4-scene, source-replace → video B)
 *    with BOTH extractions terminal (real course data for the gallery),
 *  - durable v2 project with two real video items (backed by S03 API rows).
 */
export async function setupSuite(): Promise<Suite> {
  const fs = await import("fs");
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  await startBackend();

  const proj = await setupProjectWithVideo("h01-multivideo", VIDEO_PATH);
  await runExtraction(proj.projectId, proj.videoItemId, proj.sourceSha);
  const videoA = proj.videoItemId;
  await uploadVideo(proj.projectId, VIDEO_PATH_2);
  await postAnalyze(proj.projectId);
  const chain = await waitChainCompleted(proj.projectId);
  const videoB = chain.video_item_id!;
  await runExtraction(proj.projectId, videoB, chain.source_sha256 as string);

  const durableName = `h01-durable ${Date.now().toString(36)}`;
  const created = (await apiJson("/api/v2/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: durableName }),
  })) as { project_id: string };
  const v1 = (await apiJson(`/api/v2/projects/${created.project_id}/videos`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "H01 video 1.mp4" }),
  })) as { video_item_id: string };
  const v2 = (await apiJson(`/api/v2/projects/${created.project_id}/videos`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "H01 video 2.mp4" }),
  })) as { video_item_id: string };

  return {
    legacy: { projectId: proj.projectId, videoA, videoB },
    durable: {
      projectId: created.project_id,
      videoA: v1.video_item_id,
      videoB: v2.video_item_id,
      name: durableName,
    },
  };
}
