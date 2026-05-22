# AGENTS.md

## Cursor Cloud specific instructions

### Project Overview
This is a **FastMCP Windows Automation Server** (`win_mcp`) — an MCP server that enables LLMs to control Windows desktop applications via pywinauto. See `README.md` for full architecture details.

### Running on Linux (Cloud Agent environment)
This project is designed for Windows, but the MCP server, tests, and Streamlit UI can run on Linux with limitations:
- **`winocr`** cannot be installed on Linux (requires Windows Runtime). All OCR-dependent features will be unavailable.
- **`pywinauto`** installs on Linux but Windows GUI automation features won't work without a Windows desktop.
- **`core/network_utils.py`** uses Windows-specific commands (`netstat`, `taskkill`). The `kill_process_on_port` call in `mcp_server.py` will fail silently on Linux — this is non-blocking for server startup.

### Key commands
- **Install dependencies**: `pip install --ignore-installed PyYAML==6.0.3 pyjwt && pip install -r requirements.txt` (PyYAML and PyJWT need `--ignore-installed` due to system package conflicts)
- **Start MCP server**: `python3 mcp_server.py --transport http --host 0.0.0.0 --port 8000`
- **Run tests**: `python3 -m pytest tests/test_logic.py -v` (the only working test suite; `test_feature_execution_skill.py` references a missing module `skills.feature_execution_skill`)
- **Lint**: `ruff check --select=E,F .` (no lint config in the repo; `ruff` must be installed separately)
- **Streamlit UI**: `streamlit run LLM/streamlit_app.py`

### MCP server interaction
The server uses `streamable-http` transport. HTTP requests must include `Accept: application/json, text/event-stream` header. Responses use SSE format with `\r\n` line endings. Session ID is returned in the `Mcp-Session-Id` response header and must be included in subsequent requests.

### Environment variables for LLM features
LLM-powered features (Streamlit chat, LangGraph workflows) require an OpenAI-compatible API key. Set via:
- `OPENAI_API_KEY` or `INTERNAL_LLM_API_KEY`
- `OPENAI_BASE_URL` or `INTERNAL_LLM_BASE_URL` (default: `https://api.groq.com/openai/v1`)
- `OPENAI_MODEL` or `INTERNAL_LLM_MODEL` (default: `openai/gpt-oss-120b`)
