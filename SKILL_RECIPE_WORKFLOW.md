# GenXBot Skill → Recipe → Runtime Workflow

This document explains exactly how GenXBot processes a request, with focus on **skill resolution**, **recipe resolution**, and **LLM runtime execution**.

---

## High-level model

- **Skill** = intent/routing layer (what kind of task this is)
- **Recipe** = executable template layer (what actions/template to run)
- **Runtime (GenXAI)** = execution/planning layer (how to execute with allowed tools)

In current implementation, skill/recipe resolution is done by backend code first, then passed to runtime.

## Workflow diagram

```mermaid
flowchart TD
    A[Incoming RunTaskRequest\nPOST /api/v1/runs] --> B[_prepare_resolved_run_request]

    B --> C[_route_skill_from_goal]
    C --> D{skill_id already set\nor trigger matched?}
    D -- No --> E[Keep original request]
    D -- Yes --> F[Set/keep skill_id]

    E --> G[_resolve_skill_request]
    F --> G

    G --> H[Render skill templates\n(goal/context/action_templates)]
    H --> I[Apply skill tool_allowlist\nif request allowlist is empty]
    I --> J{Skill has recipe_id\nand request.recipe_id empty?}
    J -- Yes --> K[Inject recipe_id from skill]
    J -- No --> L[Keep existing recipe_id]

    K --> M[_resolve_recipe_request]
    L --> M
    M --> N{recipe_id exists?}
    N -- No --> O[Skip recipe resolution]
    N -- Yes --> P[Render recipe templates\n(goal/context/action_templates)]

    O --> Q[Resolved request ready]
    P --> Q

    Q --> R[orchestrator.create_run]
    R --> S[_build_genxai_stack]
    S --> T[Filter runtime tools\nby resolved tool_allowlist]
    T --> U[Run GenXAI pipeline\n(single/multi/hybrid)]
    U --> V[Proposed actions + approvals + execution timeline]
```

This reflects the current backend implementation: **skill and recipe are resolved first, then runtime/LLM executes**.

### Plain-text diagram (fallback)

If Mermaid is not rendering in your editor, use this plain-text version:

```text
Incoming RunTaskRequest (POST /api/v1/runs)
  |
  v
_prepare_resolved_run_request
  |
  +--> _route_skill_from_goal
  |       - uses existing skill_id OR trigger phrase match
  |
  +--> _resolve_skill_request
  |       - render skill goal/context
  |       - apply tool_allowlist
  |       - inject recipe_id (if skill has one)
  |
  +--> _resolve_recipe_request
          - render recipe goal/context/actions
          - produce final resolved request

Resolved request
  |
  v
orchestrator.create_run
  |
  v
_build_genxai_stack
  |
  v
Filter tools by tool_allowlist
  |
  v
GenXAI runtime execution (single/multi/hybrid)
  |
  v
Proposed actions / approvals / execution timeline
```

### Why you may not see Mermaid

- Some Markdown previews don’t render Mermaid by default.
- In VS Code, install/enable a Mermaid-capable Markdown preview extension (or open the built-in preview if Mermaid support is enabled).

---

## Actual execution order (current code)

In `backend/app/api/routes_runs.py`, `create_run()` calls:

```python
_prepare_resolved_run_request(request)
```

That function applies this exact order:

1. `_route_skill_from_goal(request)`
2. `_resolve_skill_request(routed)`
3. `_resolve_recipe_request(skilled)`
4. `orchestrator.create_run(resolved)`

So yes: **skill first, then recipe, then runtime**.

---

## Step-by-step explanation

### 1) Skill routing (`_route_skill_from_goal`)

- If `skill_id` is already provided, keep it.
- Otherwise, match request goal text against `skill.trigger_phrases`.
- If a phrase matches, set that `skill_id`.

This is deterministic matching (not LLM reasoning).

### 2) Skill resolution (`_resolve_skill_request`)

Once a skill is selected:

- Render `goal_template` / `context_template` using `skill_inputs`.
- Apply `tool_allowlist` from skill (unless explicitly provided in request).
- If skill has inline `action_templates`, prepare `recipe_actions`.
- If skill has `recipe_id` and request didn’t set one, inject that `recipe_id`.

This is where the request is shaped into an execution-ready intent.

### 3) Recipe resolution (`_resolve_recipe_request`)

If request contains `recipe_id`:

- Load recipe definition.
- Render recipe `goal_template`, `context_template`, and `action_templates` using `recipe_inputs`.
- Merge results into the final run request.

Recipe is the workflow template layer.

### 4) Runtime execution (`orchestrator.create_run`)

Only after skill+recipe are resolved:

- Run context is created.
- Runtime stack is built.
- Tool set is filtered by `tool_allowlist`.
- GenXAI pipeline executes (`single` / `multi` / `hybrid` mode).

---

## Important clarification about `tool_allowlist`

`tool_allowlist` is **not a sequence**.

It defines the allowed tool boundary, e.g.:

```json
"tool_allowlist": ["api_caller", "http_client"]
```

Meaning:

- runtime may use one, both, or neither
- order is dynamic
- it is permission/capability filtering, not step ordering

If you need strict order, model that in recipe action templates/workflow steps.

---

## Example request flows

### A) Explicit skill flow

```json
{
  "goal": "placeholder",
  "repo_path": ".",
  "skill_id": "logs-investigation-assistant",
  "skill_inputs": {
    "system_area": "backend-api",
    "priority": "high",
    "constraints": "no external services"
  }
}
```

Flow:

`skill_id provided` → skill resolved → skill injects `recipe_id=logs-investigation` → recipe resolved → runtime executes.

### B) Natural language auto-routing flow

```json
{
  "goal": "Please investigate backend incident logs",
  "repo_path": "."
}
```

Flow:

goal text matches skill trigger phrase → skill selected → recipe mapped by skill → recipe resolved → runtime executes.

---

## Why this design is useful

- Keeps routing deterministic and predictable
- Keeps execution templates reusable (recipes)
- Keeps runtime constrained and safer (`tool_allowlist`)
- Lets you evolve each layer independently (skills, recipes, runtime modes)
