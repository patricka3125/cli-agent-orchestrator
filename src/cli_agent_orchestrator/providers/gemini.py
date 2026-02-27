"""Gemini CLI provider implementation.

This module provides the GeminiProvider class for integrating with Google's
Gemini CLI (gemini), an AI-powered coding assistant that operates through
a full-screen terminal TUI (Ink-based).

Gemini CLI Features:
- Interactive chat with Gemini models
- File system access and code manipulation capabilities
- YOLO mode for auto-accepting tool calls (--yolo / --approval-mode yolo)
- System prompt injection via developer instructions
- MCP server configuration
- Full-screen TUI with status bar and input area

The provider detects the following terminal states:
- IDLE: Agent is waiting for user input (shows * prompt with placeholder text)
- PROCESSING: Agent is generating a response (no idle prompt visible)
- COMPLETED: Agent has finished responding (✦ response + * idle prompt)
- WAITING_USER_ANSWER: Agent is waiting for user approval
- ERROR: Agent encountered an error during processing

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

# Idle prompt: the input area shows "* " followed by either user text or
# the placeholder "Type your message or @path/to/file".
# The * (U+002A) appears at the start of the input bar in the bottom portion
# of the TUI. We check the last few lines for this.
IDLE_PROMPT_PATTERN = r"^\s*\*\s"

# Number of lines from bottom to check for idle prompt and TUI chrome.
# Gemini CLI uses a full-screen TUI, so the idle prompt and status bar
# are always rendered at the bottom.
IDLE_PROMPT_TAIL_LINES = 8

# Placeholder text shown in the input area when idle
IDLE_PLACEHOLDER_PATTERN = r"Type your message"

# TUI status bar / footer indicators
TUI_FOOTER_PATTERN = r"\? for shortcuts"
TUI_STATUS_BAR_PATTERN = r"(?:/model\s|no sandbox|YOLO)"

# Processing indicator: Gemini shows a spinner/thinking indicator while
# generating. The key signal is absence of the idle prompt (* ) in the
# bottom lines.

# Approval/permission prompt patterns (when not in YOLO mode)
APPROVAL_PROMPT_PATTERN = r"(?:Allow|Approve|Confirm).*\?"

# Error indicators
ERROR_INDICATORS = [
    "Error:",
    "error:",
    "Something went wrong",
    "Unable to connect",
    "rate limit",
]

# The idle prompt pattern for pipe-pane log files (raw stream).
# In the raw TUI output, the * prompt is rendered with ANSI color codes.
# The pattern matches the colored * followed by the placeholder or empty input.
# Since Gemini uses a full-screen TUI (alternate screen), pipe-pane may not
# capture useful output. We use the "? for shortcuts" footer text as a
# reliable indicator that the TUI is active and rendered.
IDLE_PROMPT_PATTERN_LOG = r"\? for shortcuts"

# Separator lines used by Gemini CLI TUI (box drawing characters)
SEPARATOR_PATTERN = r"^[─▀▄]{10,}"


class GeminiProvider(BaseProvider):
    """Provider for Gemini CLI tool integration.

    This provider manages the lifecycle of a Gemini CLI chat session within
    a tmux window, including initialization, status detection, and response
    extraction.

    Gemini CLI runs as a full-screen Ink TUI (similar to Codex with alt screen).
    Status detection uses tmux capture-pane to read the rendered screen.

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

    def initialize(self) -> bool:
        """Initialize Gemini CLI provider by starting the gemini command.

        This method:
        1. Verifies npx is available on PATH
        2. Waits for the shell to be ready in the tmux window
        3. Sends the gemini CLI command with --yolo flag
        4. Waits for the agent to reach IDLE state (ready for input)

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

        # Step 3: Build and send the Gemini CLI command
        command = self._build_gemini_command()
        tmux_client.send_keys(self.session_name, self.window_name, command)

        # Step 4: Wait for Gemini CLI to fully initialize and show the idle prompt.
        # Gemini CLI may take a while to start (npm/npx overhead + auth).
        if not wait_until_status(self, TerminalStatus.IDLE, timeout=60.0, polling_interval=1.0):
            raise TimeoutError("Gemini CLI initialization timed out after 60 seconds")

        self._initialized = True
        return True

    def get_status(self, tail_lines: Optional[int] = None) -> TerminalStatus:
        """Get Gemini CLI status by analyzing the dynamic window title.

        Gemini CLI sets the terminal pane title via OSC escape sequences when
        ``ui.dynamicWindowTitle`` is enabled (default). The title reflects the
        agent's current state:

        - ``◇  Ready``            → IDLE or COMPLETED
        - ``✦  Working...``       → PROCESSING
        - ``✋  Action Required``  → WAITING_USER_ANSWER

        If the title is empty or unrecognized (pre-boot, feature disabled, or
        an error state), we fall back to capture-pane output parsing.

        Args:
            tail_lines: Number of lines to capture from terminal history
                        (used only by the capture-pane fallback).

        Returns:
            Current TerminalStatus enum value
        """
        # --- Primary: window title ---
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

        # --- Fallback: capture-pane output parsing ---
        return self._get_status_from_output(tail_lines=tail_lines)

    def _get_status_from_output(self, tail_lines: Optional[int] = None) -> TerminalStatus:
        """Fallback status detection by analyzing captured terminal output.

        Used when the pane title is empty or unrecognized (e.g., before the
        TUI boots, when ``ui.dynamicWindowTitle`` is disabled, or for error
        detection which the title does not cover).

        Status detection logic (in priority order):
        1. No output → ERROR
        2. Check bottom lines for idle prompt (* )
        3. If idle prompt found + ✦ response marker → COMPLETED
        4. If idle prompt found + no response → IDLE
        5. If approval prompt visible → WAITING_USER_ANSWER
        6. Error indicators → ERROR
        7. Default → PROCESSING

        Args:
            tail_lines: Number of lines to capture from terminal history.

        Returns:
            Current TerminalStatus enum value
        """
        output = tmux_client.get_history(self.session_name, self.window_name, tail_lines=tail_lines)

        if not output:
            return TerminalStatus.ERROR

        # Strip ANSI codes for reliable pattern matching
        clean_output = re.sub(ANSI_CODE_PATTERN, "", output)

        # Get the bottom lines where the TUI chrome lives
        all_lines = clean_output.splitlines()
        bottom_lines = all_lines[-IDLE_PROMPT_TAIL_LINES:]

        # Check for the idle prompt (* ) in the bottom portion of the screen
        has_idle_prompt = any(
            re.search(IDLE_PROMPT_PATTERN, line) for line in bottom_lines
        )

        # Check for TUI footer (? for shortcuts) to confirm TUI is rendered
        has_tui_footer = any(
            re.search(TUI_FOOTER_PATTERN, line) for line in all_lines
        )

        if not has_tui_footer:
            # TUI hasn't rendered yet or has crashed
            # Check for error indicators in raw output
            for indicator in ERROR_INDICATORS:
                if indicator.lower() in clean_output.lower():
                    return TerminalStatus.ERROR
            return TerminalStatus.PROCESSING

        # Check for approval prompts (when not in YOLO mode)
        if re.search(APPROVAL_PROMPT_PATTERN, clean_output, re.IGNORECASE):
            return TerminalStatus.WAITING_USER_ANSWER

        # Check for error indicators
        for indicator in ERROR_INDICATORS:
            if indicator.lower() in clean_output.lower():
                # Only count as error if we also have an idle prompt
                # (error message displayed, agent returned to prompt)
                if has_idle_prompt:
                    return TerminalStatus.ERROR

        if has_idle_prompt:
            # Check if there's a completed response (✦ marker) in the output
            # Look for ✦ in the main content area (above the input bar)
            has_response = bool(re.search(RESPONSE_PATTERN, clean_output, re.MULTILINE))

            if has_response and self._input_received:
                return TerminalStatus.COMPLETED

            # Idle with no response (or pre-first-input)
            return TerminalStatus.IDLE

        # No idle prompt visible — agent is processing
        return TerminalStatus.PROCESSING

    def get_idle_pattern_for_log(self) -> str:
        """Return Gemini CLI IDLE prompt pattern for log files.

        Since Gemini CLI uses a full-screen TUI, the raw pipe-pane output
        may contain TUI escape sequences. We use the footer text as indicator.
        """
        return IDLE_PROMPT_PATTERN_LOG

    def extract_last_message_from_script(self, script_output: str) -> str:
        """Extract Gemini's final response message using ✦ indicator.

        Gemini CLI marks each response with ✦ (U+2726). We find the last
        occurrence and extract the text between it and the next idle prompt
        or separator.

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

        # Extract everything after the last ✦ until the next separator or input area
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

            # Stop at TUI chrome lines (separator bars, status bar, input prompt)
            stripped = line.strip()
            if re.match(SEPARATOR_PATTERN, stripped):
                break
            if re.search(TUI_FOOTER_PATTERN, line):
                break
            if re.search(TUI_STATUS_BAR_PATTERN, line):
                break
            if re.match(r"^\s*\*\s", line):
                break
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
