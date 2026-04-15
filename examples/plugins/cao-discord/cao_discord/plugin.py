"""Discord plugin lifecycle and configuration management."""

import os

import httpx
from dotenv import find_dotenv, load_dotenv

from cli_agent_orchestrator.plugins.base import CaoPlugin


class DiscordPlugin(CaoPlugin):
    """Discord plugin scaffold with configuration and client lifecycle."""

    _webhook_url: str
    _client: httpx.AsyncClient

    async def setup(self) -> None:
        """Load configuration and initialize the HTTP client."""

        load_dotenv(find_dotenv(usecwd=True))

        webhook_url = os.environ.get("CAO_DISCORD_WEBHOOK_URL")
        if not webhook_url:
            raise RuntimeError(
                "CAO_DISCORD_WEBHOOK_URL is not set. "
                "Set it in the environment or in a .env file before starting cao-server."
            )

        self._webhook_url = webhook_url
        timeout = float(os.environ.get("CAO_DISCORD_TIMEOUT_SECONDS", "5.0"))
        self._client = httpx.AsyncClient(timeout=timeout)

    async def teardown(self) -> None:
        """Close the HTTP client when setup completed successfully."""

        if hasattr(self, "_client"):
            await self._client.aclose()
