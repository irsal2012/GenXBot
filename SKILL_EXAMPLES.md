## GenXBot Skill Examples (10)

These examples follow the current `SkillCreateRequest` shape used by:

- `POST /api/v1/runs/skills`

---

### 1) Market Research

```json
{
  "id": "market-research",
  "name": "Market Research",
  "description": "Find reliable market/stock information sources for user questions",
  "goal_template": "Find reliable websites for market and stock information, then summarize useful links",
  "context_template": "focus=web_research",
  "recipe_id": null,
  "trigger_phrases": ["stock price", "stock prices", "market research"],
  "tool_allowlist": ["api_caller", "web_scraper", "http_client"],
  "tags": ["research", "web"],
  "action_templates": []
}
```

### 2) Docs Assistant

```json
{
  "id": "docs-assistant",
  "name": "Docs Assistant",
  "description": "Create or improve documentation pages",
  "goal_template": "Create or improve documentation for {topic}",
  "context_template": "audience={audience}",
  "recipe_id": "discord",
  "trigger_phrases": ["update docs", "write docs", "documentation"],
  "tool_allowlist": ["api_caller"],
  "tags": ["docs"],
  "action_templates": []
}
```

### 3) Test Fixer

```json
{
  "id": "test-fixer",
  "name": "Test Fixer",
  "description": "Diagnose and fix failing tests",
  "goal_template": "Investigate failing tests in {target_area}, apply fixes, and summarize root cause",
  "context_template": "priority={priority}",
  "recipe_id": "test-hardening",
  "trigger_phrases": ["failing tests", "fix tests", "pytest failed"],
  "tool_allowlist": ["api_caller"],
  "tags": ["testing", "quality"],
  "action_templates": []
}
```

### 4) API Endpoint Builder

```json
{
  "id": "api-endpoint-builder",
  "name": "API Endpoint Builder",
  "description": "Implement a backend API endpoint and related tests",
  "goal_template": "Implement endpoint {endpoint_name} with validation and tests",
  "context_template": "service={service_name}",
  "recipe_id": null,
  "trigger_phrases": ["add endpoint", "create api", "new route"],
  "tool_allowlist": ["api_caller", "http_client"],
  "tags": ["backend", "api"],
  "action_templates": []
}
```

### 5) Frontend Bug Triage

```json
{
  "id": "frontend-bug-triage",
  "name": "Frontend Bug Triage",
  "description": "Analyze and fix UI bugs quickly",
  "goal_template": "Diagnose and fix frontend bug: {bug_summary}",
  "context_template": "component={component_name}",
  "recipe_id": null,
  "trigger_phrases": ["ui bug", "frontend bug", "react issue"],
  "tool_allowlist": ["api_caller"],
  "tags": ["frontend", "bugfix"],
  "action_templates": []
}
```

### 6) Security Review

```json
{
  "id": "security-review",
  "name": "Security Review",
  "description": "Review code and config for common security risks",
  "goal_template": "Perform security review for {scope} and list prioritized fixes",
  "context_template": "compliance={standard}",
  "recipe_id": null,
  "trigger_phrases": ["security audit", "security review", "vulnerability"],
  "tool_allowlist": ["api_caller", "http_client"],
  "tags": ["security"],
  "action_templates": []
}
```

### 7) Performance Optimizer

```json
{
  "id": "performance-optimizer",
  "name": "Performance Optimizer",
  "description": "Find and optimize performance bottlenecks",
  "goal_template": "Analyze performance bottlenecks in {scope} and implement high-impact optimizations",
  "context_template": "budget_ms={budget_ms}",
  "recipe_id": null,
  "trigger_phrases": ["slow", "performance", "optimize"],
  "tool_allowlist": ["api_caller", "http_client"],
  "tags": ["performance"],
  "action_templates": []
}
```

### 8) Data Extraction Assistant

```json
{
  "id": "data-extraction",
  "name": "Data Extraction",
  "description": "Extract structured data from pages or APIs",
  "goal_template": "Extract structured data for {dataset_name} and provide normalized output",
  "context_template": "format={output_format}",
  "recipe_id": null,
  "trigger_phrases": ["extract data", "scrape data", "collect records"],
  "tool_allowlist": ["web_scraper", "api_caller", "http_client"],
  "tags": ["data", "automation"],
  "action_templates": []
}
```

