"""OpenBB App Builder Agent.

A FastAPI server that bridges OpenBB Copilot with Claude Code CLI,
enabling local app generation using .claude skills and reference backends.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openbb_ai import message_chunk, reasoning_step
from openbb_ai.models import QueryRequest
from sse_starlette.sse import EventSourceResponse

from .claude_runner import ClaudeRunnerConfig, run_claude_code
from .config import check_claude_installed, check_target_repo, settings
from .prompt_builder import build_continuation_prompt, build_prompt
from .request_parser import extract_conversation_id, parse_request
from .session_manager import session_manager

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler - check dependencies on startup."""
    claude_ok, claude_msg = check_claude_installed()
    if not claude_ok:
        logger.warning(f"Claude CLI: {claude_msg}")
    else:
        logger.info(f"Claude CLI: {claude_msg}")

    repo_ok, repo_msg = check_target_repo()
    if not repo_ok:
        logger.warning(f"Target repo: {repo_msg}")
    else:
        logger.info(f"Target repo: {repo_msg}")

    yield


app = FastAPI(
    title="OpenBB App Builder Agent",
    description="Builds OpenBB Workspace backend apps via Claude Code and local .claude skills",
    version="0.1.0",
    lifespan=lifespan,
)

# Enable CORS for OpenBB Pro/Workspace
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> JSONResponse:
    """Health check with dependency status."""
    claude_ok, claude_msg = check_claude_installed()
    repo_ok, repo_msg = check_target_repo()

    # Determine overall status
    if claude_ok and repo_ok:
        status = "healthy"
    elif claude_ok:
        status = "degraded"  # Can run but no target repo
    else:
        status = "unhealthy"

    return JSONResponse(
        content={
            "status": status,
            "service": "openbb-app-builder-agent",
            "dependencies": {
                "claude_cli": {"available": claude_ok, "message": claude_msg},
                "target_repo": {"available": repo_ok, "message": repo_msg},
            },
        }
    )


@app.get("/agents.json")
def agents_json() -> JSONResponse:
    """Return agent configuration for OpenBB Copilot discovery."""
    return JSONResponse(
        content={
            "openbb_app_builder_agent": {
                "name": "OpenBB App Builder Agent",
                "description": (
                    "Build custom OpenBB Workspace backend apps using Claude Code CLI "
                    "and local .claude skills. Supports widget context for data-driven "
                    "app generation."
                ),
                "image": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8a/Anthropic_logo.svg/1280px-Anthropic_logo.svg.png",
                "endpoints": {"query": "/v1/query"},
                "features": {
                    "streaming": True,
                    "widget-dashboard-select": True,
                    "widget-dashboard-search": True,
                },
            }
        }
    )


