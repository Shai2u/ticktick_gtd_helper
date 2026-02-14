from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


def load_env() -> None:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe TickTick via pyticktick (unofficial flow).")
    parser.add_argument("--title", default="Focus Hazafa to balance", help="Task title substring to search.")
    parser.add_argument("--dump-json", default="", help="Optional path to dump raw batch JSON.")
    args = parser.parse_args()

    load_env()

    username = os.getenv("TICKTICK_USER") or os.getenv("TT_USER") or ""
    password = os.getenv("TICKTICK_PASS") or os.getenv("TT_PASS") or ""

    if not username or not password or password == "your_password":
        raise SystemExit("Missing real TickTick credentials in .env. Set TICKTICK_USER and TICKTICK_PASS.")

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
