"""Tests for Discord plugin configuration loading and lifecycle."""

from unittest.mock import AsyncMock

import pytest

from cao_discord.plugin import DiscordPlugin


def _timeout_values(plugin: DiscordPlugin) -> tuple[float | None, float | None, float | None, float | None]:
    """Return the configured timeout values from the plugin's HTTP client."""

    timeout = plugin._client.timeout
    return timeout.connect, timeout.read, timeout.write, timeout.pool


@pytest.mark.asyncio
async def test_setup_raises_when_webhook_url_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Missing configuration should raise a RuntimeError with guidance."""

    monkeypatch.delenv("CAO_DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("CAO_DISCORD_TIMEOUT_SECONDS", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("cao_discord.plugin.find_dotenv", lambda usecwd=True: "")

    plugin = DiscordPlugin()

    with pytest.raises(RuntimeError, match="CAO_DISCORD_WEBHOOK_URL"):
        await plugin.setup()


@pytest.mark.asyncio
async def test_setup_reads_webhook_url_from_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A .env file in the process CWD should populate the webhook URL."""

    webhook_url = "https://discord.example/from-dotenv"
    (tmp_path / ".env").write_text(f"CAO_DISCORD_WEBHOOK_URL={webhook_url}\n", encoding="utf-8")

    monkeypatch.delenv("CAO_DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("CAO_DISCORD_TIMEOUT_SECONDS", raising=False)
    monkeypatch.chdir(tmp_path)

    plugin = DiscordPlugin()
    await plugin.setup()

    assert plugin._webhook_url == webhook_url
    await plugin.teardown()


@pytest.mark.asyncio
async def test_setup_prefers_process_env_over_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Process environment variables should override .env values."""

    dotenv_url = "https://discord.example/from-dotenv"
    env_url = "https://discord.example/from-env"
    (tmp_path / ".env").write_text(f"CAO_DISCORD_WEBHOOK_URL={dotenv_url}\n", encoding="utf-8")

    monkeypatch.setenv("CAO_DISCORD_WEBHOOK_URL", env_url)
    monkeypatch.delenv("CAO_DISCORD_TIMEOUT_SECONDS", raising=False)
    monkeypatch.chdir(tmp_path)

    plugin = DiscordPlugin()
    await plugin.setup()

    assert plugin._webhook_url == env_url
    await plugin.teardown()


@pytest.mark.asyncio
async def test_setup_uses_configured_timeout_or_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Timeout should default to 5.0 seconds and honor configured overrides."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("cao_discord.plugin.find_dotenv", lambda usecwd=True: "")

    default_plugin = DiscordPlugin()
    monkeypatch.setenv("CAO_DISCORD_WEBHOOK_URL", "https://discord.example/default-timeout")
    monkeypatch.delenv("CAO_DISCORD_TIMEOUT_SECONDS", raising=False)
    await default_plugin.setup()

    configured_plugin = DiscordPlugin()
    monkeypatch.setenv("CAO_DISCORD_WEBHOOK_URL", "https://discord.example/custom-timeout")
    monkeypatch.setenv("CAO_DISCORD_TIMEOUT_SECONDS", "2.5")
    await configured_plugin.setup()

    assert _timeout_values(default_plugin) == (5.0, 5.0, 5.0, 5.0)
    assert _timeout_values(configured_plugin) == (2.5, 2.5, 2.5, 2.5)

    await default_plugin.teardown()
    await configured_plugin.teardown()


@pytest.mark.asyncio
async def test_teardown_is_safe_after_failed_setup(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Teardown should be a no-op when setup failed before client creation."""

    monkeypatch.delenv("CAO_DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("CAO_DISCORD_TIMEOUT_SECONDS", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("cao_discord.plugin.find_dotenv", lambda usecwd=True: "")

    plugin = DiscordPlugin()

    with pytest.raises(RuntimeError, match="CAO_DISCORD_WEBHOOK_URL"):
        await plugin.setup()

    await plugin.teardown()


@pytest.mark.asyncio
async def test_teardown_closes_client_after_successful_setup(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Successful setup should create a client that teardown closes."""

    monkeypatch.setenv("CAO_DISCORD_WEBHOOK_URL", "https://discord.example/teardown")
    monkeypatch.delenv("CAO_DISCORD_TIMEOUT_SECONDS", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("cao_discord.plugin.find_dotenv", lambda usecwd=True: "")

    plugin = DiscordPlugin()
    await plugin.setup()
    plugin._client.aclose = AsyncMock()

    await plugin.teardown()

    plugin._client.aclose.assert_awaited_once()
