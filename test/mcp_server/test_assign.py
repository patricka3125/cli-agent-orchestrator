"""Tests for assign MCP tool."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from cli_agent_orchestrator.mcp_server.server import _build_assign_description
from cli_agent_orchestrator.models.terminal import TerminalStatus


class TestAssignSenderIdInjection:
    """Tests for sender ID injection in _assign_impl."""

    @pytest.mark.asyncio
    @patch("cli_agent_orchestrator.mcp_server.server.asyncio.sleep", new_callable=AsyncMock)
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status", return_value=True)
    @patch("cli_agent_orchestrator.mcp_server.server.ENABLE_SENDER_ID_INJECTION", True)
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    async def test_assign_appends_sender_id_when_injection_enabled(
        self, mock_create, mock_send, mock_wait, mock_sleep
    ):
        """When injection is enabled, assign should append sender ID suffix."""
        from cli_agent_orchestrator.mcp_server.server import _assign_impl

        mock_create.return_value = ("worker-1", "claude_code")
        mock_send.return_value = None

        with patch.dict(os.environ, {"CAO_TERMINAL_ID": "supervisor-abc123"}):
            result = await _assign_impl("developer", "Analyze the logs")

        assert result["success"] is True
        sent_message = mock_send.call_args[0][1]
        assert mock_send.call_args[0][2] == "assign"
        assert sent_message.startswith("Analyze the logs")
        assert "[Assigned by terminal supervisor-abc123" in sent_message
        assert "send results back to terminal supervisor-abc123 using send_message]" in sent_message

    @pytest.mark.asyncio
    @patch("cli_agent_orchestrator.mcp_server.server.asyncio.sleep", new_callable=AsyncMock)
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status", return_value=True)
    @patch("cli_agent_orchestrator.mcp_server.server.ENABLE_SENDER_ID_INJECTION", False)
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    async def test_assign_no_suffix_when_injection_disabled(
        self, mock_create, mock_send, mock_wait, mock_sleep
    ):
        """When injection is disabled, assign should send the message unchanged."""
        from cli_agent_orchestrator.mcp_server.server import _assign_impl

        mock_create.return_value = ("worker-2", "claude_code")
        mock_send.return_value = None

        with patch.dict(os.environ, {"CAO_TERMINAL_ID": "supervisor-abc123"}):
            result = await _assign_impl("developer", "Analyze the logs")

        assert result["success"] is True
        sent_message = mock_send.call_args[0][1]
        assert mock_send.call_args[0][2] == "assign"
        assert sent_message == "Analyze the logs"

    @pytest.mark.asyncio
    @patch("cli_agent_orchestrator.mcp_server.server.asyncio.sleep", new_callable=AsyncMock)
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status", return_value=True)
    @patch("cli_agent_orchestrator.mcp_server.server.ENABLE_SENDER_ID_INJECTION", True)
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    async def test_assign_sender_id_fallback_unknown(
        self, mock_create, mock_send, mock_wait, mock_sleep
    ):
        """When CAO_TERMINAL_ID is not set, suffix should use 'unknown'."""
        from cli_agent_orchestrator.mcp_server.server import _assign_impl

        mock_create.return_value = ("worker-3", "codex")
        mock_send.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await _assign_impl("developer", "Build feature X")

        sent_message = mock_send.call_args[0][1]
        assert mock_send.call_args[0][2] == "assign"
        assert "[Assigned by terminal unknown" in sent_message

    @pytest.mark.asyncio
    @patch("cli_agent_orchestrator.mcp_server.server.asyncio.sleep", new_callable=AsyncMock)
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status", return_value=True)
    @patch("cli_agent_orchestrator.mcp_server.server.ENABLE_SENDER_ID_INJECTION", True)
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    async def test_assign_suffix_is_appended_not_prepended(
        self, mock_create, mock_send, mock_wait, mock_sleep
    ):
        """The sender ID should be a suffix, not a prefix."""
        from cli_agent_orchestrator.mcp_server.server import _assign_impl

        mock_create.return_value = ("worker-4", "claude_code")
        mock_send.return_value = None
        original = "Do the task described in /path/to/task.md"

        with patch.dict(os.environ, {"CAO_TERMINAL_ID": "sup-111"}):
            await _assign_impl("developer", original)

        sent_message = mock_send.call_args[0][1]
        assert mock_send.call_args[0][2] == "assign"
        assert sent_message.startswith(original)
        assert sent_message.index("[Assigned by terminal") > len(original)

    @pytest.mark.asyncio
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status", return_value=False)
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    async def test_assign_fails_when_terminal_not_ready(self, mock_create, mock_send, mock_wait):
        """Assign should return a failure when terminal readiness times out."""
        from cli_agent_orchestrator.mcp_server.server import _assign_impl

        mock_create.return_value = ("worker-5", "claude_code")

        result = await _assign_impl("developer", "Do something")

        assert result["success"] is False
        assert result["terminal_id"] == "worker-5"
        assert "did not reach ready status" in result["message"]
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    @patch("cli_agent_orchestrator.mcp_server.server.asyncio.sleep", new_callable=AsyncMock)
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status", return_value=True)
    @patch("cli_agent_orchestrator.mcp_server.server.ENABLE_SENDER_ID_INJECTION", False)
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    async def test_assign_waits_for_idle_or_completed(
        self, mock_create, mock_send, mock_wait, mock_sleep
    ):
        """Assign should wait for terminal readiness before sending."""
        from cli_agent_orchestrator.mcp_server.server import _assign_impl

        mock_create.return_value = ("worker-6", "claude_code")
        mock_send.return_value = None

        await _assign_impl("developer", "Task")

        mock_wait.assert_called_once_with(
            "worker-6",
            {TerminalStatus.IDLE, TerminalStatus.COMPLETED},
            timeout=120.0,
        )
        mock_sleep.assert_awaited_once_with(2)


class TestBuildAssignDescription:
    """Tests for the _build_assign_description helper.

    Covers all four combinations of (enable_sender_id, enable_workdir) flags.
    """

    # ------------------------------------------------------------------
    # Shared content assertions
    # ------------------------------------------------------------------

    def test_always_starts_with_action_sentence(self):
        """All combinations begin with the same one-liner action summary."""
        for sender_id in (True, False):
            for workdir in (True, False):
                desc = _build_assign_description(sender_id, workdir)
                assert desc.startswith("Assigns a task to another agent without blocking.")

    def test_always_contains_args_section(self):
        """All combinations include an Args section with agent_profile and message."""
        for sender_id in (True, False):
            for workdir in (True, False):
                desc = _build_assign_description(sender_id, workdir)
                assert "Args:" in desc
                assert "agent_profile:" in desc
                assert "message:" in desc

    def test_always_contains_returns_section(self):
        """All combinations include a Returns section."""
        for sender_id in (True, False):
            for workdir in (True, False):
                desc = _build_assign_description(sender_id, workdir)
                assert "Returns:" in desc
                assert "Dict with success status" in desc

    # ------------------------------------------------------------------
    # Sender ID injection flag
    # ------------------------------------------------------------------

    def test_sender_id_enabled_uses_auto_injection_overview(self):
        """When sender ID injection is on, overview says ID is automatically appended."""
        desc = _build_assign_description(enable_sender_id=True, enable_workdir=False)
        assert "automatically be appended" in desc

    def test_sender_id_enabled_omits_manual_callback_instructions(self):
        """When injection is on, no manual CAO_TERMINAL_ID instructions are included."""
        desc = _build_assign_description(enable_sender_id=True, enable_workdir=False)
        assert "CAO_TERMINAL_ID" not in desc
        assert "send results back" not in desc

    def test_sender_id_disabled_includes_manual_callback_instructions(self):
        """When injection is off, the description instructs the caller to include callback info."""
        desc = _build_assign_description(enable_sender_id=False, enable_workdir=False)
        assert "CAO_TERMINAL_ID" in desc
        assert "send results back" in desc
        assert "Example message:" in desc

    def test_sender_id_disabled_omits_auto_injection_mention(self):
        """When injection is off, no mention of automatic appending."""
        desc = _build_assign_description(enable_sender_id=False, enable_workdir=False)
        assert "automatically be appended" not in desc

    # ------------------------------------------------------------------
    # Working directory flag
    # ------------------------------------------------------------------

    def test_workdir_enabled_includes_working_directory_section(self):
        """When workdir is enabled, a '## Working Directory' section is present."""
        desc = _build_assign_description(enable_sender_id=False, enable_workdir=True)
        assert "## Working Directory" in desc
        assert "supervisor's current working directory" in desc

    def test_workdir_enabled_includes_working_directory_arg(self):
        """When workdir is on, working_directory appears in the Args section."""
        desc = _build_assign_description(enable_sender_id=False, enable_workdir=True)
        assert "working_directory:" in desc

    def test_workdir_disabled_omits_working_directory_section(self):
        """When workdir is off, no Working Directory section."""
        desc = _build_assign_description(enable_sender_id=False, enable_workdir=False)
        assert "## Working Directory" not in desc

    def test_workdir_disabled_omits_working_directory_arg(self):
        """When workdir is off, working_directory does not appear in Args."""
        desc = _build_assign_description(enable_sender_id=False, enable_workdir=False)
        assert "working_directory:" not in desc

    # ------------------------------------------------------------------
    # All four flag combinations
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "enable_sender_id, enable_workdir",
        [
            (False, False),
            (False, True),
            (True, False),
            (True, True),
        ],
    )
    def test_returns_non_empty_string(self, enable_sender_id, enable_workdir):
        """All combinations produce a non-empty string."""
        desc = _build_assign_description(enable_sender_id, enable_workdir)
        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_sender_id_true_workdir_true(self):
        """Both flags on: auto-injection overview + Working Directory section present."""
        desc = _build_assign_description(enable_sender_id=True, enable_workdir=True)
        assert "automatically be appended" in desc
        assert "## Working Directory" in desc
        assert "working_directory:" in desc
        assert "CAO_TERMINAL_ID" not in desc

    def test_sender_id_true_workdir_false(self):
        """Injection on, workdir off: no Working Directory section."""
        desc = _build_assign_description(enable_sender_id=True, enable_workdir=False)
        assert "automatically be appended" in desc
        assert "## Working Directory" not in desc
        assert "working_directory:" not in desc

    def test_sender_id_false_workdir_true(self):
        """Injection off, workdir on: manual callback instructions + Working Directory."""
        desc = _build_assign_description(enable_sender_id=False, enable_workdir=True)
        assert "CAO_TERMINAL_ID" in desc
        assert "## Working Directory" in desc
        assert "working_directory:" in desc

    def test_sender_id_false_workdir_false(self):
        """Both flags off: manual callback instructions, no Working Directory section."""
        desc = _build_assign_description(enable_sender_id=False, enable_workdir=False)
        assert "CAO_TERMINAL_ID" in desc
        assert "## Working Directory" not in desc
        assert "working_directory:" not in desc

    # ------------------------------------------------------------------
    # Structural ordering
    # ------------------------------------------------------------------

    def test_args_section_appears_after_overview(self):
        """The Args section should come after the overview text."""
        desc = _build_assign_description(enable_sender_id=False, enable_workdir=False)
        overview_pos = desc.index("Assigns a task")
        args_pos = desc.index("Args:")
        assert overview_pos < args_pos

    def test_working_directory_section_appears_before_args(self):
        """The Working Directory section should come before the Args section."""
        desc = _build_assign_description(enable_sender_id=False, enable_workdir=True)
        workdir_pos = desc.index("## Working Directory")
        args_pos = desc.index("Args:")
        assert workdir_pos < args_pos

    def test_returns_section_appears_after_args(self):
        """The Returns section should come after the Args section."""
        desc = _build_assign_description(enable_sender_id=False, enable_workdir=False)
        args_pos = desc.index("Args:")
        returns_pos = desc.index("Returns:")
        assert args_pos < returns_pos
