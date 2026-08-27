/**
 * S09-T06B-C7 — Windows-compatible backend/frontend launcher helpers.
 *
 * C7 hardening (F1/F2/F3):
 *  - Every instance gets a truly isolated runtime root (own MOTIONFORGE_ROOT,
 *    own SQLite file, own artifact/output directories, own port) with
 *    stdout/stderr captured (never ignore). No kill-by-port path exists.
 *  - stopLaunched is the ONLY teardown — kills exactly the owned PID/handle,
 *    awaits graceful exit with bounded timeout, falls back to exact-PID
 *    SIGKILL only if needed, then FAILS CLOSED if owned PID still alive OR
 *    if the port still has a listener (no silent resolve).
 *  - Frontend launched via explicit node + Next CLI JS (no shell:true), with
 *    retained handle so cleanup can await graceful exit and prove it.
 *  - Added helpers: assertPortFree, listenerOwnerPid, waitForPortListenerOwnedBy,
 *    launchFrontend, nextCliPath.
 *  - All launch helpers use shell:false (spawn without shell word) so C:/ paths
 *    are visible (no WSL translation).
 */

import { spawn, type ChildProcess } from "node:child_process";
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

export interface LaunchedBackend {
  proc: ChildProcess;
  port: number;
  runtimeRoot: string;
  logFile: string;
}

export interface LaunchedFrontend {
  proc: ChildProcess;
  port: number;
  logFile: string;
}

/**
 * Launch ONE isolated production backend instance via deterministic
 * Windows-compatible path (never shell word).
 */
export function launchIsolatedBackend(opts: {
  worktree: string;
  runtimeRoot: string;
  port: number;
  extraEnv?: Record<string, string>;
  corsOrigins?: string;
}): LaunchedBackend {
  const { worktree, runtimeRoot, port, extraEnv, corsOrigins } = opts;

  fs.mkdirSync(runtimeRoot, { recursive: true });
  const logFile = path.join(runtimeRoot, `prod-backend-${port}.log`);
  const logFd = fs.openSync(logFile, "a");

  const env: NodeJS.ProcessEnv = { ...process.env } as NodeJS.ProcessEnv;
  env.PYTHONPATH = worktree;
  env.MOTIONFORGE_ROOT = runtimeRoot;
  env.MOTIONFORGE_OUTPUT = path.join(runtimeRoot, "output");
  env.MOTIONFORGE_MODELS = path.join(runtimeRoot, "models");
  // Fail-closed C3 decision binding: _c3_decision_path checks this override first,
  // otherwise _repo_root (MOTIONFORGE_ROOT) would look at worktree/output/... which
  // is not the isolated runtime's staged decision.
  env.MOTIONFORGE_S09_DECISION_DIR = path.join(runtimeRoot, "frozen-c3");
  env.MOTIONFORGE_CORS_ORIGINS =
    corsOrigins ??
    "http://localhost:3115,http://127.0.0.1:3115,http://localhost:3000";
  env.PYTHONUTF8 = "1";
  delete env.MOTIONFORGE_DATABASE_URL;
  if (extraEnv) {
    for (const [k, v] of Object.entries(extraEnv)) env[k] = v;
  }

  const proc = spawn(
    "python",
    ["-m", "uvicorn", "app.api.app:app", "--port", String(port), "--log-level", "warning"],
    {
      cwd: runtimeRoot,
      env: env as unknown as Record<string, string>,
      stdio: ["ignore", logFd as unknown as NodeJS.WritableStream, logFd as unknown as NodeJS.WritableStream] as unknown as ["ignore", "pipe", "pipe"],
      detached: false,
    } as unknown as Parameters<typeof spawn>[2],
  ) as unknown as ChildProcess;

  try {
    fs.closeSync(logFd);
  } catch {
    /* already closed */
  }

  if (!proc.pid) {
    const tail = safeTail(logFile);
    throw new Error(
      `[t06bc4-helpers] launchIsolatedBackend port=${port} spawn failed (no pid); log tail:\n${tail.slice(-1200)}`,
    );
  }

  return { proc, port, runtimeRoot, logFile };
}

export function nextCliPath(worktree: string): string {
  return path.join(worktree, "frontend/node_modules/next/dist/bin/next");
}

