# TinyFish Search/Fetch MCP Server

A lightweight, stdio-based Model Context Protocol (MCP) server designed to provide search and fetch capabilities through the TinyFish ecosystem.

**Note:** This MCP server provides access exclusively to the TinyFish Free Access API (Search & Fetch).

## Overview

TinyFish Search/Fetch MCP Server is a standalone MCP server that offers web search via the TinyFish Search API and content fetching via the TinyFish Fetch API. It uses stdio transport for seamless integration with MCP-compatible clients such as Claude Desktop, Cursor, Windsurf, or any custom client supporting the stdio protocol.

## Features

- **Search**: Quickly find relevant information using TinyFish search capabilities.
- **Fetch**: Retrieve content from web resources efficiently.
- **Burst Fetch**: Fetch and extract clean content from up to 10 URLs in a single request.
- **Stdio Transport**: Designed for seamless integration with MCP clients (e.g. Claude Desktop, Cursor).

## Available Tools

### `search`

Search the web using TinyFish Search API.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search query. Search operators such as `site:example.com` may be used. |
| `location` | string | No | Country code, e.g. `JP`, `US`, `GB`, `FR`. |
| `language` | string | No | Language code, e.g. `ja`, `en`, `fr`. |
| `max_results` | integer | No | Local truncation count for returned results. Must be positive. |

**Returns:** JSON text containing the TinyFish search response.

### `fetch_content`

Fetch and extract clean content from a single URL using TinyFish Fetch API.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | URL to fetch. Must use `http` or `https` scheme. |
| `format` | string | No | Output format: `markdown` (default), `html`, or `json`. |
| `links` | boolean | No | Include extracted page links when supported. Default: `false`. |
| `image_links` | boolean | No | Include extracted image links when supported. Default: `false`. |

**Returns:** JSON text containing the TinyFish fetch response.

### `fetch_contents`

Fetch and extract clean content from up to 10 URLs using TinyFish Fetch API.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `urls` | string[] | Yes | Non-empty list of URLs to fetch. Maximum 10. Each must use `http` or `https` scheme. |
| `format` | string | No | Output format: `markdown` (default), `html`, or `json`. |
| `links` | boolean | No | Include extracted page links when supported. Default: `false`. |
| `image_links` | boolean | No | Include extracted image links when supported. Default: `false`. |

**Returns:** JSON text containing the TinyFish fetch response.

## Tool Schemas

### search

```json
{
  "name": "search",
  "parameters": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "query": {
        "type": "string",
        "description": "Search query. Search operators such as site:example.com may be used."
      },
      "location": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "description": "Optional country code, e.g. JP, US, GB, FR."
      },
      "language": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "description": "Optional language code, e.g. ja, en, fr."
      },
      "max_results": {
        "anyOf": [
          {
            "type": "integer"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "minimum": 1,
        "description": "Optional local truncation count for returned results."
      }
    },
    "required": ["query"]
  }
}
```

### fetch_content

```json
{
  "name": "fetch_content",
  "parameters": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "url": {
        "type": "string",
        "description": "URL to fetch. Must be http or https."
      },
      "format": {
        "type": "string",
        "enum": ["markdown", "html", "json"],
        "default": "markdown",
        "description": "Output format: markdown, html, or json."
      },
      "links": {
        "type": "boolean",
        "default": false,
        "description": "Include extracted page links when supported."
      },
      "image_links": {
        "type": "boolean",
        "default": false,
        "description": "Include extracted image links when supported."
      }
    },
    "required": ["url"]
  }
}
```


### fetch_contents

```json
{
  "name": "fetch_contents",
  "parameters": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "urls": {
        "type": "array",
        "items": {
          "type": "string"
        },
        "minItems": 1,
        "maxItems": 10,
        "description": "URLs to fetch. Maximum 10. Each must be http or https."
      },
      "format": {
        "type": "string",
        "enum": ["markdown", "html", "json"],
        "default": "markdown",
        "description": "Output format: markdown, html, or json."
      },
      "links": {
        "type": "boolean",
        "default": false,
        "description": "Include extracted page links when supported."
      },
      "image_links": {
        "type": "boolean",
        "default": false,
        "description": "Include extracted image links when supported."
      }
    },
    "required": ["urls"]
  }
}
```


## Comparison with the Official Integration

While TinyFish provides an official MCP integration using OAuth 2.1 for secure authentication (which requires a browser-based flow for initial setup), this implementation uses a **single TinyFish API Key**. This makes it better suited for:

- **Headless Environments**: Ideal for servers or environments where no web browser is available.
- **Free Access**: Optimized specifically for usage with the TinyFish Free Access API.

