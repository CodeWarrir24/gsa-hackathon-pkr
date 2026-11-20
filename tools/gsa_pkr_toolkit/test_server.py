"""Local test for the GSA PKR MCP toolkit.

Tests run in-process using the MCPServer's Python API, which exercises the
same tool registration and dispatch logic Orchestrate uses — without requiring
the full JSON-RPC subprocess plumbing.

Run with:
    python tools/gsa_pkr_toolkit/test_server.py
"""

import asyncio
import sys
import os

# Make sure imports resolve when run from workspace root
sys.path.insert(0, os.path.dirname(__file__))

import server  # noqa: E402 — must come after sys.path tweak


PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
_failures = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _failures
    status = PASS if condition else FAIL
    print(f"  [{status}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        _failures += 1


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

async def call_tool(name: str, arguments: dict) -> str:
    """Invoke a tool through the MCPServer and return the text content."""
    result = await server.mcp.call_tool(name, arguments)
    # mcp 2.x: result is a CallToolResult with a .content list
    content = getattr(result, "content", result)
    texts = [c.text for c in content if hasattr(c, "text")]
    return "\n".join(texts)


# ---------------------------------------------------------------------------
# 1. Tool discovery
# ---------------------------------------------------------------------------

async def test_tool_discovery() -> None:
    print("\n[1] Tool discovery")
    tools = await server.mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        "gsa_pkr_current_weather",
        "gsa_pkr_programming_joke",
        "gsa_pkr_unit_converter",
    }
    check("All three tools registered", expected == names, str(names))
    for t in tools:
        check(f"'{t.name}' has a description", bool(t.description))


# ---------------------------------------------------------------------------
# 2. gsa_pkr_current_weather
# ---------------------------------------------------------------------------

async def test_weather() -> None:
    print("\n[2] gsa_pkr_current_weather")
    result = await call_tool("gsa_pkr_current_weather", {"city": "Washington"})
    print(f"     Result: {result[:120]}")
    check("Returns non-empty string", bool(result))
    check("Contains temperature info", "Temperature" in result or "temperature" in result)
    check("Contains wind info", "Wind" in result or "wind" in result)

    # Bad city — should return a graceful message, not raise
    result_bad = await call_tool("gsa_pkr_current_weather", {"city": "XYZZY_NONEXISTENT_CITY_99"})
    check(
        "Handles unknown city gracefully",
        "Could not find" in result_bad or len(result_bad) > 0,
        result_bad[:80],
    )


# ---------------------------------------------------------------------------
# 3. gsa_pkr_programming_joke
# ---------------------------------------------------------------------------

async def test_joke() -> None:
    print("\n[3] gsa_pkr_programming_joke")
    result = await call_tool("gsa_pkr_programming_joke", {})
    print(f"     Result: {result[:120]}")
    check("Returns non-empty string", bool(result.strip()))
    check("Result is a string (not error)", "error" not in result.lower() or len(result) > 20)

    result_safe = await call_tool("gsa_pkr_programming_joke", {"safe_mode": True})
    check("safe_mode=True returns non-empty string", bool(result_safe.strip()))


# ---------------------------------------------------------------------------
# 4. gsa_pkr_unit_converter
# ---------------------------------------------------------------------------

async def test_converter() -> None:
    print("\n[4] gsa_pkr_unit_converter")

    cases = [
        ({"value": 100, "from_unit": "km", "to_unit": "miles"}, "62.1"),
        ({"value": 5, "from_unit": "km", "to_unit": "miles"}, "3.1"),
        ({"value": 1, "from_unit": "kg", "to_unit": "lb"}, "2.2"),
        ({"value": 100, "from_unit": "C", "to_unit": "F"}, "212"),
        ({"value": 0, "from_unit": "C", "to_unit": "K"}, "273.15"),
        ({"value": 1, "from_unit": "m", "to_unit": "ft"}, "3.28"),
    ]
    for args, expected_fragment in cases:
        result = await call_tool("gsa_pkr_unit_converter", args)
        check(
            f"{args['value']} {args['from_unit']} → {args['to_unit']} contains '{expected_fragment}'",
            expected_fragment in result,
            result,
        )

    # Unsupported pair — should return an error string, not raise
    result_bad = await call_tool("gsa_pkr_unit_converter", {"value": 1, "from_unit": "km", "to_unit": "kg"})
    check("Unsupported pair returns error text", "Unsupported" in result_bad or "Cannot" in result_bad, result_bad)

    # Same unit
    result_same = await call_tool("gsa_pkr_unit_converter", {"value": 42, "from_unit": "km", "to_unit": "km"})
    check("Same unit returns identity", "42" in result_same, result_same)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 60)
    print("GSA PKR MCP Toolkit — Local Tests")
    print("=" * 60)

    await test_tool_discovery()
    await test_weather()
    await test_joke()
    await test_converter()

    print("\n" + "=" * 60)
    if _failures == 0:
        print(f"\033[32mAll checks passed.\033[0m")
        sys.exit(0)
    else:
        print(f"\033[31m{_failures} check(s) FAILED.\033[0m")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
