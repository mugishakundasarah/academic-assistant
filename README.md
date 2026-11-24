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

Startup applies the SQLite migration automatically. The default database is
`backend/instance/academic.sqlite3` when started from the backend directory.
Set `SQLITE_PATH` to use a different file. The health endpoint checks the migrated database.

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
