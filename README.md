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
- `TICKTICK_REDIRECT_URI` or `TT_REDIRECT_URI` (example: `http://127.0.0.1:8022/oauth/callback/`)
- `DJANGO_SECRET_KEY`
- `DEBUG=True`

## Run

```powershell
C:/Users/shai/Documents/personal/personal_projects/ticktick-gtd/.venv/Scripts/python.exe manage.py migrate
C:/Users/shai/Documents/personal/personal_projects/ticktick-gtd/.venv/Scripts/python.exe manage.py runserver
```

Open http://127.0.0.1:8020 and click “Connect TickTick”.

## Simple API playground script

Use [scripts/ticktick_playground.py](scripts/ticktick_playground.py) for direct API testing.

Set an access token in env (from your OAuth flow):

```powershell
$env:TICKTICK_ACCESS_TOKEN="YOUR_ACCESS_TOKEN"
```

Examples:

```powershell
# List projects/lists
C:/Users/shai/Documents/personal/personal_projects/ticktick-gtd/.venv/Scripts/python.exe scripts/ticktick_playground.py /project

# Get all tasks endpoint (may return 500 on some accounts)
C:/Users/shai/Documents/personal/personal_projects/ticktick-gtd/.venv/Scripts/python.exe scripts/ticktick_playground.py /task

# Get tasks by project id
C:/Users/shai/Documents/personal/personal_projects/ticktick-gtd/.venv/Scripts/python.exe scripts/ticktick_playground.py /task --param projectId=659b98208f0806acbf9f814e

# Get project data (often includes tasks)
C:/Users/shai/Documents/personal/personal_projects/ticktick-gtd/.venv/Scripts/python.exe scripts/ticktick_playground.py /project/659b98208f0806acbf9f814e/data
```

