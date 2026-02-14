from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

BASE_URL = "https://api.ticktick.com/open/v1"


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simple TickTick OpenAPI playground (GET only)."
    )
    parser.add_argument(
        "path",
        help="API path under /open/v1, e.g. /project or /task or /project/<id>/data",
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
    resp = api_get(token=token, path=args.path, params=params)
    print_response(resp)


if __name__ == "__main__":
    main()
