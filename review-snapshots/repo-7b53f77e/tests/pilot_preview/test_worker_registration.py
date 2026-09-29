from __future__ import annotations

from app.workflow.pilot_preview_jobs import JOB_TYPE_PILOT_PREVIEW, register_pilot_preview_handler


class FakeWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def register_handler(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))


def test_pilot_handler_uses_manifest_bound_output_validator() -> None:
    worker = FakeWorker()
    register_pilot_preview_handler(worker)
    assert len(worker.calls) == 1
    args, kwargs = worker.calls[0]
    assert args[0] == JOB_TYPE_PILOT_PREVIEW
    assert kwargs["declared_outputs"] is None
    assert callable(kwargs["output_validator"])
    assert kwargs["resource_class"] == "cpu_video_preview"
