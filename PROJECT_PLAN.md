# Academic Assistant project plan

The application will use a Next.js and TypeScript frontend, a Python and FastAPI backend, and SQLite. Keep the backend a modular monolith with clear boundaries for integrations, tasks, scheduling, and AI. The local foundation is working. Read-only pull previews can be tested before building the task register. Persisted imports and deduplication still depend on the task register.

| Milestone | Depends on | Acceptance check |
| --- | --- | --- |
| Frontend and backend foundation | Development workflow | Build the frontend, call a local backend endpoint, and migrate a fresh SQLite database. |
| Read-only academic pull previews | Foundation and supported provider access | Fetch one course’s records with offline fixtures, then verify authorized live access. Canvas assignment pagination has fixture coverage. Gradescope and Ed Discussion await supported access details. |
| Task register and quick capture | Foundation | Create and update tasks, preserve provenance, and verify repeated imports do not create duplicates. |
| Academic ingestion | Task register | Test Canvas, Ed Discussion, Gradescope, and Outlook in separate assignments using fixtures. Verify incremental sync, retries, and stable source IDs. Verify institution-supported access before any live account testing. |
| Evening review | Task register | Review pending tasks, capture changes, and resume an interrupted review without losing saved updates. |
| Scheduling | Task register | Create an explainable proposed schedule from deadlines, calendar availability, durations, and priorities. Verify conflict and infeasibility handling. Use fixture calendars until Outlook access is approved. |
| Estimate corrections | Scheduling | Record corrected estimates, retain their history, and demonstrate how corrections affect later proposals. |
| Source-grounded AI answers | Academic ingestion | Answer from indexed coursework with traceable citations and indicate when the sources do not support an answer. Test with a fixed corpus and mock provider. |

For each active feature, track owner, status, dependencies, acceptance checks, and review findings in the working plan. Start live integration and deployment work only with the approvals described in [AGENTS.md](AGENTS.md).
