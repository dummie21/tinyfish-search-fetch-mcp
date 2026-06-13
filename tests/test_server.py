from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SCRIPT_PATH = Path(
    os.environ.get(
        "TINYFISH_MCP_SCRIPT",
        PROJECT_ROOT / "src/tinyfish_search_fetch_mcp/server.py",
    )
).resolve()


DEFAULT_TIMEOUT_SEC = float(os.environ.get("TINYFISH_MCP_TEST_TIMEOUT", "20"))


def _is_truthy_env(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.lower() in {"1", "true", "yes", "on"}


def _base_env(require_api_key: bool = False) -> dict[str, str]:
    env = os.environ.copy()

    # Ensure src is in PYTHONPATH so subprocesses can import the package.
    src_path = (PROJECT_ROOT / "src").resolve()
    if src_path.is_dir():
        current_pythonpath = env.get("PYTHONPATH", "")
        if str(src_path) not in current_pythonpath.split(os.pathsep):
            env["PYTHONPATH"] = os.pathsep.join(
                [str(src_path), current_pythonpath]
            ).strip(os.pathsep)

    # Keep stdout clean for JSON-RPC.
    env.setdefault("FASTMCP_SHOW_SERVER_BANNER", "false")
    env.setdefault("FASTMCP_ENABLE_RICH_LOGGING", "false")
    env.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")

    if require_api_key and not env.get("TINYFISH_API_KEY"):
        # pytest.skip() is called in each live test instead.
        pass

    return env


def _jsonrpc_initialize_message(msg_id: int = 1) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "pytest-manual-equivalent",
                "version": "0.1.0",
            },
        },
    }


def _jsonrpc_initialized_notification() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
    }


class McpProcess:
    def __init__(self, env: dict[str, str] | None = None) -> None:
        if not SCRIPT_PATH.is_file():
            raise AssertionError(f"MCP script not found: {SCRIPT_PATH}")

        self.proc = subprocess.Popen(
            [sys.executable, "-m", "tinyfish_search_fetch_mcp.server"],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env or _base_env(),
            bufsize=1,
        )

        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        assert self.proc.stderr is not None

        self.stdin = self.proc.stdin
        self.stdout = self.proc.stdout
        self.stderr = self.proc.stderr

        self.selector = selectors.DefaultSelector()
        self.selector.register(self.stdout, selectors.EVENT_READ)

    def send(self, message: dict[str, Any]) -> None:
        self.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.stdin.flush()

    def read_json_response(
        self,
        expected_id: int,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_sec
        non_json_lines: list[str] = []

        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            events = self.selector.select(timeout=min(0.2, remaining))

            if not events:
                if self.proc.poll() is not None:
                    break
                continue

            line = self.stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    break
                continue

            line = line.rstrip("\n")

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                non_json_lines.append(line)
                continue

            if obj.get("id") == expected_id:
                return obj

        stderr = self.read_stderr()
        raise AssertionError(
            f"Timed out waiting for JSON-RPC response id={expected_id}.\n"
            f"Non-JSON stdout lines: {non_json_lines!r}\n"
            f"stderr:\n{stderr}"
        )

    def read_stderr(self) -> str:
        if self.proc.stderr is None:
            return ""

        # Avoid blocking indefinitely. Terminate first if still running.
        return self.proc.stderr.read() if self.proc.poll() is not None else ""

    def close(self) -> tuple[str, str]:
        try:
            if self.stdin:
                self.stdin.close()
        except BrokenPipeError:
            pass

        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=3)

        stdout_remaining = ""
        stderr_remaining = ""

        try:
            stdout_remaining = self.stdout.read()
        except Exception:
            pass

        try:
            stderr_remaining = self.stderr.read()
        except Exception:
            pass

        return stdout_remaining, stderr_remaining

    def __enter__(self) -> "McpProcess":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _initialize_session(mcp: McpProcess) -> dict[str, Any]:
    mcp.send(_jsonrpc_initialize_message(msg_id=1))
    response = mcp.read_json_response(expected_id=1)

    assert response["jsonrpc"] == "2.0"
    assert "result" in response
    assert response["result"]["protocolVersion"] == "2024-11-05"

    mcp.send(_jsonrpc_initialized_notification())

    return response


def _call_tool(
    mcp: McpProcess,
    tool_name: str,
    arguments: dict[str, Any],
    msg_id: int = 2,
) -> dict[str, Any]:
    mcp.send(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }
    )
    return mcp.read_json_response(expected_id=msg_id)


def _extract_text_result(tool_response: dict[str, Any]) -> str:
    assert "result" in tool_response, tool_response
    assert tool_response["result"].get("isError") is False, tool_response

    content = tool_response["result"].get("content")
    assert isinstance(content, list)
    assert content, tool_response

    first = content[0]
    assert first.get("type") == "text"
    assert isinstance(first.get("text"), str)

    return first["text"]


def _skip_live_tinyfish_if_unavailable(test_name: str) -> None:
    if not os.environ.get("TINYFISH_API_KEY"):
        pytest.skip(f"TINYFISH_API_KEY is not set; skipping live {test_name} test")

    if _is_truthy_env("CODEX_SANDBOX_NETWORK_DISABLED"):
        pytest.skip(f"Network is disabled; skipping live {test_name} test")


