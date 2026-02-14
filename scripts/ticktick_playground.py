from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from openpyxl import Workbook
from tqdm import tqdm

BASE_URL = "https://api.ticktick.com/open/v1"

EXPORT_COLUMNS = [
    "tags",
    "title",
    "content",
    "desc",
    "id",
    "projectId",
    "status",
    # Useful extras
    "parentId",
    "priority",
    "createdTime",
    "startDate",
    "dueDate",
    "completedTime",
    "modifiedTime",
]


def load_env() -> None:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")


def token_from_django_session() -> str:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ticktick_gtd.settings")

    import django

    django.setup()

    from django.contrib.sessions.models import Session

    for session in Session.objects.order_by("-expire_date"):
        data = session.get_decoded()
        token = data.get("ticktick_oauth_token")
        if isinstance(token, dict) and token.get("access_token"):
            return str(token["access_token"])
    return ""


def parse_params(values: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Invalid --param value: {value!r}. Expected key=value")
        key, raw = value.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        if not key:
            raise ValueError(f"Invalid --param key in: {value!r}")
        params[key] = raw
    return params


def api_get(token: str, path: str, params: dict[str, str] | None = None) -> requests.Response:
    if not path.startswith("/"):
        path = f"/{path}"
    url = f"{BASE_URL}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    return requests.get(url, headers=headers, params=params, timeout=30)


def print_response(resp: requests.Response) -> None:
    print(f"status: {resp.status_code}")
    print(f"ok: {resp.ok}")
    print(f"url: {resp.url}")
    print("-" * 60)
    try:
        payload: Any = resp.json()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    except ValueError:
        print(resp.text)


def extract_tasks(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("tasks", "task"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def has_no_project(task: dict[str, Any]) -> bool:
    value = task.get("projectId")
    return value in (None, "")


def has_no_parent(task: dict[str, Any]) -> bool:
    value = task.get("parentId")
    return value in (None, "")


def apply_task_filters(
    tasks: list[dict[str, Any]],
    only_no_project: bool,
    only_inbox_heuristic: bool,
    only_no_parent: bool,
) -> list[dict[str, Any]]:
    filtered = tasks

    if only_no_project:
        filtered = [t for t in filtered if has_no_project(t)]

    if only_inbox_heuristic:
        filtered = [
            t
            for t in filtered
            if has_no_project(t) or str(t.get("projectId", "")).startswith("inbox")
        ]

    if only_no_parent:
        filtered = [t for t in filtered if has_no_parent(t)]

    return filtered


def export_tasks_to_excel(tasks: list[dict[str, Any]], output_path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "tasks"

    ws.append(EXPORT_COLUMNS)
    for task in tasks:
        row: list[Any] = []
        for col in EXPORT_COLUMNS:
            value = task.get(col)
            if col == "tags" and isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            elif isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            row.append(value)
        ws.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)


def list_projects(token: str) -> list[dict[str, Any]]:
    resp = api_get(token=token, path="/project")
    if not resp.ok:
        raise SystemExit(f"Failed to list projects: {resp.status_code} {resp.text}")

    payload: Any = resp.json() if resp.text else None
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("projects"), list):
        return [item for item in payload["projects"] if isinstance(item, dict)]
    return []


def list_all_tasks_via_projects(token: str) -> list[dict[str, Any]]:
    projects = list_projects(token)
    all_tasks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for project in tqdm(projects, desc="Scanning projects", unit="project"):
        project_id = str(project.get("id", "")).strip()
        if not project_id:
            continue

        resp = api_get(token=token, path=f"/project/{project_id}/data")
        if not resp.ok:
            continue

        payload: Any = resp.json() if resp.text else None
        tasks = extract_tasks(payload)
        for task in tasks:
            if "projectId" not in task or task.get("projectId") in (None, ""):
                task["projectId"] = project_id

            tid = str(task.get("id", "")).strip()
            if tid and tid in seen_ids:
                continue
            if tid:
                seen_ids.add(tid)
            all_tasks.append(task)

    return all_tasks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simple TickTick OpenAPI playground (GET only)."
    )
    parser.add_argument(
        "path",
        help="API path under /open/v1 (e.g. /project, /task, /project/<id>/data) or /all-tasks (aggregated mode)",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="Query string parameter as key=value. Can be used multiple times.",
    )
    parser.add_argument(
        "--token",
        default="",
        help="Access token. If omitted, reads TICKTICK_ACCESS_TOKEN or TT_ACCESS_TOKEN from env.",
    )
    parser.add_argument(
        "--from-django-session",
        action="store_true",
        help="If no token is provided, try reading the latest OAuth token from Django sessions.",
    )
    parser.add_argument(
        "--only-no-project",
        action="store_true",
        help="When response contains tasks, keep only tasks with empty/missing projectId.",
    )
    parser.add_argument(
        "--only-inbox-heuristic",
        action="store_true",
        help="When response contains tasks, keep tasks with empty/missing projectId OR projectId starting with 'inbox'.",
    )
    parser.add_argument(
        "--only-no-parent",
        action="store_true",
        help="When response contains tasks, keep only tasks with empty/missing parentId.",
    )
    parser.add_argument(
        "--export-xlsx",
        default="",
        help="Optional path to export tasks to .xlsx (after filters are applied).",
    )

    args = parser.parse_args()

    load_env()

    token = args.token or os.getenv("TICKTICK_ACCESS_TOKEN") or os.getenv("TT_ACCESS_TOKEN")
    # Always try Django session fallback if env/arg token is missing.
    # The flag is still accepted, but fallback is enabled by default to simplify debugging.
    if not token:
        token = token_from_django_session()

    if not token:
        raise SystemExit(
            "Missing access token. Reconnect once in the Django app so a session token exists, or pass --token / set TICKTICK_ACCESS_TOKEN."
        )

    params = parse_params(args.param)

    if args.path.strip().lower() in {"/all-tasks", "all-tasks"}:
        tasks = list_all_tasks_via_projects(token)
        print("status: 200")
        print("ok: True")
        print("url: aggregated:/project/*/data")
        print("-" * 60)

        filtered = apply_task_filters(
            tasks,
            only_no_project=args.only_no_project,
            only_inbox_heuristic=args.only_inbox_heuristic,
            only_no_parent=args.only_no_parent,
        )

        print(f"tasks total: {len(tasks)}")
        print(f"tasks filtered: {len(filtered)}")

        if args.export_xlsx:
            output = Path(args.export_xlsx).expanduser().resolve()
            export_tasks_to_excel(filtered, output)
            print(f"exported: {output}")
            return

        print(json.dumps(filtered, indent=2, ensure_ascii=False))
        return

    resp = api_get(token=token, path=args.path, params=params)

    try:
        payload: Any = resp.json() if resp.text else None
    except ValueError:
        payload = None

    if (args.only_no_project or args.only_inbox_heuristic or args.only_no_parent or args.export_xlsx) and payload is not None:
        tasks = extract_tasks(payload)
        if tasks:
            filtered = apply_task_filters(
                tasks,
                only_no_project=args.only_no_project,
                only_inbox_heuristic=args.only_inbox_heuristic,
                only_no_parent=args.only_no_parent,
            )

            print(f"status: {resp.status_code}")
            print(f"ok: {resp.ok}")
            print(f"url: {resp.url}")
            print("-" * 60)
            print(f"tasks total: {len(tasks)}")
            print(f"tasks filtered: {len(filtered)}")

            if args.export_xlsx:
                output = Path(args.export_xlsx).expanduser().resolve()
                export_tasks_to_excel(filtered, output)
                print(f"exported: {output}")
                return

            print(json.dumps(filtered, indent=2, ensure_ascii=False))
            return

    print_response(resp)


if __name__ == "__main__":
    main()
