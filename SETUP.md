# Setup

## 1. Install

You have `uv`, so the least-fuss path is:

    cd ~/projects/py-ast-mcp
    uv sync            # creates .venv and installs deps
    uv run pytest      # 144 tests, should all pass

Optional semantic extras (cross-file resolution via jedi — the server
degrades gracefully without it):

    uv sync --extra semantic

## 2. Wire into Claude Code

A `.mcp.json` has already been dropped into `~/projects/health-access-map`.
To use it anywhere else, add this to that repo's `.mcp.json`:

    {
      "mcpServers": {
        "py-ast": {
          "command": "uv",
          "args": ["run", "--directory", "/Users/gabriellluch/projects/py-ast-mcp", "py-ast-mcp"]
        }
      }
    }

Then `claude` in that directory and run `/mcp` to confirm `py-ast` connected.

To make it global instead of per-repo:

    claude mcp add py-ast -s user -- uv run --directory /Users/gabriellluch/projects/py-ast-mcp py-ast-mcp

## 3. Verify

    uv run python scripts/stdio_smoke_test.py

Spawns the real binary, speaks raw JSON-RPC, exercises 13 tool calls.
Prints ALL CHECKS PASSED on success.

## 4. First things worth trying on this machine

    call_graph on pipeline/join_and_score.py with scope=package
    code_complexity on pipeline/validate_fqhc_lever.py
    dead_code on pipeline/
    find_errors on pipeline/build_supply.py

`dead_code` on `pipeline/` is the interesting one — 30-odd modules that
have accreted across 23 work cycles is exactly the situation it's for.
