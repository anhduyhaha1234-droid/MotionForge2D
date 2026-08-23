"""Global configuration for MotionForge 2D backend."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: The protected production MAIN root (C:\\Users\\<user>\\MotionForge2D).
#: QA/test processes must NEVER resolve project/managed roots to (or under)
#: this tree — it holds user data (channels.json, data/motionforge.db, the
#: SAM2.1 checkpoint).  Production (non-QA) runs on MAIN are legitimate.
PROTECTED_MAIN_ROOT: Path = Path.home() / "MotionForge2D"

#: Env values that switch a process into QA mode (explicit isolated roots
#: required; the protected MAIN root is rejected).
_QA_MODE_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

#: Env var that switches a process into QA mode.
QA_MODE_ENV = "MOTIONFORGE_QA_MODE"


def _env_flag(name: str) -> bool:
    """Read a boolean-ish environment flag (empty/unset = False)."""
    return os.environ.get(name, "").strip().lower() in _QA_MODE_TRUE_VALUES


def qa_mode_enabled() -> bool:
    """True when the process explicitly declares QA mode (env flag)."""
    return _env_flag(QA_MODE_ENV)


def test_mode_enabled() -> bool:
    """True when the process runs inside pytest (PYTEST_CURRENT_TEST set)."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def runtime_qa_or_test_mode() -> bool:
    """True in any QA/test process — the fail-closed guard is active.

    A process is QA/test when it explicitly declares QA mode OR runs under
    pytest.  In such a process the effective project/managed roots must be
    explicit, absolute and isolated from the protected MAIN root.
    """
    return qa_mode_enabled() or test_mode_enabled()


class UnsafeRuntimeRootError(RuntimeError):
    """The effective runtime root violates the QA/test fail-closed policy."""


def validate_runtime_roots(
    project_root: str | Path | None,
    managed_root: str | Path | None,
    *,
    require_env_project_root: bool = False,
    mode_on: bool | None = None,
) -> None:
    """Fail closed on unsafe runtime roots in QA/test mode (S08-R01 AC6).

    Active only when *mode_on* is true (default: the live
    ``runtime_qa_or_test_mode()``).  When active:

    - ``project_root``, when provided (None = the caller owns the database
      target and only the managed root is guarded), must be absolute, and
      NOT the protected MAIN root (nor inside it);
    - ``managed_root`` must be provided, absolute, and NOT the protected
      MAIN root (nor inside it) — a CWD-relative managed root is the exact
      defect that let QA runs write ``uploads``/``staging`` into the
      worktree root;
    - when *require_env_project_root* is true (explicit QA mode), the
      project root must come from an explicit ``MOTIONFORGE_ROOT`` env var
      (launchers may not rely on defaults or ``cd``).

    Raises :class:`UnsafeRuntimeRootError` with a stable, specific message.
    Production processes (mode off) are never affected.
    """
    if mode_on is None:
        mode_on = runtime_qa_or_test_mode()
    if not mode_on:
        return

    problems: list[str] = []
    main = PROTECTED_MAIN_ROOT.resolve()
    if require_env_project_root:
        env_root = os.environ.get("MOTIONFORGE_ROOT", "").strip()
        if not env_root:
            problems.append(
                "QA mode requires an explicit absolute MOTIONFORGE_ROOT "
                "environment variable (never the default or the CWD)"
            )
        elif not Path(env_root).is_absolute():
            problems.append(
                f"MOTIONFORGE_ROOT {env_root!r} is relative; QA mode "
                "requires an explicit absolute root"
            )
    if project_root is not None:
        proj = Path(project_root)
        if not proj.is_absolute():
            problems.append(
                f"project root {proj} is not absolute; QA/test mode "
                "requires an explicit absolute project root"
            )
        else:
            resolved = proj.resolve()
            if resolved == main or resolved.is_relative_to(main):
                problems.append(
                    f"project root {proj} is the protected MAIN tree "
                    f"({main}); QA/test mode must use an isolated root"
                )
    if managed_root is None or str(managed_root).strip() == "":
        problems.append("managed artifact root is not set; QA/test mode "
                        "requires an explicit absolute managed root")
    else:
        managed = Path(managed_root)
        if not managed.is_absolute():
            problems.append(
                f"managed artifact root {managed} is not absolute "
                "(CWD-relative roots are forbidden in QA/test mode)"
            )
        else:
            resolved = managed.resolve()
            if resolved == main or resolved.is_relative_to(main):
                problems.append(
                    f"managed artifact root {managed} is the protected "
                    f"MAIN tree ({main}); QA/test mode must use an "
                    "isolated root"
                )
    if problems:
        raise UnsafeRuntimeRootError(
            "unsafe runtime roots in QA/test mode: " + "; ".join(problems)
        )


