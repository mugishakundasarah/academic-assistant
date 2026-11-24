# Academic Assistant

Local Next.js and TypeScript frontend with a FastAPI and SQLite backend.

## Local development

Use Python 3.12 and Node.js 24. From the repository root, set up the backend and start it in one terminal.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements.lock
cd backend
python -m uvicorn academic_assistant.main:app --reload
```

Startup applies any pending SQLite migrations automatically, upgrading an
existing database in place. The default database is
`backend/instance/academic.sqlite3` when started from the backend directory.
Set `SQLITE_PATH` to use a different file. The health endpoint checks that the
database is at the latest schema version.

If `backend/.env` exists, startup loads it with python-dotenv (installed from
the lock file). Variables already set in the process environment win over the
file. Copy `backend/.env.example` to start; `.env` is ignored by git.

In a second terminal, from the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Open the URL printed by Next.js. The status page calls the backend server-side.
Set `BACKEND_URL` in the frontend process if FastAPI runs on a different address.

## Checks

Run `python -m unittest discover -s tests -v` from `backend` with the virtual
environment active. Run `npm run build` from `frontend`.

## Canvas sync

The backend syncs each active Canvas course's assignments (with your submission
status) and announcements from the last 60 days into SQLite and serves them
under `/api`: `GET /api/canvas/status`, `POST /api/canvas/sync`,
`GET /api/courses`, `GET /api/courses/{id}`, `GET /api/courses/{id}/items`,
`GET /api/upcoming`, `GET /api/notifications`,
`POST /api/notifications/{id}/read` and `POST /api/notifications/read-all`.
FastAPI serves interactive documentation at `/docs`.

### Demo mode

To try the app without a Canvas account, start the backend with
`CANVAS_DEMO=1`, or uncomment it in `backend/.env`. Demo mode is off by
default. While it is on, it overrides any live Canvas credentials and sync never
contacts Canvas:

```sh
cd backend
CANVAS_DEMO=1 SQLITE_PATH=instance/demo.sqlite3 python -m uvicorn academic_assistant.main:app --reload
curl -X POST http://127.0.0.1:8000/api/canvas/sync
```

Sync then reads the JSON fixtures in
`academic_assistant/integrations/fixtures/canvas_demo` instead of the network:
three courses with readings, submissions, a quiz, discussions, completed and
missing work, and announcements with attachments. Dates are relative to the
start of the current week, so there is always upcoming and overdue work. The
second demo sync adds a new assignment and announcement and moves a due date,
so the notifications can be tried. Demo links point to the placeholder host
`canvas.example.com` and do not open real files. Use a separate `SQLITE_PATH`
for demo data, because demo and live records share the same tables.

### Live Canvas

Use a live account only after access is approved and with an
institution-authorized token. Set `CANVAS_BASE_URL` to the institution's HTTPS
Canvas origin (for example `https://canvas.your-school.edu`) and
`CANVAS_API_TOKEN` to the token, either in the backend process environment or in
`backend/.env`. Leave `CANVAS_DEMO` unset, because demo mode takes precedence
over live credentials. Never put the token in the frontend, source control, or chat.
`GET /api/canvas/status` reports `configured: true` once both values are valid;
without them, and without demo mode, the sync endpoint returns 503.

The backend sends the token only to the configured origin, refuses redirects
and cross-origin pagination links, and reports Canvas failures with generic
messages such as `Canvas request failed (HTTP 401).` A failure for one course
is listed in the sync response's `errors` and does not stop other courses.
Within a single server process only one sync runs at a time, and a concurrent
request returns 409. The lock is held in memory, so several server processes
(for example, multiple uvicorn workers) can sync at the same time.

### What is stored locally

The SQLite file holds, for each synced course: the course name and code;
assignment titles, plain-text descriptions, due dates, points, submission and
missing status; announcement titles, plain-text messages, authors and post
dates; the links found in them (including Canvas attachment URLs, which can
carry a per-file `verifier` parameter); and in-app notifications. Canvas HTML
is converted to plain text and only absolute `http(s)` links are kept. The
backend never downloads Canvas files and never stores the API token. Treat the
database as private coursework data.

### Limitations

- Items deleted or unpublished in Canvas, and courses you leave, stay in the
  local database; deletion handling is not implemented.
- Announcements older than 60 days are not fetched.
- The first sync of a course is a baseline: it only notifies about
  announcements posted in the last 7 days.
- Due date and content changes to an assignment that was already completed and
  is still completed are stored without a notification.
- `last_synced_at` is not updated when every course fails to sync.
- Changes to announcements after they are first seen do not notify.
- Canvas course IDs are used as local course IDs, so do not point one database
  at two Canvas instances (or at demo and live data).
- Sync runs only when `POST /api/canvas/sync` is called; there is no scheduler.

## Canvas import preview

After live account access is approved, configure `CANVAS_BASE_URL` with the
institution's HTTPS Canvas origin and supply `CANVAS_API_TOKEN` securely in the
backend process environment. Use an institution-authorized token. From
`backend`, run the preview with your numeric course ID:

```sh
python -m academic_assistant.integrations canvas 123
```

The command retrieves all assignment pages for that course and prints the source
records locally. It performs read-only requests and does not write assignments
to SQLite. The preview may contain private coursework data.

Gradescope and Ed Discussion need institution-supported methods for reading
course data before live connectors can be implemented.

## Canvas MCP tool

The local MCP server exposes `list_canvas_assignments`. It takes a positive
numeric `course_id` and returns assignment IDs, names, due dates, and Canvas
links. It uses the same read-only Canvas client as the import preview.

After installing the backend dependencies, register a local stdio server in
your MCP client. Use the backend directory as the working directory, the
virtual environment's Python as the command, and the following arguments:

```text
-m academic_assistant.integrations.canvas_mcp
```

The MCP host must securely supply `CANVAS_BASE_URL` and `CANVAS_API_TOKEN` to
the server process for live calls. Keep the token out of shared MCP config,
source control, and chat. Discovery and the fixture tests work without an
account. Confirm that the MCP host and model are approved to receive private
coursework before using the tool with live data.

## Continuous integration and deployment

Use GitHub feature branches and pull requests to share changes between VS Code
and Codex. GitHub Actions runs backend tests and the frontend type check and
production build on pull requests targeting `main` and pushes to `main`.
The checks use fixtures and require no academic credentials.

Deployment requires a hosting target that can run Next.js and FastAPI and retain
the SQLite file across releases. Once a target is approved, configure the release
job to deploy only a revision that passed CI and require human approval before
deployment. Keep deployment and academic credentials in the appropriate secret
stores.
