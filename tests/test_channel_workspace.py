"""Tests for channel workspace service."""

from __future__ import annotations

import pytest

from app.config import config as app_config
from app.schemas import ChannelWorkspace, TaskStatus
from app.workflow.channel_service import ChannelService


@pytest.fixture
def svc() -> ChannelService:
    return ChannelService(app_config)


class TestChannelCRUD:
    def test_create_channel(self, svc: ChannelService) -> None:
        """Create a channel returns valid workspace."""
        ch = svc.create_channel("Test Channel", target_lang="en")
        assert ch.channel_id
        assert ch.name == "Test Channel"
        assert ch.target_lang == "en"
        assert ch.created_at

    def test_list_channels(self, svc: ChannelService) -> None:
        """List returns created channels."""
        svc.create_channel("Channel A")
        svc.create_channel("Channel B")
        channels = svc.list_channels()
        assert len(channels) >= 2

    def test_get_channel(self, svc: ChannelService) -> None:
        """Get by ID returns correct channel."""
        ch = svc.create_channel("Find Me")
        found = svc.get_channel(ch.channel_id)
        assert found is not None
        assert found.name == "Find Me"

    def test_get_nonexistent_channel(self, svc: ChannelService) -> None:
        """Get nonexistent channel returns None."""
        assert svc.get_channel("nonexistent") is None

    def test_delete_channel(self, svc: ChannelService) -> None:
        """Delete removes channel."""
        ch = svc.create_channel("Delete Me")
        assert svc.delete_channel(ch.channel_id) is True
        assert svc.get_channel(ch.channel_id) is None

    def test_delete_nonexistent(self, svc: ChannelService) -> None:
        """Delete nonexistent returns False."""
        assert svc.delete_channel("nonexistent") is False


class TestTaskStatus:
    def test_task_status_values(self) -> None:
        """TaskStatus enum has expected values."""
        assert TaskStatus.DRAFT == "draft"
        assert TaskStatus.IN_PROGRESS == "in_progress"
        assert TaskStatus.READY_TO_STITCH == "ready_to_stitch"
        assert TaskStatus.COMPLETED == "completed"


class TestChannelWorkspace:
    def test_default_values(self) -> None:
        """ChannelWorkspace has correct defaults."""
        ch = ChannelWorkspace()
        assert ch.channel_id == ""
        assert ch.name == ""
        assert ch.target_lang == "en"
