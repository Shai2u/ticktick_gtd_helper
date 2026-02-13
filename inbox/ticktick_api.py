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


def _extract_tasks_from_project_data(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    for key in ("tasks", "task"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _dedupe_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task.get("id", ""))
        if task_id and task_id in seen:
            continue
        if task_id:
            seen.add(task_id)
        result.append(task)
    return result


def list_inbox_tasks(access_token: str, inbox_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    debug: dict[str, Any] = {
        "source_task_endpoint_count": 0,
        "source_project_data_count": 0,
    }

    task_endpoint_tasks: list[dict[str, Any]] = []
    project_data_tasks: list[dict[str, Any]] = []

    try:
        data = api_get("/task", access_token, params={"projectId": inbox_id})
        if isinstance(data, list):
            task_endpoint_tasks = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict) and isinstance(data.get("tasks"), list):
            task_endpoint_tasks = [item for item in data["tasks"] if isinstance(item, dict)]
        debug["source_task_endpoint_count"] = len(task_endpoint_tasks)
    except TickTickAPIError as ex:
        debug["task_endpoint_error"] = str(ex)

    try:
        project_data = api_get(f"/project/{inbox_id}/data", access_token)
        project_data_tasks = _extract_tasks_from_project_data(project_data)
        debug["source_project_data_count"] = len(project_data_tasks)
    except TickTickAPIError as ex:
        debug["project_data_error"] = str(ex)

    merged = _dedupe_tasks(task_endpoint_tasks + project_data_tasks)
    debug["merged_count"] = len(merged)
    return merged, debug


def _task_project_id(task: dict[str, Any]) -> str:
    pid = task.get("projectId") or task.get("project_id") or task.get("project") or ""
    return str(pid)


def _counts_by_project(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        pid = _task_project_id(task)
        counts[pid] = counts.get(pid, 0) + 1
    return counts


def normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": task.get("title") or task.get("content") or "(untitled)",
        "tags": task.get("tags") or [],
        "created_time": task.get("createdTime") or "",
        "due_date": task.get("dueDate") or "",
    }


def fetch_inbox_listing(access_token: str) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    projects = list_projects(access_token)
    inbox_id = find_inbox_id(projects)
    raw_tasks, task_debug = list_inbox_tasks(access_token, inbox_id)

    all_tasks_count = None
    all_tasks_error = ""
    try:
        all_tasks_payload = api_get("/task", access_token)
        if isinstance(all_tasks_payload, list):
            all_tasks_count = len([t for t in all_tasks_payload if isinstance(t, dict)])
            all_tasks_items = [t for t in all_tasks_payload if isinstance(t, dict)]
        elif isinstance(all_tasks_payload, dict) and isinstance(all_tasks_payload.get("tasks"), list):
            all_tasks_items = [t for t in all_tasks_payload["tasks"] if isinstance(t, dict)]
            all_tasks_count = len(all_tasks_items)
        else:
            all_tasks_items = []
    except TickTickAPIError as ex:
        all_tasks_error = str(ex)
        all_tasks_items = []

    all_counts = _counts_by_project(all_tasks_items)
    inbox_in_all_tasks_count = all_counts.get(inbox_id, 0)

    project_name_by_id = {
        str(p.get("id", "")): str(p.get("name", ""))
        for p in projects
    }

    top_projects = sorted(all_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    all_tasks_top_projects = [
        {
            "id": pid,
            "name": project_name_by_id.get(pid, "(unknown)"),
            "count": count,
        }
        for pid, count in top_projects
    ]

    sample_tasks = [
        {
            "title": str(t.get("title") or t.get("content") or "(untitled)"),
            "project_id": _task_project_id(t),
        }
        for t in all_tasks_items[:5]
    ]

    diagnosis = ""
    merged_count = int(task_debug.get("merged_count", 0))
    if merged_count == 0:
        if all_tasks_count and all_tasks_count > 0:
            diagnosis = "API is connected, but Inbox appears empty. Your tasks are likely in other lists/projects."
        elif all_tasks_count == 0:
            diagnosis = "API is connected, but no tasks were returned at all for this token/account."

    project_list = [
        {
            "id": str(p.get("id", "")),
            "name": str(p.get("name", "")),
            "group_id": str(p.get("groupId", "")),
            "parent_id": str(p.get("parentId", "")),
        }
        for p in projects
    ]

    debug = {
        "projects_count": len(projects),
        "project_list": project_list[:20],
        "project_list_truncated": len(project_list) > 20,
        "all_tasks_count": all_tasks_count,
        "inbox_in_all_tasks_count": inbox_in_all_tasks_count,
        "all_tasks_error": all_tasks_error,
        "all_tasks_top_projects": all_tasks_top_projects,
        "all_tasks_sample": sample_tasks,
        "diagnosis": diagnosis,
        **task_debug,
    }
    tasks = [normalize_task(t) for t in raw_tasks]
    return inbox_id, tasks, debug
