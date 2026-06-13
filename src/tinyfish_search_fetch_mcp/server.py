from __future__ import annotations

import argparse
import json
import logging
import logging.config
import os
import queue
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastmcp import FastMCP
from tinyfish import TinyFish

LOGGER_NAME = "tinyfish_search_fetch_mcp"

logger = logging.getLogger(LOGGER_NAME)

mcp = FastMCP("tinyfish_search_fetch")


def apply_fastmcp_stdio_defaults() -> None:
    """
    Configure FastMCP for stdio usage.

    These must be set before mcp.run().

    - Disable banner because it is not emitted through Python logging.
    - Disable Rich logging to avoid mixed log formats.
    - Disable update checks to avoid startup HTTP noise.
    """
    os.environ.setdefault("FASTMCP_SHOW_SERVER_BANNER", "false")
    os.environ.setdefault("FASTMCP_ENABLE_RICH_LOGGING", "false")
    os.environ.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")


def setup_default_logging() -> None:
    """
    Configure default human-readable logging to stderr.

    stdout must not be used because stdio MCP uses stdout for protocol messages.
    """
    handler = logging.StreamHandler(sys.stderr)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s:%(lineno)d %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    # Keep noisy libraries quieter by default.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logger.debug("default stderr logging configured")


def setup_logging_from_config(config_path: str | Path) -> None:
    """
    Load logging configuration from file.

    Supported:
      - .json: logging.config.dictConfig
      - others: logging.config.fileConfig

    fileConfig can be .conf / .ini style.

    Note:
      If you use a custom config, ensure handlers write to stderr, not stdout.
    """
    path = Path(config_path).expanduser().resolve()

    if not path.is_file():
        raise FileNotFoundError(f"log config file not found: {path}")

    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as f:
            config = json.load(f)
        logging.config.dictConfig(config)
    else:
        logging.config.fileConfig(
            fname=str(path),
            disable_existing_loggers=False,
        )

    logger.debug("logging configured from file: %s", path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="TinyFish Search/Fetch-only stdio MCP server"
    )

    parser.add_argument(
        "--log-config",
        help=(
            "Optional logging config file. "
            "Use .json for dictConfig, otherwise logging fileConfig format."
        ),
    )

    return parser.parse_args()


_client: TinyFish | None = None


def _get_client() -> TinyFish:
    global _client

    if _client is not None:
        return _client

    if not os.environ.get("TINYFISH_API_KEY"):
        logger.error("TINYFISH_API_KEY is not set")
        raise RuntimeError(
            "TINYFISH_API_KEY is not set. "
            'Run: export TINYFISH_API_KEY="your_api_key_here"'
        )

    _client = TinyFish()
    logger.info("TinyFish client initialized")

    return _client


def _to_jsonable(obj: Any) -> Any:
    """
    Convert SDK/Pydantic-like objects into JSON-serializable structures.
    This keeps the MCP response robust against minor SDK model changes.
    """
    if obj is None:
        return None

    if isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, list):
        return [_to_jsonable(x) for x in obj]

    if isinstance(obj, tuple):
        return [_to_jsonable(x) for x in obj]

    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}

    if hasattr(obj, "model_dump"):
        return _to_jsonable(obj.model_dump())

    if hasattr(obj, "dict"):
        return _to_jsonable(obj.dict())

    if hasattr(obj, "__dict__"):
        return {
            str(k): _to_jsonable(v)
            for k, v in vars(obj).items()
            if not k.startswith("_")
        }

    return str(obj)


def _to_json_text(obj: Any) -> str:
    """
    Convert any SDK response to JSON text.

    Returning str from FastMCP tools is more compatible than returning
    arbitrary nested dict/list responses from third-party SDKs.
    """
    jsonable = _to_jsonable(obj)
    return json.dumps(jsonable, ensure_ascii=False, indent=2, default=str)


def _fetch_tinyfish_contents(
    client: TinyFish,
    urls: list[str],
    *,
    format: Literal["markdown", "html", "json"],
    links: bool,
    image_links: bool,
) -> Any:
    if format != "json":
        return client.fetch.get_contents(
            urls=urls,
            format=format,
            links=links,
            image_links=image_links,
        )

    body: dict[str, object] = {
        "urls": urls,
        "format": format,
        "links": links,
        "image_links": image_links,
    }

    # tinyfish 0.2.5 validates fetch results as strings, but JSON format may
    # return structured text. Keep the public SDK path for other formats and
    # request raw JSON only for this known response-shape mismatch.
    return client._request("POST", "/v1/fetch", json=body).json()


