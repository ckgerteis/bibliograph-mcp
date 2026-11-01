"""ndl-mcp — MCP server for NDL Search.

Importing this package does not start the server; call `main()`, run
`python -m ndl_mcp`, or use the installed `ndl-mcp` console script.
"""
from .server import __version__, main

__all__ = ["main", "__version__"]
