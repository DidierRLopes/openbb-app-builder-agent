"""Parser for Claude Code CLI JSON stream output.

Claude Code CLI with --output-format stream-json outputs one JSON object per line.
This module parses these events and converts them to OpenBB Copilot SSE events.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Generator

from openbb_ai import message_chunk, reasoning_step

logger = logging.getLogger(__name__)


@dataclass
class ParsedEvent:
    """A parsed event ready to be yielded as SSE."""

    event_type: str
    data: dict[str, Any]


def parse_claude_event(event: dict[str, Any]) -> Generator[ParsedEvent, None, None]:
    """Parse a single Claude Code JSON event into OpenBB SSE events.

    Args:
        event: A parsed JSON object from Claude Code's stream output.

    Yields:
        ParsedEvent objects to be converted to SSE.
    """
    event_type = event.get("type", "")

    if event_type == "system":
        subtype = event.get("subtype", "")
        if subtype == "init":
            yield ParsedEvent(
                event_type="reasoning_step",
                data=reasoning_step(
                    event_type="INFO",
                    message="Claude Code session initialized",
                    details={"session_id": event.get("session_id", "")},
                ).model_dump(),
            )

    elif event_type == "stream_event":
        # Real-time streaming events from Claude
        inner_event = event.get("event", {})
        inner_type = inner_event.get("type", "")

        if inner_type == "content_block_delta":
            delta = inner_event.get("delta", {})
            delta_type = delta.get("type", "")

            if delta_type == "text_delta":
                text = delta.get("text", "")
                if text:
                    yield ParsedEvent(
                        event_type="message_chunk",
                        data=message_chunk(text).model_dump(),
                    )

    elif event_type == "assistant":
        # Complete assistant message (may contain tool_use and text)
        message = event.get("message", {})
        content = message.get("content", [])

        for block in content:
            block_type = block.get("type", "")

            if block_type == "tool_use":
                tool_name = block.get("name", "unknown")
                tool_input = block.get("input", {})

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
                        message=f"Executing: {tool_name}",
                        details=details,
                    ).model_dump(),
                )

            elif block_type == "text":
                # Text content from assistant
                text = block.get("text", "")
                if text:
                    yield ParsedEvent(
                        event_type="message_chunk",
                        data=message_chunk(text).model_dump(),
                    )

    elif event_type == "user":
        # Tool result being fed back to Claude
        content = event.get("content", [])

        for block in content:
            block_type = block.get("type", "")

            if block_type == "tool_result":
                tool_content = block.get("content", "")
                is_error = block.get("is_error", False)

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

    elif event_type == "result":
        # Final result from Claude Code
        result_text = event.get("result", "")
        is_error = event.get("is_error", False)

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
        elif result_text:
            # Emit final result text as message chunk
            yield ParsedEvent(
                event_type="message_chunk",
                data=message_chunk(result_text).model_dump(),
            )
