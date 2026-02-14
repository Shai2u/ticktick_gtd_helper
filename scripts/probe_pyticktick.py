from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import requests
from tqdm import tqdm


def load_env() -> None:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")


def oauth_token_from_django_session() -> str:
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


def to_plain(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool, list, dict)):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except TypeError:
            return obj.model_dump()
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return {k: to_plain(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)


def get_value(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in d:
            return d[key]
    return default


def extract_projects(batch_plain: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("project_profiles", "projectProfiles", "projects"):
        value = get_value(batch_plain, key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def extract_tasks(batch_plain: dict[str, Any]) -> list[dict[str, Any]]:
    sync_task_bean = get_value(batch_plain, "sync_task_bean", "syncTaskBean", default={})
    if isinstance(sync_task_bean, dict):
        update = get_value(sync_task_bean, "update")
        if isinstance(update, list):
            return [x for x in update if isinstance(x, dict)]

    for key in ("tasks", "task", "update"):
        value = get_value(batch_plain, key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]

    return []


def find_inbox_candidates(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in projects:
        pid = str(get_value(p, "id", default=""))
        name = str(get_value(p, "name", default=""))
        kind = str(get_value(p, "kind", default=""))
        ptype = str(get_value(p, "type", default=""))
        is_inbox = bool(get_value(p, "isInbox", "is_inbox", default=False))

        score = 0
        if pid.startswith("inbox"):
            score += 2
        if "inbox" in name.lower():
            score += 2
        if kind.upper() == "INBOX" or ptype.upper() == "INBOX" or is_inbox:
            score += 3

        if score > 0:
            out.append(
                {
                    "score": score,
                    "id": pid,
                    "name": name,
                    "kind": kind,
                    "type": ptype,
                    "isInbox": is_inbox,
                }
            )

    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def task_project_id(task: dict[str, Any]) -> str:
    return str(get_value(task, "projectId", "project_id", default=""))


def task_title(task: dict[str, Any]) -> str:
    return str(get_value(task, "title", "content", default="")).strip()


def openapi_get(token: str, path: str) -> requests.Response:
    url = f"https://api.ticktick.com/open/v1{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    return requests.get(url, headers=headers, timeout=30)


def run_oauth_mode(title: str, oauth_token: str, max_projects: int = 0) -> None:
    print("Using OAuth token mode (OpenAPI)")

    projects_resp = openapi_get(oauth_token, "/project")
    if not projects_resp.ok:
        raise SystemExit(f"Failed /project: {projects_resp.status_code} {projects_resp.text}")

    payload = projects_resp.json() if projects_resp.text else None
    if isinstance(payload, list):
        projects = [x for x in payload if isinstance(x, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("projects"), list):
        projects = [x for x in payload["projects"] if isinstance(x, dict)]
    else:
        projects = []

    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    projects_to_scan = projects[:max_projects] if max_projects and max_projects > 0 else projects

    for p in tqdm(projects_to_scan, desc="OAuth scan", unit="project"):
        pid = str(get_value(p, "id", default="")).strip()
        if not pid:
            continue
        data_resp = openapi_get(oauth_token, f"/project/{pid}/data")
        if not data_resp.ok:
            continue
        pd = data_resp.json() if data_resp.text else None
        ptasks = extract_tasks(pd)
        for t in ptasks:
            if t.get("projectId") in (None, ""):
                t["projectId"] = pid
            tid = str(get_value(t, "id", default="")).strip()
            if tid and tid in seen:
                continue
            if tid:
                seen.add(tid)
            tasks.append(t)

    print("\n=== RESULT 1: TOTAL TASK COUNT ===")
    print(f"Projects scanned: {len(projects_to_scan)} / {len(projects)}")
    print(f"Total tasks returned in OAuth mode: {len(tasks)}")

    print("\n=== RESULT 2: INBOX CANDIDATES ===")
    inbox_candidates = find_inbox_candidates(projects)
    print(f"Project count: {len(projects)}")
    print(f"Inbox candidate count: {len(inbox_candidates)}")
    for c in inbox_candidates[:20]:
        print(
            f"- score={c['score']} name={c['name']} id={c['id']} kind={c['kind']} type={c['type']} isInbox={c['isInbox']}"
        )

    print("\n=== RESULT 3: TITLE MATCH ===")
    needle = title.strip().lower()
    matches = []
    for t in tasks:
        ttitle = task_title(t)
        if needle and needle in ttitle.lower():
            matches.append(
                {
                    "id": str(get_value(t, "id", default="")),
                    "title": ttitle,
                    "projectId": task_project_id(t),
                    "status": get_value(t, "status", default=""),
                }
            )
    print(f"Matches for {title!r}: {len(matches)}")
    for m in matches[:20]:
        print(f"- {m['title']} | projectId={m['projectId']} | status={m['status']} | id={m['id']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe TickTick via pyticktick (unofficial flow).")
    parser.add_argument("--oauth-token", default="", help="Use OAuth access token directly (OpenAPI mode).")
    parser.add_argument("--oauth-from-django-session", action="store_true", help="Load OAuth token from Django session.")
    parser.add_argument("--max-projects", type=int, default=0, help="In OAuth mode, scan only first N projects (0 means all).")
    parser.add_argument("--username", default="", help="TickTick username/email")
    parser.add_argument("--password", default="", help="TickTick password")
    parser.add_argument("--title", default="Focus Hazafa to balance", help="Task title substring to search.")
    parser.add_argument("--dump-json", default="", help="Optional path to dump raw batch JSON.")
    args = parser.parse_args()

    load_env()

    oauth_token = (
        args.oauth_token
        or os.getenv("TICKTICK_ACCESS_TOKEN")
        or os.getenv("TT_ACCESS_TOKEN")
    )
    if not oauth_token and args.oauth_from_django_session:
        oauth_token = oauth_token_from_django_session()

    if oauth_token:
        run_oauth_mode(args.title, oauth_token, max_projects=args.max_projects)
        return

    username = args.username or os.getenv("TICKTICK_USER") or os.getenv("TT_USER") or ""
    password = args.password or os.getenv("TICKTICK_PASS") or os.getenv("TT_PASS") or ""

    if not username:
        username = input("TickTick username/email: ").strip()
    if not password or password == "your_password":
        password = getpass.getpass("TickTick password: ").strip()

    if not username or not password:
        raise SystemExit("Missing credentials. Pass --username/--password or set TICKTICK_USER and TICKTICK_PASS.")

    from pyticktick import Client

    print("Connecting with pyticktick...")
    client = Client(v2_username=username, v2_password=password)

    print("Fetching batch v2 payload...")
    batch = client.get_batch_v2()
    batch_plain = to_plain(batch)
    if not isinstance(batch_plain, dict):
        raise SystemExit("Unexpected batch payload format from pyticktick")

    if args.dump_json:
        dump_path = Path(args.dump_json).expanduser().resolve()
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        dump_path.write_text(json.dumps(batch_plain, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Raw batch JSON saved to: {dump_path}")

    projects = extract_projects(batch_plain)
    tasks = extract_tasks(batch_plain)

    print("\n=== RESULT 1: TOTAL TASK COUNT ===")
    print(f"Total tasks returned by pyticktick batch: {len(tasks)}")

    print("\n=== RESULT 2: INBOX CANDIDATES ===")
    inbox_candidates = find_inbox_candidates(projects)
    print(f"Project count: {len(projects)}")
    print(f"Inbox candidate count: {len(inbox_candidates)}")
    for c in inbox_candidates[:20]:
        print(
            f"- score={c['score']} name={c['name']} id={c['id']} kind={c['kind']} type={c['type']} isInbox={c['isInbox']}"
        )

    print("\n=== RESULT 3: TITLE MATCH ===")
    needle = args.title.strip().lower()
    matches: list[dict[str, Any]] = []
    for t in tasks:
        title = task_title(t)
        if needle and needle in title.lower():
            matches.append(
                {
                    "id": str(get_value(t, "id", default="")),
                    "title": title,
                    "projectId": task_project_id(t),
                    "status": get_value(t, "status", default=""),
                }
            )

    print(f"Matches for {args.title!r}: {len(matches)}")
    for m in matches[:20]:
        print(f"- {m['title']} | projectId={m['projectId']} | status={m['status']} | id={m['id']}")


if __name__ == "__main__":
    main()
