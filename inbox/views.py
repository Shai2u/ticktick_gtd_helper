from __future__ import annotations

import secrets

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .ticktick_api import (
    TickTickAPIError,
    build_authorize_url,
    exchange_code_for_token,
    fetch_inbox_listing,
)


SESSION_TOKEN_KEY = "ticktick_oauth_token"
SESSION_STATE_KEY = "ticktick_oauth_state"


def home(request: HttpRequest) -> HttpResponse:
    token = request.session.get(SESSION_TOKEN_KEY)
    if not token or not token.get("access_token"):
        return render(request, "inbox/home.html", {"connected": False})

    try:
        inbox_id, tasks, debug = fetch_inbox_listing(token["access_token"])
        return render(
            request,
            "inbox/home.html",
            {
                "connected": True,
                "inbox_id": inbox_id,
                "tasks": tasks,
                "debug": debug,
                "error": "",
            },
        )
    except TickTickAPIError as ex:
        return render(
            request,
            "inbox/home.html",
            {
                "connected": True,
                "tasks": [],
                "debug": {},
                "error": f"TickTick API error: {ex}",
            },
        )


def oauth_login(request: HttpRequest) -> HttpResponse:
    state = secrets.token_urlsafe(24)
    request.session[SESSION_STATE_KEY] = state
    return redirect(build_authorize_url(state))


def oauth_callback(request: HttpRequest) -> HttpResponse:
    expected_state = request.session.get(SESSION_STATE_KEY)
    got_state = request.GET.get("state")
    code = request.GET.get("code")

    if not expected_state or expected_state != got_state:
        return HttpResponse("Invalid OAuth state", status=400)
    if not code:
        return HttpResponse("Missing OAuth code", status=400)

    try:
        token = exchange_code_for_token(code)
        request.session[SESSION_TOKEN_KEY] = token
    except TickTickAPIError as ex:
        return HttpResponse(f"OAuth exchange failed: {ex}", status=400)

    return redirect("home")


def disconnect(request: HttpRequest) -> HttpResponse:
    request.session.pop(SESSION_TOKEN_KEY, None)
    request.session.pop(SESSION_STATE_KEY, None)
    return redirect("home")
