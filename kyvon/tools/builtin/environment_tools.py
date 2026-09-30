"""Time, location and weather."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import Field

from kyvon.integrations import geocode_nominatim
from kyvon.services.environment_context import safe_zone
from kyvon.tools.base import ToolArgs, ToolContext, ToolError
from kyvon.tools.registry import ToolRegistry


class WeatherArgs(ToolArgs):
    place: str | None = Field(
        default=None,
        max_length=120,
        description="A city or place name. Leave empty to use the user's current location.",
    )


class NoArgs(ToolArgs):
    pass


class TimeArgs(ToolArgs):
    timezone: str | None = Field(
        default=None,
        max_length=64,
        description="IANA name such as America/Chicago. Default: the user's.",
    )


NO_LOCATION = (
    "I don't know the user's location yet. Ask them to allow location access in the app, "
    "or to name a place."
)


def user_timezone(ctx: ToolContext) -> str:
    """The user's time zone: their setting, else the last known location's, else UTC."""
    from kyvon.services.settings_service import timezone_for

    return timezone_for(ctx.session, ctx.user_id, ctx.services.environment_cache.get(ctx.user_id))


def register(registry: ToolRegistry) -> None:
    @registry.tool(
        "get_weather",
        "Get the current weather for a place, or for the user's current location.",
        WeatherArgs,
        retries=1,
        untrusted_output=True,
        timeout=20,
    )
    def get_weather(ctx: ToolContext, args: WeatherArgs):
        services = ctx.services
        if args.place:
            found = geocode_nominatim.forward_geocode(args.place)
            if found is None:
                raise ToolError(f"I couldn't find a place called '{args.place}'.")
            weather = services.environment.get_weather(found["latitude"], found["longitude"])
            return {"place": found["display"], "weather": weather}
        cached = services.environment_cache.get(ctx.user_id)
        if not cached:
            raise ToolError(NO_LOCATION)
        return {"place": cached["location"]["display"], "weather": cached["weather"]}

    @registry.tool(
        "get_location",
        "Get the user's current location (city, state, country) if they have shared it.",
        NoArgs,
    )
    def get_location(ctx: ToolContext, args: NoArgs):
        cached = ctx.services.environment_cache.get(ctx.user_id)
        if not cached:
            raise ToolError(NO_LOCATION)
        return cached["location"]

    @registry.tool(
        "get_current_time",
        "Get the current date and time, in the user's time zone or another one.",
        TimeArgs,
    )
    def get_current_time(ctx: ToolContext, args: TimeArgs):
        zone = safe_zone(args.timezone) if args.timezone else safe_zone(user_timezone(ctx))
        now = (ctx.now() if ctx.now else datetime.now(UTC)).astimezone(zone)
        return {
            "iso": now.isoformat(),
            "readable": now.strftime("%A, %B %d, %Y, %I:%M %p"),
            "timezone": str(zone),
        }
