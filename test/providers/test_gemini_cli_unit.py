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
    @patch("cli_agent_orchestrator.providers.gemini.shutil")
    @patch("cli_agent_orchestrator.providers.gemini.wait_until_status")
    @patch("cli_agent_orchestrator.providers.gemini.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_initialize_success(self, mock_tmux, mock_wait_shell, mock_wait_status, mock_shutil):
        mock_shutil.which.return_value = "/usr/bin/npx"
        mock_wait_shell.return_value = True
        mock_wait_status.return_value = True

        provider = GeminiProvider("test1234", "test-session", "window-0", None)
        with patch.object(provider, "_ensure_gemini_settings"):
            result = provider.initialize()

        assert result is True
        assert provider._initialized is True
        mock_shutil.which.assert_called_once_with("npx")
        mock_wait_shell.assert_called_once()
        sent_command = mock_tmux.send_keys.call_args.args[2]
        assert "CAO_TERMINAL_ID=test1234" in sent_command
        assert "npx @google/gemini-cli --yolo" in sent_command
        mock_wait_status.assert_called_once()

    @patch("cli_agent_orchestrator.providers.gemini.shutil")
    @patch("cli_agent_orchestrator.providers.gemini.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_initialize_shell_timeout(self, mock_tmux, mock_wait_shell, mock_shutil):
        mock_shutil.which.return_value = "/usr/bin/npx"
        mock_wait_shell.return_value = False

        provider = GeminiProvider("test1234", "test-session", "window-0", None)

        with pytest.raises(TimeoutError, match="Shell initialization timed out"):
            provider.initialize()

    @patch("cli_agent_orchestrator.providers.gemini.shutil")
    @patch("cli_agent_orchestrator.providers.gemini.wait_until_status")
    @patch("cli_agent_orchestrator.providers.gemini.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_initialize_gemini_timeout(self, mock_tmux, mock_wait_shell, mock_wait_status, mock_shutil):
        mock_shutil.which.return_value = "/usr/bin/npx"
        mock_wait_shell.return_value = True
        mock_wait_status.return_value = False

        provider = GeminiProvider("test1234", "test-session", "window-0", None)

        with pytest.raises(TimeoutError, match="Gemini CLI initialization timed out"):
            with patch.object(provider, "_ensure_gemini_settings"):
                provider.initialize()

    @patch("cli_agent_orchestrator.providers.gemini.shutil")
    def test_initialize_npx_not_found(self, mock_shutil):
        """ProviderError is raised when npx is not on PATH."""
        mock_shutil.which.return_value = None

        provider = GeminiProvider("test1234", "test-session", "window-0", None)

        with pytest.raises(ProviderError, match="npx is not available on PATH"):
            provider.initialize()

    @patch("cli_agent_orchestrator.providers.gemini.shutil")
    @patch("cli_agent_orchestrator.providers.gemini.wait_until_status")
    @patch("cli_agent_orchestrator.providers.gemini.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_initialize_calls_ensure_gemini_settings(
        self, mock_tmux, mock_wait_shell, mock_wait_status, mock_shutil
    ):
        """_ensure_gemini_settings is called before sending the CLI command."""
        mock_shutil.which.return_value = "/usr/bin/npx"
        mock_wait_shell.return_value = True
        mock_wait_status.return_value = True

        provider = GeminiProvider("test1234", "test-session", "window-0", None)
        with patch.object(provider, "_ensure_gemini_settings") as mock_ensure:
            provider.initialize()
            mock_ensure.assert_called_once()

    def test_ensure_gemini_settings_calls_merge(self):
        """_ensure_gemini_settings merges required UI settings."""
        with patch(
            "cli_agent_orchestrator.providers.gemini._REQUIRED_GEMINI_SETTINGS",
            {"ui": {"useAlternateBuffer": False}},
        ) as mock_settings, patch(
            "cli_agent_orchestrator.cli.commands.install._merge_gemini_settings"
        ) as mock_merge:
            GeminiProvider._ensure_gemini_settings()
            mock_merge.assert_called_once_with(mock_settings)


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

    def test_build_command_special_chars_in_terminal_id(self):
        """Terminal IDs with shell metacharacters are safely quoted."""
        provider = GeminiProvider("term with spaces & $pecial", "test-session", "window-0", None)
        command = provider._build_gemini_command()

        # shlex.quote wraps the value so shell metacharacters are safe
        assert "npx @google/gemini-cli --yolo" in command
        # The terminal ID must appear quoted (not raw)
        assert "term with spaces" not in command.split("CAO_TERMINAL_ID=")[0]
        # Verify the command is parseable by the shell
        import shlex
        tokens = shlex.split(command)
        # First token should be the env assignment
        assert tokens[0].startswith("CAO_TERMINAL_ID=")


class TestGeminiProviderTitleBasedStatus:
    """Tests for status detection via dynamic window title."""

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_title_ready_is_idle(self, mock_tmux):
        mock_tmux.get_pane_title.return_value = "◇  Ready"
        mock_tmux.get_history.return_value = "Model: Welcome to Gemini!\n"

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.IDLE

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_title_ready_after_input_is_completed(self, mock_tmux):
        mock_tmux.get_pane_title.return_value = "◇  Ready"
        mock_tmux.get_history.return_value = "Model: Here is the answer.\n"

        provider = GeminiProvider("test1234", "test-session", "window-0")
        provider._input_received = True
        status = provider.get_status()

        assert status == TerminalStatus.COMPLETED

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_title_ready_no_model_marker_is_processing(self, mock_tmux):
        """Title flickers to Ready before CLI produces first response."""
        mock_tmux.get_pane_title.return_value = "◇  Ready"
        mock_tmux.get_history.return_value = "Loading...\n"

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_title_ready_empty_output_is_processing(self, mock_tmux):
        """Title says Ready but pane content is empty → still booting."""
        mock_tmux.get_pane_title.return_value = "◇  Ready"
        mock_tmux.get_history.return_value = ""

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_title_ready_history_error_is_processing(self, mock_tmux):
        """If get_history raises while title is Ready, default to PROCESSING."""
        mock_tmux.get_pane_title.return_value = "◇  Ready"
        mock_tmux.get_history.side_effect = Exception("capture-pane failed")

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_title_working_is_processing(self, mock_tmux):
        mock_tmux.get_pane_title.return_value = "✦  Working..."

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_title_action_required_is_waiting(self, mock_tmux):
        mock_tmux.get_pane_title.return_value = "✋  Action Required"

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.WAITING_USER_ANSWER

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_empty_title_is_processing(self, mock_tmux):
        """When title is empty (pre-boot), status should be PROCESSING."""
        mock_tmux.get_pane_title.return_value = ""

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_title_exception_is_processing(self, mock_tmux):
        """If get_pane_title raises, default to PROCESSING."""
        mock_tmux.get_pane_title.side_effect = Exception("tmux error")

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_unrecognized_title_is_processing(self, mock_tmux):
        """Unrecognized title text should default to PROCESSING."""
        mock_tmux.get_pane_title.return_value = "Some random title"

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.gemini.tmux_client")
    def test_tail_lines_ignored(self, mock_tmux):
        """tail_lines parameter is accepted but unused (interface compat)."""
        mock_tmux.get_pane_title.return_value = "◇  Ready"
        mock_tmux.get_history.return_value = "Model: Hello\n"

        provider = GeminiProvider("test1234", "test-session", "window-0")
        status = provider.get_status(tail_lines=50)

        assert status == TerminalStatus.IDLE


class TestGeminiProviderMessageExtraction:
    def test_extract_last_message_success(self):
        output = (
            "> say hello world, one sentence only\n"
            "\n"
            "Model: Hello, world — it's great to be here!\n"
        )

        provider = GeminiProvider("test1234", "test-session", "window-0")
        message = provider.extract_last_message_from_script(output)

        assert "Hello, world" in message
        assert "great to be here" in message

    def test_extract_message_multi_turn(self):
        output = (
            "> first question\n"
            "\n"
            "Model: First answer from Gemini.\n"
            "\n"
            "> second question\n"
            "\n"
            "Model: Second and final answer.\n"
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
            "Model: Here's a Python function:\n"
            "\n"
            "```python\n"
            "def hello():\n"
            "    print('hello world')\n"
            "```\n"
            "\n"
            "Let me know if you need changes.\n"
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
        output = "Model:   \n\n"

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
        import re

        # Should match the Model: response marker
        assert re.search(pattern, "Model: Hello world")

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