@dataclass(frozen=True)
class AppConfig:
    """Application configuration loaded from environment or defaults."""

    # Paths
    project_root: Path = field(default_factory=lambda: Path(os.environ.get(
        "MOTIONFORGE_ROOT", str(Path.home() / "MotionForge2D")
    )))
    models_dir: Path = field(default_factory=lambda: Path(os.environ.get(
        "MOTIONFORGE_MODELS", str(Path.home() / "MotionForge2D" / "models_checkpoints")
    )))
    output_dir: Path = field(default_factory=lambda: Path(os.environ.get(
        "MOTIONFORGE_OUTPUT", str(Path.home() / "MotionForge2D" / "output")
    )))
    #: QA mode (S08-R01 AC6): explicit isolated roots required and the
    #: protected MAIN root rejected when enabled.
    qa_mode: bool = field(default_factory=lambda: qa_mode_enabled())

    # SAM 2.1
    sam2_model_cfg: str = "configs/sam2.1/sam2.1_hiera_l.yaml"
    sam2_checkpoint: str = ""  # Set after download

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # CORS / cross-origin allowlist (S08-H02).  Comma-separated
    # ``MOTIONFORGE_CORS_ORIGINS``; defaults are the REAL local frontend
    # origins (Next dev proxy target + direct-browser fetch).  Never "*".
    # The API is a local app that does NOT use cookie credentials, so
    # ``cors_allow_credentials`` stays False unless explicitly enabled.
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        o.strip()
        for o in os.environ.get(
            "MOTIONFORGE_CORS_ORIGINS",
            "http://localhost:8888,http://127.0.0.1:8888,"
            "http://localhost:3000,http://127.0.0.1:3000,"
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if o.strip()
    ))
    #: True only when the product actually authenticates with cookie
    #: credentials (today it does not — JWT-free local app).
    cors_allow_credentials: bool = field(default_factory=lambda: _env_flag(
        "MOTIONFORGE_CORS_ALLOW_CREDENTIALS"
    ))

    # Upload limits (S08-H02): hard byte ceilings enforced while a request
    # body streams to disk — an over-limit body is rejected and its staging
    # partial removed.
    max_upload_bytes: int = field(default_factory=lambda: int(os.environ.get(
        "MOTIONFORGE_MAX_UPLOAD_BYTES", str(2 * 1024 ** 3)
    )))
    #: Replacement-image uploads are far smaller; images beyond this are 413.
    max_image_upload_bytes: int = field(default_factory=lambda: int(os.environ.get(
        "MOTIONFORGE_MAX_IMAGE_UPLOAD_BYTES", str(64 * 1024 ** 2)
    )))

    # Media decode limits (S08-H02): a content probe/decoder must never be
    # able to allocate unbounded output.  ``max_image_dimension`` bounds the
    # largest pixel side accepted from uploaded image media; ``max_image_pixels``
    # bounds the total pixel count (upright), an independent memory ceiling;
    # the requested output dimension of any on-demand frame decode is capped
    # the same way.  ``max_video_duration_seconds`` bounds an uploaded source
    # video's probe duration.
    max_image_dimension: int = field(default_factory=lambda: int(os.environ.get(
        "MOTIONFORGE_MAX_IMAGE_DIMENSION", "16384"
    )))
    max_image_pixels: int = field(default_factory=lambda: int(os.environ.get(
        "MOTIONFORGE_MAX_IMAGE_PIXELS", "40000000"
    )))
    max_video_duration_seconds: float = field(default_factory=lambda: float(os.environ.get(
        "MOTIONFORGE_MAX_VIDEO_DURATION_SECONDS", "21600.0"
    )))
    #: Timeout for ffmpeg/ffprobe-based media decodes (seconds).
    decode_timeout_seconds: int = field(default_factory=lambda: int(os.environ.get(
        "MOTIONFORGE_DECODE_TIMEOUT_SECONDS", "60"
    )))

    # Processing
    max_frames_per_scene: int = 1000
    mask_propagation_batch: int = 8

    def __post_init__(self) -> None:
        if not self.sam2_checkpoint:
            object.__setattr__(
                self,
                "sam2_checkpoint",
                str(self.models_dir / "sam2.1_hiera_large.pt"),
            )

    def ensure_dirs(self) -> None:
        """Create output and model directories if they don't exist."""
        for subdir in ["scenes", "frames", "masks", "renders", "debug", "audio"]:
            (self.output_dir / subdir).mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)


# Singleton config
config = AppConfig()
