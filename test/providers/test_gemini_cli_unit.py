"""Unit tests for Gemini CLI provider."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.gemini import GeminiProvider, ProviderError

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(filename: str) -> str:
    with open(FIXTURES_DIR / filename, "r") as f:
        return f.read()


class TestGeminiProviderInitialization:
    @patch("cli_agent_orchestrator.providers.gemini.wait_until_status")
    @patch("cli_agent_orchestrator.providers.gemini.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_initialize_success(self, mock_tmux, mock_wait_shell, mock_wait_status):
        mock_wait_shell.return_value = True
        mock_wait_status.return_value = True

        provider = GeminiProvider("test1234", "test-session", "window-0", None)
        result = provider.initialize()

        assert result is True
        assert provider._initialized is True
        mock_wait_shell.assert_called_once()
        sent_command = mock_tmux.send_keys.call_args.args[2]
        assert "CAO_TERMINAL_ID=test1234" in sent_command
        assert "npx @google/gemini-cli --yolo" in sent_command
        mock_wait_status.assert_called_once()

    @patch("cli_agent_orchestrator.providers.gemini.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_initialize_shell_timeout(self, mock_tmux, mock_wait_shell):
        mock_wait_shell.return_value = False

        provider = GeminiProvider("test1234", "test-session", "window-0", None)

        with pytest.raises(TimeoutError, match="Shell initialization timed out"):
            provider.initialize()

    @patch("cli_agent_orchestrator.providers.gemini.wait_until_status")
    @patch("cli_agent_orchestrator.providers.gemini.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_initialize_gemini_timeout(self, mock_tmux, mock_wait_shell, mock_wait_status):
        mock_wait_shell.return_value = True
        mock_wait_status.return_value = False

        provider = GeminiProvider("test1234", "test-session", "window-0", None)

        with pytest.raises(TimeoutError, match="Gemini CLI initialization timed out"):
            provider.initialize()


class TestGeminiBuildCommand:
    def test_build_command_no_profile(self):
        provider = GeminiProvider("test1234", "test-session", "window-0", None)
        command = provider._build_gemini_command()
        assert command == "CAO_TERMINAL_ID=test1234 npx @google/gemini-cli --yolo"

    def test_build_command_includes_terminal_id(self):
        """CAO_TERMINAL_ID is set as inline env var for MCP env expansion."""
        provider = GeminiProvider("term-abc-123", "test-session", "window-0", None)
        command = provider._build_gemini_command()
        assert command.startswith("CAO_TERMINAL_ID=term-abc-123 ")
        assert "npx @google/gemini-cli --yolo" in command

    @patch("cli_agent_orchestrator.providers.gemini.load_agent_profile")
    def test_build_command_with_agent_profile(self, mock_load_profile):
        mock_profile = MagicMock()
        mock_profile.system_prompt = "You are a code supervisor agent."
        mock_profile.mcpServers = None
        mock_load_profile.return_value = mock_profile

        provider = GeminiProvider("test1234", "test-session", "window-0", "code_supervisor")
        command = provider._build_gemini_command()

        mock_load_profile.assert_called_once_with("code_supervisor")
        assert "npx @google/gemini-cli --yolo" in command
        assert "-i" in command
        assert "You are a code supervisor agent." in command

    @patch("cli_agent_orchestrator.providers.gemini.load_agent_profile")
    def test_build_command_escapes_newlines(self, mock_load_profile):
        mock_profile = MagicMock()
        mock_profile.system_prompt = "Line one.\nLine two.\n\n## Section\n- Item"
        mock_profile.mcpServers = None
        mock_load_profile.return_value = mock_profile

        provider = GeminiProvider("test1234", "test-session", "window-0", "test_agent")
        command = provider._build_gemini_command()

        # Literal newlines must be escaped for tmux compatibility
        assert "\n" not in command
        assert "\\n" in command

    @patch("cli_agent_orchestrator.providers.gemini.load_agent_profile")
    def test_build_command_empty_system_prompt(self, mock_load_profile):
        mock_profile = MagicMock()
        mock_profile.system_prompt = ""
        mock_profile.mcpServers = None
        mock_load_profile.return_value = mock_profile

        provider = GeminiProvider("test1234", "test-session", "window-0", "empty_agent")
        command = provider._build_gemini_command()

        assert command == "CAO_TERMINAL_ID=test1234 npx @google/gemini-cli --yolo"
        assert "-i" not in command

    @patch("cli_agent_orchestrator.providers.gemini.load_agent_profile")
    def test_build_command_none_system_prompt(self, mock_load_profile):
        mock_profile = MagicMock()
        mock_profile.system_prompt = None
        mock_profile.mcpServers = None
        mock_load_profile.return_value = mock_profile

        provider = GeminiProvider("test1234", "test-session", "window-0", "none_agent")
        command = provider._build_gemini_command()

        assert command == "CAO_TERMINAL_ID=test1234 npx @google/gemini-cli --yolo"

    @patch("cli_agent_orchestrator.providers.gemini.load_agent_profile")
    def test_build_command_profile_load_failure(self, mock_load_profile):
        mock_load_profile.side_effect = RuntimeError("Profile not found")

        provider = GeminiProvider("test1234", "test-session", "window-0", "bad_agent")

        with pytest.raises(ProviderError, match="Failed to load agent profile"):
            provider._build_gemini_command()


class TestGeminiProviderStatusDetection:
    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_get_status_idle(self, mock_tmux):
        mock_tmux.get_history.return_value = load_fixture("gemini_idle_output.txt")

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.IDLE

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_get_status_completed(self, mock_tmux):
        mock_tmux.get_history.return_value = load_fixture("gemini_completed_output.txt")

        provider = GeminiProvider("test1234", "test-session", "window-0")
        provider._input_received = True
        status = provider.get_status()

        assert status == TerminalStatus.COMPLETED

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_get_status_completed_without_input_received_is_idle(self, mock_tmux):
        """Before any input is sent, a response marker should still be IDLE."""
        mock_tmux.get_history.return_value = load_fixture("gemini_completed_output.txt")

        provider = GeminiProvider("test1234", "test-session", "window-0")
        provider._input_received = False
        status = provider.get_status()

        # The welcome ✦ is present but no input was sent, so it's IDLE
        assert status == TerminalStatus.IDLE

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_get_status_processing(self, mock_tmux):
        mock_tmux.get_history.return_value = load_fixture("gemini_processing_output.txt")

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_get_status_error(self, mock_tmux):
        mock_tmux.get_history.return_value = load_fixture("gemini_error_output.txt")

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.ERROR

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_get_status_empty_output(self, mock_tmux):
        mock_tmux.get_history.return_value = ""

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.ERROR

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_get_status_waiting_user_answer(self, mock_tmux):
        mock_tmux.get_history.return_value = (
            "> delete all files\n"
            "\n"
            "Allow Gemini to run this command?\n"
            "? for shortcuts                                    YOLO\n"
        )

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.WAITING_USER_ANSWER

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_get_status_with_tail_lines(self, mock_tmux):
        mock_tmux.get_history.return_value = load_fixture("gemini_idle_output.txt")

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status(tail_lines=50)

        assert status == TerminalStatus.IDLE
        mock_tmux.get_history.assert_called_once_with("test-session", "window-0", tail_lines=50)

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_get_status_no_tui_footer_is_processing(self, mock_tmux):
        """Before TUI renders, output without footer should be PROCESSING."""
        mock_tmux.get_history.return_value = "Loading Gemini CLI...\nInitializing...\n"

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_get_status_error_before_tui_renders(self, mock_tmux):
        """Error output before TUI renders should detect as ERROR."""
        mock_tmux.get_history.return_value = "Error: Unable to connect to Gemini API.\n"

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.ERROR


class TestGeminiProviderMessageExtraction:
    def test_extract_last_message_success(self):
        output = load_fixture("gemini_completed_output.txt")

        provider = GeminiProvider("test1234", "test-session", "window-0")
        message = provider.extract_last_message_from_script(output)

        assert "Hello, world" in message
        assert "great to be here" in message

    def test_extract_message_multi_turn(self):
        output = (
            "> first question\n"
            "\n"
            "✦ First answer from Gemini.\n"
            "\n"
            "> second question\n"
            "\n"
            "✦ Second and final answer.\n"
            "\n"
            "*   Type your message\n"
            "? for shortcuts\n"
        )

        provider = GeminiProvider("test1234", "test-session", "window-0")
        message = provider.extract_last_message_from_script(output)

        # Should extract only the last response
        assert "First answer" not in message
        assert "Second and final answer." in message

    def test_extract_message_with_code_block(self):
        output = (
            "> show me a function\n"
            "\n"
            "✦ Here's a Python function:\n"
            "\n"
            "```python\n"
            "def hello():\n"
            "    print('hello world')\n"
            "```\n"
            "\n"
            "Let me know if you need changes.\n"
            "\n"
            "*   Type your message\n"
            "? for shortcuts\n"
        )

        provider = GeminiProvider("test1234", "test-session", "window-0")
        message = provider.extract_last_message_from_script(output)

        assert "def hello():" in message
        assert "Let me know if you need changes." in message

    def test_extract_message_no_marker(self):
        output = "No response marker here"

        provider = GeminiProvider("test1234", "test-session", "window-0")

        with pytest.raises(ValueError, match="No Gemini CLI response found"):
            provider.extract_last_message_from_script(output)

    def test_extract_message_empty_response(self):
        output = "✦   \n\n*   Type your message\n"

        provider = GeminiProvider("test1234", "test-session", "window-0")

        with pytest.raises(ValueError, match="Empty Gemini CLI response"):
            provider.extract_last_message_from_script(output)


class TestGeminiProviderMisc:
    def test_paste_enter_count(self):
        provider = GeminiProvider("test1234", "test-session", "window-0")
        assert provider.paste_enter_count == 2

    def test_get_idle_pattern_for_log(self):
        provider = GeminiProvider("test1234", "test-session", "window-0")
        pattern = provider.get_idle_pattern_for_log()
        assert pattern == r"\? for shortcuts"
        import re

        assert re.search(pattern, "? for shortcuts")

    def test_exit_cli(self):
        provider = GeminiProvider("test1234", "test-session", "window-0")
        assert provider.exit_cli() == "/exit"

    def test_cleanup(self):
        provider = GeminiProvider("test1234", "test-session", "window-0")
        provider._initialized = True
        provider._input_received = True
        provider.cleanup()
        assert provider._initialized is False
        assert provider._input_received is False

    def test_mark_input_received(self):
        provider = GeminiProvider("test1234", "test-session", "window-0")
        assert provider._input_received is False
        provider.mark_input_received()
        assert provider._input_received is True

    def test_init_defaults(self):
        provider = GeminiProvider("test1234", "test-session", "window-0")
        assert provider.terminal_id == "test1234"
        assert provider.session_name == "test-session"
        assert provider.window_name == "window-0"
        assert provider._agent_profile is None
        assert provider._initialized is False
        assert provider._input_received is False
        assert provider.status == TerminalStatus.IDLE

    def test_init_with_agent_profile(self):
        provider = GeminiProvider("test1234", "test-session", "window-0", "reviewer")
        assert provider._agent_profile == "reviewer"
