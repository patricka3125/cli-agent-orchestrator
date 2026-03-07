"""Claude Code agent configuration model.

Converts AgentProfile fields to Claude Code CLI flags at runtime.
Used by ClaudeCodeProvider._build_claude_command() to extend the
base 'claude --agent <name>' command with additional flags like
--model, --allowedTools, --tools, and --settings (for hooks).
"""

import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ClaudeAgentConfig(BaseModel):
    """Claude Code agent configuration for CLI flag generation.

    Fields map to Claude Code CLI flags. MCP servers are excluded from
    to_cli_flags() because _inject_mcp_terminal_id in claude_code.py
    already handles --mcp-config separately.
    """

    name: str
    description: str

    # Optional pass-through fields mapped to CLI flags
    model: Optional[str] = None
    allowedTools: Optional[List[str]] = None
    tools: Optional[List[str]] = None
    mcpServers: Optional[Dict[str, Any]] = None
    hooks: Optional[Dict[str, Any]] = None

    def to_cli_flags(self) -> List[str]:
        """Convert config fields to a list of Claude Code CLI flag pairs.

        Returns a flat list like ["--model", "sonnet", "--tools", "Bash,Edit"].
        MCP servers are excluded (handled separately by _inject_mcp_terminal_id).
        """
        flags: List[str] = []

        if self.model:
            flags.extend(["--model", self.model])

        if self.allowedTools:
            flags.extend(["--allowedTools"] + self.allowedTools)

        if self.tools:
            flags.extend(["--tools", ",".join(self.tools)])

        if self.hooks:
            settings_json = json.dumps({"hooks": self.hooks})
            flags.extend(["--settings", settings_json])

        return flags

    class Config:
        # Exclude None values when serializing to JSON
        exclude_none = True