export function launchFrontend(opts: {
  worktree: string;
  port: number;
  backendPort: number;
  logFile: string;
  benchmarkRel?: string;
  benchmarkSha?: string;
}): LaunchedFrontend {
  const { worktree, port, backendPort, logFile, benchmarkRel, benchmarkSha } = opts;
  fs.mkdirSync(path.dirname(logFile), { recursive: true });
  const logFd = fs.openSync(logFile, "a");
  const cli = nextCliPath(worktree);
  if (!fs.existsSync(cli)) {
    throw new Error(`[t06bc4-helpers] Next CLI not found at ${cli}`);
  }
  const env: NodeJS.ProcessEnv = { ...process.env } as NodeJS.ProcessEnv;
  env.NEXT_PUBLIC_API_URL = `http://localhost:${backendPort}`;
  if (benchmarkRel) env.NEXT_PUBLIC_S09_BENCHMARK_RESULTS = benchmarkRel;
  if (benchmarkSha) env.NEXT_PUBLIC_S09_BENCHMARK_CONTENT_SHA256 = benchmarkSha;
  const proc = spawn("node", [cli, "start", "-p", String(port)], {
    cwd: path.join(worktree, "frontend"),
    env: env as unknown as Record<string, string>,
    stdio: ["ignore", logFd as unknown as NodeJS.WritableStream, logFd as unknown as NodeJS.WritableStream] as unknown as ["ignore", "pipe", "pipe"],
    detached: false,
  } as unknown as Parameters<typeof spawn>[2]) as unknown as ChildProcess;
  try {
    fs.closeSync(logFd);
  } catch {
    /* closed */
  }
  if (!proc.pid) {
    const tail = safeTail(logFile);
    throw new Error(`[t06bc4-helpers] launchFrontend port=${port} spawn failed (no pid); log tail:\n${tail.slice(-1200)}`);
  }
  return { proc, port, logFile };
}

export async function waitForBackendReady(
  request: { get: (url: string) => Promise<{ ok(): boolean }> },
  port: number,
  timeoutMs = 45000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastErr = "";
  while (Date.now() < deadline) {
    try {
      const r = await request.get(`http://localhost:${port}/api/v2/projects?active_only=true`);
      if (r.ok()) return;
      lastErr = `HTTP ${String((r as unknown as { status?: number }).status ?? "?")}`;
    } catch (e) {
      lastErr = String(e).slice(0, 300);
    }
    await new Promise<void>((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(
    `[t06bc4-helpers] backend on :${port} not ready within ${timeoutMs}ms; last: ${lastErr}`,
  );
}

export async function waitForFrontendReady(port: number, timeoutMs = 90000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`http://localhost:${port}/demo-compare`);
      if (r.ok || (r.status >= 200 && r.status < 500)) return;
    } catch {
      /* booting */
    }
    await new Promise<void>((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`[t06bc4-helpers] frontend on :${port} not ready within ${timeoutMs}ms`);
}

/**
 * Fail-closed teardown: kill exactly owned PID, await graceful exit,
 * bounded exact-PID SIGKILL only, then assert owned PID exited and
 * the port has no remaining LISTENING listener. Fails closed (throws)
 * if PID or port remains.
 */
export async function stopLaunched(
  launched: LaunchedBackend | LaunchedFrontend | null | undefined,
  opts: { graceMs?: number; killGraceMs?: number } = {},
): Promise<void> {
  if (!launched?.proc?.pid) return;
  const ownedPid = launched.proc.pid;
  const port = (launched as LaunchedBackend).port ?? (launched as LaunchedFrontend).port;
  const graceMs = opts.graceMs ?? 4000;
  const killGraceMs = opts.killGraceMs ?? 3000;

  try {
    launched.proc.kill("SIGTERM");
  } catch {
    /* already gone */
  }

  const exitedGracefully = await waitForExit(launched, graceMs);
  if (!exitedGracefully) {
    try {
      if (launched.proc.exitCode === null && launched.proc.signalCode === null) {
        launched.proc.kill("SIGKILL");
      }
    } catch {
      /* gone */
    }
    const exitedAfterKill = await waitForExit(launched, killGraceMs);
    if (!exitedAfterKill) {
      const stillAlive = isPidAlive(ownedPid);
      if (stillAlive) {
        throw new Error(
          `[t06bc4-helpers] stopLaunched port=${port} owned PID ${ownedPid} did not exit after SIGTERM+SIGKILL (grace ${graceMs}ms + kill ${killGraceMs}ms)`,
        );
      }
    }
  }

  // Fail-closed port release assertion: after owned PID exited, no listener on this port.
  // Poll briefly because the OS may still hold the socket for a short window after exit.
  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    const owner = listenerOwnerPid(port);
    if (owner === null) return;
    // If listener still shows ownedPid (OS lag), re-assert PID gone then keep polling
    if (owner === ownedPid) {
      // PID was shown exited above; give OS a moment to release the port
      await new Promise<void>((resolve) => setTimeout(resolve, 400));
      continue;
    }
    // Port still LISTENING but by a different PID -> fail closed (leaked/so stolen)
    throw new Error(
      `[t06bc4-helpers] stopLaunched port=${port} still LISTENING after owned PID ${ownedPid} exited (current owner PID ${owner})`,
    );
  }
  const finalOwner = listenerOwnerPid(port);
  if (finalOwner !== null) {
    throw new Error(
      `[t06bc4-helpers] stopLaunched port=${port} still LISTENING after timeout (owner PID ${finalOwner}, owned was ${ownedPid})`,
    );
  }
}

export async function stopFrontendLaunched(
  launched: LaunchedFrontend | null | undefined,
  opts: { graceMs?: number; killGraceMs?: number } = {},
): Promise<void> {
  return stopLaunched(launched as unknown as LaunchedBackend, opts);
}

export function isPidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (e: unknown) {
    const code = (e as { code?: string })?.code;
    if (code === "ESRCH") return false;
    if (code === "EPERM") return true;
    return false;
  }
}

