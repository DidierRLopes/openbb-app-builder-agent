# openbb-app-builder-agent

A dedicated OpenBB Copilot agent for building OpenBB Workspace apps using a local Claude Code instance and repo-local `.claude` skills (especially an app-builder skill).

## Goal

This repository will host a minimal but reliable agent that:

1. Receives requirements/specs from OpenBB Copilot (the UI)
2. Reads selected widget context and tool-result data from the OpenBB request payload
3. Persists that context for reproducible local runs
4. Invokes Claude Code CLI (or similar) in a target workspace repo
5. Guides Claude to build an OpenBB Workspace backend app inspired by `getting-started/reference-backend`
6. Runs validation scripts and reports progress/results back via streaming responses

## Status

Planning scaffold only. See `ROADMAP.md` and `docs/PHASE_TEST_MATRIX.md` for the implementation plan and validation criteria.

## Key External References

- `../backend-examples-for-openbb-workspace` (target app patterns, validators, local `.claude` skills)
- `../agents-for-openbb` (OpenBB agent examples, Claude CLI streaming agent example)

## Planned Architecture (High Level)

- `FastAPI` service exposing OpenBB agent endpoints (`/agents.json`, `/health`, `/v1/query`)
- OpenBB request normalizer (messages, widgets, tool outputs)
- Session store (`.agent_sessions/<session_id>/...`) for prompt context + generated artifacts
- Claude Code subprocess runner (`claude --output-format stream-json`)
- SSE event parser -> OpenBB-compatible streaming events
- Build workflow orchestrator (spec -> plan -> build -> validate)

## Repository Layout

- `ROADMAP.md`: Full implementation roadmap (milestones, tasks, risks, acceptance criteria)
- `docs/PHASE_TEST_MATRIX.md`: Phase-by-phase test checklist (implementation + builder workflow phases)
- `docs/ARCHITECTURE.md`: Initial architecture and data flow contracts
- `src/openbb_app_builder_agent/`: Code (stub for now)
- `tests/`: Smoke tests for initial scaffold

## Next Steps

1. Implement Phase 0 and Phase 1 from `ROADMAP.md`
2. Add OpenBB `QueryRequest` parsing fixtures from `../agents-for-openbb/testing/test_payloads`
3. Wire Claude subprocess runner with target working directory set to the app-builder workspace repo
