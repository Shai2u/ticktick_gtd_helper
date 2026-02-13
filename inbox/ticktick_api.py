from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import requests
from django.conf import settings


class TickTickAPIError(Exception):
    pass


AUTH_URL = "https://ticktick.com/oauth/authorize"
TOKEN_URLS = [
    "https://ticktick.com/oauth/token",
    "https://api.ticktick.com/oauth/token",
]
OPEN_API_BASE = "https://api.ticktick.com/open/v1"


def build_authorize_url(state: str) -> str:
    if not settings.TICKTICK_CLIENT_ID:
        raise TickTickAPIError("Missing TICKTICK_CLIENT_ID/TT_CLIENT_ID in .env")

    params = {
        "client_id": settings.TICKTICK_CLIENT_ID,
        "scope": settings.TICKTICK_SCOPE,
        "state": state,
        "redirect_uri": settings.TICKTICK_REDIRECT_URI,
        "response_type": "code",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code_for_token(code: str) -> dict[str, Any]:
    payload = {
        "client_id": settings.TICKTICK_CLIENT_ID,
        "client_secret": settings.TICKTICK_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": settings.TICKTICK_REDIRECT_URI,
        "scope": settings.TICKTICK_SCOPE,
    }

    if not settings.TICKTICK_CLIENT_ID or not settings.TICKTICK_CLIENT_SECRET:
        raise TickTickAPIError("Missing TickTick client id/secret in .env")

    last_error = "Token exchange failed"
    for token_url in TOKEN_URLS:
        try:
            response = requests.post(token_url, data=payload, timeout=20)
            if response.ok:
                data = response.json()
                if "access_token" in data:
                    expires_in = int(data.get("expires_in", 3600))
                    data["expires_at"] = (
                        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                    ).isoformat()
                    return data
            last_error = f"{response.status_code} {response.text}"
        except requests.RequestException as ex:
            last_error = str(ex)

    raise TickTickAPIError(last_error)


def api_get(path: str, access_token: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{OPEN_API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    response = requests.get(url, headers=headers, params=params, timeout=20)
    if not response.ok:
        raise TickTickAPIError(f"{response.status_code} {response.text}")
    return response.json()


def list_projects(access_token: str) -> list[dict[str, Any]]:
    data = api_get("/project", access_token)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("projects"), list):
        return data["projects"]
    raise TickTickAPIError("Unexpected projects response")


def find_inbox_id(projects: list[dict[str, Any]]) -> str:
    for p in projects:
        pid = str(p.get("id", ""))
        name = str(p.get("name", "")).lower().strip()
        if pid.startswith("inbox") or name == "inbox":
            return pid
    raise TickTickAPIError("Inbox not found")


def list_inbox_tasks(access_token: str, inbox_id: str) -> list[dict[str, Any]]:
    try:
        data = api_get("/task", access_token, params={"projectId": inbox_id})
        if isinstance(data, list):
            return data
    except TickTickAPIError:
        pass

    project_data = api_get(f"/project/{inbox_id}/data", access_token)
    if isinstance(project_data, dict) and isinstance(project_data.get("tasks"), list):
        return project_data["tasks"]
    return []


def normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": task.get("title") or task.get("content") or "(untitled)",
        "tags": task.get("tags") or [],
        "created_time": task.get("createdTime") or "",
        "due_date": task.get("dueDate") or "",
    }


def fetch_inbox_listing(access_token: str) -> tuple[str, list[dict[str, Any]]]:
    projects = list_projects(access_token)
    inbox_id = find_inbox_id(projects)
    tasks = [normalize_task(t) for t in list_inbox_tasks(access_token, inbox_id)]
    return inbox_id, tasks
