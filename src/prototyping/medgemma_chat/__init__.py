"""MedGemma + Anonymizer MCP chat prototype (CLI / Gradio).

Typical MCP LLM client: initialize → tools/list → generate → tools/call.
No NL/regex planner. Gradio is optional (``uv sync --group dev``).
"""


DEFAULT_MCP_URL = "http://127.0.0.1:8000/mcp"