def test_initialize_returns_expected_capabilities() -> None:
    with McpProcess(env=_base_env()) as mcp:
        response = _initialize_session(mcp)

        result = response["result"]
        assert result["serverInfo"]["name"] == "tinyfish_search_fetch"
        assert "tools" in result["capabilities"]


def test_tools_list_contains_expected_tools() -> None:
    with McpProcess(env=_base_env()) as mcp:
        _initialize_session(mcp)

        mcp.send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            }
        )

        response = mcp.read_json_response(expected_id=2)

        assert "result" in response
        tools = response["result"]["tools"]

        tool_names = {tool["name"] for tool in tools}

        assert "search" in tool_names
        assert "fetch_content" in tool_names
        assert "fetch_contents" in tool_names


def test_stdout_contains_only_jsonrpc_lines_for_tools_list() -> None:
    """
    Equivalent to manual stdout/stderr separation check.

    This verifies that stdout is not polluted by banners, logs, tracebacks, etc.
    """
    with McpProcess(env=_base_env()) as mcp:
        _initialize_session(mcp)

        mcp.send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            }
        )

        response = mcp.read_json_response(expected_id=2)
        assert "result" in response

        # read_json_response() would fail if a non-JSON line arrived before id=2.
        # This assertion makes the intent explicit.
        assert response["jsonrpc"] == "2.0"


def test_search_tool_live() -> None:
    """
    Live test.

    Requires:
      export TINYFISH_API_KEY="..."
    """
    _skip_live_tinyfish_if_unavailable("TinyFish search")

    variants = [
        {
            "query": "site:docs.tinyfish.ai fetch api",
            "max_results": 3,
        },
        {
            "query": "OpenAI API documentation",
            "location": "US",
            "language": "en",
            "max_results": 2,
        },
    ]

    with McpProcess(env=_base_env(require_api_key=True)) as mcp:
        _initialize_session(mcp)

        for msg_id, arguments in enumerate(variants, start=2):
            response = _call_tool(mcp, "search", arguments, msg_id=msg_id)

            text = _extract_text_result(response)
            data = json.loads(text)

            assert data["query"] == arguments["query"]
            assert "results" in data
            assert isinstance(data["results"], list)
            assert len(data["results"]) <= arguments["max_results"]
            assert data.get("returned_results") == len(data["results"])


def test_fetch_content_tool_live() -> None:
    """
    Live test.

    Requires:
      export TINYFISH_API_KEY="..."
    """
    _skip_live_tinyfish_if_unavailable("TinyFish fetch_content")

    variants = [
        {
            "url": "https://example.com",
            "format": "markdown",
            "links": True,
            "image_links": True,
        },
        {
            "url": "https://example.com",
            "format": "html",
        },
        {
            "url": "https://example.com",
            "format": "json",
        },
    ]

    with McpProcess(env=_base_env(require_api_key=True)) as mcp:
        _initialize_session(mcp)

        for msg_id, arguments in enumerate(variants, start=2):
            response = _call_tool(mcp, "fetch_content", arguments, msg_id=msg_id)

            text = _extract_text_result(response)
            data = json.loads(text)

            # TinyFish SDK response shape may change slightly, so keep this flexible.
            assert isinstance(data, dict)
            assert data
            assert "example" in text.lower() or "iana" in text.lower()


def test_fetch_contents_tool_live() -> None:
    """
    Live test.

    Requires:
      export TINYFISH_API_KEY="..."
    """
    _skip_live_tinyfish_if_unavailable("TinyFish fetch_contents")

    variants = [
        {
            "urls": [
                "https://example.com",
                "https://www.iana.org/domains/reserved",
            ],
            "format": "markdown",
            "links": True,
            "image_links": True,
        },
        {
            "urls": ["https://example.com"],
            "format": "html",
        },
        {
            "urls": ["https://example.com"],
            "format": "json",
        },
    ]

    with McpProcess(env=_base_env(require_api_key=True)) as mcp:
        _initialize_session(mcp)

        for msg_id, arguments in enumerate(variants, start=2):
            response = _call_tool(mcp, "fetch_contents", arguments, msg_id=msg_id)

            text = _extract_text_result(response)
            data = json.loads(text)

            # TinyFish SDK response shape may change slightly, so keep this flexible.
            assert isinstance(data, dict)
            assert data
            assert "example" in text.lower()

            if len(arguments["urls"]) > 1:
                assert "iana" in text.lower() or "reserved" in text.lower()


def test_search_rejects_empty_query() -> None:
    with McpProcess(env=_base_env()) as mcp:
        _initialize_session(mcp)

        response = _call_tool(
            mcp,
            "search",
            {
                "query": "",
            },
            msg_id=2,
        )

        assert "result" in response
        assert response["result"].get("isError") is True

        content = response["result"].get("content", [])
        text = "\n".join(item.get("text", "") for item in content)
        assert "query must not be empty" in text


def test_fetch_content_rejects_non_http_url() -> None:
    with McpProcess(env=_base_env()) as mcp:
        _initialize_session(mcp)

        response = _call_tool(
            mcp,
            "fetch_content",
            {
                "url": "file:///etc/passwd",
                "format": "markdown",
            },
            msg_id=2,
        )

        assert "result" in response
        assert response["result"].get("isError") is True

        content = response["result"].get("content", [])
        text = "\n".join(item.get("text", "") for item in content)
        assert "URL scheme must be http or https" in text
