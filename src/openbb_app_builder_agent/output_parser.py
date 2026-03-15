"""Parser for OpenCode CLI JSON stream output.

OpenCode CLI with --format json outputs one JSON object per line.
This module parses these events and converts them to OpenBB Copilot SSE events.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Generator

from openbb_ai import message_chunk, reasoning_step

logger = logging.getLogger(__name__)


def format_tool_message(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Generate a human-readable message describing a tool execution.

    Args:
        tool_name: The name of the tool being executed.
        tool_input: The input parameters for the tool.

    Returns:
        A descriptive message about what the tool is doing.
    """
    name_lower = tool_name.lower()

    if name_lower == "read" or name_lower == "view":
        file_path = tool_input.get("file_path", "")
        if file_path:
            short_path = file_path.split("/")[-1] if "/" in file_path else file_path
            return f"Reading file: {short_path}"
        return "Reading file"

    if name_lower == "write":
        file_path = tool_input.get("file_path", "")
        if file_path:
            short_path = file_path.split("/")[-1] if "/" in file_path else file_path
            return f"Creating file: {short_path}"
        return "Creating file"

    if name_lower == "edit":
        file_path = tool_input.get("file_path", "")
        if file_path:
            short_path = file_path.split("/")[-1] if "/" in file_path else file_path
            return f"Editing file: {short_path}"
        return "Editing file"

    if name_lower == "bash":
        command = tool_input.get("command", "")
        if command:
            short_cmd = command[:50] + "..." if len(command) > 50 else command
            return f"Running: {short_cmd}"
        return "Running shell command"

    if name_lower == "glob":
        pattern = tool_input.get("pattern", "")
        if pattern:
            return f"Searching for files: {pattern}"
        return "Searching for files"

    if name_lower == "grep":
        pattern = tool_input.get("pattern", "")
        if pattern:
            short_pattern = pattern[:30] + "..." if len(pattern) > 30 else pattern
            return f"Searching for: '{short_pattern}'"
        return "Searching file contents"

    if name_lower == "ls":
        path = tool_input.get("path", "")
        if path:
            return f"Listing directory: {path}"
        return "Listing directory"

    if name_lower == "task" or name_lower == "agent":
        description = tool_input.get("description", "") or tool_input.get("prompt", "")
        if description:
            return f"Spawning agent: {description}"
        return "Spawning sub-agent"

    return f"Executing: {tool_name}"


@dataclass
class ParsedEvent:
    """A parsed event ready to be yielded as SSE."""

    event_type: str
    data: dict[str, Any]


def parse_opencode_event(event: dict[str, Any]) -> Generator[ParsedEvent, None, None]:
    """Parse a single OpenCode JSON event into OpenBB SSE events.

    Args:
        event: A parsed JSON object from OpenCode's stream output.

    Yields:
        ParsedEvent objects to be converted to SSE.
    """
    event_type = event.get("type", "")

    if event_type == "session":
        yield ParsedEvent(
            event_type="reasoning_step",
            data=reasoning_step(
                event_type="INFO",
                message="OpenCode session initialized",
                details={"session_id": event.get("session_id", "")},
            ).model_dump(),
        )

    elif event_type == "assistant":
        message = event.get("message", {})
        content = message.get("content", [])

        if isinstance(content, str):
            if content:
                yield ParsedEvent(
                    event_type="message_chunk",
                    data=message_chunk(content).model_dump(),
                )
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type", "")

                    if block_type == "text":
                        text = block.get("text", "")
                        if text:
                            yield ParsedEvent(
                                event_type="message_chunk",
                                data=message_chunk(text).model_dump(),
                            )

                    elif block_type == "tool_use":
                        tool_name = block.get("name", "unknown")
                        tool_input = block.get("input", {})

                        msg = format_tool_message(tool_name, tool_input)

                        details = {"tool": tool_name}
                        if tool_input:
                            input_str = json.dumps(tool_input)
                            if len(input_str) > 300:
                                input_str = input_str[:300] + "..."
                            details["input"] = input_str

                        yield ParsedEvent(
                            event_type="reasoning_step",
                            data=reasoning_step(
                                event_type="INFO",
                                message=msg,
                                details=details,
                            ).model_dump(),
                        )

    elif event_type == "tool_use":
        tool_name = event.get("name", "unknown")
        tool_input = event.get("input", {})

        msg = format_tool_message(tool_name, tool_input)

        details = {"tool": tool_name}
        if tool_input:
            input_str = json.dumps(tool_input)
            if len(input_str) > 300:
                input_str = input_str[:300] + "..."
            details["input"] = input_str

        yield ParsedEvent(
            event_type="reasoning_step",
            data=reasoning_step(
                event_type="INFO",
                message=msg,
                details=details,
            ).model_dump(),
        )

    elif event_type == "tool_result":
        tool_content = event.get("content", "")
        is_error = event.get("is_error", False)

        if isinstance(tool_content, str) and len(tool_content) > 500:
            display_content = tool_content[:500] + "..."
        else:
            display_content = str(tool_content)[:500]

        yield ParsedEvent(
            event_type="reasoning_step",
            data=reasoning_step(
                event_type="ERROR" if is_error else "INFO",
                message="Tool failed" if is_error else "Tool completed",
                details={"output": display_content},
            ).model_dump(),
        )

    elif event_type == "content":
        text = event.get("text", "")
        if text:
            yield ParsedEvent(
                event_type="message_chunk",
                data=message_chunk(text).model_dump(),
            )

    elif event_type == "result":
        result_text = event.get("result", "") or event.get("content", "")
        is_error = event.get("is_error", False)

        logger.info(
            f"Received result event: is_error={is_error}, "
            f"result_length={len(result_text) if result_text else 0}"
        )

        if is_error:
            yield ParsedEvent(
                event_type="reasoning_step",
                data=reasoning_step(
                    event_type="ERROR",
                    message="Execution failed",
                    details={
                        "error": result_text[:500] if result_text else "Unknown error"
                    },
                ).model_dump(),
            )
            if result_text:
                yield ParsedEvent(
                    event_type="message_chunk",
                    data=message_chunk(f"\n\n**Error:**\n{result_text}").model_dump(),
                )
        else:
            yield ParsedEvent(
                event_type="reasoning_step",
                data=reasoning_step(
                    event_type="INFO",
                    message="OpenCode completed successfully",
                    details={"result_length": len(result_text) if result_text else 0},
                ).model_dump(),
            )
            if result_text:
                logger.info(f"Emitting final result text ({len(result_text)} chars)")
                yield ParsedEvent(
                    event_type="message_chunk",
                    data=message_chunk(result_text).model_dump(),
                )
            else:
                logger.warning("No result text received from OpenCode")
                yield ParsedEvent(
                    event_type="message_chunk",
                    data=message_chunk(
                        "\n\n**Task completed.** Check the workspace to see the results."
                    ).model_dump(),
                )

    elif event_type == "error":
        error_msg = event.get("error", "") or event.get("message", "Unknown error")
        yield ParsedEvent(
            event_type="reasoning_step",
            data=reasoning_step(
                event_type="ERROR",
                message="Error from OpenCode",
                details={"error": error_msg[:500]},
            ).model_dump(),
        )
        yield ParsedEvent(
            event_type="message_chunk",
            data=message_chunk(f"\n\n**Error:** {error_msg}").model_dump(),
        )

    elif event_type == "message":
        content = event.get("content", "")
        role = event.get("role", "")

        if role == "assistant" and content:
            yield ParsedEvent(
                event_type="message_chunk",
                data=message_chunk(content).model_dump(),
            )
