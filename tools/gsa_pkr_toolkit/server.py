"""GSA PKR MCP toolkit — stdio transport.

Three tools:
  gsa_pkr_current_weather   — proves outbound internet via open-meteo.com
  gsa_pkr_programming_joke  — calls JokeAPI (jokeapi.dev)
  gsa_pkr_unit_converter    — pure local unit conversion logic
"""

import asyncio
import requests as _requests
from mcp.server.mcpserver import MCPServer

mcp = MCPServer(
    name="gsa_pkr_toolkit",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Tool 1 — gsa_pkr_current_weather
# ---------------------------------------------------------------------------

def _weather(city: str, country_code: str = "") -> str:
    """Two-step call: geocode city, then fetch current conditions."""
    geo_params = {"name": city, "count": 1, "format": "json"}
    if country_code:
        geo_params["country_code"] = country_code
    geo_resp = _requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params=geo_params,
        timeout=10,
    )
    geo_resp.raise_for_status()
    geo_data = geo_resp.json()
    results = geo_data.get("results")
    if not results:
        return f"Could not find location: {city!r}"
    loc = results[0]
    lat, lon = loc["latitude"], loc["longitude"]
    location_label = f"{loc['name']}, {loc.get('country', '')}"

    wx_resp = _requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,wind_speed_10m",
        },
        timeout=10,
    )
    wx_resp.raise_for_status()
    wx = wx_resp.json()
    current = wx["current"]
    units = wx["current_units"]
    temp = current["temperature_2m"]
    wind = current["wind_speed_10m"]
    temp_unit = units.get("temperature_2m", "°C")
    wind_unit = units.get("wind_speed_10m", "km/h")
    return (
        f"Current weather in {location_label}:\n"
        f"  Temperature: {temp} {temp_unit}\n"
        f"  Wind speed:  {wind} {wind_unit}"
    )


@mcp.tool(
    name="gsa_pkr_current_weather",
    description=(
        "Returns the current temperature and wind speed for a given city "
        "by querying the open-meteo.com API (no API key required). "
        "Demonstrates outbound internet connectivity."
    ),
)
def gsa_pkr_current_weather(city: str, country_code: str = "") -> str:
    """Get current weather for a city.

    Args:
        city: The name of the city (e.g. 'Washington', 'London').
        country_code: Optional ISO 3166-1 alpha-2 country code to disambiguate
            cities with the same name (e.g. 'US', 'GB').

    Returns:
        A human-readable summary of current temperature and wind speed.
    """
    return _weather(city, country_code)


# ---------------------------------------------------------------------------
# Tool 2 — gsa_pkr_programming_joke
# ---------------------------------------------------------------------------

def _joke(safe_mode: bool = True) -> str:
    """Fetch a programming joke from JokeAPI."""
    url = "https://v2.jokeapi.dev/joke/Programming"
    if safe_mode:
        url += "?safe-mode"
    resp = _requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        return f"JokeAPI error: {data.get('message', 'unknown error')}"
    if data["type"] == "twopart":
        return f"{data['setup']}\n\n{data['delivery']}"
    return data["joke"]


@mcp.tool(
    name="gsa_pkr_programming_joke",
    description=(
        "Fetches a random programming joke from the public JokeAPI "
        "(https://jokeapi.dev). Handles both single-line and two-part jokes."
    ),
)
def gsa_pkr_programming_joke(safe_mode: bool = True) -> str:
    """Get a random programming joke.

    Args:
        safe_mode: When True (default) only family-friendly jokes are returned.

    Returns:
        The joke as a string. Two-part jokes are formatted as setup followed
        by the punchline on a new line.
    """
    return _joke(safe_mode)


# ---------------------------------------------------------------------------
# Tool 3 — gsa_pkr_unit_converter
# ---------------------------------------------------------------------------

# Conversion table: (from_unit, to_unit) -> multiplier
# Temperature handled separately via formulas.
_FACTORS: dict[tuple[str, str], float] = {
    ("km", "miles"): 0.621371,
    ("miles", "km"): 1.60934,
    ("m", "ft"): 3.28084,
    ("ft", "m"): 0.3048,
    ("kg", "lb"): 2.20462,
    ("lb", "kg"): 0.453592,
    ("km", "m"): 1000.0,
    ("m", "km"): 0.001,
    ("miles", "ft"): 5280.0,
    ("ft", "miles"): 1 / 5280.0,
}

_SUPPORTED_UNITS = {"km", "miles", "m", "ft", "kg", "lb", "c", "f", "k"}
_TEMP_UNITS = {"c", "f", "k"}


def _convert(value: float, from_unit: str, to_unit: str) -> str:
    f = from_unit.lower().strip()
    t = to_unit.lower().strip()

    if f not in _SUPPORTED_UNITS:
        return f"Unsupported unit: '{from_unit}'. Supported: km, miles, m, ft, kg, lb, C, F, K"
    if t not in _SUPPORTED_UNITS:
        return f"Unsupported unit: '{to_unit}'. Supported: km, miles, m, ft, kg, lb, C, F, K"

    if f == t:
        return f"{value} {from_unit} = {value} {to_unit}"

    # Temperature conversions
    if f in _TEMP_UNITS or t in _TEMP_UNITS:
        if f not in _TEMP_UNITS or t not in _TEMP_UNITS:
            return f"Cannot convert temperature unit '{from_unit}' to non-temperature unit '{to_unit}'"
        if f == "c" and t == "f":
            result = value * 9 / 5 + 32
        elif f == "f" and t == "c":
            result = (value - 32) * 5 / 9
        elif f == "c" and t == "k":
            result = value + 273.15
        elif f == "k" and t == "c":
            result = value - 273.15
        elif f == "f" and t == "k":
            result = (value - 32) * 5 / 9 + 273.15
        elif f == "k" and t == "f":
            result = (value - 273.15) * 9 / 5 + 32
        else:
            return f"Unsupported temperature conversion: {from_unit} → {to_unit}"
        return f"{value} {from_unit.upper()} = {round(result, 4)} {to_unit.upper()}"

    # All other units
    key = (f, t)
    if key not in _FACTORS:
        return (
            f"Unsupported conversion: '{from_unit}' → '{to_unit}'. "
            "Supported pairs: km↔miles, km↔m, miles↔ft, m↔ft, kg↔lb"
        )
    result = value * _FACTORS[key]
    return f"{value} {from_unit} = {round(result, 6)} {to_unit}"


@mcp.tool(
    name="gsa_pkr_unit_converter",
    description=(
        "Converts a numeric value between common units using local logic "
        "(no network call). Supports: length (km, miles, m, ft), "
        "weight (kg, lb), temperature (C, F, K)."
    ),
)
def gsa_pkr_unit_converter(value: float, from_unit: str, to_unit: str) -> str:
    """Convert a value from one unit to another.

    Args:
        value: The numeric value to convert.
        from_unit: The source unit (km, miles, m, ft, kg, lb, C, F, K).
        to_unit: The target unit (km, miles, m, ft, kg, lb, C, F, K).

    Returns:
        A string like '5.0 km = 3.107 miles', or an error message if the
        unit pair is not supported.
    """
    return _convert(value, from_unit, to_unit)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(mcp.run_stdio_async())
