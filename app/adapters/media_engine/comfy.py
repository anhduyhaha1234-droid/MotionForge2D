"""App-side Comfy shot-engine adapter — the ``mf_comfy`` dependency, packaged (MF-END-18).

This module is the ONLY app-side door to the ComfyUI stage adapter.  It does not
re-implement a queue, a lease, a submission authority or a graph runner: it
composes the FROZEN ``mf_comfy`` package that MF-V1-COMFY shipped at commit
``70f718098f00f9dbdeb6cc9c5d7808b243eb0c57`` (R28 MATRIX: 13/13 rows, 269/269
checks; negative control PRE_FIX_BEHAVIOUR_CONFIRMED) and it composes the FROZEN
shot contract ``app.schemas.shot_reskin`` (MF-END-01) for every input/output it
hands over.  Nothing here is a second engine: there is exactly ONE heavy-GPU
stage gate, ONE instance lease directory, ONE durable prompt-reservation ledger
and ONE instance epoch per managed root — the package's own files on disk.

Dependency resolution (micro-job MF-END-18.2)
---------------------------------------------
The package is never imported from a developer worktree and this module never
touches ``sys.path``.  ``scripts/build_mf_comfy_dependency.py`` builds a wheel
from the git OBJECT STORE at the pinned commit, verifies every module byte
against the manifest below, stamps an in-package provenance record, and installs
it (explicit target directory or the active environment).  At runtime this module
verifies, on every engine load:

1. the package is importable through the normal import system;
2. it carries ``mf_comfy/_mf_provenance.json`` with the expected schema;
3. its ``source_commit`` equals :data:`MF_COMFY_SOURCE_COMMIT_PIN`;
4. every pinned module file exists with the pinned sha256 and NO extra ``*.py``;
5. the provenance manifest agrees with :data:`MF_COMFY_MODULE_FILES`.

Any failure refuses with a typed :class:`ComfyEngineRefusalCode` — the engine is
never "best effort".  ``engine_status()`` reports the same decision without
raising, so a caller can render a reason instead of crashing.

Authority layout inside the app managed root (micro-job MF-END-18.3)
---------------------------------------------------------------------
``<managed_root>/media_engine/comfy_shot_engine/``

* ``stage/``          artifact staging (``StagePaths`` scoping: artifacts are
                      re-materialised, hashed and decoded inside this root);
* ``state/instance_epoch.json``  boot identity of the local ComfyUI launch,
                      written by the launcher (``serve_comfy``); absent ⇒ the
                      engine refuses (``epoch_missing``) — no submit under an
                      unknown boot identity;
* ``state/reservations/``        durable submit authority (``PromptReservations``);
* ``state/leases/``              exclusive instance lease (``InstanceLease``),
                      which authorises ``/interrupt`` and nothing else;
* ``state/gpu_stage.lock``       machine-wide one-heavy-stage gate (``GpuStageGate``).

One adapter INSTANCE is minted per attempt (the package allows exactly one POST
per adapter lifetime, by design); all attempts of one engine share the SAME
gate, lease directory, reservation ledger, epoch and transport object — that is
what "one GPU lease and one durable submit authority" means here.

Integration contract (micro-job MF-END-18.4)
--------------------------------------------
* **error** — engine terminal faults come back as a ``ShotExecutionRecord`` with
  ``outcome="failed"`` and ``ShotEngineError.code`` = the engine's typed code
  (OOM / execution error / interrupted / artifact missing / partial output /
  invalid graph).  Boundary faults are raised as :class:`ComfyEngineRefusal`:
  capability missing (missing node class / model option), pin mismatch (workflow
  / node-inventory / model / artifact hash), ambiguous after submit (timeout
  with no queue/history/epoch proof — the attempt stays unresolved, the durable
  reservation is kept, and a second POST is never sent).
* **replay** — :meth:`ComfyShotEngine.replay` (and any re-invocation of
  :meth:`run_shot` with the same declared identity) reuses the durable completion
  receipt: no gate, no lease, no second POST; the returned record is rebuilt from
  the receipt's re-hashed artifacts.
* **cancel** — :meth:`ComfyShotEngine.cancel` is lease-gated inside the package:
  a prompt this attempt does not provably own raises ``lease_not_held`` and
  makes NO HTTP call.
* **foreign identity** — a durable record belonging to another work item is
  never adopted, never released and never becomes this attempt's output; the
  engine refuses typed (``reservation_mismatch`` / ``reservation_conflict`` /
  ``attempt_already_terminal``) and this wrapper surfaces it as
  ``foreign_identity_refused``.

Record mapping policy (disclosed): ``EngineOutputBinding.decoded`` is derived
from the shot's declared output contract (``frame_count`` / output stream
timebase, ``first_pts_ticks=0``) unless the caller passes measured
``decoded_facts``; ``vram_peak_mib`` is the sampler's measured peak when a
sampler is configured, else 0 (not measured — the engine's own
``StageOutput.resources`` records ``{"measured": false}``).  ``publishable`` is
set for artifact kinds the contract allows to ever be published; acceptance/
publication themselves stay with the app (S10/S12).

No GPU work happens in this module or its tests: the engine's HTTP transport is
the process boundary, and tests drive a fake transport at exactly that boundary.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.util
import json
import re
import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

from app.schemas.shot_reskin import (
    ENGINE_PUBLISHABLE_ARTIFACT_KINDS,
    EngineArtifactOutput,
    EngineDecodedFacts,
    EngineInputBinding,
    EngineOutputBinding,
    ShotEngineError,
    ShotExecutionRecord,
)

__all__ = [
    "ENGINE_ATTRIBUTES_REQUIRED",
    "MF_COMFY_DIST_NAME",
    "MF_COMFY_DIST_VERSION",
    "MF_COMFY_MODULE_FILES",
    "MF_COMFY_PROVENANCE_FILENAME",
    "MF_COMFY_PROVENANCE_SCHEMA",
    "MF_COMFY_SOURCE_COMMIT_PIN",
    "ComfyEngineRefusal",
    "ComfyEngineRefusalCode",
    "ComfyShotEngine",
    "engine_status",
]

# ── dependency identity (must equal scripts/build_mf_comfy_dependency.py) ─────

#: Source artifact this dependency is pinned to (MF-V1-COMFY R28).
MF_COMFY_SOURCE_COMMIT_PIN = "70f718098f00f9dbdeb6cc9c5d7808b243eb0c57"
MF_COMFY_DIST_NAME = "mf-comfy"
MF_COMFY_DIST_VERSION = "0.1.0"
MF_COMFY_PROVENANCE_FILENAME = "_mf_provenance.json"
MF_COMFY_PROVENANCE_SCHEMA = "mf.end18.comfy_dependency.provenance/1"

#: sha256 of every module file at the pin — the runtime half of the provenance
#: pin.  The build script and tests carry the byte-identical manifest.
MF_COMFY_MODULE_FILES: dict[str, str] = {
    "__init__.py": "1ea9885bd140d01aa0f19d9e756bbe705b5a8066012687780a3c46c5b094b7dd",
    "adapter.py": "945753341086c732f6701d543b5abeba991ced3559a5426737b96c6794f8b646",
    "contract.py": "935a6db9fd6a85a4c4cbf7381392ac0af105e80ac5c32913a737d5b9f3624700",
    "errors.py": "4bc873da04c0d4a309842dacd8266730eb04885837fd1d656345665c87f070b9",
    "gpugate.py": "e2b7117ff0da735416595935a20549847c3e59ea34cb2f1da157e27ab382d792",
    "lease.py": "3ee28fa3aad29d58de122f047e2288715c249e7f0b3510e129d8fa01d9c77371",
    "paths.py": "0295ff75108e70bd4d9b0f1a5c9caa1b9b575eacce23d4d4e62ee038f5d13661",
    "pinning.py": "0474ba45b2d65934d74aaab5f2407e0eb46b41803ba5e71d231ef8bd6d9e16b0",
    "reskin.py": "efa535c1b8578c265a6cdd60609724214ff37705dcea651c9a6eb8f88aa00d4c",
    "resources.py": "a6f264311a0c822ad9f99edd13957fe758774c3351302e119a743d40c0d17f6a",
    "transport.py": "c9861e1b609a37d90a4bbd4b5f34e95fc1530a216e4c49dc9c31d098d9f07265",
}

#: Package symbols this wrapper drives.  A package that verifies byte-exact but
#: lacks one of these is a different interface — refused, never guessed around.
ENGINE_ATTRIBUTES_REQUIRED = (
    "ComfyStageAdapter",
    "RunSpec",
    "StageInput",
    "StageOutput",
    "MfComfyError",
    "GpuStageGate",
    "InstanceEpoch",
    "InstanceLease",
    "PromptReservations",
    "StagePaths",
    "HttpTransport",
    "parse_base_url",
    "pinning",
    "hash_node_inventory",
    "sha256_file",
)

_STATE_SUBDIR = Path("media_engine") / "comfy_shot_engine"
_TERMINAL_KIND_MAP = {"image": ("images", "image"), "video": ("videos", "video"),
                      "audio": ("audio", "audio")}
_ENGINE_KIND_TO_APP = {"images": "image", "gifs": "image", "videos": "video", "audio": "audio"}

#: Engine failures returned as a failed record (terminal execution faults).
_ENGINE_TERMINAL_FAULT_CODES = frozenset({
    "MF_COMFY_OOM",
    "MF_COMFY_EXECUTION_ERROR",
    "MF_COMFY_EXECUTION_INTERRUPTED",
    "MF_COMFY_INVALID_GRAPH",
    "MF_COMFY_ARTIFACT_MISSING",
    "MF_COMFY_PARTIAL_OUTPUT",
})
_ENGINE_CAPABILITY_CODES = frozenset({"MF_COMFY_MISSING_NODE", "MF_COMFY_MISSING_MODEL"})
_ENGINE_PIN_CODES = frozenset({
    "MF_COMFY_WORKFLOW_HASH_MISMATCH",
    "MF_COMFY_NODE_INVENTORY_MISMATCH",
    "MF_COMFY_MODEL_HASH_MISMATCH",
    "MF_COMFY_ARTIFACT_HASH_MISMATCH",
})
_ENGINE_FOREIGN_IDENTITY_CODES = frozenset({
    "MF_COMFY_RESERVATION_MISMATCH",
    "MF_COMFY_RESERVATION_CONFLICT",
    "MF_COMFY_ATTEMPT_ALREADY_TERMINAL",
})


class ComfyEngineRefusalCode(str, Enum):
    """Typed app-side refusals.  One code per refusal; never a generic error."""

    ENGINE_UNAVAILABLE = "mf_end18_engine_unavailable"
    PROVENANCE_MISSING = "mf_end18_provenance_missing"
    PROVENANCE_MISMATCH = "mf_end18_provenance_mismatch"
    ENGINE_CONTRACT_MISSING = "mf_end18_engine_contract_missing"
    EPOCH_MISSING = "mf_end18_epoch_missing"
    HEALTH_UNREACHABLE = "mf_end18_health_unreachable"
    CAPABILITY_MISSING = "mf_end18_capability_missing"
    PIN_MISMATCH = "mf_end18_pin_mismatch"
    FOREIGN_IDENTITY_REFUSED = "mf_end18_foreign_identity_refused"
    AMBIGUOUS_AFTER_SUBMIT = "mf_end18_ambiguous_after_submit"
    RECORD_INCOMPLETE = "mf_end18_record_incomplete"
    ENGINE_REFUSED = "mf_end18_engine_refused"


class ComfyEngineRefusal(Exception):  # noqa: N818 — mirrors the contract's refusal naming
    """Fail-closed integration refusal.  Never swallowed into a generic error."""

    def __init__(
        self,
        code: ComfyEngineRefusalCode,
        detail: str,
        *,
        engine_code: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail
        self.engine_code = engine_code
        self.retryable = retryable

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code.value, "detail": self.detail}
        if self.engine_code:
            out["engine_code"] = self.engine_code
        if self.retryable:
            out["retryable"] = True
        return out


def _sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _package_dir() -> Path | None:
    """Directory of an IMPORTABLE ``mf_comfy`` package, or ``None``."""
    try:
        spec = importlib.util.find_spec("mf_comfy")
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    origin = getattr(spec, "origin", None)
    if spec is None or origin is None:
        return None
    return Path(origin).resolve().parent


def _provenance_problems(package_dir: Path) -> tuple[ComfyEngineRefusalCode | None, str]:
    """Verify provenance + pinned bytes.  Returns (None, detail) or (code, detail)."""
    provenance_path = package_dir / MF_COMFY_PROVENANCE_FILENAME
    if not provenance_path.is_file():
        return (
            ComfyEngineRefusalCode.PROVENANCE_MISSING,
            f"{provenance_path} is absent: the install did not come from "
            "scripts/build_mf_comfy_dependency.py",
        )
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return (
            ComfyEngineRefusalCode.PROVENANCE_MISMATCH,
            f"{provenance_path} is unreadable: {type(exc).__name__}:{exc}",
        )
    if not isinstance(provenance, dict) or provenance.get("schema") != MF_COMFY_PROVENANCE_SCHEMA:
        return (
            ComfyEngineRefusalCode.PROVENANCE_MISMATCH,
            f"{provenance_path} does not declare schema {MF_COMFY_PROVENANCE_SCHEMA!r}",
        )
    if provenance.get("source_commit") != MF_COMFY_SOURCE_COMMIT_PIN:
        return (
            ComfyEngineRefusalCode.PROVENANCE_MISMATCH,
            f"installed provenance pins source_commit "
            f"{provenance.get('source_commit')!r}; this wrapper requires "
            f"{MF_COMFY_SOURCE_COMMIT_PIN}",
        )
    if provenance.get("dist_name") != MF_COMFY_DIST_NAME:
        return (
            ComfyEngineRefusalCode.PROVENANCE_MISMATCH,
            f"installed provenance names dist {provenance.get('dist_name')!r}",
        )
    manifest = provenance.get("files")
    if not isinstance(manifest, dict) or set(manifest) != set(MF_COMFY_MODULE_FILES):
        return (
            ComfyEngineRefusalCode.PROVENANCE_MISMATCH,
            "the provenance file manifest does not cover exactly the pinned module files",
        )
    present = {p.name for p in package_dir.glob("*.py")}
    if present != set(MF_COMFY_MODULE_FILES):
        return (
            ComfyEngineRefusalCode.PROVENANCE_MISMATCH,
            f"installed module file set {sorted(present)} != pinned "
            f"{sorted(MF_COMFY_MODULE_FILES)}",
        )
    for name, want in sorted(MF_COMFY_MODULE_FILES.items()):
        entry = manifest.get(name) or {}
        if entry.get("sha256") != want:
            return (
                ComfyEngineRefusalCode.PROVENANCE_MISMATCH,
                f"provenance manifest for {name} records {entry.get('sha256')!r}, expected {want}",
            )
        got = _sha256_file(package_dir / name)
        if got != want:
            return (
                ComfyEngineRefusalCode.PROVENANCE_MISMATCH,
                f"{name} on disk is {got}; the pin requires {want}",
            )
    return None, (
        f"{len(MF_COMFY_MODULE_FILES)} module files byte-verified against "
        f"{MF_COMFY_SOURCE_COMMIT_PIN[:12]}"
    )


def engine_status() -> dict[str, Any]:
    """Provenance-verified dependency status.  NEVER raises — always a dict.

    ``{"available": bool, "code": <refusal code>, "detail": str, ...}`` —
    available reports the verified package directory, the pinned source commit
    and how many files were byte-verified.
    """
    try:
        package_dir = _package_dir()
    except Exception as exc:  # noqa: BLE001 — status reporting must not explode
        return {
            "available": False,
            "code": ComfyEngineRefusalCode.ENGINE_UNAVAILABLE.value,
            "detail": f"import resolution failed: {type(exc).__name__}:{exc}",
        }
    if package_dir is None:
        return {
            "available": False,
            "code": ComfyEngineRefusalCode.ENGINE_UNAVAILABLE.value,
            "detail": "mf_comfy is not importable: install the pinned dependency with "
            "scripts/build_mf_comfy_dependency.py",
        }
    code, detail = _provenance_problems(package_dir)
    if code is not None:
        return {"available": False, "code": code.value, "detail": detail,
                "package_dir": str(package_dir)}
    return {
        "available": True,
        "package_dir": str(package_dir),
        "dist": f"{MF_COMFY_DIST_NAME}=={MF_COMFY_DIST_VERSION}",
        "source_commit": MF_COMFY_SOURCE_COMMIT_PIN,
        "files_verified": len(MF_COMFY_MODULE_FILES),
        "detail": detail,
    }


def _load_engine() -> Any:
    """Import the verified engine package or refuse typed.  Never a stub."""
    status = engine_status()
    if not status["available"]:
        code = ComfyEngineRefusalCode(status["code"])
        raise ComfyEngineRefusal(code, status["detail"])
    module = importlib.import_module("mf_comfy")
    missing = [name for name in ENGINE_ATTRIBUTES_REQUIRED if not hasattr(module, name)]
    if missing:
        raise ComfyEngineRefusal(
            ComfyEngineRefusalCode.ENGINE_CONTRACT_MISSING,
            f"mf_comfy lacks required symbols {missing}; expected the pin "
            f"{MF_COMFY_SOURCE_COMMIT_PIN[:12]} interface",
        )
    return module


def _safe_component(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]", "_", value or "") or "unknown"


class ComfyShotEngine:
    """App-side driver of the pinned ComfyUI stage adapter (one per managed root)."""

    def __init__(
        self,
        *,
        managed_root: str | Path,
        base_url: str = "http://127.0.0.1:8188",
        owner: str = "motionforge.comfy_shot_engine",
        stage_timeout_s: float = 900.0,
        poll_s: float = 1.0,
        http_timeout_s: float = 60.0,
        gate_timeout_s: float = 0.0,
        transport: Any | None = None,
        resource_sampler: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.managed_root = Path(managed_root).resolve()
        self.base_url = base_url
        self.owner = owner
        self.stage_timeout_s = float(stage_timeout_s)
        self.poll_s = float(poll_s)
        self.http_timeout_s = float(http_timeout_s)
        self.gate_timeout_s = float(gate_timeout_s)
        self.clock = clock
        self.sleep = sleep
        self.engine_version_probe_notes: list[str] = []

        self.state_root = self.managed_root / _STATE_SUBDIR
        self.stage_root = self.state_root / "stage"
        self.epoch_path = self.state_root / "instance_epoch.json"
        self.reservations_root = self.state_root / "reservations"
        self.lease_dir = self.state_root / "leases"
        self.lock_path = self.state_root / "gpu_stage.lock"
        self.evidence_dir = self.state_root / "evidence"

        self._transport = transport
        self._resource_sampler = resource_sampler
        self._module: Any | None = None
        self._adapter: Any | None = None
        self._gate: Any | None = None
        self._lease: Any | None = None
        self._reservations: Any | None = None
        self._epoch_record: dict | None = None
        #: The most recent attempt that did NOT reach a terminal state (its
        #: durable reservation is still on disk and its lease covers the prompt).
        self._open_attempt: dict[str, Any] | None = None

    # ── authority ─────────────────────────────────────────────────────────────

    def authority(self) -> dict[str, str]:
        """The SINGLE on-disk authority this engine uses (one lease, one ledger)."""
        return {
            "stage_root": str(self.stage_root),
            "epoch": str(self.epoch_path),
            "reservations": str(self.reservations_root),
            "leases": str(self.lease_dir),
            "gpu_stage_lock": str(self.lock_path),
        }

    def _ensure_engine(self) -> Any:
        if self._adapter is not None:
            return self._adapter
        module = _load_engine()
        self._module = module
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.stage_root.mkdir(parents=True, exist_ok=True)
        self.lease_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        epoch = module.InstanceEpoch(self.epoch_path)
        record = epoch.read()
        if not record or not record.get("instance_id"):
            raise ComfyEngineRefusal(
                ComfyEngineRefusalCode.EPOCH_MISSING,
                f"no live ComfyUI boot identity at {self.epoch_path}; the launcher "
                "(serve_comfy) writes it for the instance this app drives — refusing "
                "to submit under an unknown instance epoch",
            )
        self._epoch_record = record
        if self._transport is None:
            try:
                self._transport = module.HttpTransport(
                    base_url=self.base_url, http_timeout_s=self.http_timeout_s
                )
            except module.MfComfyError as exc:
                raise self._refuse_engine(exc) from exc
        self._reservations = module.PromptReservations(self.reservations_root)
        self._gate = module.GpuStageGate(
            self.lock_path,
            timeout_s=self.gate_timeout_s,
            epoch_path=self.epoch_path,
            reservations=self._reservations,
        )
        self._lease = module.InstanceLease(self.lease_dir, str(record["instance_id"]), self.owner)
        self._adapter = self._new_adapter()
        return self._adapter

    def _new_adapter(self) -> Any:
        """A fresh adapter INSTANCE per attempt, over the SAME shared authority.

        The package refuses a second POST for one adapter lifetime; attempts are
        therefore driven by fresh instances that share the transport, stage
        paths, lease, gate, epoch and reservation ledger — never a second
        authority.
        """
        module = self._module
        adapter = module.ComfyStageAdapter(
            self._transport,
            module.StagePaths(self.stage_root),
            lease=self._lease,
            gate=self._gate,
            epoch=module.InstanceEpoch(self.epoch_path),
            clock=self.clock,
            sleep=self.sleep,
            sampler=self._resource_sampler,
            owner=self.owner,
        )
        adapter.instance_epoch = self._epoch_record
        return adapter

    # ── refusal mapping ──────────────────────────────────────────────────────

    def _refuse_engine(self, exc: Any, *, health: bool = False) -> ComfyEngineRefusal:
        code = str(getattr(exc, "code", "MF_COMFY_ERROR"))
        message = str(getattr(exc, "message", exc))
        retryable = bool(getattr(exc, "retryable", False))
        if health or code == "MF_COMFY_TRANSPORT_ERROR":
            return ComfyEngineRefusal(
                ComfyEngineRefusalCode.HEALTH_UNREACHABLE if health
                else ComfyEngineRefusalCode.ENGINE_REFUSED,
                f"{message} (engine {code})",
                engine_code=code,
                retryable=retryable,
            )
        if code in _ENGINE_CAPABILITY_CODES:
            return ComfyEngineRefusal(
                ComfyEngineRefusalCode.CAPABILITY_MISSING,
                f"{message} (engine {code})",
                engine_code=code,
            )
        if code in _ENGINE_PIN_CODES:
            return ComfyEngineRefusal(
                ComfyEngineRefusalCode.PIN_MISMATCH,
                f"{message} (engine {code})",
                engine_code=code,
            )
        if code in _ENGINE_FOREIGN_IDENTITY_CODES:
            return ComfyEngineRefusal(
                ComfyEngineRefusalCode.FOREIGN_IDENTITY_REFUSED,
                f"{message} (engine {code})",
                engine_code=code,
            )
        if code == "MF_COMFY_AMBIGUOUS_AFTER_SUBMIT":
            return ComfyEngineRefusal(
                ComfyEngineRefusalCode.AMBIGUOUS_AFTER_SUBMIT,
                f"{message} — the attempt stays unresolved, the durable reservation is "
                "kept and a second POST is never sent (engine "
                f"{code})",
                engine_code=code,
            )
        if code == "MF_COMFY_LEASE_NOT_HELD":
            return ComfyEngineRefusal(
                ComfyEngineRefusalCode.ENGINE_REFUSED,
                f"{message} (engine {code}; no HTTP call was made)",
                engine_code=code,
            )
        return ComfyEngineRefusal(
            ComfyEngineRefusalCode.ENGINE_REFUSED,
            f"{message} (engine {code})",
            engine_code=code,
            retryable=retryable,
        )

    # ── probes ───────────────────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        """Server liveness + capabilities via the engine's own `/system_stats` probe."""
        adapter = self._ensure_engine()
        try:
            caps = adapter.transport.probe_capabilities()
        except self._module.MfComfyError as exc:
            raise self._refuse_engine(exc, health=True) from exc
        return {
            "ok": True,
            "base_url": caps.get("base_url", self.base_url),
            "loopback_only": bool(caps.get("loopback_only", False)),
            "comfyui_version": caps.get("comfyui_version", ""),
            "device_name": caps.get("device_name", ""),
            "device_total_vram_mib": caps.get("device_total_vram_mib", 0),
            "node_class_count": caps.get("node_class_count", 0),
        }

    def capability_probe(
        self,
        *,
        required_node_classes: tuple[str, ...] = (),
        required_models: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """`/object_info` capability probe; refuses typed when a requirement is missing.

        ``required_models``: ``{class_type: {input_name: value}}`` — the value
        must be present in that input's option list on THIS server.
        """
        adapter = self._ensure_engine()
        module = self._module
        try:
            object_info = adapter.transport.object_info()
            caps = adapter.transport.probe_capabilities(object_info)
        except module.MfComfyError as exc:
            raise self._refuse_engine(exc, health=True) from exc
        missing_classes = module.pinning.inventory_missing_classes(
            object_info, list(required_node_classes)
        )
        missing_models: list[dict[str, str]] = []
        for class_type, inputs in sorted((required_models or {}).items()):
            spec = (object_info.get(class_type) or {}).get("input") or {}
            required = spec.get("required") or {}
            if class_type not in object_info:
                missing_models.append(
                    {"class_type": class_type, "input": "", "value": "",
                     "why": "class not exposed by this server"}
                )
                continue
            for input_name, value in sorted(inputs.items()):
                spec_def = required.get(input_name)
                options = None
                if isinstance(spec_def, list) and spec_def and isinstance(spec_def[0], list):
                    options = spec_def[0]
                if options is not None and value not in options:
                    missing_models.append(
                        {"class_type": class_type, "input": input_name, "value": value,
                         "why": "value not in the server's option list"}
                    )
        if missing_classes or missing_models:
            raise ComfyEngineRefusal(
                ComfyEngineRefusalCode.CAPABILITY_MISSING,
                f"the ComfyUI server does not expose the required capability: "
                f"missing_classes={missing_classes} missing_models={missing_models}",
            )
        return {
            "base_url": caps.get("base_url", self.base_url),
            "comfyui_version": caps.get("comfyui_version", ""),
            "node_class_count": len(object_info or {}),
            "node_inventory_sha256": module.hash_node_inventory(object_info),
            "missing_classes": [],
            "missing_models": [],
            "required_node_classes": sorted(required_node_classes),
        }

    # ── the shot call ────────────────────────────────────────────────────────

    def run_shot(
        self,
        binding: EngineInputBinding,
        *,
        graph: dict[str, Any],
        terminal_outputs: dict[str, dict[str, Any]] | None = None,
        expected_artifact_hashes: dict[str, str] | None = None,
        shot_id: str = "",
        params: dict[str, Any] | None = None,
        decoded_facts: EngineDecodedFacts | None = None,
    ) -> ShotExecutionRecord:
        """Drive one shot attempt through the pinned engine; return the record."""
        record, _info = self._execute(
            binding,
            graph=graph,
            terminal_outputs=terminal_outputs,
            expected_artifact_hashes=expected_artifact_hashes,
            shot_id=shot_id,
            params=params,
            decoded_facts=decoded_facts,
        )
        return record

    def replay(
        self,
        binding: EngineInputBinding,
        *,
        graph: dict[str, Any],
        terminal_outputs: dict[str, dict[str, Any]] | None = None,
        expected_artifact_hashes: dict[str, str] | None = None,
        shot_id: str = "",
        params: dict[str, Any] | None = None,
        decoded_facts: EngineDecodedFacts | None = None,
    ) -> tuple[ShotExecutionRecord, dict[str, Any]]:
        """Same-identity re-invocation: reuse durable evidence, never a second POST.

        Returns ``(record, info)``; ``info["replayed"]`` is True when the record
        was rebuilt from a durable completion receipt (no gate, no lease, no
        POST, no re-fetch).
        """
        return self._execute(
            binding,
            graph=graph,
            terminal_outputs=terminal_outputs,
            expected_artifact_hashes=expected_artifact_hashes,
            shot_id=shot_id,
            params=params,
            decoded_facts=decoded_facts,
        )

    def _execute(
        self,
        binding: EngineInputBinding,
        *,
        graph: dict[str, Any],
        terminal_outputs: dict[str, dict[str, Any]] | None,
        expected_artifact_hashes: dict[str, str] | None,
        shot_id: str,
        params: dict[str, Any] | None,
        decoded_facts: EngineDecodedFacts | None,
    ) -> tuple[ShotExecutionRecord, dict[str, Any]]:
        if not isinstance(binding, EngineInputBinding):
            raise TypeError(f"binding must be an EngineInputBinding, got {type(binding).__name__}")
        if not isinstance(graph, dict) or not graph:
            raise TypeError("graph must be the non-empty API-format workflow object")
        self._ensure_engine()
        module = self._module
        # A fresh adapter INSTANCE per attempt over the shared authority: the
        # package allows exactly one POST per adapter lifetime (by design).
        adapter = self._new_adapter()
        stage_id = binding.identity.stage
        attempt_id = binding.identity.attempt_id
        stage_input = module.StageInput(
            stage_id=stage_id,
            project_id=binding.identity.project_id,
            job_id=binding.identity.job_id or "",
            attempt_id=attempt_id,
            shot_id=shot_id,
            source_sha256=binding.source.source_sha256,
            source_frame_range=[
                binding.source.span.start_frame,
                binding.source.span.end_frame_exclusive,
            ],
            reference_assets={
                role_binding.role: role_binding.references[0].artifact.sha256
                for role_binding in binding.cast
                if role_binding.references
            },
            workflow_id=binding.graph.workflow_id,
            workflow_sha256=binding.graph.workflow_hash,
            node_inventory_sha256="",
            model_hashes=self._model_hashes(binding),
            seed=binding.graph.seed,
            params=dict(params or {}),
            staging_root=str(self.stage_root),
            requested_quality="preview",
            cost_ceiling=binding.budget.max_wall_seconds,
        )
        spec = module.RunSpec(
            stage_id=stage_id,
            workflow_id=binding.graph.workflow_id,
            graph=graph,
            workflow_sha256=binding.graph.workflow_hash,
            node_inventory_sha256="",
            model_pins=self._model_hashes(binding),
            stage_timeout_s=self.stage_timeout_s,
            poll_s=self.poll_s,
            expected_artifact_hashes=dict(expected_artifact_hashes or {}),
            allowed_types=("output",),
            attempt_id=attempt_id,
            owner=self.owner,
            terminal_outputs=_normalize_terminal_outputs(terminal_outputs),
        )
        try:
            out = adapter.run(spec, stage_input)
        except module.MfComfyError as exc:
            self._write_evidence(attempt_id, {
                "status": "refused" if str(getattr(exc, "code", "")) not in
                _ENGINE_TERMINAL_FAULT_CODES else "failed",
                "engine_failure": exc.to_dict(),
                "counters": self._counters(adapter),
                "notes": list(adapter.notes),
                "reservation": adapter.reservation_state(),
            })
            if str(getattr(exc, "code", "")) in _ENGINE_TERMINAL_FAULT_CODES:
                return (
                    ShotExecutionRecord(
                        execution_backend="comfy_shot_engine",
                        capability=binding.capability,
                        outcome="failed",
                        input=binding,
                        error=ShotEngineError(
                            code=str(exc.code), message=str(exc.message), retryable=exc.retryable
                        ),
                    ),
                    {"attempt_id": attempt_id, "status": "failed", "engine_code": str(exc.code),
                     "submit_count": adapter.submit_count, "replayed": False},
                )
            raise self._refuse_engine(exc) from exc

        if out.status != "validated":
            # "unresolved": the outcome is not provable.  The durable reservation
            # stays on disk and the lease/gate stay held — a later caller must
            # reconcile, never resubmit.
            self._open_attempt = {"adapter": adapter, "prompt_id": out.prompt_id,
                                  "attempt_id": attempt_id}
            self._write_evidence(attempt_id, {
                "status": out.status,
                "prompt_id": out.prompt_id,
                "counters": self._counters(adapter),
                "timing": out.timing,
                "notes": list(out.notes),
                "reservation": out.reservation,
            })
            raise ComfyEngineRefusal(
                ComfyEngineRefusalCode.AMBIGUOUS_AFTER_SUBMIT,
                f"attempt {attempt_id} did not reach a terminal state (engine status "
                f"{out.status!r}); the durable reservation is kept and a second POST is "
                "never sent — reconcile before retrying",
            )

        record = self._compose_record(binding, out, decoded_facts=decoded_facts)
        info = {
            "attempt_id": attempt_id,
            "status": out.status,
            "prompt_id": out.prompt_id,
            "replayed": bool(out.adopted)
            or (out.reservation or {}).get("source") == "completion_receipt",
            "adopted": bool(out.adopted),
            "submit_count": adapter.submit_count,
            "reconcile_count": adapter.reconcile_count,
            "reservation_released": adapter.reservation_released,
            "counters": self._counters(adapter),
        }
        self._write_evidence(attempt_id, {
            "status": out.status,
            "prompt_id": out.prompt_id,
            "adopted": bool(out.adopted),
            "counters": self._counters(adapter),
            "timing": out.timing,
            "resources": out.resources,
            "notes": list(out.notes),
            "reservation": out.reservation,
            "info": info,
        })
        return record, info

    # ── control ──────────────────────────────────────────────────────────────

    def cancel(self, prompt_id: str, *, wait_terminal_s: float = 0.0) -> dict[str, Any]:
        """`/interrupt` a prompt this attempt provably owns (lease-gated), then reconcile.

        Uses the adapter instance that holds this prompt's reservation when the
        attempt is still open; otherwise a fresh instance over the same shared
        lease (the lease, not the adapter, is the authority).
        """
        self._ensure_engine()
        open_attempt = self._open_attempt or {}
        adapter = (open_attempt.get("adapter")
                   if open_attempt.get("prompt_id") == prompt_id else None)
        if adapter is None:
            adapter = self._new_adapter()
        try:
            result = adapter.cancel(prompt_id, wait_terminal_s=wait_terminal_s, poll_s=self.poll_s)
        except self._module.MfComfyError as exc:
            raise self._refuse_engine(exc) from exc
        if self._open_attempt and self._open_attempt.get("prompt_id") == prompt_id:
            self._open_attempt = None
        return result

    def close(self) -> None:
        """Release this engine's holds and close the transport.  Idempotent."""
        if self._transport is not None and self._adapter is not None:
            with contextlib.suppress(Exception):  # best-effort close
                self._transport.close()
        if self._gate is not None and getattr(self._gate, "held", False):
            self._gate.release()
        if self._lease is not None:
            self._lease.release()

    # ── record composition ───────────────────────────────────────────────────

    def _model_hashes(self, binding: EngineInputBinding) -> dict[str, str]:
        hashes = {binding.graph.model.model_id: binding.graph.model.file.value}
        for aux in binding.auxiliary_models:
            hashes[aux.model_id] = aux.file.value
        return hashes

    def _counters(self, adapter: Any) -> dict[str, int]:
        return {
            "submit_count": int(adapter.submit_count),
            "reconcile_count": int(adapter.reconcile_count),
            "interrupt_count": int(adapter.interrupt_count),
            "interrupt_refusals": int(adapter.interrupt_refusals),
        }

    def _compose_record(
        self,
        binding: EngineInputBinding,
        out: Any,
        *,
        decoded_facts: EngineDecodedFacts | None,
    ) -> ShotExecutionRecord:
        contract = binding.output_contract
        if decoded_facts is None:
            if contract.stream_timebase_num is None or contract.stream_timebase_den is None:
                raise ComfyEngineRefusal(
                    ComfyEngineRefusalCode.RECORD_INCOMPLETE,
                    "the output contract records no stream timebase and no measured "
                    "decoded_facts were supplied — refusing to invent decoded facts",
                )
            decoded_facts = EngineDecodedFacts(
                decoded_frames=contract.frame_count,
                first_pts_ticks=0,
                timebase=f"{contract.stream_timebase_num}/{contract.stream_timebase_den}",
                mapping=None,
            )
        artifacts: list[EngineArtifactOutput] = []
        for staged in out.artifacts:
            staged_path = Path(staged["staged_path"]).resolve()
            try:
                store_relative = staged_path.relative_to(self.managed_root).as_posix()
            except ValueError as exc:
                raise ComfyEngineRefusal(
                    ComfyEngineRefusalCode.ENGINE_REFUSED,
                    f"engine staged {staged_path} outside the managed root "
                    f"{self.managed_root}",
                ) from exc
            app_kind = _ENGINE_KIND_TO_APP[str(staged["kind"])]
            suffix = Path(str(staged["filename"])).suffix.lower().lstrip(".")
            artifacts.append(
                EngineArtifactOutput(
                    artifact_id=f"{binding.identity.attempt_id}:{staged['node_id']}:"
                    f"{staged['filename']}",
                    kind=app_kind,
                    media_type=f"{app_kind}/{suffix}" if suffix else app_kind,
                    sha256=str(staged["sha256"]),
                    store_relative_path=store_relative,
                    size_bytes=int(staged["size_bytes"]),
                    publishable=app_kind in ENGINE_PUBLISHABLE_ARTIFACT_KINDS,
                    server_output_type=str(staged["server_type"]),
                )
            )
        timing = out.timing or {}
        wall = float(timing.get("total_s") or timing.get("replay_s") or 0.0)
        resources = out.resources or {}
        vram_peak = int(resources.get("vram_peak_mib") or 0) if resources.get("measured") else 0
        output = EngineOutputBinding(
            prompt_id=str(out.prompt_id),
            owner_session=self.owner,
            graph_sha256_server=str(out.workflow_sha256),
            artifacts=tuple(artifacts),
            decoded=decoded_facts,
            audio=contract.audio,
            server_side_wall_s=max(wall, 1e-3),
            vram_peak_mib=vram_peak,
        )
        return ShotExecutionRecord(
            execution_backend="comfy_shot_engine",
            capability=binding.capability,
            outcome="completed",
            input=binding,
            output=output,
        )

    def _write_evidence(self, attempt_id: str, payload: dict[str, Any]) -> str:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"{_safe_component(attempt_id)}.engine_evidence.json"
        doc = {"schema": "mf.end18.comfy_engine_evidence/1", "attempt_id": attempt_id,
               "owner": self.owner, "base_url": self.base_url}
        doc.update(payload)
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return str(path)


def _normalize_terminal_outputs(
    declared: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """App-side terminal declaration → the engine's ``RunSpec.terminal_outputs`` shape.

    App kinds are ``image`` / ``video`` / ``audio``; the engine keys artifacts by
    ComfyUI bucket (``images`` / ``videos`` / ``audio``) and checks the declared
    ``media_type`` against the filename suffix it staged.
    """
    normalized: dict[str, dict[str, Any]] = {}
    for node_id, conf in (declared or {}).items():
        kind = (conf or {}).get("kind")
        if kind not in _TERMINAL_KIND_MAP:
            raise ValueError(
                f"terminal_outputs[{node_id!r}].kind must be one of "
                f"{sorted(_TERMINAL_KIND_MAP)}; got {kind!r}"
            )
        if kind == "audio" and conf.get("media_type", "audio") != "audio":
            raise ValueError(f"terminal_outputs[{node_id!r}] audio media_type must be 'audio'")
        if kind != "audio" and conf.get("media_type", kind) != kind:
            raise ValueError(
                f"terminal_outputs[{node_id!r}].media_type must be {kind!r} (the engine "
                "checks it against the staged suffix), got {conf.get('media_type')!r}"
            )
        engine_kind, media_type = _TERMINAL_KIND_MAP[kind]
        normalized[str(node_id)] = {
            "kind": engine_kind,
            "media_type": media_type,
            "server_types": tuple(conf.get("server_types") or ("output",)),
        }
    return normalized