@mcp.tool()
def search(
    query: str,
    location: str | None = None,
    language: str | None = None,
    max_results: int | None = None,
) -> str:
    """
    Search the web using TinyFish Search API.

    Args:
        query: Search query. Search operators such as site:example.com may be used.
        location: Optional country code, e.g. JP, US, GB, FR.
        language: Optional language code, e.g. ja, en, fr.
        max_results: Optional local truncation count for returned results.

    Returns:
        JSON text containing TinyFish search response.
    """
    query = query.strip()

    if not query:
        logger.warning("empty search query rejected")
        raise ValueError("query must not be empty")

    if max_results is not None and max_results <= 0:
        logger.warning("invalid max_results rejected: max_results=%s", max_results)
        raise ValueError("max_results must be positive")

    logger.info(
        "TinyFish search requested: query=%r location=%r language=%r max_results=%r",
        query,
        location,
        language,
        max_results,
    )

    client = _get_client()

    kwargs: dict[str, Any] = {
        "query": query,
    }

    if location:
        kwargs["location"] = location
    if language:
        kwargs["language"] = language

    response = client.search.query(**kwargs)
    data = _to_jsonable(response)

    if max_results is not None and isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list):
            data["results"] = results[:max_results]
            data["returned_results"] = len(data["results"])

    result_count = None
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        result_count = len(data["results"])

    logger.info(
        "TinyFish search completed: query=%r result_count=%r",
        query,
        result_count,
    )

    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


@mcp.tool()
def fetch_content(
    url: str,
    format: Literal["markdown", "html", "json"] = "markdown",
    links: bool = False,
    image_links: bool = False,
) -> str:
    """
    Fetch and extract clean content from a URL using TinyFish Fetch API.

    Args:
        url: URL to fetch. Must be http or https.
        format: Output format: markdown, html, or json.
        links: Include extracted page links when supported.
        image_links: Include extracted image links when supported.

    Returns:
        JSON text containing TinyFish fetch response.
    """
    url = url.strip()
    _validate_http_url(url)

    logger.info(
        "TinyFish fetch_content requested: url=%r format=%s links=%s image_links=%s",
        url,
        format,
        links,
        image_links,
    )

    client = _get_client()

    response = _fetch_tinyfish_contents(
        client,
        urls=[url],
        format=format,
        links=links,
        image_links=image_links,
    )

    data = _to_jsonable(response)

    logger.info("TinyFish fetch_content completed: url=%r", url)

    return json.dumps(data, ensure_ascii=False, indent=2, default=str)



@mcp.tool()
def fetch_contents(
    urls: list[str],
    format: Literal["markdown", "html", "json"] = "markdown",
    links: bool = False,
    image_links: bool = False,
) -> str:
    """
    Fetch and extract clean content from up to 10 URLs using TinyFish Fetch API.

    Args:
        urls: URLs to fetch. Maximum 10. Each must be http or https.
        format: Output format: markdown, html, or json.
        links: Include extracted page links when supported.
        image_links: Include extracted image links when supported.

    Returns:
        JSON text containing TinyFish fetch response.
    """
    if not urls:
        logger.warning("empty URL list rejected")
        raise ValueError("urls must not be empty")

    if len(urls) > 10:
        logger.warning("too many URLs rejected: url_count=%s", len(urls))
        raise ValueError("TinyFish Fetch accepts at most 10 URLs per request")

    cleaned_urls: list[str] = []

    for u in urls:
        cleaned_url = u.strip()
        _validate_http_url(cleaned_url)
        cleaned_urls.append(cleaned_url)

    logger.info(
        "TinyFish fetch_contents requested: "
        "url_count=%s format=%s links=%s image_links=%s",
        len(cleaned_urls),
        format,
        links,
        image_links,
    )

    client = _get_client()

    response = _fetch_tinyfish_contents(
        client,
        urls=cleaned_urls,
        format=format,
        links=links,
        image_links=image_links,
    )

    data = _to_jsonable(response)

    logger.info(
        "TinyFish fetch_contents completed: url_count=%s",
        len(cleaned_urls),
    )

    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _validate_http_url(url: str) -> None:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        logger.warning(
            "invalid URL scheme rejected: url=%s scheme=%s",
            url,
            parsed.scheme,
        )
        raise ValueError("URL scheme must be http or https")

    if not parsed.netloc:
        logger.warning("URL has no host: url=%s", url)
        raise ValueError("URL must include a host")


