from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests


def _setup_django() -> None:
    project_root = Path(__file__).resolve().parents[1]
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ticktick_gtd.settings")
    os.chdir(project_root)
    import django

    django.setup()


def _find_latest_token() -> dict[str, Any] | None:
    from django.contrib.sessions.models import Session

    sessions = Session.objects.order_by("-expire_date")
    for s in sessions:
        data = s.get_decoded()
        token = data.get("ticktick_oauth_token")
        if isinstance(token, dict) and token.get("access_token"):
            return token
    return None


def _api_get(path: str, token: str, params: dict[str, Any] | None = None) -> Any:
    url = f"https://api.ticktick.com/open/v1{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.get(url, headers=headers, params=params, timeout=30)
    return {
        "status": r.status_code,
        "ok": r.ok,
        "json": r.json() if r.text else None,
        "text": r.text[:400],
    }


def _projects_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("projects"), list):
        return [p for p in payload["projects"] if isinstance(p, dict)]
    return []


def _tasks_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [t for t in payload if isinstance(t, dict)]
    if isinstance(payload, dict):
        for key in ("tasks", "task"):
            if isinstance(payload.get(key), list):
                return [t for t in payload[key] if isinstance(t, dict)]
    return []


def main() -> None:
    _setup_django()

    token = _find_latest_token()
    if not token:
        print("No OAuth token found in Django sessions. Reconnect in browser first.")
        return

    access_token = token.get("access_token", "")
    print(f"Found OAuth token: ...{access_token[-6:]}")

    projects_resp = _api_get("/project", access_token)
    print(f"/project -> status={projects_resp['status']} ok={projects_resp['ok']}")
    if not projects_resp["ok"]:
        print(projects_resp["text"])
        return

    projects = _projects_from_payload(projects_resp["json"])
    print(f"Projects count: {len(projects)}")

    inbox = None
    for p in projects:
        pid = str(p.get("id", ""))
        name = str(p.get("name", "")).strip()
        if pid.startswith("inbox") or name.lower() == "inbox":
            inbox = p
            break

    if not inbox:
        print("Inbox project was not found.")
        return

    inbox_id = str(inbox.get("id"))
    print(f"Inbox found: {inbox.get('name')} ({inbox_id})")

    task_filtered = _api_get("/task", access_token, params={"projectId": inbox_id})
    filtered_tasks = _tasks_from_payload(task_filtered["json"]) if task_filtered["ok"] else []
    print(
        f"/task?projectId=inbox -> status={task_filtered['status']} ok={task_filtered['ok']} count={len(filtered_tasks)}"
    )

    proj_data = _api_get(f"/project/{inbox_id}/data", access_token)
    proj_tasks = _tasks_from_payload(proj_data["json"]) if proj_data["ok"] else []
    print(f"/project/{{id}}/data -> status={proj_data['status']} ok={proj_data['ok']} count={len(proj_tasks)}")

    all_tasks_resp = _api_get("/task", access_token)
    all_tasks = _tasks_from_payload(all_tasks_resp["json"]) if all_tasks_resp["ok"] else []
    print(f"/task (all) -> status={all_tasks_resp['status']} ok={all_tasks_resp['ok']} count={len(all_tasks)}")

    inbox_from_all = [t for t in all_tasks if str(t.get("projectId", "")) == inbox_id]
    print(f"All-tasks scan where projectId == inbox_id: {len(inbox_from_all)}")

    if filtered_tasks:
        sample = filtered_tasks[0]
        print(
            f"Sample inbox task: title={sample.get('title') or sample.get('content')} due={sample.get('dueDate')}"
        )
    elif proj_tasks:
        sample = proj_tasks[0]
        print(
            f"Sample inbox task (from project data): title={sample.get('title') or sample.get('content')} due={sample.get('dueDate')}"
        )
    else:
        print("No inbox tasks found by any endpoint.")


if __name__ == "__main__":
    main()
