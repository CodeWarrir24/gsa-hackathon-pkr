# GSA PKR Tools — MCP Toolkit Plan

## Overview

Build the three approved tools (`gsa_pkr_current_weather`, `gsa_pkr_programming_joke`,
`gsa_pkr_unit_converter`) as a **single local Python MCP server** using the `mcp` SDK with
**stdio transport**. Orchestrate spawns the process and speaks JSON-RPC over stdin/stdout — there
is no separately hosted HTTP server.

### Final folder layout

```
tools/gsa_pkr_toolkit/
├── server.py          ← MCP server entry point; registers all three tools
├── requirements.txt   ← mcp, requests (and their transitive deps)
└── test_server.py     ← local test script (init + tool-list + all tool calls)
```

### ADK import command (run from workspace root)

```bash
orchestrate toolkits add \
  --kind mcp \
  --name gsa_pkr_toolkit \
  --description "GSA PKR demo toolkit: weather, programming joke, and unit converter" \
  --package_root tools/gsa_pkr_toolkit \
  --command "python server.py" \
  --tools "*"
```

---

## Sub-Task 1 — Scaffold the MCP server entry point

**Intent**
Create `server.py` using `mcp.server.Server` with `stdio_server` transport, register an
`initialize` handler and a `list_tools` handler, and wire up a single `call_tool` dispatch
function. The file is the only file Orchestrate will execute.

**Expected Outcomes**
- `tools/gsa_pkr_toolkit/server.py` exists and starts without errors when run as
  `python tools/gsa_pkr_toolkit/server.py`.
- Responds to MCP `initialize` with server info and capabilities.
- Responds to `tools/list` with an empty list (tools are added in Sub-Tasks 2–4).
- `tools/gsa_pkr_toolkit/requirements.txt` exists with at minimum `mcp` and `requests`.

**Todo List**
- [ ] Create `tools/gsa_pkr_toolkit/` directory
- [ ] Write `tools/gsa_pkr_toolkit/requirements.txt` with `mcp` and `requests`
- [ ] Write `tools/gsa_pkr_toolkit/server.py` with `mcp` SDK scaffold:
      `Server("gsa_pkr_toolkit")`, `@server.list_tools()`, `@server.call_tool()`, and
      `asyncio.run(main())` entry point using `stdio_server`
- [ ] Verify `python tools/gsa_pkr_toolkit/server.py` starts and exits cleanly when stdin closes

**Relevant Context**
- MCP Python SDK: `mcp` package (install via `pip install mcp`)
- Pattern: `from mcp.server import Server`, `from mcp.server.stdio import stdio_server`
- `@server.list_tools()` returns `list[mcp.types.Tool]`
- `@server.call_tool()` receives `name: str, arguments: dict` and returns `list[mcp.types.TextContent]`

**Status:** `[x] done`

---

## Sub-Task 2 — Add `gsa_pkr_current_weather` tool

**Intent**
Implement the weather tool inside `server.py`. Calls the free open-meteo.com geocoding + forecast
API (no key required) to prove outbound internet access.

**Expected Outcomes**
- `tools/list` response includes a tool entry named `gsa_pkr_current_weather` with an input
  schema requiring `city: string` and an optional `country_code: string`.
- `tools/call` with `{"city": "London"}` returns a non-empty weather summary string.
- Two-step HTTP flow: geocoding → forecast.

**Todo List**
- [ ] Add `gsa_pkr_current_weather` to the `Tool` list in `@server.list_tools()`
- [ ] Implement `_weather(city, country_code)` helper using `requests` to call
      `https://geocoding-api.open-meteo.com/v1/search` then
      `https://api.open-meteo.com/v1/forecast?current=temperature_2m,wind_speed_10m`
- [ ] Dispatch `gsa_pkr_current_weather` in `@server.call_tool()`, return
      `[TextContent(type="text", text=...)]`

**Relevant Context**
- open-meteo geocoding: `GET https://geocoding-api.open-meteo.com/v1/search?name=<city>&count=1`
  → returns `results[0].{latitude, longitude, name, country}`
- open-meteo forecast: `GET https://api.open-meteo.com/v1/forecast?latitude=X&longitude=Y&current=temperature_2m,wind_speed_10m`
  → returns `current.{temperature_2m, wind_speed_10m}` and `current_units`

**Status:** `[x] done`

---

## Sub-Task 3 — Add `gsa_pkr_programming_joke` tool

**Intent**
Implement the joke tool. Calls JokeAPI (jokeapi.dev) to return a programming joke, handling both
`twopart` and `single` response shapes.

**Expected Outcomes**
- `tools/list` includes `gsa_pkr_programming_joke` with an optional `safe_mode: boolean` input.
- `tools/call` with `{}` returns a non-empty joke string.
- `tools/call` with `{"safe_mode": true}` appends `?safe-mode` to the request URL.
- Both joke shapes produce a coherent string (setup + delivery for twopart, plain joke for single).

