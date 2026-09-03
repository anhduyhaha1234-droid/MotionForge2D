"""S11-T03A detector registry contract (W5).

Registry contract ready for W6 detector modules (T03B/C/D/E) to register
their detect entry points before the runner executes them:

- ``register`` is identity-idempotent: re-registering the SAME name with the
  SAME entry point succeeds and returns the (refreshed) registration;
  registering an existing name with a DIFFERENT entry point raises the
  stable ``QC_REGISTRY_CONFLICT`` error;
- ``unregister`` is idempotent: removing an absent name returns False
  without raising;
- ``get`` on an unknown name raises the stable ``QC_REGISTRY_UNKNOWN`` error
  (fail-closed — an unregistered detector can never run silently);
- invalid registration arguments raise ``QC_REGISTRY_INVALID_ARGS``
  (fail-closed, before any state change).

A module-level singleton ``registry`` backs the convenience functions
``register_detector`` / ``get_detector`` / ``unregister_detector`` used by
the runner and by W6 detector modules.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Stable error codes (string constants — contracts depend on the exact
#: values, do not reword).
QC_REGISTRY_CONFLICT = "QC_REGISTRY_CONFLICT"
QC_REGISTRY_UNKNOWN = "QC_REGISTRY_UNKNOWN"
QC_REGISTRY_INVALID_ARGS = "QC_REGISTRY_INVALID_ARGS"


class QcRegistryError(Exception):
    """Registry contract violation carrying a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class DetectorSpec:
    """Immutable registration record describing one detector entry point."""

    name: str
    entry_point: str  # "module:qualname" — resolvable by the runner child
    version: str = "1.0.0"
    description: str = ""


class DetectorRegistry:
    """Name -> DetectorSpec registry with the T03A contract semantics."""

    def __init__(self) -> None:
        self._detectors: dict[str, DetectorSpec] = {}

    def register(
        self,
        name: str,
        entry_point: str,
        *,
        version: str = "1.0.0",
        description: str = "",
    ) -> DetectorSpec:
        """Register (or idempotently re-register) a detector.

        Returns the current registration.  Raises ``QcRegistryError`` with
        ``QC_REGISTRY_INVALID_ARGS`` for malformed input and
        ``QC_REGISTRY_CONFLICT`` when the name is owned by a different
        entry point.
        """
        name = (name or "").strip()
        entry_point = (entry_point or "").strip()
        version = (version or "").strip()
        if not name or not entry_point:
            raise QcRegistryError(
                QC_REGISTRY_INVALID_ARGS,
                "detector name and entry_point must be non-empty",
            )
        module_name, _, qualname = entry_point.partition(":")
        if not module_name or not qualname:
            raise QcRegistryError(
                QC_REGISTRY_INVALID_ARGS,
                f"entry_point must be 'module:qualname', got {entry_point!r}",
            )

        existing = self._detectors.get(name)
        if existing is not None:
            if existing.entry_point != entry_point:
                raise QcRegistryError(
                    QC_REGISTRY_CONFLICT,
                    f"detector name {name!r} already registered with a "
                    f"different entry point: {existing.entry_point!r}",
                )
            spec = DetectorSpec(
                name=name,
                entry_point=entry_point,
                version=version or existing.version,
                description=description or existing.description,
            )
        else:
            spec = DetectorSpec(
                name=name,
                entry_point=entry_point,
                version=version or "1.0.0",
                description=description or "",
            )
        self._detectors[name] = spec
        return spec

    def unregister(self, name: str) -> bool:
        """Remove a registration.  Idempotent: absent names return False."""
        return self._detectors.pop(name, None) is not None

    def get(self, name: str) -> DetectorSpec:
        """Return the registration or raise ``QC_REGISTRY_UNKNOWN``."""
        spec = self._detectors.get(name)
        if spec is None:
            raise QcRegistryError(
                QC_REGISTRY_UNKNOWN,
                f"detector not registered: {name!r}",
            )
        return spec

    def names(self) -> list[str]:
        """Registered names in registration order."""
        return list(self._detectors)


#: Module-level singleton used by the runner and by W6 detector modules.
registry = DetectorRegistry()


def register_detector(
    name: str,
    entry_point: str,
    *,
    version: str = "1.0.0",
    description: str = "",
) -> DetectorSpec:
    """Convenience: register into the module singleton registry."""
    return registry.register(
        name, entry_point, version=version, description=description
    )


def get_detector(name: str) -> DetectorSpec:
    """Convenience: resolve from the module singleton registry."""
    return registry.get(name)


def unregister_detector(name: str) -> bool:
    """Convenience: idempotent removal from the module singleton registry."""
    return registry.unregister(name)