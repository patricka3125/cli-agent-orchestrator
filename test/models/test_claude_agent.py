"""Tests for Claude Code agent configuration model."""

import json

import pytest

from cli_agent_orchestrator.models.claude_agent import ClaudeAgentConfig


class TestClaudeAgentConfigConstruction:
    """Tests for ClaudeAgentConfig model construction."""

    def test_minimal_config(self):
        """Test constructing config with only required fields."""
        config = ClaudeAgentConfig(name="test", description="Test agent")
        assert config.name == "test"
        assert config.description == "Test agent"
        assert config.model is None
        assert config.allowedTools is None
        assert config.tools is None
        assert config.mcpServers is None
        assert config.hooks is None

    def test_full_config(self):
        """Test constructing config with all fields populated."""
        config = ClaudeAgentConfig(
            name="full-agent",
            description="Full agent",
            model="claude-sonnet-4-6",
            allowedTools=["Read", "Edit", "Bash(git *)"],
            tools=["Bash", "Edit", "Read"],
            mcpServers={"my-server": {"command": "my-cmd"}},
            hooks={"PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "echo test"}]}]},
        )
        assert config.model == "claude-sonnet-4-6"
        assert len(config.allowedTools) == 3
        assert len(config.tools) == 3
        assert "my-server" in config.mcpServers
        assert "PreToolUse" in config.hooks


class TestToCliFlags:
    """Tests for ClaudeAgentConfig.to_cli_flags() method."""

    def test_empty_flags_when_no_optionals(self):
        """Test that to_cli_flags returns empty list when no optional fields are set."""
        config = ClaudeAgentConfig(name="test", description="Test")
        assert config.to_cli_flags() == []

    def test_model_flag(self):
        """Test --model flag generation."""
        config = ClaudeAgentConfig(name="test", description="Test", model="sonnet")
        flags = config.to_cli_flags()
        assert flags == ["--model", "sonnet"]

    def test_allowed_tools_flag(self):
        """Test --allowedTools flag generation with space-separated list."""
        config = ClaudeAgentConfig(
            name="test", description="Test",
            allowedTools=["Read", "Edit", "Bash(git *)"],
        )
        flags = config.to_cli_flags()
        assert flags == ["--allowedTools", "Read", "Edit", "Bash(git *)"]

    def test_tools_flag(self):
        """Test --tools flag generation with comma-separated list."""
        config = ClaudeAgentConfig(
            name="test", description="Test",
            tools=["Bash", "Edit", "Read"],
        )
        flags = config.to_cli_flags()
        assert flags == ["--tools", "Bash,Edit,Read"]

    def test_hooks_flag_via_settings(self):
        """Test hooks passed via --settings flag as JSON."""
        hook_config = {
            "PreToolUse": [
                {"matcher": "Edit", "hooks": [{"type": "command", "command": "echo pre"}]}
            ]
        }
        config = ClaudeAgentConfig(
            name="test", description="Test",
            hooks=hook_config,
        )
        flags = config.to_cli_flags()
        assert flags[0] == "--settings"
        parsed = json.loads(flags[1])
        assert "hooks" in parsed
        assert parsed["hooks"] == hook_config

    def test_mcp_servers_excluded_from_flags(self):
        """Test that mcpServers are NOT included in CLI flags."""
        config = ClaudeAgentConfig(
            name="test", description="Test",
            mcpServers={"server1": {"command": "test-cmd"}},
        )
        flags = config.to_cli_flags()
        assert flags == []
        assert "--mcp-config" not in flags

    def test_all_flags_combined(self):
        """Test generating all supported flags together."""
        config = ClaudeAgentConfig(
            name="test", description="Test",
            model="opus",
            allowedTools=["Read"],
            tools=["Bash", "Read"],
            hooks={"PostToolUse": []},
            mcpServers={"s1": {"command": "cmd"}},  # should be excluded
        )
        flags = config.to_cli_flags()
        assert "--model" in flags
        assert "opus" in flags
        assert "--allowedTools" in flags
        assert "Read" in flags
        assert "--tools" in flags
        assert "Bash,Read" in flags
        assert "--settings" in flags
        assert "--mcp-config" not in flags

    def test_flag_ordering(self):
        """Test that flags are generated in consistent order: model, allowedTools, tools, settings."""
        config = ClaudeAgentConfig(
            name="test", description="Test",
            model="haiku",
            allowedTools=["Read"],
            tools=["Bash"],
            hooks={"PreToolUse": []},
        )
        flags = config.to_cli_flags()
        model_idx = flags.index("--model")
        allowed_idx = flags.index("--allowedTools")
        tools_idx = flags.index("--tools")
        settings_idx = flags.index("--settings")
        assert model_idx < allowed_idx < tools_idx < settings_idx


class TestJsonSerialization:
    """Tests for ClaudeAgentConfig JSON serialization."""

    def test_exclude_none(self):
        """Test that None fields are excluded from JSON serialization."""
        config = ClaudeAgentConfig(name="test", description="Test", model="sonnet")
        data = json.loads(config.model_dump_json(exclude_none=True))
        assert "model" in data
        assert "allowedTools" not in data
        assert "tools" not in data
        assert "hooks" not in data
        assert "mcpServers" not in data
