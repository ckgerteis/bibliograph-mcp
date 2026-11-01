"""semantic-scholar-mcp — MCP server for Semantic Scholar Academic Graph.

Importing this package does not start the server; call `main()`, run
`python -m semantic_scholar_mcp`, or use the installed `semantic-scholar-mcp` console script.
"""
from .server import __version__, main

__all__ = ["main", "__version__"]
