"""OpenCode HTTP API client for app building.

Uses OpenCode's HTTP server API for reliable communication.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

import httpx
from openbb_ai import message_chunk, reasoning_step

from .config import find_opencode_binary, settings
from .session_manager import Session, session_manager

logger = logging.getLogger(__name__)

OPENCODE_DEFAULT_PORT = 4096


@dataclass
class OpenCodeRunnerConfig:
    """Configuration for OpenCode invocation."""

    working_directory: Optional[str] = None
    timeout: float = 600.0
    port: int = OPENCODE_DEFAULT_PORT


_opencode_server_process: Optional[asyncio.subprocess.Process] = None


async def ensure_opencode_server(config: OpenCodeRunnerConfig) -> tuple[bool, str]:
    """Ensure OpenCode server is running.

    Returns:
        Tuple of (success, base_url_or_error_message)
    """
    global _opencode_server_process

    base_url = f"http://127.0.0.1:{config.port}"

    async def check_server() -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{base_url}/global/health")
                return resp.status_code == 200
        except Exception:
            return False

    if await check_server():
        logger.info(f"OpenCode server already running at {base_url}")
        return True, base_url

    opencode_binary = find_opencode_binary()
    if not opencode_binary:
        return False, "OpenCode CLI not found. Please install from https://opencode.ai"

    cwd = config.working_directory
    if not cwd and settings.resolved_target_repo:
        cwd = str(settings.resolved_target_repo)
    if not cwd:
        cwd = os.getcwd()

    logger.info(f"Starting OpenCode server on port {config.port} in {cwd}")

    cmd = [
        opencode_binary,
        "serve",
        "--port",
        str(config.port),
        "--hostname",
        "127.0.0.1",
    ]

    _opencode_server_process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )

    for i in range(30):
        await asyncio.sleep(0.5)
        if await check_server():
            logger.info(f"OpenCode server started at {base_url}")
            return True, base_url
        if _opencode_server_process.returncode is not None:
            stderr = ""
            if _opencode_server_process.stderr:
                stderr = (await _opencode_server_process.stderr.read()).decode()
            logger.error(f"OpenCode server failed: {stderr}")
            return False, f"OpenCode server failed to start: {stderr[:500]}"

    return False, "OpenCode server startup timed out"


def format_tool_message(tool_name: str, tool_input: dict) -> str:
    """Generate a human-readable message describing a tool execution."""
    name_lower = tool_name.lower()

    if name_lower in ("read", "view"):
        path = tool_input.get("file_path", "")
        return f"Reading file: {path.split('/')[-1] if path else 'unknown'}"

    if name_lower == "write":
        path = tool_input.get("file_path", "")
        return f"Creating file: {path.split('/')[-1] if path else 'unknown'}"

    if name_lower == "edit":
        path = tool_input.get("file_path", "")
        return f"Editing file: {path.split('/')[-1] if path else 'unknown'}"

    if name_lower == "bash":
        cmd = tool_input.get("command", "")
        return f"Running: {cmd[:50]}..." if len(cmd) > 50 else f"Running: {cmd}"

    if name_lower == "glob":
        pattern = tool_input.get("pattern", "")
        return f"Searching for files: {pattern}"

    if name_lower == "grep":
        pattern = tool_input.get("pattern", "")
        return f"Searching for: {pattern[:30]}..."

    return f"Executing: {tool_name}"


async def run_opencode(
    prompt: str,
    session: Session,
    config: Optional[OpenCodeRunnerConfig] = None,
) -> AsyncGenerator[dict, None]:
    """Run OpenCode via HTTP API and stream parsed events.

    Args:
        prompt: The full prompt to send to OpenCode.
        session: Session object for context management.
        config: Optional configuration overrides.

    Yields:
        Dict objects ready for SSE streaming.
    """
    config = config or OpenCodeRunnerConfig()

    server_ok, server_result = await ensure_opencode_server(config)
    if not server_ok:
        yield reasoning_step(
            event_type="ERROR",
            message="OpenCode server unavailable",
            details={"error": server_result},
        ).model_dump()
        return

    base_url = server_result
    opencode_session_id = session.opencode_session_id

    yield reasoning_step(
        event_type="INFO",
        message="Starting OpenCode execution",
        details={
            "session_id": session.session_id,
            "opencode_session_id": opencode_session_id,
            "continued": session.is_continued,
        },
    ).model_dump()

    try:
        await session_manager.acquire_process_lock()

        async with httpx.AsyncClient(timeout=config.timeout) as client:

            async def _create_new_session() -> Optional[str]:
                """Create a fresh OpenCode session, returning its ID or None on failure."""
                create_resp = await client.post(f"{base_url}/session", json={})
                if create_resp.status_code != 200:
                    return None
                return create_resp.json().get("id")

            if opencode_session_id:
                # Validate the cached session is still alive on the server.
                try:
                    check_resp = await client.get(
                        f"{base_url}/session/{opencode_session_id}",
                        timeout=5.0,
                    )
                    if check_resp.status_code != 200:
                        logger.warning(
                            f"Cached OpenCode session {opencode_session_id} "
                            f"no longer exists (HTTP {check_resp.status_code}). "
                            "Creating a new session."
                        )
                        opencode_session_id = None
                except Exception as check_err:
                    logger.warning(
                        f"Could not validate cached session: {check_err}. "
                        "Creating a new session."
                    )
                    opencode_session_id = None

            if not opencode_session_id:
                opencode_session_id = await _create_new_session()
                if not opencode_session_id:
                    yield reasoning_step(
                        event_type="ERROR",
                        message="Failed to create OpenCode session",
                        details={},
                    ).model_dump()
                    return
                session.opencode_session_id = opencode_session_id
                logger.info(f"Created OpenCode session: {opencode_session_id}")

            yield reasoning_step(
                event_type="INFO",
                message="Sending message to OpenCode...",
                details={},
            ).model_dump()

            message_resp = await client.post(
                f"{base_url}/session/{opencode_session_id}/message",
                json={
                    "parts": [{"type": "text", "text": prompt}],
                },
            )

            if message_resp.status_code != 200:
                yield reasoning_step(
                    event_type="ERROR",
                    message="Failed to send message",
                    details={
                        "status": message_resp.status_code,
                        "error": message_resp.text[:500],
                    },
                ).model_dump()
                return

            message_data = message_resp.json()
            parts = message_data.get("parts", [])

            logger.info(f"Received response with {len(parts)} parts")

            for part in parts:
                part_type = part.get("type", "")

                if part_type == "text":
                    text = part.get("text", "")
                    if text:
                        yield message_chunk(text).model_dump()

                elif part_type == "tool_use":
                    tool_name = part.get("name", "unknown")
                    tool_input = part.get("input", {})

                    msg = format_tool_message(tool_name, tool_input)
                    details = {"tool": tool_name}
                    if tool_input:
                        input_str = json.dumps(tool_input)
                        if len(input_str) > 300:
                            input_str = input_str[:300] + "..."
                        details["input"] = input_str

                    yield reasoning_step(
                        event_type="INFO",
                        message=msg,
                        details=details,
                    ).model_dump()

                elif part_type == "tool_result":
                    content = part.get("content", "")
                    is_error = part.get("is_error", False)

                    if isinstance(content, str) and len(content) > 500:
                        display_content = content[:500] + "..."
                    else:
                        display_content = str(content)[:500]

                    yield reasoning_step(
                        event_type="ERROR" if is_error else "INFO",
                        message="Tool failed" if is_error else "Tool completed",
                        details={"output": display_content},
                    ).model_dump()

            yield reasoning_step(
                event_type="INFO",
                message="OpenCode completed successfully",
                details={},
            ).model_dump()

    except httpx.TimeoutException:
        yield reasoning_step(
            event_type="ERROR",
            message="Request timed out",
            details={"timeout_seconds": config.timeout},
        ).model_dump()
    except httpx.ConnectError as e:
        yield reasoning_step(
            event_type="ERROR",
            message="Failed to connect to OpenCode server",
            details={"error": str(e)},
        ).model_dump()
    except Exception as e:
        logger.exception("Unexpected error in OpenCode runner")
        yield reasoning_step(
            event_type="ERROR",
            message="Unexpected error",
            details={"error": str(e)[:500]},
        ).model_dump()
    finally:
        session_manager.set_current_process(None)
        session_manager.release_process_lock()
