"""Gemini CLI provider implementation.

This module provides the GeminiProvider class for integrating with Google's
Gemini CLI (gemini), an AI-powered coding assistant.

Gemini CLI Features:
- Interactive chat with Gemini models
- File system access and code manipulation capabilities
- YOLO mode for auto-accepting tool calls (--yolo / --approval-mode yolo)
- System prompt injection via developer instructions
- MCP server configuration

The provider enforces ``ui.accessibility.screenReader = true`` and
``ui.useAlternateBuffer = false`` in ``~/.gemini/settings.json`` before
launching the CLI.  Screen-reader mode renders plain text (no Ink TUI),
which simplifies status detection — the sole signal is the **dynamic
window title** set via OSC escape sequences.

Detected terminal states (from window title):
- IDLE / COMPLETED: title contains ``Ready``
- PROCESSING: title contains ``Working``
- WAITING_USER_ANSWER: title contains ``Action Required``

Input Submission:
- Gemini CLI uses multi-line input; first Enter adds a newline, second
  Enter on an empty line submits. This is the same as Claude Code, so
  paste_enter_count = 2.
"""

import logging
import re
import shlex
import shutil
from typing import Optional

from cli_agent_orchestrator.clients.tmux import tmux_client
from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.base import BaseProvider
from cli_agent_orchestrator.utils.agent_profiles import load_agent_profile
from cli_agent_orchestrator.utils.terminal import wait_for_shell, wait_until_status

logger = logging.getLogger(__name__)


# Custom exception for provider errors
class ProviderError(Exception):
    """Exception raised for provider-specific errors."""

    pass


# =============================================================================
# Regex Patterns for Gemini CLI Output Analysis
# =============================================================================

# ANSI escape code pattern for stripping terminal colors
ANSI_CODE_PATTERN = r"\x1b\[[0-9;]*m"

# Gemini CLI uses ✦ (U+2726, FOUR POINTED STAR) to mark the start of responses.
# Example: "✦ Hello world."
RESPONSE_MARKER = "\u2726"
RESPONSE_PATTERN = rf"^{RESPONSE_MARKER}\s"

# User input prompt: when a message is submitted, it shows "> message"
USER_INPUT_PATTERN = r"^>\s+\S"


# Required settings merged into ~/.gemini/settings.json before every launch.
# Screen-reader mode produces plain text (no Ink TUI) and alternate buffer
# is disabled so tmux capture-pane works correctly.
_REQUIRED_GEMINI_SETTINGS: dict = {
    "ui": {
        "useAlternateBuffer": False,
        "accessibility": {
            "screenReader": True,
        },
    },
}


