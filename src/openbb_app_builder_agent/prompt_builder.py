"""Prompt builder for Claude Code app-builder invocations.

Constructs prompts that leverage:
- User requirements from OpenBB Copilot
- Widget/tool context when available
- Local .claude skills in the target repo
- Reference backend patterns
"""

import json
from typing import Optional

from .config import settings
from .request_parser import RequestContext

# System instructions for app building
APP_BUILDER_SYSTEM_PROMPT = """## OpenBB App Builder Agent

You are an expert at building OpenBB Workspace backend applications. Your task is to create
production-ready FastAPI backends that integrate with OpenBB Workspace.

### Key Guidelines

1. **Follow the reference-backend patterns** in `getting-started/reference-backend/` for:
   - Project structure
   - FastAPI app setup with CORS
   - Widget endpoint patterns
   - apps.json and widgets.json schemas

2. **Use the local .claude skill** if available at `.claude/skills/openbb-app-builder` for
   detailed guidance on OpenBB app structure.

3. **Schema Requirements** (CRITICAL):
   - `apps.json` must be an **array** of app objects (not a single object)
   - `widgets.json` must be an **object/dict** keyed by widget ID
   - Always validate against `scripts/validate_app.py` if available

4. **Output Location**:
   - Create apps under `apps/<app-name>_YYYYMMDD_HHMM/` directory
   - Use current date/time for the timestamp (e.g., `apps/stock-tracker_20250223_1430/`)
   - Include: main.py, widgets.json, apps.json, requirements.txt, CONVERSATION.md

5. **Conversation Log** (REQUIRED):
   - Always create a `CONVERSATION.md` file in the app directory
   - This file should document:
     - **Created:** Timestamp when the app was built
     - **User Request:** The original request that led to this app
     - **Widget Context:** Any widgets selected (if applicable)
     - **Data Context:** Summary of any data provided (if applicable)
     - **Implementation Notes:** Key decisions made during development
   - This serves as documentation for how/why the app was created

6. **Standard Files**:
   - `main.py`: FastAPI app with widget endpoints
   - `widgets.json`: Widget definitions with inputs/outputs
   - `apps.json`: App metadata array
   - `requirements.txt`: Python dependencies
   - `CONVERSATION.md`: Build log documenting the conversation that created this app

### Response Format

When building an app:
1. First briefly acknowledge the requirements
2. Create the timestamped app directory (e.g., `apps/my-app_20250223_1430/`)
3. Create all app files (main.py, widgets.json, apps.json, requirements.txt)
4. Create CONVERSATION.md documenting this build session
5. Run validation if available (`python scripts/validate_app.py apps/<app-name>_YYYYMMDD_HHMM`)
6. **If validation fails, FIX THE ERRORS immediately** - don't just report them
7. **IMPORTANT: At the end, provide clear instructions:**
   - Show the exact path where the app was created
   - Provide the command to run the app (e.g., `cd apps/my-app && pip install -r requirements.txt && uvicorn main:app --host 0.0.0.0 --port 8000`)
   - Show the localhost URL where the app will be accessible (e.g., `http://localhost:8000`)
   - Mention that the user can add this URL as a data connector in OpenBB Workspace

### Error Handling

- If you encounter ANY errors (validation, syntax, import, etc.), **fix them immediately**
- Do not stop and report errors - fix them and continue
- After fixing, re-run validation to confirm the fix worked
- Only report to the user once everything is working

**Always end your response with a clear "How to run" section showing the working app.**

"""


def build_prompt(
    context: RequestContext,
    include_system: bool = True,
    custom_instructions: Optional[str] = None,
) -> str:
    """Build a complete prompt from request context.

    Args:
        context: Normalized request context from OpenBB.
        include_system: Whether to include system instructions (first turn).
        custom_instructions: Optional additional instructions.

    Returns:
        Complete prompt string for Claude Code.
    """
    parts: list[str] = []

    # Add system prompt for first turn
    if include_system:
        parts.append(APP_BUILDER_SYSTEM_PROMPT)

    # Add target repo context if configured
    if settings.resolved_target_repo:
        parts.append(f"**Working Directory:** `{settings.resolved_target_repo}`\n")

    # Add custom instructions if provided
    if custom_instructions:
        parts.append(f"### Additional Instructions\n\n{custom_instructions}\n")

    # Add widget context if available
    if context.primary_widgets:
        parts.append("### Widget Context (from OpenBB Dashboard)\n")
        parts.append("The user has selected the following widgets for context:\n")

        for widget in context.primary_widgets:
            parts.append(f"\n**{widget.name}** (`{widget.widget_id}`)")
            if widget.description:
                parts.append(f"\n{widget.description}")

            if widget.params:
                parts.append("\nParameters:")
                for param in widget.params:
                    name = param.get("name", "unknown")
                    value = param.get("current_value", "N/A")
                    parts.append(f"\n- {name}: `{value}`")

        parts.append("\n")

    # Add tool results if available
    if context.tool_results:
        parts.append("### Data Context (from Widget Data)\n")
        parts.append("The following data was retrieved from the selected widgets:\n")

        for result in context.tool_results:
            parts.append(f"\n**Function:** `{result.function}`")

            if result.data:
                # Truncate large data
                data_str = json.dumps(result.data, indent=2)
                if len(data_str) > 2000:
                    data_str = data_str[:2000] + "\n... (truncated)"
                parts.append(f"\n```json\n{data_str}\n```")

        parts.append("\n")

    # Add the user's request
    parts.append("### User Request\n")
    parts.append(context.user_message)

    return "\n".join(parts)


def build_continuation_prompt(context: RequestContext) -> str:
    """Build a continuation prompt for ongoing conversations.

    Args:
        context: Normalized request context.

    Returns:
        Continuation prompt string.
    """
    # For continuations, just send the new user message with any new context
    return build_prompt(context, include_system=False)
