"""warp-mcp — MCP server for the NDL Web Archiving Project (WARP).

Importing this package does not start the server; call `main()`, run
`python -m warp_mcp`, or use the installed `warp-mcp` console script.
"""
from .server import __version__, main

__all__ = ["main", "__version__"]