def _is_truthy_env(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.lower() in {"1", "true", "yes", "on"}


def _should_use_thread_stdio_fallback() -> bool:
    """
    Detect stdio environments where AnyIO's worker-thread file wrapper can hang.

    FastMCP's default stdio transport reads stdin through anyio.wrap_file(), which
    delegates readline() to anyio.to_thread.run_sync(). In Codex's Linux sandbox
    this can block even though ordinary sys.stdin.readline() works in a normal
    thread. Keep the default transport everywhere else, and use this fallback only
    when explicitly requested or when Codex's sandbox marker is present.
    """
    return _is_truthy_env("TINYFISH_MCP_THREAD_STDIO") or _is_truthy_env(
        "CODEX_SANDBOX_NETWORK_DISABLED"
    )


@asynccontextmanager
async def _thread_stdio_server():
    """
    MCP stdio transport that avoids anyio.wrap_file() for stdin.

    This mirrors mcp.server.stdio.stdio_server() but reads stdin in a regular
    Python thread, then forwards parsed JSON-RPC messages into AnyIO streams.
    """
    import anyio
    from mcp import types
    from mcp.shared.message import SessionMessage

    read_stream_writer, read_stream = anyio.create_memory_object_stream(100)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)
    input_queue: queue.Queue[object] = queue.Queue()
    stop_reader = threading.Event()

    async def read_stream_pump() -> None:
        while True:
            try:
                item = input_queue.get_nowait()
            except queue.Empty:
                await anyio.sleep(0.01)
                continue

            if item is None:
                break

            await read_stream_writer.send(item)

        await read_stream_writer.aclose()

    async with anyio.create_task_group() as task_group:
        def stdin_reader() -> None:
            try:
                for line in sys.stdin:
                    if stop_reader.is_set():
                        break

                    try:
                        message = types.JSONRPCMessage.model_validate_json(line)
                        item = SessionMessage(message)
                    except Exception as exc:
                        item = exc

                    input_queue.put(item)
            finally:
                input_queue.put(None)

        async def stdout_writer() -> None:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    payload = session_message.message.model_dump_json(
                        by_alias=True,
                        exclude_none=True,
                    )
                    sys.stdout.write(payload + "\n")
                    sys.stdout.flush()

        reader_thread = threading.Thread(
            target=stdin_reader,
            name="mcp-stdio-reader",
            daemon=True,
        )
        reader_thread.start()

        task_group.start_soon(read_stream_pump)
        task_group.start_soon(stdout_writer)
        try:
            yield read_stream, write_stream
        finally:
            stop_reader.set()
            task_group.cancel_scope.cancel()


async def _run_mcp_server_with_thread_stdio_async() -> None:
    from fastmcp.server.context import reset_transport, set_transport
    from mcp.server.lowlevel.server import NotificationOptions

    token = set_transport("stdio")
    try:
        async with mcp._lifespan_manager():
            async with _thread_stdio_server() as (read_stream, write_stream):
                logger.info(
                    "Starting MCP server %r with sandbox-safe thread stdio",
                    mcp.name,
                )
                await mcp._mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp._mcp_server.create_initialization_options(
                        notification_options=NotificationOptions(
                            tools_changed=True,
                        ),
                    ),
                )
    finally:
        reset_transport(token)


def _run_mcp_server_with_thread_stdio() -> None:
    import anyio

    anyio.run(_run_mcp_server_with_thread_stdio_async)


def run_mcp_server() -> None:
    """
    Run FastMCP server.

    Prefer explicit stdio and banner suppression.
    If the installed FastMCP version does not accept show_banner,
    fall back to mcp.run() because the environment variable should still suppress it.
    """
    if _should_use_thread_stdio_fallback():
        logger.info("using sandbox-safe thread stdio transport")
        _run_mcp_server_with_thread_stdio()
        return

    try:
        mcp.run(
            transport="stdio",
            show_banner=False,
        )
    except TypeError as exc:
        logger.warning(
            "mcp.run(transport='stdio', show_banner=False) failed; "
            "falling back to mcp.run(): %s",
            exc,
        )
        mcp.run()


def main() -> None:
    apply_fastmcp_stdio_defaults()

    args = parse_args()

    if args.log_config:
        setup_logging_from_config(args.log_config)
    else:
        setup_default_logging()

    logger.info("starting TinyFish Search/Fetch stdio MCP server")

    try:
        run_mcp_server()
    except Exception:
        logger.exception("MCP server terminated with an exception")
        raise


if __name__ == "__main__":
    main()