export function listenerOwnerPid(port: number): number | null {
  try {
    const out = execSync(`netstat -ano`, { encoding: "utf-8", timeout: 5000 });
    for (const line of out.split("\n")) {
      // Windows netstat -ano: Proto Local Address Foreign Address State PID
      // Look for :<port> ... LISTENING ... <pid>
      if (!line.includes(`:${port} `) && !line.includes(`:${port}\t`)) continue;
      if (!line.includes("LISTENING")) continue;
      const parts = line.trim().split(/\s+/);
      const pidStr = parts[parts.length - 1];
      const pid = Number(pidStr);
      if (Number.isFinite(pid) && pid > 0) return pid;
    }
    return null;
  } catch {
    return null;
  }
}

export async function waitForPortListenerOwnedBy(port: number, expectedPid: number, timeoutMs = 15000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastOwner: number | null = null;
  while (Date.now() < deadline) {
    lastOwner = listenerOwnerPid(port);
    if (lastOwner === expectedPid) return;
    await new Promise<void>((resolve) => setTimeout(resolve, 400));
  }
  throw new Error(
    `[t06bc4-helpers] port ${port} listener owner mismatch: expected PID ${expectedPid}, got ${lastOwner ?? "no listener"} within ${timeoutMs}ms`,
  );
}

export async function assertPortFree(port: number, timeoutMs = 8000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const owner = listenerOwnerPid(port);
    if (owner === null) return;
    await new Promise<void>((resolve) => setTimeout(resolve, 300));
  }
  const owner = listenerOwnerPid(port);
  if (owner !== null) {
    throw new Error(`[t06bc4-helpers] assertPortFree port=${port} still LISTENING (owner PID ${owner})`);
  }
}

function waitForExit(
  launched: LaunchedBackend | LaunchedFrontend,
  timeoutMs: number,
): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    if (launched.proc.exitCode !== null || launched.proc.signalCode !== null) {
      resolve(true);
      return;
    }
    let done = false;
    const onExit = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      resolve(true);
    };
    launched.proc.once("exit", onExit);
    launched.proc.once("close", onExit);
    const timer = setTimeout(() => {
      if (done) return;
      done = true;
      launched.proc.off("exit", onExit);
      launched.proc.off("close", onExit);
      resolve(launched.proc.exitCode !== null || launched.proc.signalCode !== null);
    }, timeoutMs);
  });
}

function safeTail(file: string, maxBytes = 4096): string {
  try {
    const st = fs.statSync(file);
    const start = Math.max(0, st.size - maxBytes);
    const fd = fs.openSync(file, "r");
    const buf = Buffer.alloc(Math.min(maxBytes, st.size));
    fs.readSync(fd, buf, 0, buf.length, start);
    fs.closeSync(fd);
    return buf.toString("utf-8");
  } catch {
    return "(no log)";
  }
}

export const STAGING_CONTRACT = {
  decisionRelpath: "t00-i05-c3/route_decisions_c3_seed20260823.json",
  benchmarkRelpath: "output/s09/20260823_sprint_full/t00-i03-c3/run_A/benchmark_results_seed20260823.json",
} as const;
