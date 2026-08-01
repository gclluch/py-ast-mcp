#!/usr/bin/env python3
"""Hand-rolled JSON-RPC client that drives the real py-ast-mcp stdio server.

No MCP client library involved: this spawns the `py-ast-mcp` console script,
speaks newline-delimited JSON-RPC 2.0 over its stdin/stdout, and prints a
transcript. Run it after any change to the tool surface:

    python scripts/stdio_smoke_test.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
PROTOCOL_VERSION = "2024-11-05"


class Client:
    def __init__(self, cmd: list[str]) -> None:
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=str(ROOT),
            env=env,
        )
        self._id = 0
        self._stderr: list[str] = []
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self) -> None:
        assert self.proc.stderr
        for line in self.proc.stderr:
            self._stderr.append(line.rstrip())

    def _send(self, payload: dict) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        rid = self._id
        self._send(
            {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        )
        assert self.proc.stdout
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(
                    "server closed stdout; stderr:\n" + "\n".join(self._stderr[-20:])
                )
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            if msg.get("id") == rid:
                return msg

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def text_of(result: dict) -> str:
    content = result.get("result", {}).get("content", [])
    return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")


def main() -> int:
    # the running interpreter, so this works from a venv without the console
    # script being on PATH
    cmd = sys.argv[1:] or [sys.executable, "-m", "py_ast_mcp"]
    print(f"$ {' '.join(cmd)}\n")
    client = Client(cmd)
    failures = 0

    # 1. initialize
    resp = client.request(
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "stdio-smoke-test", "version": "0"},
        },
    )
    info = resp["result"]["serverInfo"]
    print(f"[initialize] -> {info['name']} v{info['version']} "
          f"protocol={resp['result']['protocolVersion']}")
    client.notify("notifications/initialized")

    # 2. tools/list
    resp = client.request("tools/list")
    tools = resp["result"]["tools"]
    print(f"[tools/list] -> {len(tools)} tools: {', '.join(t['name'] for t in tools)}\n")

    # 3. call a spread of tools
    calls: list[tuple[str, dict, str]] = [
        ("analyze_file", {"path": str(FIX / "sample.py")}, "dataclass Widget"),
        (
            "list_functions",
            {"path": str(FIX / "sample.py")},
            "async def fetch_one",
        ),
        (
            "call_graph",
            {"path": str(FIX / "samplepkg" / "core.py"), "scope": "package",
             "direction": "LR"},
            "flowchart LR",
        ),
        (
            "get_callers",
            {"path": str(FIX / "sample.py"), "function": "_internal_helper"},
            "direct callers",
        ),
        ("dead_code", {"path": str(FIX / "samplepkg")}, "_unused_private"),
        ("code_smells", {"path": str(FIX / "smelly.py")}, "mutable-default"),
        ("find_errors", {"path": str(FIX / "smelly.py")}, "late-binding-closure"),
        (
            "get_doc",
            {"path": str(FIX / "sample.py"), "name": "process"},
            "style: google",
        ),
        (
            "diff_ast",
            {
                "old_path": str(FIX / "old_version.py"),
                "new_path": str(FIX / "new_version.py"),
            },
            "+ added_function",
        ),
        (
            "find_implementations",
            {"path": str(FIX / "samplepkg" / "core.py"), "protocol": "Serializer"},
            "JsonSerializer",
        ),
        (
            "find_node_at_position",
            {"path": str(FIX / "sample.py"), "line": 30, "column": 6},
            "innermost node",
        ),
        # graceful failure paths
        ("analyze_file", {"path": str(FIX / "broken.py")}, "ERROR: cannot parse"),
        ("analyze_file", {"path": "/no/such/file.py"}, "File not found"),
    ]

    for name, args, expect in calls:
        resp = client.request("tools/call", {"name": name, "arguments": args})
        if "error" in resp:
            print(f"[tools/call {name}] JSON-RPC ERROR: {resp['error']}")
            failures += 1
            continue
        body = text_of(resp)
        ok = expect in body
        failures += 0 if ok else 1
        head = body.splitlines()[0] if body else "<empty>"
        print(
            f"[tools/call {name}] {'OK ' if ok else 'FAIL'} "
            f"{len(body):>6} chars | expect {expect!r} | {head[:90]}"
        )
        if not ok:
            print("  --- body ---")
            print("\n".join("  " + l for l in body.splitlines()[:20]))

    # 4. unknown tool must not kill the server
    resp = client.request("tools/call", {"name": "no_such_tool", "arguments": {}})
    handled = "error" in resp or resp.get("result", {}).get("isError")
    print(f"[tools/call no_such_tool] {'OK ' if handled else 'FAIL'} handled cleanly")
    failures += 0 if handled else 1

    # server must still be alive
    resp = client.request("tools/list")
    alive = len(resp["result"]["tools"]) == len(tools)
    print(f"[tools/list again] {'OK ' if alive else 'FAIL'} server still alive")
    failures += 0 if alive else 1

    client.close()
    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
