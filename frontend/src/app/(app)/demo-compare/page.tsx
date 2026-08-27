"use client";

/**
 * Demo comparison route (S09-T04) — /demo-compare
 *
 * Thin route wrapper: mounts the demo comparison panel inside the app
 * shell.  All data flows from the backend comparison API; the page itself
 * holds no state and renders no fabricated numbers.
 */

import { DemoComparePanel } from "@/features/demo/DemoComparePanel";

export default function DemoComparePage() {
  return (
    <div className="min-h-full p-4 sm:p-6">
      <DemoComparePanel />
    </div>
  );
}
