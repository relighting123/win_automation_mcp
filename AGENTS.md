# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

This is a **FastMCP Windows Automation Server** (`win_mcp`) — a Python project that uses pywinauto + WinOCR to let LLMs control Windows desktop applications via the MCP protocol. See `README.md` for full architecture and available tools.

### Environment constraints

- **Core dependencies** (`pywinauto`, `winocr`, `pyautogui`) are **Windows-only** and cannot be installed on Linux.
- On Linux (Cloud Agent VMs), the MCP server starts successfully — pywinauto absence is handled gracefully at runtime (logged as a warning). All 22 MCP tools register, but tools that invoke pywinauto/WinOCR will return errors when called.
- `core/network_utils.py` (`kill_process_on_port`) uses Windows-specific commands (`netstat`, `taskkill`). On Linux it will fail silently; if port 8000 is already in use, manually kill the occupying process before starting the server.

### Running the MCP server

```bash
python3 mcp_server.py --transport http --host 127.0.0.1 --port 8000 --path /mcp
```

The server listens at `http://127.0.0.1:8000/mcp` (Streamable HTTP / JSON-RPC).

### Running tests

```bash
python3 -m pytest tests/test_logic.py -v
```

- `tests/test_logic.py` — unit tests with mocked dependencies; runs on Linux.
- `tests/test_feature_execution_skill.py` — references a missing module (`skills/feature_execution_skill.py`); will fail with `ModuleNotFoundError`. This is a pre-existing issue in the repo.
- Other `tests/verify_*.py` files are integration/manual tests that require a live Windows environment.

### Linting

No linter config file is committed. Use `ruff check .` for quick linting. There are ~61 pre-existing lint issues (unused imports, E402, etc.).

### Dependency installation

```bash
pip install --ignore-installed PyJWT mcp==1.25.0 fastmcp==2.14.3
pip install PyYAML==6.0.3 'python-dotenv>=1.1.0' watchdog==5.0.3 typing-extensions pydantic streamlit openai groq requests langchain langchain-openai langgraph Pillow pytest pytest-asyncio ruff
```

Note: `requirements.txt` pins `python-dotenv==1.0.1`, but `fastmcp>=2.14.3` requires `>=1.1.0`. Install `python-dotenv>=1.1.0` to resolve the conflict.

### LLM / external service configuration

The server and LangGraph agent require an OpenAI-compatible LLM API. Configure via environment variables or `config/app_config.yaml`:
- `OPENAI_API_KEY` / `INTERNAL_LLM_API_KEY`
- `OPENAI_BASE_URL` / `INTERNAL_LLM_BASE_URL`
- `OPENAI_MODEL` / `INTERNAL_LLM_MODEL`