@app.post("/v1/query")
async def query(request: QueryRequest) -> EventSourceResponse:
    """Process a query from OpenBB Copilot.

    Receives the user's query, extracts widget/tool context,
    and streams responses back as SSE events.
    """
    # Check Claude CLI availability
    claude_ok, claude_msg = check_claude_installed()
    if not claude_ok:

        async def error_response() -> AsyncGenerator[dict, None]:
            yield reasoning_step(
                event_type="ERROR",
                message="Claude Code CLI not installed",
                details={"error": claude_msg},
            ).model_dump()
            yield message_chunk(
                "Claude Code CLI is not installed. Please install it from: "
                "https://docs.anthropic.com/en/docs/claude-code"
            ).model_dump()

        return EventSourceResponse(
            content=error_response(),
            media_type="text/event-stream",
        )

    # Parse request into normalized context
    context = parse_request(request)

    # Check if we should execute (last message must be human)
    if not context.should_execute:

        async def skip_response() -> AsyncGenerator[dict, None]:
            yield message_chunk("Waiting for user input...").model_dump()

        return EventSourceResponse(
            content=skip_response(),
            media_type="text/event-stream",
        )

    # No user message
    if not context.user_message:

        async def empty_response() -> AsyncGenerator[dict, None]:
            yield message_chunk("No message provided.").model_dump()

        return EventSourceResponse(
            content=empty_response(),
            media_type="text/event-stream",
        )

    # Get or create session
    conversation_id = extract_conversation_id(request)
    session = session_manager.get_or_create_session(conversation_id)

    # Persist context for debugging/reproducibility
    session_manager.persist_context(session, context.to_dict())

    logger.info(
        f"Processing query: session={session.session_id}, "
        f"continued={session.is_continued}, "
        f"widgets={len(context.primary_widgets)}, "
        f"tool_results={len(context.tool_results)}"
    )
    logger.info(f"User message: {context.user_message[:100]}...")
    if settings.resolved_target_repo:
        logger.info(f"Target repo: {settings.resolved_target_repo}")
    else:
        logger.warning("Target repo NOT configured - Claude will run in current directory")

    # Stream response
    async def execution_loop() -> AsyncGenerator[dict, None]:
        # Emit session info
        yield reasoning_step(
            event_type="INFO",
            message="Session started",
            details={
                "session_id": session.session_id,
                "is_continued": session.is_continued,
            },
        ).model_dump()

        # Emit context info if present
        if context.has_widget_context():
            widget_names = [w.name for w in context.primary_widgets]
            yield reasoning_step(
                event_type="INFO",
                message=f"Widget context: {', '.join(widget_names)}",
                details={"widget_count": len(context.primary_widgets)},
            ).model_dump()

        if context.has_tool_results():
            yield reasoning_step(
                event_type="INFO",
                message=f"Tool results available: {len(context.tool_results)}",
                details={
                    "functions": [t.function for t in context.tool_results],
                },
            ).model_dump()

        # Check target repo
        repo_ok, repo_msg = check_target_repo()
        if not repo_ok:
            yield reasoning_step(
                event_type="WARNING",
                message="Target repo not configured",
                details={"info": repo_msg},
            ).model_dump()
            yield message_chunk(
                "**Note:** Target workspace repo is not configured. "
                "Claude will run in current directory. "
                "Set `OPENBB_APP_BUILDER_TARGET_REPO_PATH` for full app building.\n\n"
            ).model_dump()

        # Build prompt based on session state
        if session.is_continued:
            prompt = build_continuation_prompt(context)
        else:
            prompt = build_prompt(context, include_system=True)

        # Configure Claude runner
        runner_config = ClaudeRunnerConfig(
            working_directory=str(settings.resolved_target_repo)
            if settings.resolved_target_repo
            else None,
            timeout=settings.claude_timeout,
            skip_permissions=settings.claude_skip_permissions,
        )

        # Execute Claude Code and stream results
        async for event in run_claude_code(prompt, session, runner_config):
            yield event.data

    return EventSourceResponse(
        content=execution_loop(),
        media_type="text/event-stream",
    )


@app.post("/v1/terminate")
async def terminate() -> JSONResponse:
    """Terminate any running Claude Code process."""
    was_terminated = await session_manager.terminate_current_process()
    return JSONResponse(
        content={
            "terminated": was_terminated,
            "message": "Process terminated" if was_terminated else "No process running",
        }
    )


@app.post("/v1/clear-sessions")
async def clear_sessions() -> JSONResponse:
    """Clear all session tracking data."""
    count = session_manager.clear_all_sessions()
    return JSONResponse(
        content={
            "cleared": count,
            "message": f"Cleared {count} sessions",
        }
    )


@app.get("/v1/sessions")
def list_sessions() -> JSONResponse:
    """List all active sessions (debugging endpoint)."""
    sessions = session_manager.list_sessions()
    return JSONResponse(
        content={
            "count": len(sessions),
            "sessions": sessions,
        }
    )


if __name__ == "__main__":
    import uvicorn

    # NOTE: reload=False to prevent crashes when Claude creates files
    uvicorn.run(
        "openbb_app_builder_agent.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