### 9) Release Notes Generator

```json
{
  "id": "release-notes",
  "name": "Release Notes Generator",
  "description": "Generate concise release notes from changes",
  "goal_template": "Generate release notes for version {version}",
  "context_template": "tone={tone}",
  "recipe_id": null,
  "trigger_phrases": ["release notes", "changelog", "summarize release"],
  "tool_allowlist": ["api_caller"],
  "tags": ["release", "docs"],
  "action_templates": []
}
```

### 10) Incident Triage

```json
{
  "id": "incident-triage",
  "name": "Incident Triage",
  "description": "Triage production incidents and propose remediation",
  "goal_template": "Triage incident {incident_id}, identify likely root cause, and draft remediation plan",
  "context_template": "severity={severity}",
  "recipe_id": null,
  "trigger_phrases": ["incident", "outage", "production issue"],
  "tool_allowlist": ["api_caller", "http_client"],
  "tags": ["ops", "incident"],
  "action_templates": []
}
```

---

## Batch Create Skills via API (curl examples)

> Base URL assumes local backend: `http://localhost:8000/api/v1/runs/skills`

### 1) Market Research

```bash
curl -X POST "http://localhost:8000/api/v1/runs/skills" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "market-research",
    "name": "Market Research",
    "description": "Find reliable market/stock information sources for user questions",
    "goal_template": "Find reliable websites for market and stock information, then summarize useful links",
    "context_template": "focus=web_research",
    "recipe_id": null,
    "trigger_phrases": ["stock price", "stock prices", "market research"],
    "tool_allowlist": ["api_caller", "web_scraper", "http_client"],
    "tags": ["research", "web"],
    "action_templates": []
  }'
```

### 2) Docs Assistant

```bash
curl -X POST "http://localhost:8000/api/v1/runs/skills" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "docs-assistant",
    "name": "Docs Assistant",
    "description": "Create or improve documentation pages",
    "goal_template": "Create or improve documentation for {topic}",
    "context_template": "audience={audience}",
    "recipe_id": "discord",
    "trigger_phrases": ["update docs", "write docs", "documentation"],
    "tool_allowlist": ["api_caller"],
    "tags": ["docs"],
    "action_templates": []
  }'
```

### 3) Test Fixer

```bash
curl -X POST "http://localhost:8000/api/v1/runs/skills" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "test-fixer",
    "name": "Test Fixer",
    "description": "Diagnose and fix failing tests",
    "goal_template": "Investigate failing tests in {target_area}, apply fixes, and summarize root cause",
    "context_template": "priority={priority}",
    "recipe_id": "test-hardening",
    "trigger_phrases": ["failing tests", "fix tests", "pytest failed"],
    "tool_allowlist": ["api_caller"],
    "tags": ["testing", "quality"],
    "action_templates": []
  }'
```

### 4) API Endpoint Builder

```bash
curl -X POST "http://localhost:8000/api/v1/runs/skills" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "api-endpoint-builder",
    "name": "API Endpoint Builder",
    "description": "Implement a backend API endpoint and related tests",
    "goal_template": "Implement endpoint {endpoint_name} with validation and tests",
    "context_template": "service={service_name}",
    "recipe_id": null,
    "trigger_phrases": ["add endpoint", "create api", "new route"],
    "tool_allowlist": ["api_caller", "http_client"],
    "tags": ["backend", "api"],
    "action_templates": []
  }'
```

### 5) Frontend Bug Triage

```bash
curl -X POST "http://localhost:8000/api/v1/runs/skills" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "frontend-bug-triage",
    "name": "Frontend Bug Triage",
    "description": "Analyze and fix UI bugs quickly",
    "goal_template": "Diagnose and fix frontend bug: {bug_summary}",
    "context_template": "component={component_name}",
    "recipe_id": null,
    "trigger_phrases": ["ui bug", "frontend bug", "react issue"],
    "tool_allowlist": ["api_caller"],
    "tags": ["frontend", "bugfix"],
    "action_templates": []
  }'
```

### 6) Security Review

