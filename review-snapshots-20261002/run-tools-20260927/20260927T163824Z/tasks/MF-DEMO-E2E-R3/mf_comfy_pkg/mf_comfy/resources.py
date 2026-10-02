"""Measured resource sampling (VRAM/RAM) for one stage.

nvidia-smi is polled for device memory; psutil for host RSS. Sampling is
best-effort and never changes the run: a sampler failure leaves the measurement
`unmeasured` rather than inventing a number.
"""
from __future__ import annotations

import subprocess
import threading
import time


class ResourceSampler:
    def __init__(self, interval_s: float = 0.5, gpu_index: int = 0) -> None:
        self.interval_s = interval_s
        self.gpu_index = gpu_index
        self.samples: list[dict] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error = ""

    def _gpu_used_mib(self) -> int | None:
        try:
            out = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used",
                    "--format=csv,noheader,nounits",
                    "-i",
                    str(self.gpu_index),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if out.returncode != 0:
                return None
            return int(out.stdout.strip().splitlines()[0])
        except (OSError, ValueError, subprocess.SubprocessError):
            return None

    def _host(self) -> dict:
        try:
            import psutil

            vm = psutil.virtual_memory()
            return {"ram_used_mib": round(vm.used / (1024 * 1024)), "ram_total_mib": round(vm.total / (1024 * 1024))}
        except Exception:  # noqa: BLE001 - measurement is optional
            return {}

    def _loop(self) -> None:
        while not self._stop.is_set():
            sample = {"t": time.time(), "gpu_used_mib": self._gpu_used_mib()}
            sample.update(self._host())
            self.samples.append(sample)
            self._stop.wait(self.interval_s)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="mf-resource-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> dict:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        return self.summary()

    def summary(self) -> dict:
        gpu = [s["gpu_used_mib"] for s in self.samples if s.get("gpu_used_mib") is not None]
        ram = [s["ram_used_mib"] for s in self.samples if s.get("ram_used_mib") is not None]
        totals = [s["ram_total_mib"] for s in self.samples if s.get("ram_total_mib") is not None]
        return {
            "samples": len(self.samples),
            "peak_vram_used_mib": max(gpu) if gpu else None,
            "min_vram_used_mib": min(gpu) if gpu else None,
            "peak_ram_used_mib": max(ram) if ram else None,
            "ram_total_mib": totals[0] if totals else None,
            "measured": bool(gpu or ram),
            "error": self.error,
        }


class NullSampler:
    """Injected in unit tests; reports `unmeasured`, never fabricates numbers."""

    def start(self) -> None:  # noqa: D401
        return None

    def stop(self) -> dict:
        return {"samples": 0, "measured": False, "peak_vram_used_mib": None,
                "peak_ram_used_mib": None, "error": ""}
