"""Read-only editor surface: the whole-timeline project document.

Deliberately the narrowest door in the service — one GET, no body, no POST sibling.
Everything the web editor can see is what ``/api/frame`` already decides to render.
"""

from __future__ import annotations

from aiohttp import web

from ..model.editor_project import TimelineAmbiguous, build_editor_project
from ..session import TimelineNotFound
from ._http import JSON, error_payload, offload, selector, session_of


async def editor_project(request: web.Request) -> web.Response:
    session = session_of(request)
    wanted = request.query.get("timeline")
    draft = selector(request)
    view = await offload(lambda: session.view(draft))
    try:
        payload = await offload(lambda: build_editor_project(view, wanted))
    except TimelineAmbiguous as exc:
        return error_payload("timeline_ambiguous", str(exc), status=409, draft=view.did,
                             timelines=[item.get("id") for item in view.timelines],
                             available=exc.available)
    except TimelineNotFound as exc:
        return error_payload("timeline_not_found", str(exc), status=404, draft=view.did,
                             available=exc.available)
    request.app["watcher"].watch(view.did, view.root)
    return JSON(payload)
