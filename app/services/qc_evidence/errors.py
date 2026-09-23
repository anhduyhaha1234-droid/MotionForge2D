"""MF-P1-QC-EVIDENCE — typed refusal taxonomy for QC evidence composition.

Every refusal carries a STABLE machine-readable code.  Nothing in this
package ever fabricates a detector input: a missing / stale / foreign /
malformed / tampered upstream fact is refused with the matching code, and a
fact that has no producer at all is reported exactly (dependency report),
never invented.

Codes (string constants — contracts depend on the exact values):

- ``QC_EVIDENCE_MISSING``    — the producer row/artifact does not exist.
- ``QC_EVIDENCE_STALE``      — evidence exists but is superseded / not
  current for the video's present source generation (an old publication,
  a superseded segment generation, a non-``ready`` artifact row).
- ``QC_EVIDENCE_FOREIGN``    — a cited row belongs to another workspace /
  project / video item: cross-owner evidence is refused, never mixed.
- ``QC_EVIDENCE_MALFORMED``  — the persisted payload cannot be parsed or
  violates its own contract (bad JSON, wrong shape, non-finite number).
- ``QC_EVIDENCE_TAMPERED``   — the persisted BYTES do not match the
  digest/size the database recorded (re-verified on read).
- ``QC_EVIDENCE_DEPENDENCY`` — the required fact genuinely has no producer;
  the error carries an exact dependency report naming the missing
  producer/fact so an operator can act on it.
"""

from __future__ import annotations

from typing import Any

QC_EVIDENCE_MISSING = "QC_EVIDENCE_MISSING"
QC_EVIDENCE_STALE = "QC_EVIDENCE_STALE"
QC_EVIDENCE_FOREIGN = "QC_EVIDENCE_FOREIGN"
QC_EVIDENCE_MALFORMED = "QC_EVIDENCE_MALFORMED"
QC_EVIDENCE_TAMPERED = "QC_EVIDENCE_TAMPERED"
QC_EVIDENCE_DEPENDENCY = "QC_EVIDENCE_DEPENDENCY"

#: Closed refusal-code set (a reviewer can assert completeness).
EVIDENCE_REFUSAL_CODES = (
    QC_EVIDENCE_MISSING,
    QC_EVIDENCE_STALE,
    QC_EVIDENCE_FOREIGN,
    QC_EVIDENCE_MALFORMED,
    QC_EVIDENCE_TAMPERED,
    QC_EVIDENCE_DEPENDENCY,
)


class QcEvidenceError(Exception):
    """A QC evidence-composition refusal with a stable code.

    ``details`` is JSON-serializable and always carries the detector (when
    known) plus the exact provenance facts a reviewer needs.  When the
    refusal is ``QC_EVIDENCE_DEPENDENCY`` the ``dependency`` mapping names
    the missing producer/fact explicitly.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        detector: str | None = None,
        dependency: dict[str, Any] | None = None,
        **details: Any,
    ) -> None:
        self.code = code
        self.message = message
        self.detector = detector
        self.dependency = dict(dependency) if dependency else None
        self.details: dict[str, Any] = {"evidence_code": code}
        self.details["detector"] = detector
        for key, value in details.items():
            self.details[key] = value
        if self.dependency is not None:
            self.details["dependency"] = dict(self.dependency)
        super().__init__(message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "detector": self.detector,
            "details": dict(self.details),
        }


def missing(detector: str, message: str, **details: Any) -> QcEvidenceError:
    return QcEvidenceError(QC_EVIDENCE_MISSING, message, detector=detector, **details)


def stale(detector: str, message: str, **details: Any) -> QcEvidenceError:
    return QcEvidenceError(QC_EVIDENCE_STALE, message, detector=detector, **details)


def foreign(detector: str, message: str, **details: Any) -> QcEvidenceError:
    return QcEvidenceError(QC_EVIDENCE_FOREIGN, message, detector=detector, **details)


def malformed(detector: str, message: str, **details: Any) -> QcEvidenceError:
    return QcEvidenceError(QC_EVIDENCE_MALFORMED, message, detector=detector, **details)


def tampered(detector: str, message: str, **details: Any) -> QcEvidenceError:
    return QcEvidenceError(QC_EVIDENCE_TAMPERED, message, detector=detector, **details)


def dependency(
    detector: str,
    message: str,
    *,
    fact: str,
    producer: str,
    persistence: str,
) -> QcEvidenceError:
    """Exact dependency report for a fact that has NO producer today."""
    return QcEvidenceError(
        QC_EVIDENCE_DEPENDENCY,
        message,
        detector=detector,
        dependency={
            "missing_fact": fact,
            "missing_producer": producer,
            "expected_persistence": persistence,
        },
        fact=fact,
        producer=producer,
        persistence=persistence,
    )