class GeminiProvider(BaseProvider):
    """Provider for Gemini CLI tool integration.

    This provider manages the lifecycle of a Gemini CLI chat session within
    a tmux window, including initialization, status detection, and response
    extraction.

    Screen-reader mode (``ui.accessibility.screenReader = true``) is enforced
    so that output is plain text.  Status detection relies exclusively on the
    dynamic window title set by Gemini CLI.

    Attributes:
        terminal_id: Unique identifier for this terminal instance
        session_name: Name of the tmux session containing this terminal
        window_name: Name of the tmux window for this terminal
        _agent_profile: Optional agent profile name for system prompt injection
        _input_received: Whether any user input has been sent since init
    """

    def __init__(
        self,
        terminal_id: str,
        session_name: str,
        window_name: str,
        agent_profile: Optional[str] = None,
    ):
        super().__init__(terminal_id, session_name, window_name)
        self._initialized = False
        self._agent_profile = agent_profile
        self._input_received = False

    @property
    def paste_enter_count(self) -> int:
        """Gemini CLI needs double-Enter to submit after bracketed paste.

        Like Claude Code, Gemini CLI enters multi-line mode after paste.
        First Enter adds a newline; second Enter on empty line submits.
        """
        return 2

    def _build_gemini_command(self) -> str:
        """Build Gemini CLI command with agent profile if provided.

        Returns properly escaped shell command string that can be safely
        sent via tmux.
        """
        # Set CAO_TERMINAL_ID as inline env var so Gemini CLI can expand
        # $CAO_TERMINAL_ID in MCP server env blocks (settings.json).
        base_cmd = (
            f"CAO_TERMINAL_ID={shlex.quote(self.terminal_id)} "
            f"npx @google/gemini-cli --yolo"
        )
        extra_args = []

        if self._agent_profile is not None:
            try:
                profile = load_agent_profile(self._agent_profile)

                system_prompt = profile.system_prompt if profile.system_prompt is not None else ""
                if system_prompt:
                    escaped_prompt = system_prompt.replace("\\", "\\\\").replace("\n", "\\n")
                    extra_args.extend(["-i", escaped_prompt])

            except Exception as e:
                raise ProviderError(f"Failed to load agent profile '{self._agent_profile}': {e}")

        if extra_args:
            return f"{base_cmd} {shlex.join(extra_args)}"
        return base_cmd

    @staticmethod
    def _ensure_gemini_settings() -> None:
        """Merge required UI settings into ``~/.gemini/settings.json``.

        Called before every launch so that screen-reader mode and
        alternate-buffer settings are guaranteed to be present.
        """
        from cli_agent_orchestrator.cli.commands.install import (
            _merge_gemini_settings,
        )

        _merge_gemini_settings(_REQUIRED_GEMINI_SETTINGS)

    def initialize(self) -> bool:
        """Initialize Gemini CLI provider by starting the gemini command.

        This method:
        1. Verifies npx is available on PATH
        2. Waits for the shell to be ready in the tmux window
        3. Merges required UI settings into settings.json
        4. Sends the gemini CLI command with --yolo flag
        5. Waits for the agent to reach IDLE state (ready for input)

        Returns:
            True if initialization was successful

        Raises:
            ProviderError: If npx is not found on PATH
            TimeoutError: If shell or Gemini CLI initialization times out
        """
        # Step 1: Verify npx is available (required to run @google/gemini-cli)
        if shutil.which("npx") is None:
            raise ProviderError(
                "npx is not available on PATH. "
                "Gemini CLI requires Node.js and npx to be installed. "
                "Install Node.js from https://nodejs.org/ and try again."
            )

        # Step 2: Wait for shell prompt to appear in the tmux window
        if not wait_for_shell(tmux_client, self.session_name, self.window_name, timeout=10.0):
            raise TimeoutError("Shell initialization timed out after 10 seconds")

        # Step 3: Ensure screen-reader mode + alt-buffer settings are in place
        self._ensure_gemini_settings()

        # Step 4: Build and send the Gemini CLI command
        command = self._build_gemini_command()
        tmux_client.send_keys(self.session_name, self.window_name, command)

        # Step 5: Wait for Gemini CLI to fully initialize and show the idle prompt.
        # Gemini CLI may take a while to start (npm/npx overhead + auth).
        if not wait_until_status(self, TerminalStatus.IDLE, timeout=60.0, polling_interval=1.0):
            raise TimeoutError("Gemini CLI initialization timed out after 60 seconds")

        self._initialized = True
        return True

    def get_status(self, tail_lines: Optional[int] = None) -> TerminalStatus:
        """Get Gemini CLI status from the dynamic window title.

        With screen-reader mode enabled, the Ink TUI is not rendered, so
        capture-pane output no longer contains reliable status indicators.
        The sole signal is the pane title set via OSC escape sequences:

        - ``◇  Ready``            → IDLE or COMPLETED
        - ``✦  Working...``       → PROCESSING
        - ``✋  Action Required``  → WAITING_USER_ANSWER

        Before the CLI boots (title is empty), we return PROCESSING.

        Args:
            tail_lines: Unused — kept for interface compatibility.

        Returns:
            Current TerminalStatus enum value
        """
        try:
            title = tmux_client.get_pane_title(self.session_name, self.window_name)
        except Exception:
            title = ""

        if title:
            if "Action Required" in title:
                return TerminalStatus.WAITING_USER_ANSWER
            if "Working" in title:
                return TerminalStatus.PROCESSING
            if "Ready" in title:
                if self._input_received:
                    return TerminalStatus.COMPLETED
                return TerminalStatus.IDLE

        # Title empty or unrecognized — CLI is still booting
        return TerminalStatus.PROCESSING

    def get_idle_pattern_for_log(self) -> str:
        """Return pattern for detecting IDLE in pipe-pane log files.

        With screen-reader mode the ✦ response marker is still present in
        plain-text output and can be used as a signal.
        """
        return RESPONSE_PATTERN

    def extract_last_message_from_script(self, script_output: str) -> str:
        """Extract Gemini's final response message using ✦ indicator.

        Gemini CLI marks each response with ✦ (U+2726). We find the last
        occurrence and extract the text between it and the next user-input
        prompt (``> ``) or another ✦ marker.

        Args:
            script_output: Raw terminal output/script content

        Returns:
            Extracted last message from Gemini

        Raises:
            ValueError: If no response is found
        """
        # Strip ANSI codes for pattern matching
        clean_output = re.sub(ANSI_CODE_PATTERN, "", script_output)

        # Find all response markers (✦)
        matches = list(re.finditer(RESPONSE_PATTERN, clean_output, re.MULTILINE))

        if not matches:
            raise ValueError("No Gemini CLI response found - no ✦ pattern detected")

        # Get the last match (final response)
        last_match = matches[-1]
        start_pos = last_match.start()

        # Extract everything after the last ✦ until a stop marker
        remaining_text = clean_output[start_pos:]

        # Split by lines and collect response lines
        lines = remaining_text.split("\n")
        response_lines = []

        for i, line in enumerate(lines):
            # Skip the first line's ✦ marker for clean extraction
            if i == 0:
                # Remove the ✦ prefix
                clean_line = re.sub(rf"^{RESPONSE_MARKER}\s*", "", line).strip()
                if clean_line:
                    response_lines.append(clean_line)
                continue

            # Stop at user-input prompt (> ) which signals end of response
            if re.match(r"^\s*>\s", line):
                break

            response_lines.append(line.rstrip())

        if not response_lines or not any(line.strip() for line in response_lines):
            raise ValueError("Empty Gemini CLI response - no content found after ✦")

        # Join lines, strip trailing whitespace, and clean up
        final_answer = "\n".join(response_lines).strip()
        # Remove any remaining ANSI codes
        final_answer = re.sub(ANSI_CODE_PATTERN, "", final_answer)
        return final_answer.strip()

    def mark_input_received(self) -> None:
        """Notify provider that user input has been sent.

        Used to distinguish between initial IDLE (no input yet) and
        COMPLETED (response received after input was sent).
        """
        self._input_received = True

    def exit_cli(self) -> str:
        """Get the command to exit Gemini CLI."""
        return "/exit"

    def cleanup(self) -> None:
        """Clean up Gemini CLI provider."""
        self._initialized = False
        self._input_received = False