[Learn more about the official integration here.](https://docs.tinyfish.ai/mcp-integration)

## Prerequisites

- Python >= 3.11
- An MCP-compatible client

## Installation

### Using `uv` (Recommended)
For a clean installation as a standalone tool with isolated dependencies, use [uv](https://github.com/astral-sh/uv):

```bash
uv tool install .
```

### Using `pip`
If you are already working in a virtual environment:

```bash
pip install .
```

## Usage

Before running the server, set your TinyFish API Key as an environment variable.

**Linux / macOS (bash, zsh):**

```bash
export TINYFISH_API_KEY="<your tinyfish api key>"
```

**Windows PowerShell:**

```powershell
$env:TINYFISH_API_KEY="<your tinyfish api key>"
```

API keys are obtained by logging in at [https://agent.tinyfish.ai/](https://agent.tinyfish.ai/). Once your API key is set, the server can be invoked via its command-line entry point:

```bash
tinyfish-search-fetch-mcp
```

You can optionally provide a Python logging configuration file. JSON files are loaded with `logging.config.dictConfig`; other extensions are loaded with `logging.config.fileConfig`. Ensure custom handlers write to stderr, not stdout, because stdout is reserved for MCP JSON-RPC messages.

```bash
tinyfish-search-fetch-mcp --log-config ./logging.json
```

## Integration with Claude Desktop

To use this server with Claude Desktop, add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "tinyfish-search-fetch": {
      "command": "tinyfish-search-fetch-mcp",
      "env": {
        "TINYFISH_API_KEY": "<your tinyfish api key>"
      }
    }
  }
}
```

*Note: If you have already defined `TINYFISH_API_KEY` in your shell environment (e.g. via `~/.bashrc`, `~/.zshrc`), the `"env"` block above is optional and can be omitted.*

*If you installed via pip in a virtual environment, ensure the command points to the correct executable path.*

## Troubleshooting

### Empty search query error

If you see an error such as `valueerror: query must not be empty`, ensure the `query` parameter contains non-whitespace characters. Leading or trailing whitespace is automatically trimmed.

### Invalid fetch format error

If you see an error such as `valueerror: format must be one of: html, json, markdown`, set `format` to `markdown`, `html`, or `json`.

### Invalid URL scheme error

If you see an error such as `valueerror: url scheme must be http or https`, ensure the `url` parameter uses either `http://` or `https://` as the scheme.

### Unsupported URL

If you see an error such as `valueerror: url must include a host`, the provided URL does not contain a valid hostname. Provide a full URL including domain (e.g. `https://example.com`).

### Stdio fallback mode

In environments where FastMCP's default stdio wrapper hangs, set `TINYFISH_MCP_THREAD_STDIO=1` to use the thread-based stdio fallback. This fallback is also selected automatically when `CODEX_SANDBOX_NETWORK_DISABLED` is truthy.

### Logging privacy

The server logs search queries and fetch URLs to stderr by default. Avoid putting secrets in queries or URLs, or provide a custom `--log-config` that adjusts the log level or redacts messages.

## Development

### Local Installation

Clone and install this server in editable mode:

**With pip:**

```bash
git clone <repository-url>
cd tinyfish-search-fetch-mcp
pip install -e ".[dev]"
```

**With uv:**

```bash
git clone <repository-url>
cd tinyfish-search-fetch-mcp
uv pip install -e ".[dev]"
```

### Running Tests

This project uses `pytest`. To run the test suite:

```bash
pip install -e ".[dev]"
python -m pytest
```

With uv, sync the default development dependency group first:

```bash
uv sync
uv run python -m pytest
```

Live tests exercise the real TinyFish Search/Fetch APIs. They require both network access and `TINYFISH_API_KEY`.

- If `TINYFISH_API_KEY` is not set, live tests are skipped.
- If `CODEX_SANDBOX_NETWORK_DISABLED=1`, live tests are skipped because outbound network access is unavailable.
- With network access and an API key, the live tests call all three MCP tools and cover parameter variants such as `location`, `language`, `max_results`, `format`, `links`, and `image_links`.

### Coding Standards

Dependencies are intentionally version-bounded in `pyproject.toml` to reduce breakage from FastMCP and TinyFish SDK changes. The uv `dev` dependency group is included by default so `uv run python -m pytest` has pytest available; use `uv run --no-dev ...` for runtime-only checks. If you change dependency bounds or dependency groups, update `uv.lock` as well.

Use `ruff` for linting:

```bash
python -m ruff check src tests
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
