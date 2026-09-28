"""Shot render content-keyed cache + attempt lifecycle (MF-END-20).

One deterministic content key over ``source/span/cast/input/graph/model/params``
(:func:`shot_key_texture` -> :func:`shot_content_key`).  A completed render pins
a durable receipt in the DB AND a receipt sidecar next to the managed artifact
(sha in the row).  Cache replay NEVER issues a new engine POST and never
duplicates a publication.

Attempt lifecycle (``prepared -> submitted -> completed | failed | cancelled |
superseded``) is safe across restart BEFORE/AFTER submit and BEFORE/AFTER
publication:

* restart before submit re-uses the ``prepared`` attempt (no duplicate rows);
* restart after submit sees ``submitted`` and refuses to re-POST an in-doubt
  submit (typed ``shot_cache_submit_in_doubt``); only an explicit retry
  supersedes the in-doubt attempt with a NEW attempt number;
* a cancelled or superseded attempt can never pin (publish) a late output;
* invalidation is per shot or per dependent key component — bounded statements,
  other shots keep their exact receipt/hash.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import uuid
from collections.abc import Callable, Mapping
from enum import Enum
from pathlib import Path
from typing import Any

from sqlalchemy import text as sa_text

from app.persistence.artifacts import hash_file

__all__ = [
    "COMPONENTS",
    "SCHEMA_VERSION",
    "ShotCacheRefusal",
    "ShotCacheRefusalCode",
    "ShotReskinCache",
    "run_cached_shot_render",
    "shot_content_key",
    "shot_key_texture",
]

SCHEMA_VERSION = "mf.shot_reskin_cache.v1"
KEY_SCHEMA_VERSION = "mf.shot_reskin_cache.key.v1"
RECEIPT_SUBDIR = "shot_render_cache"

#: Key texture components (dependent invalidation seams).
COMPONENTS: tuple[str, ...] = (
    "source",
    "span",
    "cast",
    "input",
    "graph",
    "model",
    "params",
)

ATTEMPT_PREPARED = "prepared"
ATTEMPT_SUBMITTED = "submitted"
ATTEMPT_COMPLETED = "completed"
ATTEMPT_FAILED = "failed"
ATTEMPT_CANCELLED = "cancelled"
ATTEMPT_SUPERSEDED = "superseded"
ATTEMPT_TERMINAL = frozenset(
    {ATTEMPT_COMPLETED, ATTEMPT_FAILED, ATTEMPT_CANCELLED, ATTEMPT_SUPERSEDED}
)
RECEIPT_VALID = "valid"
RECEIPT_INVALIDATED = "invalidated"

WIN_MAX_PATH = 259


class ShotCacheRefusalCode(str, Enum):
    """Typed refusal codes (the caller maps them to its own error domain)."""

    SHOT_CACHE_KEY_INVALID = "shot_cache_key_invalid"
    SHOT_CACHE_SUBMIT_IN_DOUBT = "shot_cache_submit_in_doubt"
    SHOT_CACHE_ATTEMPT_CANCELLED = "shot_cache_attempt_cancelled"
    SHOT_CACHE_ATTEMPT_UNKNOWN = "shot_cache_attempt_unknown"
    SHOT_CACHE_STATE_INVALID = "shot_cache_state_invalid"
    SHOT_CACHE_RECEIPT_CONFLICT = "shot_cache_receipt_conflict"
    SHOT_CACHE_REPLAY_ARTIFACT_STALE = "shot_cache_replay_artifact_stale"


class ShotCacheRefusal(RuntimeError):  # noqa: N818 - mirrors the executor refusal naming
    """Typed refusal — fail closed, never continue on a weakened assumption."""

    def __init__(self, code: ShotCacheRefusalCode, detail: str, **context: Any) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail
        self.context = context

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "detail": self.detail,
            "context": dict(self.context),
        }


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(text_value: str) -> str:
    return hashlib.sha256(text_value.encode("utf-8")).hexdigest()


def _long_path(path: Path, *, force: bool = False) -> Path:
    """Windows extended-length path (mirrors the FullApply ``_lp`` helper)."""
    raw = str(path)
    if os.name == "nt" and not raw.startswith("\\\\?\\") and (force or len(raw) > WIN_MAX_PATH):
        return Path("\\\\?\\" + os.path.abspath(raw))
    return path


def _hex64(value: Any) -> str:
    text_value = str(value or "").strip().lower()
    if len(text_value) != 64 or any(ch not in "0123456789abcdef" for ch in text_value):
        return ""
    return text_value


def shot_key_texture(request: Mapping[str, Any]) -> dict[str, str]:
    """Per-component digests of one shot render request (fail closed).

    Every component is a digest over canonical JSON of the pinned inputs the
    engine call actually consumes: source bytes+span+fps, cast pack versions +
    reference hashes, staged/anchor input digests, the frozen graph bytes,
    model/profile identity (+seed/output shape) and the generation parameters.
    A missing pin refuses — the cache never keys on a guessed value.
    """
    try:
        source = dict(request.get("source") or {})
        span = dict(source.get("span") or {})
        fps = dict(source.get("fps") or {})
        start = int(span.get("start_frame"))
        end = int(span.get("end_frame_exclusive"))
        fps_num = int(fps.get("num") or 30)
        fps_den = int(fps.get("den") or 1)
        source_sha = _hex64(source.get("sha256"))
        if not source_sha or end <= start or fps_den < 1:
            raise ValueError("source sha256/span/fps pins incomplete")
        staged_raw = dict(request.get("staged_inputs") or {})
        staged: dict[str, Any] = {}
        for name, entry in sorted(staged_raw.items()):
            if not isinstance(entry, Mapping):
                raise ValueError(f"staged input {name!r} is not an object")
            staged[str(name)] = {
                "relative_path": str(entry.get("relative_path") or ""),
                "sha256": _hex64(entry.get("sha256")),
            }
        anchor = dict(request.get("anchor") or {})
        anchor_sha = _hex64(anchor.get("sha256"))
        cast: list[dict[str, Any]] = []
        for entry in request.get("cast") or []:
            if not isinstance(entry, Mapping):
                raise ValueError("cast entry is not an object")
            refs = [
                {
                    "key": str(r.get("key") or ""),
                    "sha256": _hex64(r.get("sha256")),
                }
                for r in (entry.get("references") or [])
                if isinstance(r, Mapping)
            ]
            refs.sort(key=lambda r: (r["key"], r["sha256"]))
            cast.append(
                {
                    "role": str(entry.get("role") or ""),
                    "character_id": str(entry.get("character_id") or ""),
                    "pack_version_id": str(entry.get("pack_version_id") or ""),
                    "references": refs,
                }
            )
        cast.sort(key=lambda c: (c["role"], c["pack_version_id"], c["character_id"]))
        backend = dict(request.get("backend") or {})
        graph = dict(request.get("graph") or {})
        graph_file = str(graph.get("file") or backend.get("graph_file") or "")
        graph_sha = _hex64(graph.get("file_sha256") or backend.get("graph_sha256"))
        if not graph_file or not graph_sha:
            raise ValueError("graph file/digest pin incomplete")
        profile_id = str(backend.get("profile_id") or "")
        if not profile_id:
            raise ValueError("backend profile_id missing")
        output = dict(request.get("output_contract") or {})
        params = {
            "prompt": str((request.get("parameters") or {}).get("prompt") or ""),
            "seed": int(backend.get("seed") if backend.get("seed") is not None else 0),
            "output_node": str(backend.get("output_node") or ""),
            "width": int(output.get("width") or 0),
            "height": int(output.get("height") or 0),
            "fps_num": int(output.get("fps_num") or fps_num),
            "fps_den": int(output.get("fps_den") or fps_den),
            "frame_count": int(output.get("frame_count") or (end - start)),
            "container": str(output.get("container") or ""),
            "video_codec": str(output.get("video_codec") or ""),
            "audio_mode": str((output.get("audio") or {}).get("mode") or ""),
        }
    except (TypeError, ValueError) as exc:
        raise ShotCacheRefusal(
            ShotCacheRefusalCode.SHOT_CACHE_KEY_INVALID,
            f"shot render request cannot be content-keyed: {exc}",
        ) from exc
    texture = {
        "source": _sha(
            _canonical(
                {
                    "sha256": source_sha,
                    "relative_path": str(source.get("relative_path") or ""),
                    "size_bytes": source.get("size_bytes"),
                }
            )
        ),
        "span": _sha(_canonical({"start": start, "end": end, "fps": [fps_num, fps_den]})),
        "cast": _sha(_canonical(cast)),
        "input": _sha(
            _canonical(
                {
                    "staged": staged,
                    "anchor": {
                        "relative_path": str(anchor.get("relative_path") or ""),
                        "sha256": anchor_sha,
                    },
                }
            )
        ),
        "graph": _sha(_canonical({"file": graph_file, "file_sha256": graph_sha})),
        "model": _sha(
            _canonical(
                {
                    "profile_id": profile_id,
                    "capability": str(backend.get("capability") or ""),
                }
            )
        ),
        "params": _sha(_canonical(params)),
    }
    return texture


def shot_content_key(request: Mapping[str, Any]) -> str:
    """The deterministic content key of one shot render request."""
    return _sha(_canonical({"schema": KEY_SCHEMA_VERSION, "texture": shot_key_texture(request)}))


class ShotReskinCache:
    """Durable cache receipts + attempt lifecycle over a Session (caller commits)."""

    def __init__(self, session: Any, *, managed_root: str | Path | None = None) -> None:
        self._session = session
        self._managed_root: Path | None = None
        if managed_root is not None:
            self._managed_root = _long_path(Path(managed_root), force=True)
        self._ensure_tables()

    # ── schema ──────────────────────────────────────────────────────────────

    def _ensure_tables(self) -> None:
        self._session.execute(
            sa_text(
                """
                CREATE TABLE IF NOT EXISTS shot_reskin_cache_receipt (
                    receipt_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    content_key TEXT NOT NULL,
                    shot_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    attempt_row_id TEXT NOT NULL,
                    source_digest TEXT NOT NULL,
                    span_digest TEXT NOT NULL,
                    cast_digest TEXT NOT NULL,
                    input_digest TEXT NOT NULL,
                    graph_digest TEXT NOT NULL,
                    model_digest TEXT NOT NULL,
                    params_digest TEXT NOT NULL,
                    output_relative_path TEXT NOT NULL,
                    output_sha256 TEXT NOT NULL,
                    output_size_bytes INTEGER NOT NULL,
                    decoded_sha256 TEXT NOT NULL,
                    decoded_frame_count INTEGER NOT NULL,
                    fps_num INTEGER NOT NULL,
                    fps_den INTEGER NOT NULL,
                    prompt_id TEXT,
                    graph_object_sha256_submitted TEXT,
                    receipt_rel_path TEXT,
                    receipt_file_sha256 TEXT,
                    state TEXT NOT NULL DEFAULT 'valid',
                    invalidate_reason TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(workspace_id, content_key)
                )
                """
            )
        )
        self._session.execute(
            sa_text(
                """
                CREATE TABLE IF NOT EXISTS shot_reskin_cache_attempt (
                    attempt_row_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    content_key TEXT NOT NULL,
                    shot_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    prompt_id TEXT,
                    superseded_by TEXT,
                    late_output_json TEXT,
                    detail TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(workspace_id, attempt_id, attempt_no)
                )
                """
            )
        )
        self._session.flush()

    # ── bounded reads ───────────────────────────────────────────────────────

    def _load_attempt(self, workspace_id: str, attempt_row_id: str) -> dict[str, Any]:
        row = self._session.execute(
            sa_text(
                "SELECT * FROM shot_reskin_cache_attempt "
                "WHERE workspace_id=:ws AND attempt_row_id=:rid"
            ),
            {"ws": workspace_id, "rid": attempt_row_id},
        ).mappings().first()
        if row is None:
            raise ShotCacheRefusal(
                ShotCacheRefusalCode.SHOT_CACHE_ATTEMPT_UNKNOWN,
                f"attempt {attempt_row_id!r} is not registered for workspace {workspace_id!r}",
            )
        return dict(row)

    def _load_receipt(self, workspace_id: str, content_key: str) -> dict[str, Any] | None:
        row = self._session.execute(
            sa_text(
                "SELECT * FROM shot_reskin_cache_receipt WHERE workspace_id=:ws AND content_key=:k"
            ),
            {"ws": workspace_id, "k": content_key},
        ).mappings().first()
        return dict(row) if row is not None else None

    def _latest_attempt(self, workspace_id: str, content_key: str) -> dict[str, Any] | None:
        row = self._session.execute(
            sa_text(
                "SELECT * FROM shot_reskin_cache_attempt WHERE workspace_id=:ws AND content_key=:k "
                "ORDER BY attempt_no DESC LIMIT 1"
            ),
            {"ws": workspace_id, "k": content_key},
        ).mappings().first()
        return dict(row) if row is not None else None

    # ── receipt verification + sidecar ───────────────────────────────────────

    def _verify_receipt_bytes(self, receipt: Mapping[str, Any]) -> bool:
        if self._managed_root is None:
            return True
        rel = str(receipt.get("output_relative_path") or "")
        if not rel:
            return False
        abs_path = _long_path(self._managed_root / rel)
        if not abs_path.is_file():
            return False
        if abs_path.stat().st_size != int(receipt.get("output_size_bytes") or 0):
            return False
        return hash_file(abs_path) == str(receipt.get("output_sha256") or "")

    def _receipt_sidecar_rel(self, shot_id: str, chunk_id: str) -> str:
        safe_shot = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in shot_id) or "shot"
        safe_chunk = (
            "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in chunk_id) or "chunk"
        )
        return f"{RECEIPT_SUBDIR}/{safe_shot}/{safe_chunk}.receipt.json"

    def _write_receipt_sidecar(self, payload: Mapping[str, Any]) -> tuple[str, str]:
        """Atomic managed-root write (same-directory staging + replace)."""
        if self._managed_root is None:
            raise ShotCacheRefusal(
                ShotCacheRefusalCode.SHOT_CACHE_STATE_INVALID,
                "receipt sidecar write requires a managed root",
            )
        rel = self._receipt_sidecar_rel(
            str(payload.get("shot_id") or ""), str(payload.get("chunk_id") or "")
        )
        target = _long_path(self._managed_root / rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = _long_path(target.with_name(f".{target.name}.{uuid.uuid4().hex}.staging"))
        try:
            tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            tmp.replace(target)
        except BaseException:
            with contextlib.suppress(Exception):
                tmp.unlink(missing_ok=True)
            raise
        return rel, hash_file(target)

    # ── lookup / replay ─────────────────────────────────────────────────────

    def lookup(
        self, *, workspace_id: str, content_key: str, verify_bytes: bool = True
    ) -> dict[str, Any] | None:
        """The live receipt for ``content_key`` or ``None`` (bounded: 1 SELECT).

        A receipt whose managed artifact is missing/tampered is invalidated
        (state kept, never deleted) so the replay re-renders instead of
        publishing drifted bytes.
        """
        receipt = self._load_receipt(workspace_id, content_key)
        if receipt is None or str(receipt["state"]) != RECEIPT_VALID:
            return None
        if verify_bytes and not self._verify_receipt_bytes(receipt):
            self._session.execute(
                sa_text(
                    "UPDATE shot_reskin_cache_receipt SET state='invalidated', "
                    "invalidate_reason='stale_unverified_artifact', updated_at=CURRENT_TIMESTAMP "
                    "WHERE workspace_id=:ws AND content_key=:k"
                ),
                {"ws": workspace_id, "k": content_key},
            )
            self._session.flush()
            return None
        return receipt

    def replay(
        self, *, workspace_id: str, request: Mapping[str, Any], verify_bytes: bool = True
    ) -> dict[str, Any]:
        """Replay verdict for a request: hit => NO engine POST is required."""
        content_key = shot_content_key(request)
        receipt = self.lookup(
            workspace_id=workspace_id, content_key=content_key, verify_bytes=verify_bytes
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "content_key": content_key,
            "hit": receipt is not None,
            "receipt": receipt,
            "engine_post_required": receipt is None,
        }

    # ── attempt lifecycle ───────────────────────────────────────────────────

    def begin_attempt(
        self,
        *,
        workspace_id: str,
        request: Mapping[str, Any],
        run_id: str,
        retry: bool = False,
    ) -> dict[str, Any]:
        """Decide what a (re)entry may do WITHOUT duplicating a submit.

        Returns an action dict:

        * ``cache_hit`` — a live receipt exists; the caller returns it and
          issues ZERO engine POSTs;
        * ``submit``    — a fresh/resumed ``prepared`` attempt may be submitted
          (``resumed=True`` when a previous entry already created it);
        * ``in_doubt``  — the latest attempt is ``submitted``: a POST may have
          been issued before the previous process died.  A bare restart must
          NOT re-POST (typed refusal); ``retry=True`` supersedes the in-doubt
          attempt with a NEW attempt and returns ``submit``.
        """
        content_key = shot_content_key(request)
        receipt = self.lookup(workspace_id=workspace_id, content_key=content_key)
        if receipt is not None:
            return {
                "action": "cache_hit",
                "content_key": content_key,
                "receipt": receipt,
                "attempt": None,
            }
        latest = self._latest_attempt(workspace_id, content_key)
        shot_id = str(request.get("shot_id") or "")
        chunk_id = str(request.get("chunk_id") or "")
        attempt_id = str(request.get("attempt_id") or f"shot-{chunk_id}")
        if latest is not None and str(latest["state"]) == ATTEMPT_PREPARED:
            return {
                "action": "submit",
                "content_key": content_key,
                "attempt": latest,
                "resumed": True,
                "superseded": None,
                "receipt": None,
            }
        superseded: dict[str, Any] | None = None
        if latest is not None and str(latest["state"]) == ATTEMPT_SUBMITTED:
            if not retry:
                return {
                    "action": "in_doubt",
                    "content_key": content_key,
                    "attempt": latest,
                    "resumed": True,
                    "superseded": None,
                    "receipt": None,
                }
            new_row_id = f"{attempt_id}#{int(latest['attempt_no']) + 1}"
            self._session.execute(
                sa_text(
                    "UPDATE shot_reskin_cache_attempt SET state='superseded', superseded_by=:by, "
                    "detail='explicit retry supersedes in-doubt submit', "
                    "updated_at=CURRENT_TIMESTAMP "
                    "WHERE workspace_id=:ws AND attempt_row_id=:rid AND state='submitted'"
                ),
                {"by": new_row_id, "ws": workspace_id, "rid": str(latest["attempt_row_id"])},
            )
            self._session.flush()
            superseded = self._load_attempt(workspace_id, str(latest["attempt_row_id"]))
        attempt_no = int(latest["attempt_no"]) + 1 if latest is not None else 1
        attempt_row_id = f"{attempt_id}#{attempt_no}"
        self._session.execute(
            sa_text(
                "INSERT INTO shot_reskin_cache_attempt(attempt_row_id, workspace_id, content_key, "
                "shot_id, chunk_id, run_id, attempt_id, attempt_no, state) "
                "VALUES (:rid, :ws, :k, :shot, :chunk, :run, :aid, :no, 'prepared')"
            ),
            {
                "rid": attempt_row_id,
                "ws": workspace_id,
                "k": content_key,
                "shot": shot_id,
                "chunk": chunk_id,
                "run": run_id,
                "aid": attempt_id,
                "no": attempt_no,
            },
        )
        self._session.flush()
        return {
            "action": "submit",
            "content_key": content_key,
            "attempt": self._load_attempt(workspace_id, attempt_row_id),
            "resumed": False,
            "superseded": superseded,
            "receipt": None,
        }

    def mark_submitted(
        self, *, workspace_id: str, attempt_row_id: str, prompt_id: str | None = None
    ) -> bool:
        """Pin the SUBMIT EPOCH before the engine POST (prompt_id later).

        Called BEFORE the engine call so a process death between the epoch and
        the response leaves a durable ``submitted`` row — the restart then sees
        ``in_doubt`` instead of silently re-POSTing.
        """
        result = self._session.execute(
            sa_text(
                "UPDATE shot_reskin_cache_attempt SET state='submitted', "
                "prompt_id=COALESCE(:pid, prompt_id), updated_at=CURRENT_TIMESTAMP "
                "WHERE workspace_id=:ws AND attempt_row_id=:rid "
                "AND state IN ('prepared','submitted')"
            ),
            {"pid": prompt_id, "ws": workspace_id, "rid": attempt_row_id},
        )
        self._session.flush()
        return bool(result.rowcount == 1)

    def complete_attempt(
        self,
        *,
        workspace_id: str,
        attempt_row_id: str,
        receipt_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Pin a receipt from a SUBMITTED attempt (CAS; winner only).

        A cancelled/superseded attempt NEVER pins: the late output is recorded
        on the attempt row (``late_output_json``) and ``pinned=False`` is
        returned so the caller withholds the publication.
        """
        row = self._load_attempt(workspace_id, attempt_row_id)
        state = str(row["state"])
        if state in (ATTEMPT_CANCELLED, ATTEMPT_SUPERSEDED):
            self._record_late_output(row, receipt_payload, reason=state)
            return {
                "pinned": False,
                "late_dropped": True,
                "reason": state,
                "receipt": None,
                "attempt_row_id": attempt_row_id,
            }
        if state == ATTEMPT_COMPLETED:
            return {
                "pinned": True,
                "late_dropped": False,
                "reason": "already_completed",
                "receipt": self._load_receipt(workspace_id, str(row["content_key"])),
                "attempt_row_id": attempt_row_id,
            }
        if state != ATTEMPT_SUBMITTED:
            raise ShotCacheRefusal(
                ShotCacheRefusalCode.SHOT_CACHE_STATE_INVALID,
                f"attempt is {state!r}; a receipt can only be pinned from a SUBMITTED attempt",
                attempt_row_id=attempt_row_id,
            )
        latest = self._latest_attempt(workspace_id, str(row["content_key"]))
        if latest is not None and int(latest["attempt_no"]) > int(row["attempt_no"]):
            self._session.execute(
                sa_text(
                    "UPDATE shot_reskin_cache_attempt SET state='superseded', superseded_by=:by, "
                    "updated_at=CURRENT_TIMESTAMP "
                    "WHERE workspace_id=:ws AND attempt_row_id=:rid AND state='submitted'"
                ),
                {"by": str(latest["attempt_row_id"]), "ws": workspace_id, "rid": attempt_row_id},
            )
            self._session.flush()
            self._record_late_output(row, receipt_payload, reason=ATTEMPT_SUPERSEDED)
            return {
                "pinned": False,
                "late_dropped": True,
                "reason": "superseded",
                "receipt": None,
                "attempt_row_id": attempt_row_id,
            }
        cas = self._session.execute(
            sa_text(
                "UPDATE shot_reskin_cache_attempt SET state='completed', "
                "updated_at=CURRENT_TIMESTAMP "
                "WHERE workspace_id=:ws AND attempt_row_id=:rid AND state='submitted'"
            ),
            {"ws": workspace_id, "rid": attempt_row_id},
        )
        if cas.rowcount != 1:
            fresh = self._load_attempt(workspace_id, attempt_row_id)
            self._record_late_output(fresh, receipt_payload, reason=str(fresh["state"]))
            return {
                "pinned": False,
                "late_dropped": True,
                "reason": str(fresh["state"]),
                "receipt": None,
                "attempt_row_id": attempt_row_id,
            }
        receipt = self._pin_receipt(workspace_id, row, receipt_payload)
        self._session.flush()
        return {
            "pinned": True,
            "late_dropped": False,
            "reason": "completed",
            "receipt": receipt,
            "attempt_row_id": attempt_row_id,
        }

    def fail_attempt(
        self, *, workspace_id: str, attempt_row_id: str, detail: str = ""
    ) -> bool:
        """Mark a live attempt ``failed`` (bounded; rows are never deleted)."""
        result = self._session.execute(
            sa_text(
                "UPDATE shot_reskin_cache_attempt SET state='failed', detail=:detail, "
                "updated_at=CURRENT_TIMESTAMP "
                "WHERE workspace_id=:ws AND attempt_row_id=:rid "
                "AND state IN ('prepared','submitted')"
            ),
            {"detail": detail, "ws": workspace_id, "rid": attempt_row_id},
        )
        self._session.flush()
        return bool(result.rowcount == 1)

    def cancel_attempt(
        self, *, workspace_id: str, attempt_row_id: str, detail: str = ""
    ) -> bool:
        """Mark a live attempt ``cancelled`` (row kept; no slot/lease loss).

        The returned bool is False when the attempt already reached a terminal
        state — cancel never resurrects and never deletes bookkeeping.
        """
        result = self._session.execute(
            sa_text(
                "UPDATE shot_reskin_cache_attempt SET state='cancelled', detail=:detail, "
                "updated_at=CURRENT_TIMESTAMP "
                "WHERE workspace_id=:ws AND attempt_row_id=:rid "
                "AND state IN ('prepared','submitted')"
            ),
            {"detail": detail, "ws": workspace_id, "rid": attempt_row_id},
        )
        self._session.flush()
        return bool(result.rowcount == 1)

    def _record_late_output(
        self, row: Mapping[str, Any], receipt_payload: Mapping[str, Any], *, reason: str
    ) -> None:
        late = {
            "reason": reason,
            "output_relative_path": str(receipt_payload.get("output_relative_path") or ""),
            "output_sha256": str(receipt_payload.get("output_sha256") or ""),
            "pinned": False,
        }
        self._session.execute(
            sa_text(
                "UPDATE shot_reskin_cache_attempt SET late_output_json=:late, "
                "updated_at=CURRENT_TIMESTAMP "
                "WHERE workspace_id=:ws AND attempt_row_id=:rid AND late_output_json IS NULL"
            ),
            {
                "late": _canonical(late),
                "ws": str(row["workspace_id"]),
                "rid": str(row["attempt_row_id"]),
            },
        )
        self._session.flush()

    def _pin_receipt(
        self,
        workspace_id: str,
        attempt: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        content_key = str(attempt["content_key"])
        required = ("shot_id", "chunk_id", "output_relative_path", "output_sha256")
        missing = [k for k in required if not str(payload.get(k) or "")]
        if missing or len(_hex64(payload.get("output_sha256"))) != 64:
            raise ShotCacheRefusal(
                ShotCacheRefusalCode.SHOT_CACHE_KEY_INVALID,
                f"receipt payload missing/invalid fields: {missing or ['output_sha256']}",
            )
        existing = self._load_receipt(workspace_id, content_key)
        if existing is not None and str(existing["output_sha256"]) != str(payload["output_sha256"]):
            raise ShotCacheRefusal(
                ShotCacheRefusalCode.SHOT_CACHE_RECEIPT_CONFLICT,
                "a receipt for this content key already pins different output bytes (fail closed)",
                existing_sha256=str(existing["output_sha256"]),
                new_sha256=str(payload["output_sha256"]),
            )
        sidecar_rel = (
            str(existing["receipt_rel_path"])
            if existing is not None and existing["receipt_rel_path"]
            else None
        )
        sidecar_sha = (
            str(existing["receipt_file_sha256"])
            if existing is not None and existing["receipt_file_sha256"]
            else None
        )
        if self._managed_root is not None:
            sidecar_rel, sidecar_sha = self._write_receipt_sidecar(payload)
        if existing is not None:
            self._session.execute(
                sa_text(
                    "UPDATE shot_reskin_cache_receipt SET state='valid', invalidate_reason=NULL, "
                    "attempt_row_id=:arid, prompt_id=:pid, graph_object_sha256_submitted=:gsha, "
                    "receipt_rel_path=:sc, receipt_file_sha256=:scsha, "
                    "updated_at=CURRENT_TIMESTAMP "
                    "WHERE workspace_id=:ws AND content_key=:k"
                ),
                {
                    "arid": str(attempt["attempt_row_id"]),
                    "pid": str(payload.get("prompt_id") or ""),
                    "gsha": str(payload.get("graph_object_sha256_submitted") or ""),
                    "sc": sidecar_rel,
                    "scsha": sidecar_sha,
                    "ws": workspace_id,
                    "k": content_key,
                },
            )
        else:
            receipt_id = str(uuid.uuid4())
            self._session.execute(
                sa_text(
                    "INSERT INTO shot_reskin_cache_receipt(receipt_id, workspace_id, content_key, "
                    "shot_id, chunk_id, attempt_row_id, source_digest, span_digest, cast_digest, "
                    "input_digest, graph_digest, model_digest, params_digest, "
                    "output_relative_path, "
                    "output_sha256, output_size_bytes, decoded_sha256, decoded_frame_count, "
                    "fps_num, fps_den, prompt_id, graph_object_sha256_submitted, receipt_rel_path, "
                    "receipt_file_sha256, state) "
                    "VALUES (:rid, :ws, :k, :shot, :chunk, :arid, :source, :span, :cast, :input, "
                    ":graph, :model, :params, :out, :osha, :osz, :dsha, :dfc, :fn, :fd, :pid, "
                    ":gsha, :sc, :scsha, 'valid')"
                ),
                {
                    "rid": receipt_id,
                    "ws": workspace_id,
                    "k": content_key,
                    "shot": str(payload["shot_id"]),
                    "chunk": str(payload["chunk_id"]),
                    "arid": str(attempt["attempt_row_id"]),
                    "source": str(payload.get("source_digest") or ""),
                    "span": str(payload.get("span_digest") or ""),
                    "cast": str(payload.get("cast_digest") or ""),
                    "input": str(payload.get("input_digest") or ""),
                    "graph": str(payload.get("graph_digest") or ""),
                    "model": str(payload.get("model_digest") or ""),
                    "params": str(payload.get("params_digest") or ""),
                    "out": str(payload["output_relative_path"]),
                    "osha": str(payload["output_sha256"]),
                    "osz": int(payload.get("output_size_bytes") or 0),
                    "dsha": str(payload.get("decoded_sha256") or ""),
                    "dfc": int(payload.get("decoded_frame_count") or 0),
                    "fn": int(payload.get("fps_num") or 30),
                    "fd": int(payload.get("fps_den") or 1),
                    "pid": str(payload.get("prompt_id") or ""),
                    "gsha": str(payload.get("graph_object_sha256_submitted") or ""),
                    "sc": sidecar_rel,
                    "scsha": sidecar_sha,
                },
            )
        self._session.flush()
        receipt = self._load_receipt(workspace_id, content_key)
        if receipt is None:
            raise ShotCacheRefusal(
                ShotCacheRefusalCode.SHOT_CACHE_STATE_INVALID,
                "receipt pin failed unexpectedly",
            )
        return receipt

    def receipt_payload(
        self,
        *,
        request: Mapping[str, Any],
        result: Mapping[str, Any],
        attempt_row_id: str,
    ) -> dict[str, Any]:
        """Build the receipt payload from an accepted shot render result."""
        texture = shot_key_texture(request)
        payload: dict[str, Any] = {
            "shot_id": str(request.get("shot_id") or ""),
            "chunk_id": str(request.get("chunk_id") or ""),
            "attempt_row_id": str(attempt_row_id),
            "output_relative_path": str(result.get("output_relative_path") or ""),
            "output_sha256": _hex64(result.get("output_sha256")),
            "output_size_bytes": int(result.get("output_size_bytes") or 0),
            "decoded_sha256": str(result.get("decoded_sha256") or ""),
            "decoded_frame_count": int(result.get("decoded_frame_count") or 0),
            "fps_num": int(result.get("fps_num") or 30),
            "fps_den": int(result.get("fps_den") or 1),
            "prompt_id": str(result.get("prompt_id") or ""),
            "graph_object_sha256_submitted": str(result.get("graph_object_sha256_submitted") or ""),
        }
        for component, digest in texture.items():
            payload[f"{component}_digest"] = digest
        return payload

    # ── invalidation (per shot / per dependent component seam) ──────────────

    def invalidate_receipt(self, *, workspace_id: str, content_key: str, reason: str) -> bool:
        result = self._session.execute(
            sa_text(
                "UPDATE shot_reskin_cache_receipt SET state='invalidated', invalidate_reason=:why, "
                "updated_at=CURRENT_TIMESTAMP "
                "WHERE workspace_id=:ws AND content_key=:k AND state='valid'"
            ),
            {"why": reason, "ws": workspace_id, "k": content_key},
        )
        self._session.flush()
        return bool(result.rowcount == 1)

    def invalidate_shot(self, *, workspace_id: str, shot_id: str, reason: str) -> int:
        """Invalidate exactly ONE shot's receipts (bounded: 1 UPDATE).

        Other shots' receipts (their exact output hashes) are untouched.
        """
        result = self._session.execute(
            sa_text(
                "UPDATE shot_reskin_cache_receipt SET state='invalidated', invalidate_reason=:why, "
                "updated_at=CURRENT_TIMESTAMP "
                "WHERE workspace_id=:ws AND shot_id=:shot AND state='valid'"
            ),
            {"why": reason, "ws": workspace_id, "shot": shot_id},
        )
        self._session.flush()
        return int(result.rowcount or 0)

    def invalidate_component(
        self, *, workspace_id: str, component: str, digest: str, reason: str
    ) -> int:
        """Invalidate receipts whose dependent texture component matches.

        The dependent seam: a cast/graph/source change invalidates only the
        receipts that consumed that exact component digest (bounded: 1 UPDATE
        over a denormalized column, never a scan of every row's JSON).
        """
        if component not in COMPONENTS:
            raise ShotCacheRefusal(
                ShotCacheRefusalCode.SHOT_CACHE_KEY_INVALID,
                f"unknown key component {component!r}; expected one of {list(COMPONENTS)}",
            )
        if not _hex64(digest):
            raise ShotCacheRefusal(
                ShotCacheRefusalCode.SHOT_CACHE_KEY_INVALID,
                f"component digest for {component!r} must be a 64-hex digest",
            )
        result = self._session.execute(
            sa_text(
                f"UPDATE shot_reskin_cache_receipt SET state='invalidated', "
                f"invalidate_reason=:why, updated_at=CURRENT_TIMESTAMP "
                f"WHERE workspace_id=:ws AND {component}_digest=:digest AND state='valid'"
            ),
            {"why": reason, "ws": workspace_id, "digest": digest},
        )
        self._session.flush()
        return int(result.rowcount or 0)

    # ── reopen / status (all-row counts, bounded statements) ────────────────

    def status(
        self, *, workspace_id: str | None = None, run_id: str | None = None
    ) -> dict[str, Any]:
        """All-row counts with a FIXED number of statements (2 GROUP BYs).

        Counts every receipt and every attempt row exactly once; re-running the
        read is idempotent and cannot observe a half-updated counter (each
        statement is atomic, the DB is consistent at read time).
        """
        statements = 0
        attempt_filter = "WHERE workspace_id=:ws" if workspace_id else ""
        params: dict[str, Any] = {}
        if workspace_id:
            params["ws"] = workspace_id
        if run_id is not None:
            attempt_filter = (
                f"{attempt_filter} AND run_id=:rid" if attempt_filter else "WHERE run_id=:rid"
            )
            params["rid"] = run_id
        attempts = self._session.execute(
            sa_text(
                "SELECT state, COUNT(*) AS n FROM shot_reskin_cache_attempt "
                f"{attempt_filter} GROUP BY state"
            ),
            params,
        ).mappings().all()
        statements += 1
        receipt_filter = "WHERE workspace_id=:ws" if workspace_id else ""
        receipts = self._session.execute(
            sa_text(
                "SELECT state, COUNT(*) AS n FROM shot_reskin_cache_receipt "
                f"{receipt_filter} GROUP BY state"
            ),
            params if workspace_id else {},
        ).mappings().all()
        statements += 1
        by_state = {str(r["state"]): int(r["n"]) for r in attempts}
        receipt_state = {str(r["state"]): int(r["n"]) for r in receipts}
        return {
            "schema_version": SCHEMA_VERSION,
            "workspace_id": workspace_id,
            "run_id": run_id,
            "statements_used": statements,
            "attempts": {
                "total": sum(by_state.values()),
                "by_state": by_state,
                "in_doubt": by_state.get(ATTEMPT_SUBMITTED, 0),
            },
            "receipts": {
                "total": sum(receipt_state.values()),
                "by_state": receipt_state,
            },
        }

    def reopen_state(self, *, workspace_id: str, run_id: str) -> dict[str, Any]:
        """Reopen the run's cache ledger: ALL rows in ONE bounded JOIN.

        Every attempt row of the run is returned exactly once (with its pinned
        receipt joined in), so a reviewer can count every row and see each
        attempt's state/winner without a per-row query loop.  Read-only: a
        retry/cancel race cannot make the reopen lose or double-count a row.
        """
        rows = self._session.execute(
            sa_text(
                "SELECT a.attempt_row_id, a.content_key, a.shot_id, a.chunk_id, a.attempt_id, "
                "a.attempt_no, a.state AS attempt_state, a.prompt_id, a.superseded_by, "
                "a.late_output_json, r.receipt_id, r.state AS receipt_state, "
                "r.output_sha256, r.output_relative_path "
                "FROM shot_reskin_cache_attempt a "
                "LEFT JOIN shot_reskin_cache_receipt r "
                "  ON r.workspace_id = a.workspace_id AND r.content_key = a.content_key "
                "WHERE a.workspace_id=:ws AND a.run_id=:rid "
                "ORDER BY a.content_key, a.attempt_no"
            ),
            {"ws": workspace_id, "rid": run_id},
        ).mappings().all()
        by_state: dict[str, int] = {}
        winner_by_key: dict[str, str] = {}
        winner_no: dict[str, int] = {}
        completed_by_key: dict[str, int] = {}
        late_dropped = 0
        receipt_ids: dict[str, str] = {}
        for row in rows:
            state = str(row["attempt_state"])
            by_state[state] = by_state.get(state, 0) + 1
            if row["late_output_json"]:
                late_dropped += 1
            key = str(row["content_key"])
            attempt_no = int(row["attempt_no"])
            if key not in winner_no or attempt_no > winner_no[key]:
                winner_no[key] = attempt_no
                winner_by_key[key] = str(row["attempt_row_id"])
            if state == ATTEMPT_COMPLETED:
                completed_by_key[key] = completed_by_key.get(key, 0) + 1
            if row["receipt_id"]:
                receipt_ids[str(row["receipt_id"])] = str(row["receipt_state"])
        ambiguous = sorted(key for key, n in completed_by_key.items() if n > 1)
        return {
            "schema_version": SCHEMA_VERSION,
            "workspace_id": workspace_id,
            "run_id": run_id,
            "statements_used": 1,
            "attempts": {
                "total": len(rows),
                "by_state": by_state,
                "in_doubt": by_state.get(ATTEMPT_SUBMITTED, 0),
                "late_dropped": late_dropped,
            },
            "receipts": {
                "total": len(receipt_ids),
                "valid": sum(1 for s in receipt_ids.values() if s == RECEIPT_VALID),
            },
            "winner_by_key": winner_by_key,
            "ambiguous_keys": ambiguous,
            "rows_total": len(rows),
        }

    # ── publication guard ───────────────────────────────────────────────────

    def assert_run_receipts_live(self, *, workspace_id: str, run_id: str) -> dict[str, Any]:
        """Publication-time guard: this run's pinned receipts stay byte-live.

        Bounded: ONE join over the run's attempts x pinned receipts, then a
        byte check per distinct receipt.  A receipt whose managed artifact is
        missing/tampered refuses the publication (typed) — replay can never
        publish drifted bytes.
        """
        rows = self._session.execute(
            sa_text(
                "SELECT DISTINCT r.receipt_id, r.output_relative_path, r.output_sha256, "
                "r.output_size_bytes, r.state "
                "FROM shot_reskin_cache_receipt r "
                "JOIN shot_reskin_cache_attempt a "
                "  ON a.workspace_id = r.workspace_id AND a.attempt_row_id = r.attempt_row_id "
                "WHERE a.workspace_id=:ws AND a.run_id=:rid"
            ),
            {"ws": workspace_id, "rid": run_id},
        ).mappings().all()
        stale: list[dict[str, Any]] = []
        checked = 0
        for row in rows:
            if str(row["state"]) != RECEIPT_VALID:
                continue
            checked += 1
            if not self._verify_receipt_bytes(row):
                stale.append(
                    {
                        "receipt_id": str(row["receipt_id"]),
                        "output_relative_path": str(row["output_relative_path"]),
                        "expected_sha256": str(row["output_sha256"]),
                    }
                )
        if stale:
            raise ShotCacheRefusal(
                ShotCacheRefusalCode.SHOT_CACHE_REPLAY_ARTIFACT_STALE,
                "publication refused: pinned cache receipt artifact(s) missing/tampered",
                stale=stale,
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "checked": checked,
            "live": checked,
            "statements_used": 1,
        }


def run_cached_shot_render(
    *,
    session_factory: Callable[[], Any],
    managed_root: str | Path | None,
    workspace_id: str,
    run_id: str,
    request: Mapping[str, Any],
    render: Callable[[], dict[str, Any]],
    retry: bool = False,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Run ONE shot render through the cache with a durable submit epoch.

    * cache hit  -> ``render`` is NOT called (zero engine POSTs);
    * in-doubt   -> typed refusal (a bare restart never re-POSTs);
    * cancel     -> a cancelled attempt never pins; the late output is dropped
      and the caller must withhold the publication.
    """
    with session_factory() as session:
        cache = ShotReskinCache(session, managed_root=managed_root)
        begin = cache.begin_attempt(
            workspace_id=workspace_id, request=request, run_id=run_id, retry=retry
        )
        action = str(begin["action"])
        if action == "cache_hit":
            session.commit()
            return {
                "cache_hit": True,
                "receipt": begin["receipt"],
                "attempt": None,
                "result": None,
                "content_key": str(begin["content_key"]),
            }
        if action == "in_doubt":
            attempt = begin["attempt"]
            session.commit()
            raise ShotCacheRefusal(
                ShotCacheRefusalCode.SHOT_CACHE_SUBMIT_IN_DOUBT,
                "the latest attempt was already SUBMITTED before the restart; refusing to "
                "re-POST the same attempt (only an explicit retry may supersede it)",
                attempt_row_id=str(attempt["attempt_row_id"]) if attempt else "",
                pipeline_attempt=int(attempt["attempt_no"]) if attempt else 0,
            )
        attempt = begin["attempt"]
        attempt_row_id = str(attempt["attempt_row_id"])
        cache.mark_submitted(workspace_id=workspace_id, attempt_row_id=attempt_row_id)
        session.commit()
    try:
        result = render()
    except BaseException as exc:
        with session_factory() as session:
            ShotReskinCache(session, managed_root=managed_root).fail_attempt(
                workspace_id=workspace_id,
                attempt_row_id=attempt_row_id,
                detail=f"{type(exc).__name__}: {str(exc)[:200]}",
            )
            session.commit()
        raise
    with session_factory() as session:
        cache = ShotReskinCache(session, managed_root=managed_root)
        if is_cancelled is not None and is_cancelled():
            cache.cancel_attempt(
                workspace_id=workspace_id,
                attempt_row_id=attempt_row_id,
                detail="cancelled after render, before completion — output withheld",
            )
            session.commit()
            raise ShotCacheRefusal(
                ShotCacheRefusalCode.SHOT_CACHE_ATTEMPT_CANCELLED,
                "attempt cancelled before completion — the rendered output is withheld "
                "(no receipt, no publication)",
                attempt_row_id=attempt_row_id,
                output_relative_path=str(result.get("output_relative_path") or ""),
            )
        payload = cache.receipt_payload(
            request=request, result=result, attempt_row_id=attempt_row_id
        )
        completion = cache.complete_attempt(
            workspace_id=workspace_id, attempt_row_id=attempt_row_id, receipt_payload=payload
        )
        session.commit()
    if not completion["pinned"]:
        raise ShotCacheRefusal(
            ShotCacheRefusalCode.SHOT_CACHE_ATTEMPT_CANCELLED,
            f"late output dropped: attempt is {completion['reason']!r} (not the winner) — "
            "no receipt, no publication",
            attempt_row_id=attempt_row_id,
            output_relative_path=str(result.get("output_relative_path") or ""),
        )
    return {
        "cache_hit": False,
        "receipt": completion["receipt"],
        "attempt": attempt,
        "result": result,
        "content_key": str(begin["content_key"]),
    }
