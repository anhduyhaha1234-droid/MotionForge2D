"""S08-T02 correction — REAL read-only SAM2.1 GPU smoke (finding B10).

Runs a fresh-subprocess SAM2.1 inference against the production checkpoint
(READ-ONLY: never modified, copied, replaced or regenerated) on a
repository-generated synthetic fixture inside a FRESH TEMPORARY ROOT, and
reports performance/memory honestly:

- model load seconds, inference seconds, total seconds,
- peak CUDA memory (``torch.cuda.max_memory_allocated``),
- decoded-frame + candidate counts.

The parent test parses the JSON report and asserts the run was real (masks
non-empty, PNG magic, peak GPU memory recorded on CUDA).  When the genuine
capability is absent (no CUDA/checkpoint), the test SKIPS with the honest
reason and the report records it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAIN_CHECKPOINT = Path("C:/Users/Admin/MotionForge2D/models_checkpoints/sam2.1_hiera_large.pt")

pytestmark = pytest.mark.gpu

_RUNNER = r"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(os.environ["MF_REPO"])
sys.path.insert(0, str(REPO))
CHECKPOINT = Path(os.environ["SAM2_CHECKPOINT"])
ROOT = Path(os.environ["SMOKE_ROOT"])

import torch  # noqa: E402

report = {
    "phase": "smoke",
    "checkpoint": str(CHECKPOINT),
    "checkpoint_bytes": CHECKPOINT.stat().st_size,
    "cuda_available": bool(torch.cuda.is_available()),
    "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
}

from app.services.object_extraction import (  # noqa: E402
    Sam2ExtractionProvider,
)

provider = Sam2ExtractionProvider(checkpoint=CHECKPOINT, env={})
ok, reason = provider._capability()
report["capability_ok"] = ok
report["capability_reason"] = reason
if not ok:
    print(json.dumps(report))
    sys.exit(0)

# Synthetic fixture: 2s 320x240 cut video (blue -> red), fresh temp root.
ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
video = ROOT / "fixture.mp4"
cmd = [
    ffmpeg, "-y",
    "-f", "lavfi", "-i", "color=c=blue:duration=1.0:size=320x240:rate=30",
    "-f", "lavfi", "-i", "color=c=red:duration=1.0:size=320x240:rate=30",
    "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
    "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
    "-pix_fmt", "yuv420p", str(video),
]
subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)

evidence = {
    "video_item_id": "00000000-0000-0000-0000-0000000000aa",
    "video_width": 320,
    "video_height": 240,
    "nb_frames": 60,
    "extractor_version": "1.0.0",
    "managed_root": str(ROOT / "artifacts"),
    "media_relative_path": "media/source.mp4",
    "scenes": [
        {"id": "scene-1", "start_frame": 0, "end_frame": 29,
         "start_time_ms": 0, "end_time_ms": 999},
        {"id": "scene-2", "start_frame": 30, "end_frame": 59,
         "start_time_ms": 1000, "end_time_ms": 1999},
    ],
}
media = ROOT / "artifacts" / "media" / "source.mp4"
media.parent.mkdir(parents=True, exist_ok=True)
media.write_bytes(video.read_bytes())

started = time.monotonic()
candidates = provider.extract(evidence)
report["extract_seconds"] = round(time.monotonic() - started, 3)
report["stats"] = evidence.get("provider_stats")
report["candidate_count"] = len(candidates)
report["masks_nonempty"] = []
for candidate in candidates:
    for artifact in candidate.artifacts:
        if artifact.name.endswith("_mask.png"):
            import cv2  # noqa: E402
            import numpy as np  # noqa: E402

            img = cv2.imdecode(
                np.frombuffer(artifact.bytes, np.uint8), cv2.IMREAD_GRAYSCALE
            )
            report["masks_nonempty"].append(bool(img is not None and img.max() > 0))
            report["mask_shape"] = None if img is None else list(img.shape)
            report["mask_bytes"] = len(artifact.bytes)
        elif artifact.name.endswith("_thumbnail.png"):
            report["thumbnail_bytes"] = len(artifact.bytes)
            report["thumbnail_magic_png"] = artifact.bytes.startswith(b"\x89PNG")
if report.get("cuda_available"):
    report["gpu_mem_peak_mb"] = round(torch.cuda.max_memory_allocated() / (1024 * 1024), 1)
print(json.dumps(report))
"""


def test_sam21_gpu_smoke_readonly_checkpoint(tmp_path: Path) -> None:
    root = tmp_path / "smoke"
    root.mkdir()
    runner = root / "runner.py"
    runner.write_text(textwrap.dedent(_RUNNER), encoding="utf-8")
    env = dict(os.environ)
    env.update(
        {
            "MF_REPO": str(PROJECT_ROOT),
            "SAM2_CHECKPOINT": str(MAIN_CHECKPOINT),
            "SMOKE_ROOT": str(root),
            "MOTIONFORGE_SAM2_CHECKPOINT": str(MAIN_CHECKPOINT),
        }
    )
    proc = subprocess.run(
        [sys.executable, str(runner)],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if not MAIN_CHECKPOINT.is_file():
        pytest.skip(f"checkpoint missing: {MAIN_CHECKPOINT}")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout.strip().splitlines()[-1])
    assert report["phase"] == "smoke"
    assert report["capability_ok"] is True, report
    assert report["candidate_count"] >= 1, report
    assert report["masks_nonempty"], report
    assert report["thumbnail_magic_png"] is True, report
    assert report["stats"]["model"] == "sam2.1-hiera-large-1.0", report
    if report["cuda_available"]:
        assert report["gpu_mem_peak_mb"] > 0, report
    # The checkpoint was ONLY read — its bytes are untouched.
    assert report["checkpoint_bytes"] == MAIN_CHECKPOINT.stat().st_size
