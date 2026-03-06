# AGENTS.md — CLI Agent Orchestrator

## Project Overview

CLI Agent Orchestrator (CAO, pronounced "kay-oh") is a lightweight orchestration system for managing multiple AI agent sessions in tmux terminals. It enables hierarchical multi-agent collaboration via MCP server, where a supervisor agent coordinates work across specialized worker agents.

- **Language:** Python 3.10+
- **Package Manager:** [uv](https://docs.astral.sh/uv/)
- **Build System:** Hatchling
- **Framework:** FastAPI (HTTP API on port 9889)
- **License:** Apache-2.0

## Repository Layout

```
cli-agent-orchestrator/
├── src/cli_agent_orchestrator/    # Main source package
│   ├── api/                       # FastAPI HTTP server (cao-server, port 9889)
│   ├── cli/commands/              # CLI entry points (cao launch, cao install, cao shutdown, cao flow, etc.)
│   ├── clients/                   # External system clients (tmux, SQLite database)
│   ├── mcp_server/                # MCP server (handoff, assign, send_message tools)
│   ├── models/                    # Pydantic data models (Terminal, Session, InboxMessage, Flow, AgentProfile)
│   ├── providers/                 # CLI tool provider integrations
│   │   ├── base.py                # Abstract provider interface
│   │   ├── manager.py             # Provider registry (maps terminal_id → provider)
│   │   ├── kiro_cli.py            # Kiro CLI provider (default)
│   │   ├── claude_code.py         # Claude Code provider
│   │   ├── codex.py               # Codex/ChatGPT CLI provider
│   │   └── q_cli.py               # Amazon Q CLI provider
│   ├── services/                  # Business logic layer (session, terminal, inbox, flow)
│   ├── utils/                     # Utilities (ID generation, logging, agent profiles, templates)
│   ├── agent_store/               # Built-in agent profile definitions (.md files)
│   └── constants.py               # Application-wide constants
├── test/                          # Test suite (mirrors src/ structure)
│   ├── api/                       # API endpoint tests
│   ├── cli/                       # CLI command tests
│   ├── clients/                   # Client tests
│   ├── e2e/                       # End-to-end tests (require running CAO server + tmux)
│   ├── mcp_server/                # MCP server tests
│   ├── models/                    # Data model tests
│   ├── providers/                 # Provider unit + integration tests
│   ├── services/                  # Service layer tests
│   └── utils/                     # Utility tests
├── docs/                          # Provider docs, API docs, architecture assets
├── examples/                      # Example workflows (assign, flow, etc.)
├── tasks/                         # Task definitions
├── scripts/                       # Helper scripts
├── pyproject.toml                 # Project config, dependencies, tool settings
├── mypy.ini                       # Type checking configuration
├── CODEBASE.md                    # Detailed architecture & data flow documentation
├── DEVELOPMENT.md                 # Dev environment setup & testing guide
└── CONTRIBUTING.md                # Contribution guidelines
```

## Architecture

CAO follows a layered architecture:

```
Entry Points (CLI commands, MCP server)
         ↓
   FastAPI HTTP API (:9889)
         ↓
   Services Layer (session, terminal, inbox, flow)
         ↓
   ┌─────────────┬───────────────┐
   │   Clients   │   Providers   │
   │ (tmux, db)  │ (kiro, claude,│
   │             │  codex, q)    │
   └─────────────┴───────────────┘
```

- **Entry points:** `cao` (CLI), `cao-server` (FastAPI), `cao-mcp-server` (MCP server)
- **Services** contain business logic and orchestrate clients/providers
- **Clients** wrap external systems (tmux sessions, SQLite)
- **Providers** abstract each CLI agent tool (Kiro CLI, Claude Code, Codex, Q CLI) behind a common interface defined in `providers/base.py`

See [CODEBASE.md](CODEBASE.md) for detailed data flow diagrams.

## Development Setup

```bash
# Clone and install
git clone https://github.com/awslabs/cli-agent-orchestrator.git
cd cli-agent-orchestrator/
uv sync          # Creates .venv/ and installs all deps
uv run cao --help  # Verify
```

### Prerequisites

- Python 3.10+
- tmux 3.3+
- [uv](https://docs.astral.sh/uv/) package manager

## Running Tests

```bash
# Unit tests only (fast, no external deps)
uv run pytest test/ --ignore=test/e2e --ignore=test/providers/test_q_cli_integration.py -v

# Unit tests with coverage
uv run pytest test/ --ignore=test/e2e --cov=src --cov-report=term-missing -v

# Specific provider tests
uv run pytest test/providers/test_claude_code_unit.py -v
uv run pytest test/providers/test_codex_provider_unit.py -v
uv run pytest test/providers/test_kiro_cli_unit.py -v
uv run pytest test/providers/test_q_cli_unit.py -v

# E2E tests (require running cao-server + tmux + authenticated CLI tools)
uv run pytest -m e2e test/e2e/ -v

# Run all tests
uv run pytest -v
```

### Test Markers

| Marker        | Purpose                                    |
|---------------|--------------------------------------------|
| `asyncio`     | Async tests                                |
| `integration` | Integration tests (require real CLI tools) |
| `e2e`         | End-to-end tests (require full stack)      |
| `slow`        | Long-running tests                         |

Default `pytest` config (`pyproject.toml`) excludes `e2e` tests and includes coverage.

## Code Quality

```bash
# Formatting (black, line-length 100, target py310)
uv run black src/ test/

# Import sorting (isort, black-compatible profile)
uv run isort src/ test/

# Type checking (mypy, strict mode)
uv run mypy src/
```

### Style Rules

- **Line length:** 100 characters (configured in `pyproject.toml`)
- **Formatting:** `black` with `target-version = ['py310']`
- **Import sorting:** `isort` with `profile = "black"`
- **Type checking:** `mypy` with `strict = true` (see `mypy.ini` for per-module overrides)

## Key Concepts for Agents

### Provider Pattern

All CLI tool integrations follow the abstract interface in `providers/base.py`. When adding a new provider:

1. Subclass the base provider
2. Implement required methods: `initialize()`, `get_status()`, `get_output()`, `build_command()`, `exit_agent()`
3. Register in `providers/manager.py`
4. Add the provider type to `models/provider.py` (`ProviderType` enum)
5. Add corresponding unit tests mirroring existing provider test files

### Orchestration Modes

CAO supports three orchestration patterns between agents:

- **Handoff** — Synchronous: create terminal → send task → wait for completion → return output → exit
- **Assign** — Asynchronous: create terminal → send task → return immediately (agent calls back via `send_message`)
- **Send Message** — Direct communication with an existing agent's inbox

### Agent Profiles

Agent profiles are Markdown files with YAML frontmatter (name, description). They define agent behavior and are stored in:
- Built-in: `src/cli_agent_orchestrator/agent_store/`
- User-installed: `~/.aws/cli-agent-orchestrator/agent-store/`

### Terminal ID System

Each agent terminal gets a unique `CAO_TERMINAL_ID` environment variable. The server uses this to route messages, track status (`IDLE`, `PROCESSING`, `COMPLETED`, `ERROR`), and coordinate orchestration.

### Data Storage

- **SQLite** database at `~/.aws/cli-agent-orchestrator/db/cli-agent-orchestrator.db`
- Tables: `terminals`, `inbox_messages`
- Terminal logs: `~/.aws/cli-agent-orchestrator/logs/terminal/`

## CI/CD

CI runs on all pushes to `main` and all PRs:

- **Unit tests:** Python 3.10, 3.11, 3.12 matrix with coverage
- **Code quality:** black, isort, mypy
- **Security scan:** Trivy (CRITICAL/HIGH)
- **Dependency review:** License and vulnerability checks on PRs

Provider-specific workflows trigger only when relevant files change (see `.github/workflows/`).

## Useful References

- [README.md](README.md) — User-facing docs, quick start, orchestration modes
- [CODEBASE.md](CODEBASE.md) — Architecture diagrams and data flow documentation
- [DEVELOPMENT.md](DEVELOPMENT.md) — Full development guide with troubleshooting
- [CONTRIBUTING.md](CONTRIBUTING.md) — Contribution workflow
- [docs/api.md](docs/api.md) — REST API documentation
- [docs/agent-profile.md](docs/agent-profile.md) — Agent profile format specification
- [docs/claude-code.md](docs/claude-code.md) — Claude Code provider docs
- [docs/codex-cli.md](docs/codex-cli.md) — Codex CLI provider docs
- [docs/kiro-cli.md](docs/kiro-cli.md) — Kiro CLI provider docs