**Todo List**
- [ ] Add `gsa_pkr_programming_joke` to the `Tool` list in `@server.list_tools()`
- [ ] Implement `_joke(safe_mode)` helper calling
      `https://v2.jokeapi.dev/joke/Programming` with optional `?safe-mode` query param
- [ ] Handle `response["type"] == "twopart"` → `"{setup}\n{delivery}"` and `"single"` → `joke`
- [ ] Dispatch in `@server.call_tool()`

**Relevant Context**
- JokeAPI: `GET https://v2.jokeapi.dev/joke/Programming` (no auth, free)
- Response schema: `{type: "single"|"twopart", joke?: str, setup?: str, delivery?: str}`
- `safe-mode` query param filters to family-friendly jokes

**Status:** `[x] done`

---

## Sub-Task 4 — Add `gsa_pkr_unit_converter` tool

**Intent**
Implement the pure-local converter. No outbound calls — demonstrates tools that need no network.

**Expected Outcomes**
- `tools/list` includes `gsa_pkr_unit_converter` with required inputs
  `value: number`, `from_unit: string`, `to_unit: string`.
- `tools/call` with `{"value": 5, "from_unit": "km", "to_unit": "miles"}` returns `"5.0 km = 3.107 miles"`.
- Supported unit families: length (km, miles, m, ft), weight (kg, lb), temperature (C, F, K).
- Unsupported pair raises an error message returned as `TextContent` (not a Python exception that
  would crash the server process).

**Todo List**
- [ ] Add `gsa_pkr_unit_converter` to the `Tool` list in `@server.list_tools()`
- [ ] Implement `_convert(value, from_unit, to_unit)` with a conversion table / formula set
- [ ] Return clear error text for unsupported pairs (do not let exceptions propagate to MCP layer)
- [ ] Dispatch in `@server.call_tool()`

**Relevant Context**
- Conversion must be case-insensitive on unit strings
- Temperature conversions require formulas (not a simple multiplier); handle C↔F, C↔K, F↔K
- All other conversions can use a multiply/divide factor table

**Status:** `[x] done`

---

## Sub-Task 5 — Local test script

**Intent**
Write a local test that directly exercises the MCP server over stdio (subprocess), verifying
initialization, tool discovery, and all three tool calls — without requiring an Orchestrate
environment.

**Expected Outcomes**
- `tools/gsa_pkr_toolkit/test_server.py` is a self-contained Python script.
- When run as `python tools/gsa_pkr_toolkit/test_server.py` it:
  1. Spawns `server.py` as a subprocess.
  2. Sends `initialize` → asserts server name and capabilities.
  3. Sends `tools/list` → asserts all three tool names are present.
  4. Calls `gsa_pkr_current_weather` with `{"city": "Washington"}` → asserts non-empty result.
  5. Calls `gsa_pkr_programming_joke` with `{}` → asserts non-empty result.
  6. Calls `gsa_pkr_unit_converter` with `{"value": 100, "from_unit": "km", "to_unit": "miles"}`
     → asserts result contains `"62.1"`.
  7. Exits with code 0 on all assertions passed, prints PASS/FAIL per check.
- All tests pass before proceeding to Sub-Task 6.

**Todo List**
- [ ] Write `tools/gsa_pkr_toolkit/test_server.py` using `subprocess` + raw JSON-RPC over stdin/stdout
- [ ] Run `python tools/gsa_pkr_toolkit/test_server.py` and confirm exit code 0

**Relevant Context**
- MCP JSON-RPC framing: newline-delimited JSON messages, each with `{"jsonrpc":"2.0","id":N,"method":"...","params":{...}}`
- `initialize` params: `{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}}`
- `tools/list` params: `{}`
- `tools/call` params: `{"name":"<tool>","arguments":{...}}`

**Status:** `[x] done`

---

## Sub-Task 6 — Import into watsonx Orchestrate and verify

**Intent**
Import the MCP toolkit into the active Orchestrate environment (draft) and confirm all three tools
are visible and callable.

**Expected Outcomes**
- `orchestrate toolkits add` exits 0 for the `gsa_pkr_toolkit`.
- `orchestrate toolkits list` shows `gsa_pkr_toolkit`.
- `orchestrate tools list` shows all three `gsa_pkr_*` tool names.
- Spot-call each tool via `orchestrate tools run` (or equivalent) and confirm a valid response.

**Todo List**
- [ ] Confirm `orchestrate env use` is targeting the correct draft environment
      (`orchestrate env list` to check)
- [ ] Run `orchestrate toolkits add --kind mcp --name gsa_pkr_toolkit ...` (full command above)
- [ ] Run `orchestrate toolkits list` and assert `gsa_pkr_toolkit` is present
- [ ] Run `orchestrate tools list` and assert the three `gsa_pkr_*` tool names appear

**Relevant Context**
- No credentials or connection needed — tools 1 and 2 make unauthenticated public API calls;
  tool 3 is pure local
- If toolkit already exists from a previous attempt: `orchestrate toolkits remove -n gsa_pkr_toolkit`
  then re-add
- ADK version in venv: `ibm_watsonx_orchestrate==2.18.2`

**Status:** `[x] done`