```bash
curl -X POST "http://localhost:8000/api/v1/runs/skills" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "security-review",
    "name": "Security Review",
    "description": "Review code and config for common security risks",
    "goal_template": "Perform security review for {scope} and list prioritized fixes",
    "context_template": "compliance={standard}",
    "recipe_id": null,
    "trigger_phrases": ["security audit", "security review", "vulnerability"],
    "tool_allowlist": ["api_caller", "http_client"],
    "tags": ["security"],
    "action_templates": []
  }'
```

### 7) Performance Optimizer

```bash
curl -X POST "http://localhost:8000/api/v1/runs/skills" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "performance-optimizer",
    "name": "Performance Optimizer",
    "description": "Find and optimize performance bottlenecks",
    "goal_template": "Analyze performance bottlenecks in {scope} and implement high-impact optimizations",
    "context_template": "budget_ms={budget_ms}",
    "recipe_id": null,
    "trigger_phrases": ["slow", "performance", "optimize"],
    "tool_allowlist": ["api_caller", "http_client"],
    "tags": ["performance"],
    "action_templates": []
  }'
```

### 8) Data Extraction

```bash
curl -X POST "http://localhost:8000/api/v1/runs/skills" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "data-extraction",
    "name": "Data Extraction",
    "description": "Extract structured data from pages or APIs",
    "goal_template": "Extract structured data for {dataset_name} and provide normalized output",
    "context_template": "format={output_format}",
    "recipe_id": null,
    "trigger_phrases": ["extract data", "scrape data", "collect records"],
    "tool_allowlist": ["web_scraper", "api_caller", "http_client"],
    "tags": ["data", "automation"],
    "action_templates": []
  }'
```

### 9) Release Notes

```bash
curl -X POST "http://localhost:8000/api/v1/runs/skills" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "release-notes",
    "name": "Release Notes Generator",
    "description": "Generate concise release notes from changes",
    "goal_template": "Generate release notes for version {version}",
    "context_template": "tone={tone}",
    "recipe_id": null,
    "trigger_phrases": ["release notes", "changelog", "summarize release"],
    "tool_allowlist": ["api_caller"],
    "tags": ["release", "docs"],
    "action_templates": []
  }'
```

### 10) Incident Triage

```bash
curl -X POST "http://localhost:8000/api/v1/runs/skills" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "incident-triage",
    "name": "Incident Triage",
    "description": "Triage production incidents and propose remediation",
    "goal_template": "Triage incident {incident_id}, identify likely root cause, and draft remediation plan",
    "context_template": "severity={severity}",
    "recipe_id": null,
    "trigger_phrases": ["incident", "outage", "production issue"],
    "tool_allowlist": ["api_caller", "http_client"],
    "tags": ["ops", "incident"],
    "action_templates": []
  }'
```

---

## Built-in Skill Run Examples (newly added)

Use these with `POST /api/v1/runs` to execute a specific skill directly.

> Base URL: `http://localhost:8000/api/v1/runs`

### 1) Spotify Assistant

```json
{
  "goal": "placeholder",
  "repo_path": ".",
  "skill_id": "spotify-assistant",
  "skill_inputs": {"priority": "high"}
}
```

### 2) Voice Call Assistant

```json
{
  "goal": "placeholder",
  "repo_path": ".",
  "skill_id": "voice-call-assistant",
  "skill_inputs": {"priority": "high"}
}
```

### 3) GitHub Issues Assistant

```json
{
  "goal": "placeholder",
  "repo_path": ".",
  "skill_id": "github-issues-assistant",
  "skill_inputs": {"priority": "medium"}
}
```

### 4) Tmux Assistant

```json
{
  "goal": "placeholder",
  "repo_path": ".",
  "skill_id": "tmux-assistant",
  "skill_inputs": {"priority": "medium"}
}
```

### 5) Session Logs Assistant

```json
{
  "goal": "placeholder",
  "repo_path": ".",
  "skill_id": "session-logs-assistant",
  "skill_inputs": {"priority": "high"}
}
```

### 6) Model Usage Assistant

```json
{
  "goal": "placeholder",
  "repo_path": ".",
  "skill_id": "model-usage-assistant",
  "skill_inputs": {"priority": "medium"}
}
```
