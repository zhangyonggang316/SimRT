# Optional development tools

These third-party tools are optional for MATLAB automation. They are not
dependencies of the packaged APP or Linux model runtime.

| Component | Source |
| --- | --- |
| MATLAB Agentic Toolkit | https://github.com/matlab/matlab-agentic-toolkit |
| Simulink Agentic Toolkit | https://github.com/matlab/simulink-agentic-toolkit |
| MATLAB MCP Core Server | https://github.com/matlab/matlab-mcp-core-server |
| MATLAB MCP Windows executable | https://github.com/matlab/matlab-mcp-core-server/releases |
| Python 3.9.10 installer | https://www.python.org/downloads/release/python-3910/ |

The matching GitHub Release contains an optional archive of the local tool
versions, including their license/source files and excluding nested `.git`
metadata and caches. Extract it into the repository root to restore the paths
referenced by `.vscode/mcp.json`.

See [release restore instructions](../../docs/GITHUB_DELIVERY.md).
