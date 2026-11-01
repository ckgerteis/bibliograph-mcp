"""openalex-mcp — MCP server for OpenAlex.

Importing this package does not start the server; call `main()`, run
`python -m openalex_mcp`, or use the installed `openalex-mcp` console script.
"""
from .server import __version__, main

__all__ = ["main", "__version__"]
