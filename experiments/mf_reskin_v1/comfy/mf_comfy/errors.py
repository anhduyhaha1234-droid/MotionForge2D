"""Typed failures for the MotionForge ComfyUI stage adapter (MF-V1-COMFY).

Every failure the adapter can produce is a typed exception with a stable `code`.
Nothing in this package retries a prompt submission: the only retry that exists
is a WebSocket reconnect in the transport, which never re-submits a prompt.
"""
from __future__ import annotations

from typing import Any


class MfComfyError(Exception):
    """Base class: typed adapter failure."""

    code = "MF_COMFY_ERROR"
    retryable = False

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }

    def __str__(self) -> str:  # keeps log lines single-line and greppable
        return f"[{self.code}] {self.message}"


# --- configuration / boundary violations -----------------------------------
class NonLoopbackEndpoint(MfComfyError):
    """Refused to talk to a non-loopback ComfyUI endpoint (must stay local)."""

    code = "MF_COMFY_NON_LOOPBACK"


class PathScopeViolation(MfComfyError):
    """A requested artifact path escapes the stage root."""

    code = "MF_COMFY_PATH_SCOPE_VIOLATION"


# --- preflight / capability -------------------------------------------------
class MissingNode(MfComfyError):
    """Workflow references a node class this server does not expose."""

    code = "MF_COMFY_MISSING_NODE"


class MissingModel(MfComfyError):
    """Workflow references a model/checkpoint this server cannot list."""

    code = "MF_COMFY_MISSING_MODEL"


class InvalidGraph(MfComfyError):
    """Graph failed server-side or adapter-side structural validation."""

    code = "MF_COMFY_INVALID_GRAPH"


# --- pinning ----------------------------------------------------------------
class WorkflowPinMismatch(MfComfyError):
    code = "MF_COMFY_WORKFLOW_HASH_MISMATCH"


class NodeInventoryPinMismatch(MfComfyError):
    code = "MF_COMFY_NODE_INVENTORY_MISMATCH"


class ModelPinMismatch(MfComfyError):
    code = "MF_COMFY_MODEL_HASH_MISMATCH"


# --- lifecycle --------------------------------------------------------------
class ServerEpochChanged(MfComfyError):
    """History/queue no longer belong to the instance epoch we submitted to."""

    code = "MF_COMFY_SERVER_EPOCH_CHANGED"


class AmbiguousAfterSubmit(MfComfyError):
    """Submit outcome cannot be proven from queue/history/epoch.

    This is terminal for the attempt: it MUST NOT be resolved by resubmitting.
    """

    code = "MF_COMFY_AMBIGUOUS_AFTER_SUBMIT"


class OomFailure(MfComfyError):
    """GPU/host out-of-memory reported by the engine for this prompt."""

    code = "MF_COMFY_OOM"


class ExecutionInterrupted(MfComfyError):
    """Prompt was cancelled before completing.

    Observed on the real server (v0.28.2): a cancelled prompt lands in
    `/history/{prompt_id}` with `status_str == "error"` and an
    `execution_interrupted` message. It is reported as its own typed failure so a
    caller can distinguish "we cancelled it" from "it crashed" — never as success.
    """

    code = "MF_COMFY_EXECUTION_INTERRUPTED"


class ExecutionError(MfComfyError):
    """Engine reported a non-OOM execution failure for this prompt."""

    code = "MF_COMFY_EXECUTION_ERROR"


class TransportError(MfComfyError):
    """HTTP/WS transport failure (not proof of engine outcome)."""

    code = "MF_COMFY_TRANSPORT_ERROR"
    retryable = True


class BlindResubmitRefused(MfComfyError):
    """A second prompt submission for the same attempt was refused."""

    code = "MF_COMFY_BLIND_RESUBMIT_REFUSED"


class WsDisconnected(MfComfyError):
    """WebSocket dropped. NOT proof the job failed; history is the authority."""

    code = "MF_COMFY_WS_DISCONNECT"
    retryable = True


# --- artefacts --------------------------------------------------------------
class ArtifactMissing(MfComfyError):
    code = "MF_COMFY_ARTIFACT_MISSING"


class PartialOutput(MfComfyError):
    """Artifact is a partial/undecodable file — never publishable."""

    code = "MF_COMFY_PARTIAL_OUTPUT"


class ArtifactHashMismatch(MfComfyError):
    code = "MF_COMFY_ARTIFACT_HASH_MISMATCH"


# --- resource arbitration ---------------------------------------------------
class LeaseNotHeld(MfComfyError):
    """`/interrupt` refused: this attempt does not hold the exclusive lease."""

    code = "MF_COMFY_LEASE_NOT_HELD"


class LeaseConflict(MfComfyError):
    code = "MF_COMFY_LEASE_CONFLICT"


class GpuStageBusy(MfComfyError):
    """Another heavy GPU stage holds the machine-wide stage gate."""

    code = "MF_COMFY_GPU_STAGE_BUSY"


class UnresolvedReservation(MfComfyError):
    """Gate refused: a prompt of this instance still has an unprovable outcome.

    Raised by `GpuStageGate.acquire` when the durable reservation ledger still
    holds a reservation for this instance epoch. The reservation is a file on
    disk, so it survives a caller crash or a process restart; it is released
    exactly once, and only after the outcome is provable from
    `/queue` + `/history` + the instance epoch.
    """

    code = "MF_COMFY_UNRESOLVED_RESERVATION"
    retryable = True


class ReservationConflict(MfComfyError):
    """Refused to open a reservation while one is already unresolved."""

    code = "MF_COMFY_RESERVATION_CONFLICT"


class CorruptReservation(MfComfyError):
    """Gate refused: a reservation marker exists but cannot be read.

    A malformed / truncated / unreadable marker is UNKNOWN state, not "no
    reservation": the marker may be the only record of a prompt that is still
    occupying the server. The gate therefore fails closed with this typed
    refusal and never submits. The marker itself is left untouched as evidence.
    """

    code = "MF_COMFY_CORRUPT_RESERVATION"
    retryable = False


class ReservationMismatch(MfComfyError):
    """Refused to adopt a reservation that belongs to another boot identity."""

    code = "MF_COMFY_RESERVATION_MISMATCH"


OOM_MARKERS = (
    "out of memory",
    "outofmemoryerror",
    "cuda oom",
    "insufficient memory",
    "allocation on device",
    "failed to allocate",
    "torch.cuda.outofmemoryerror",
)


def classify_execution_message(text: str) -> MfComfyError:
    """Map an engine error string to a typed failure.

    Verified against the pinned ComfyUI commit: execution failures surface as a
    history entry with `status.status_str == "error"` plus `status.messages`
    carrying the node traceback (and `status.exception_type`).
    """
    low = (text or "").lower()
    if "execution_interrupted" in low:
        return ExecutionInterrupted("the prompt was cancelled before completing",
                                    engine_text=text[:4000])
    if any(m in low for m in OOM_MARKERS):
        return OomFailure("engine reported an out-of-memory failure", engine_text=text[:4000])
    return ExecutionError("engine reported an execution failure", engine_text=text[:4000])
