# Action Trigger Examples (50 Prompts)

Use these as **natural-language action prompts** in chat (no `/run` required).  
They are written to trigger the command/run workflow instead of small-talk chat.

## Backend (Python / FastAPI)

1. Build a FastAPI `/health` endpoint and add pytest coverage.
2. Add request validation for `channel_id` and return clear 400 errors.
3. Refactor duplicated response-building logic in `routes_runs.py`.
4. Add a new `/runs/{id}/cancel` endpoint with audit logging.
5. Implement pagination on `GET /runs` with `limit` and `cursor`.
6. Add structured logging middleware with trace IDs.
7. Add unit tests for idempotency cache prune behavior.
8. Add retry + timeout around outbound webhook calls.
9. Add API tests for unauthorized admin access paths.
10. Improve error messages for malformed channel payloads.

## Frontend (React / Vite)

11. Create a settings page with API base URL and save button.
12. Add a run filter UI for status: created, running, completed, failed.
13. Add a loading skeleton while run details are fetching.
14. Add toast notifications for approve/reject actions.
15. Build a reusable `RunStatusBadge` component.
16. Add a dark mode toggle and persist it in localStorage.
17. Add form validation for run creation inputs.
18. Add an error boundary around the main app shell.
19. Refactor API calls into a dedicated `services/api.ts` module.
20. Add a timeline view component for run events.

## Testing & Quality

21. Add integration tests for web channel chat-vs-run intent routing.
22. Add tests for approval aliases `yes/y` and rejection aliases `no/n`.
23. Add regression tests for replay attack detection in webhook security.
24. Add tests for pairing flow from blocked to approved sender.
25. Add tests that ensure unsafe shell operators are blocked.
26. Increase coverage for `ChannelSessionService` sqlite persistence.
27. Add test fixtures for repeated channel event payloads.
28. Add a test for maintenance mode enable/disable transitions.
29. Add tests for recipe rendering with missing template fields.
30. Add a smoke test that creates run → status → approve flow.

## Refactor & Cleanup

31. Split `routes_runs.py` into smaller route modules by feature area.
32. Extract shared channel response helpers into a utility module.
33. Introduce typed constants for command names and event names.
34. Refactor long conditional blocks in channel ingestion into handlers.
35. Remove dead code and unused imports across backend services.
36. Standardize exception handling to reduce repeated try/except logic.
37. Add docstrings to all public service methods missing documentation.
38. Normalize naming for run/action fields for consistency.
39. Simplify nested conditionals in approval command handling.
40. Add lint rules and fix current lint warnings in backend.

## DevOps / Docs / Tooling

41. Add a Dockerfile for backend and document local container run steps.
42. Add `docker-compose.yml` for backend + frontend local startup.
43. Add a Makefile with `test`, `lint`, and `run` shortcuts.
44. Update README with channel setup examples for Slack and Telegram.
45. Add a troubleshooting guide for webhook signature failures.
46. Document all admin headers and role requirements in one table.
47. Add a CI workflow to run pytest and frontend build on PR.
48. Add pre-commit hooks for formatting and linting.
49. Add a sample `.env.example` with clear descriptions.
50. Write an operator playbook for approvals, retries, and maintenance mode.

---

## Prompt Template (recommended)

For more reliable action triggers, use:

**Goal:** <what to build/fix>  
**Scope:** <files or module>  
**Constraints:** <tech stack, no breaking changes, etc.>  
**Acceptance Criteria:** <specific testable outcomes>

Example:

> Goal: Add pagination to runs list endpoint.  
> Scope: `backend/app/api/routes_runs.py` and related schemas/tests.  
> Constraints: Keep backward compatibility and default behavior unchanged.  
> Acceptance Criteria: `limit` + `cursor` supported, tests added, docs updated.