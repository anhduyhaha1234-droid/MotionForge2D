"""Independent S12 export output validator (S12-T04A).

Pure output validator over the frozen ``s12-export-v1`` contract
(``docs/contracts/s12-export.md`` §5 ``ValidationContract``, T01 owner).
It consumes the frozen manifest contract read-only — it needs no runner
code, no DB and no publication side effect.

Pipeline (probes follow ``ValidationContract.required_probes`` order):

1. ``completeness`` — file exists, no ``.partial`` suffix, decodes.
2. ``resolution`` — raster WxH vs expected (master 3840x2160).
3. ``codec`` — video codec vs expected (h264/hevc).
4. ``streams`` — stream inventory (video present, audio policy).
5. ``frame_count`` — decoded frame count vs expected (when measurable).
6. ``frame_order`` — presentation-timestamp monotonicity (B-frame safe).
7. ``timebase`` — stream time_base/fps present and sane.
8. ``duration`` — container duration vs expected (A-V policy).
9. ``av_policy`` — audio presence/absence vs expected policy.
10. ``provenance`` — sha256 identity vs manifest hash (never file size).

Verdict vocabulary (frozen): ``PASS | FAIL | NOT_MEASURED``.
Insufficient evidence → FAIL or NOT_MEASURED, never a fake PASS.

The validator never publishes and never touches the DB: :func:`validate`
is a pure function returning a :class:`ValidationVerdict`.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.services.ffmpeg_utils import find_ffprobe

__all__ = [
    "MASTER_WIDTH",
    "MASTER_HEIGHT",
    "PARTIAL_SUFFIX",
    "REQUIRED_PROBES",
    "VERDICTS",
    "ProbeVerdict",
    "ValidationExpectation",
    "ValidationVerdict",
    "sha256_file",
    "validate",
]

#: Frozen master raster (contract §4/§5).
MASTER_WIDTH = 3840
MASTER_HEIGHT = 2160

#: Frozen ``.partial`` suffix — never a completed output (contract §6).
PARTIAL_SUFFIX = ".partial"

#: Probe order consumed from ``ValidationContract.required_probes``.
REQUIRED_PROBES: tuple[str, ...] = (
    "resolution",
    "codec",
    "streams",
    "frame_count",
    "frame_order",
    "timebase",
    "duration",
    "av_policy",
    "provenance",
    "completeness",
)

#: Frozen verdict vocabulary.
VERDICTS: tuple[str, ...] = ("PASS", "FAIL", "NOT_MEASURED")

Verdict = Literal["PASS", "FAIL", "NOT_MEASURED"]

_HASH_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class ProbeVerdict:
    """One named probe outcome inside the validation verdict."""

    name: str
    verdict: Verdict
    detail: str = ""


@dataclass(frozen=True)
class ValidationExpectation:
    """Expected output facts the validator compares the media against.

    All expectations come from the frozen manifest/run contract (T01/T03A
    authorities). ``None`` means "not asserted by the manifest" — the
    corresponding probe then reports NOT_MEASURED instead of guessing.
    """

    width: int = MASTER_WIDTH
    height: int = MASTER_HEIGHT
    codec: str = "h264"
    # Audio policy: "required" (must carry audio), "absent" (must be
    # silent), "either" (manifest does not constrain audio).
    audio_policy: str = "either"
    expected_frame_count: int | None = None
    expected_duration_sec: float | None = None
    # Duration tolerance as a relative fraction (2% default).
    duration_tolerance: float = 0.02
    # Provenance identity: sha256 of the completed output, from the
    # manifest. ``None`` → provenance probe is NOT_MEASURED.
    expected_sha256: str | None = None


@dataclass(frozen=True)
class ValidationVerdict:
    """Pure validator outcome — no publish, no DB write."""

    verdict: Verdict
    probes: tuple[ProbeVerdict, ...] = field(default_factory=tuple)
    output_path: str = ""
    contract_version: str = "s12-export-v1"

    def probe(self, name: str) -> ProbeVerdict | None:
        for item in self.probes:
            if item.name == name:
                return item
        return None


def sha256_file(path: Path, chunk_size: int = _HASH_CHUNK) -> str:
    """Streamed sha256 of ``path`` (lowercase 64-hex, contract §1)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ffprobe_json(path: Path) -> dict | None:
    """Run ffprobe stream+format inventory; None when unmeasurable."""
    try:
        completed = subprocess.run(
            [
                find_ffprobe(),
                "-hide_banner",
                "-v",
                "error",
                "-show_entries",
                (
                    "stream=index,codec_type,codec_name,width,height,"
                    "avg_frame_rate,time_base,duration,nb_frames"
                ),
                "-show_entries",
                "format=duration,nb_streams,size",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _ffprobe_frames(path: Path) -> list[dict] | None:
    """Decode-order frame table; None when the file does not decode."""
    try:
        completed = subprocess.run(
            [
                find_ffprobe(),
                "-hide_banner",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "frame=pts,pkt_dts,pict_type,key_frame",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except (ValueError, TypeError):
        return None
    frames = payload.get("frames") if isinstance(payload, dict) else None
    if not isinstance(frames, list):
        return None
    return [item for item in frames if isinstance(item, dict)]


def _fail(name: str, detail: str) -> ProbeVerdict:
    return ProbeVerdict(name=name, verdict="FAIL", detail=detail)


def _pass(name: str, detail: str) -> ProbeVerdict:
    return ProbeVerdict(name=name, verdict="PASS", detail=detail)


def _unknown(name: str, detail: str) -> ProbeVerdict:
    return ProbeVerdict(name=name, verdict="NOT_MEASURED", detail=detail)


def _aggregate(probes: list[ProbeVerdict]) -> Verdict:
    if any(item.verdict == "FAIL" for item in probes):
        return "FAIL"
    if any(item.verdict == "NOT_MEASURED" for item in probes):
        return "NOT_MEASURED"
    return "PASS"


def _parse_rate(value: object) -> float | None:
    if not isinstance(value, str) or "/" not in value:
        return None
    try:
        num, den = value.split("/", 1)
        rate = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        return None
    if rate <= 0:
        return None
    return rate


def validate(
    output_path: str | Path,
    expectation: ValidationExpectation | None = None,
) -> ValidationVerdict:
    """Validate one completed export output (pure: no publish, no DB).

    ``output_path`` must be the final completed path — a ``.partial``
    path fails ``completeness``. Missing/truncated/corrupt media fails
    (or reports NOT_MEASURED when the evidence is insufficient), never a
    fake PASS.
    """
    exp = expectation or ValidationExpectation()
    path = Path(output_path)
    probes: list[ProbeVerdict] = []

    # --- completeness: existence + suffix + container readability ---------
    if path.suffix == PARTIAL_SUFFIX or path.name.endswith(PARTIAL_SUFFIX):
        probes.append(_fail("completeness", f"partial path rejected: {path.name}"))
        return ValidationVerdict(
            verdict="FAIL", probes=tuple(probes), output_path=str(path)
        )
    if not path.is_file():
        probes.append(_fail("completeness", f"output missing: {path}"))
        return ValidationVerdict(
            verdict="FAIL", probes=tuple(probes), output_path=str(path)
        )

    inventory = _ffprobe_json(path)
    if inventory is None:
        probes.append(_fail("completeness", "ffprobe cannot read container"))
        return ValidationVerdict(
            verdict="FAIL", probes=tuple(probes), output_path=str(path)
        )
    probes.append(_pass("completeness", "container readable, completed suffix"))

    streams = inventory.get("streams")
    if not isinstance(streams, list):
        streams = []
    video = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"]
    audio = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"]

    # --- resolution -------------------------------------------------------
    if not video:
        probes.append(_fail("resolution", "no video stream"))
    else:
        primary = video[0]
        width = primary.get("width")
        height = primary.get("height")
        if width == exp.width and height == exp.height:
            probes.append(_pass("resolution", f"{width}x{height}"))
        elif isinstance(width, int) and isinstance(height, int):
            probes.append(
                _fail(
                    "resolution",
                    f"got {width}x{height}, expected {exp.width}x{exp.height}",
                )
            )
        else:
            probes.append(_unknown("resolution", "width/height unreadable"))

    # --- codec ------------------------------------------------------------
    if not video:
        probes.append(_fail("codec", "no video stream"))
    else:
        codec = str(video[0].get("codec_name") or "")
        if codec == exp.codec:
            probes.append(_pass("codec", codec))
        elif codec:
            probes.append(_fail("codec", f"got {codec}, expected {exp.codec}"))
        else:
            probes.append(_unknown("codec", "codec_name unreadable"))

    # --- streams ----------------------------------------------------------
    if not video:
        probes.append(_fail("streams", "no video stream present"))
    else:
        probes.append(
            _pass(
                "streams",
                f"video=1 audio={len(audio)} total={len(streams)}",
            )
        )

    # --- frame_count / frame_order / timebase (decode layer) --------------
    frames = _ffprobe_frames(path) if video else None
    if not video:
        probes.append(_fail("frame_count", "no video stream"))
        probes.append(_fail("frame_order", "no video stream"))
        probes.append(_fail("timebase", "no video stream"))
    elif frames is None:
        probes.append(_fail("frame_count", "frames do not decode"))
        probes.append(_fail("frame_order", "frames do not decode"))
        probes.append(_fail("timebase", "frames do not decode"))
    else:
        if exp.expected_frame_count is None:
            probes.append(
                _unknown(
                    "frame_count",
                    f"decoded={len(frames)} but manifest asserts no count",
                )
            )
        elif len(frames) == exp.expected_frame_count:
            probes.append(_pass("frame_count", f"{len(frames)} frames"))
        else:
            probes.append(
                _fail(
                    "frame_count",
                    f"decoded={len(frames)}, expected={exp.expected_frame_count}",
                )
            )

        pts_values: list[int] = []
        order_ok = True
        for item in frames:
            try:
                pts_values.append(int(item["pts"]))
            except (KeyError, TypeError, ValueError):
                order_ok = False
                break
        if not pts_values:
            probes.append(_unknown("frame_order", "no presentation timestamps"))
        elif not order_ok:
            probes.append(_fail("frame_order", "unreadable presentation timestamp"))
        elif all(later > earlier for earlier, later in zip(pts_values, pts_values[1:])):
            probes.append(_pass("frame_order", f"{len(pts_values)} pts strictly increasing"))
        else:
            probes.append(_fail("frame_order", "presentation timestamps not monotonic"))

        time_base = video[0].get("time_base")
        fps = _parse_rate(video[0].get("avg_frame_rate"))
        if isinstance(time_base, str) and "/" in time_base and fps is not None:
            probes.append(_pass("timebase", f"time_base={time_base} fps~{fps:.3f}"))
        else:
            probes.append(
                _unknown(
                    "timebase",
                    f"time_base={time_base!r} avg_frame_rate={video[0].get('avg_frame_rate')!r}",
                )
            )

    # --- duration ---------------------------------------------------------
    if exp.expected_duration_sec is None:
        probes.append(_unknown("duration", "manifest asserts no duration"))
    else:
        raw: object = inventory.get("format", {}).get("duration") if isinstance(
            inventory.get("format"), dict
        ) else None
        if raw is None and video:
            raw = video[0].get("duration")
        try:
            measured = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            measured = None
        if measured is None or measured <= 0:
            probes.append(_unknown("duration", "duration unreadable"))
        else:
            tolerance = abs(exp.expected_duration_sec) * exp.duration_tolerance + 0.05
            if abs(measured - exp.expected_duration_sec) <= tolerance:
                probes.append(
                    _pass("duration", f"{measured:.3f}s vs {exp.expected_duration_sec:.3f}s")
                )
            else:
                probes.append(
                    _fail(
                        "duration",
                        f"{measured:.3f}s vs expected {exp.expected_duration_sec:.3f}s",
                    )
                )

    # --- av_policy --------------------------------------------------------
    if exp.audio_policy not in ("required", "absent", "either"):
        probes.append(_fail("av_policy", f"unknown audio_policy={exp.audio_policy!r}"))
    elif exp.audio_policy == "either":
        probes.append(_unknown("av_policy", f"audio streams={len(audio)}, unconstrained"))
    elif exp.audio_policy == "required" and audio:
        probes.append(_pass("av_policy", f"audio present ({audio[0].get('codec_name')})"))
    elif exp.audio_policy == "absent" and not audio:
        probes.append(_pass("av_policy", "no audio stream as required"))
    elif exp.audio_policy == "required":
        probes.append(_fail("av_policy", "audio required but no audio stream"))
    else:
        probes.append(_fail("av_policy", f"audio must be absent, found {len(audio)}"))

    # --- provenance (identity, never file size) ----------------------------
    if exp.expected_sha256 is None:
        probes.append(_unknown("provenance", "manifest asserts no sha256"))
    else:
        try:
            actual = sha256_file(path)
        except OSError as exc:
            probes.append(_fail("provenance", f"unhashable output: {exc}"))
            actual = None
        if actual is not None:
            if actual == exp.expected_sha256:
                probes.append(_pass("provenance", f"sha256={actual[:16]}…"))
            else:
                probes.append(
                    _fail(
                        "provenance",
                        f"sha256 mismatch got={actual[:16]}… expected={exp.expected_sha256[:16]}…",
                    )
                )

    # Order probes per REQUIRED_PROBES for a stable verdict shape.
    order = {name: index for index, name in enumerate(REQUIRED_PROBES)}
    probes.sort(key=lambda item: order.get(item.name, len(order)))
    return ValidationVerdict(
        verdict=_aggregate(probes), probes=tuple(probes), output_path=str(path)
    )
