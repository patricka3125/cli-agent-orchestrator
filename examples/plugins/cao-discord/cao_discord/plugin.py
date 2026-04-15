"""Stub plugin for CAO entry-point discovery tests."""

from cli_agent_orchestrator.plugins.base import CaoPlugin


class DiscordPlugin(CaoPlugin):
    """Minimal Discord plugin scaffold for registry discovery."""

    async def setup(self) -> None:
        """Perform plugin startup initialization."""

    async def teardown(self) -> None:
        """Perform plugin shutdown cleanup."""
