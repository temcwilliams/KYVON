"""Google Calendar tools. Reading is automatic; every change needs the user's confirmation."""

from __future__ import annotations

from pydantic import Field

from kyvon.services.calendar_service import CalendarService
from kyvon.services.errors import IntegrationError, NotConnectedError, ValidationFailure
from kyvon.tools.base import RiskLevel, ToolArgs, ToolContext, ToolError
from kyvon.tools.registry import ToolRegistry

TIME_HELP = (
    "ISO 8601: a date (2026-10-03, all-day) or date-time (2026-10-03T14:00, in the user's time "
    "zone). Work out 'tomorrow', 'Friday' and so on from the current date in your context."
)


class ListEventsArgs(ToolArgs):
    start: str | None = Field(
        default=None, max_length=40, description=TIME_HELP + " Default: today."
    )
    end: str | None = Field(
        default=None,
        max_length=40,
        description="Same format. A date means through the end of that day. Default: 7 days after start.",
    )
    query: str | None = Field(default=None, max_length=100, description="Text to search for.")
    calendar_id: str | None = Field(default=None, max_length=256, description="Default: primary.")
    max_results: int = Field(default=25, ge=1, le=50)


class CreateEventArgs(ToolArgs):
    title: str = Field(min_length=1, max_length=200)
    start: str = Field(max_length=40, description=TIME_HELP)
    end: str | None = Field(
        default=None, max_length=40, description="Default: one hour after start."
    )
    all_day: bool | None = None
    location: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=2000)
    calendar_id: str | None = Field(default=None, max_length=256)


class UpdateEventArgs(ToolArgs):
    event_id: str = Field(min_length=1, max_length=256, description="From calendar_list_events.")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    start: str | None = Field(default=None, max_length=40, description=TIME_HELP)
    end: str | None = Field(default=None, max_length=40)
    location: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    calendar_id: str | None = Field(default=None, max_length=256)


class DeleteEventArgs(ToolArgs):
    event_id: str = Field(min_length=1, max_length=256, description="From calendar_list_events.")
    calendar_id: str | None = Field(default=None, max_length=256)


class NoArgs(ToolArgs):
    pass


def _service(ctx: ToolContext) -> CalendarService:
    return CalendarService(
        ctx.session,
        ctx.user_id,
        settings=ctx.settings,
        http=ctx.services.http,
        now=ctx.now,
    )


def _guard(action):
    try:
        return action()
    except (NotConnectedError, IntegrationError, ValidationFailure) as problem:
        raise ToolError(str(problem)) from problem


def _event_label(ctx: ToolContext | None, event_id: str, calendar_id: str | None) -> str:
    """Look the event up so the confirmation names it ("Team sync, Fri 3-4 PM")."""
    if ctx is None:
        return f"event {event_id}"
    try:
        service = _service(ctx)
        event = service.get_event(event_id, calendar_id)
        return f'"{event["title"]}" ({service.describe_when(event)})'
    except Exception:
        return f"event {event_id}"


def _when_text(ctx: ToolContext | None, start: str, end: str | None, all_day: bool | None) -> str:
    if ctx is None:
        return start
    try:
        service = _service(ctx)
        start_obj, end_obj = service._times(start, end, all_day)
        event = {
            "all_day": "date" in start_obj,
            "start": start_obj.get("date") or start_obj.get("dateTime"),
            "end": end_obj.get("date") or end_obj.get("dateTime"),
        }
        return service.describe_when(event)
    except Exception:
        return start


def register(registry: ToolRegistry) -> None:
    enabled = lambda services: services.settings.calendar_configured  # noqa: E731

    @registry.tool(
        "calendar_list_calendars",
        "List the user's Google calendars.",
        NoArgs,
        enabled=enabled,
        untrusted_output=True,
        retries=1,
    )
    def calendar_list_calendars(ctx: ToolContext, args: NoArgs):
        return _guard(lambda: _service(ctx).list_calendars())

    @registry.tool(
        "calendar_list_events",
        "List or search events on the user's Google Calendar in a date range. Use this to "
        "answer 'what's on my calendar' and to find an event's id before changing it.",
        ListEventsArgs,
        enabled=enabled,
        untrusted_output=True,
        retries=1,
    )
    def calendar_list_events(ctx: ToolContext, args: ListEventsArgs):
        return _guard(
            lambda: _service(ctx).list_events(
                args.start,
                args.end,
                calendar_id=args.calendar_id,
                query=args.query,
                max_results=args.max_results,
            )
        )

    @registry.tool(
        "calendar_create_event",
        "Add an event to the user's Google Calendar. The user must approve before it is created.",
        CreateEventArgs,
        risk=RiskLevel.EXTERNAL,
        enabled=enabled,
        summarize=lambda a, ctx: (
            f'Add to Google Calendar: "{a.title}" — {_when_text(ctx, a.start, a.end, a.all_day)}'
            + (f" at {a.location}" if a.location else "")
        ),
    )
    def calendar_create_event(ctx: ToolContext, args: CreateEventArgs):
        return _guard(
            lambda: _service(ctx).create_event(
                args.title,
                args.start,
                args.end,
                all_day=args.all_day,
                location=args.location,
                description=args.description,
                calendar_id=args.calendar_id,
            )
        )

    @registry.tool(
        "calendar_update_event",
        "Change an existing Google Calendar event (for example move it to another time). Find "
        "its id with calendar_list_events first. The user must approve the change.",
        UpdateEventArgs,
        risk=RiskLevel.EXTERNAL,
        enabled=enabled,
        summarize=lambda a, ctx: (
            f"Change the event {_event_label(ctx, a.event_id, a.calendar_id)}"
            + (f' → title "{a.title}"' if a.title else "")
            + (f" → start {a.start}" if a.start else "")
            + (f" → end {a.end}" if a.end else "")
            + (f' → location "{a.location}"' if a.location is not None else "")
        ),
    )
    def calendar_update_event(ctx: ToolContext, args: UpdateEventArgs):
        return _guard(
            lambda: _service(ctx).update_event(
                args.event_id,
                title=args.title,
                start=args.start,
                end=args.end,
                location=args.location,
                description=args.description,
                calendar_id=args.calendar_id,
            )
        )

    @registry.tool(
        "calendar_delete_event",
        "Delete a Google Calendar event. Find its id with calendar_list_events first. The user "
        "must approve the deletion.",
        DeleteEventArgs,
        risk=RiskLevel.DESTRUCTIVE,
        enabled=enabled,
        summarize=lambda a, ctx: (
            f"Delete the calendar event {_event_label(ctx, a.event_id, a.calendar_id)}"
        ),
    )
    def calendar_delete_event(ctx: ToolContext, args: DeleteEventArgs):
        _guard(lambda: _service(ctx).delete_event(args.event_id, args.calendar_id))
        return {"deleted": args.event_id}
