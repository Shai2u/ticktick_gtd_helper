# TickTick GTD

Minimal Django app for OAuth login to TickTick and Inbox listing.

## What it shows

- Inbox tasks
- `tags`
- `createdTime`
- `dueDate`

## Environment

Configure [.env](.env) with either key set:

- `TICKTICK_CLIENT_ID` or `TT_CLIENT_ID`
- `TICKTICK_CLIENT_SECRET` or `TT_CLIENT_SECRET`
- `TICKTICK_REDIRECT_URI` or `TT_REDIRECT_URI` (example: `http://127.0.0.1:8000/oauth/callback/`)
- `DJANGO_SECRET_KEY`
- `DEBUG=True`

## Run

```powershell
C:/Users/shai/Documents/personal/personal_projects/ticktick-gtd/.venv/Scripts/python.exe manage.py migrate
C:/Users/shai/Documents/personal/personal_projects/ticktick-gtd/.venv/Scripts/python.exe manage.py runserver
```

Open http://127.0.0.1:8000 and click “Connect TickTick”.

