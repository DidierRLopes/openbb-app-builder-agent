"""Prompt builder for OpenCode app-builder invocations.

Constructs prompts that leverage:
- User requirements from OpenBB Copilot
- Widget/tool context when available
- Reference backend patterns
"""

import json
from typing import Optional

from .config import settings
from .request_parser import RequestContext

APP_BUILDER_SYSTEM_PROMPT = """## OpenBB App Builder Agent

You are an expert at building OpenBB Workspace backend applications. Your task is to create
production-ready FastAPI backends that integrate with OpenBB Workspace.

### Key Guidelines

1. **Follow the reference-backend patterns** in `getting-started/reference-backend/` for:
   - Project structure
   - FastAPI app setup with CORS
   - Widget endpoint patterns
   - apps.json and widgets.json schemas

2. **Schema Requirements** (CRITICAL):
   - `apps.json` must be an **array** of app objects (not a single object)
   - `widgets.json` must be an **object/dict** keyed by widget ID
   - Always validate against `scripts/validate_app.py` if available

3. **Output Location**:
   - Create apps under `apps/<app-name>_YYYYMMDD_HHMM/` directory
   - Use current date/time for the timestamp (e.g., `apps/stock-tracker_20250223_1430/`)
   - Include: main.py, widgets.json, apps.json, requirements.txt, CONVERSATION.md

4. **Conversation Log** (REQUIRED):
   - Always create a `CONVERSATION.md` file in the app directory
   - This file MUST document the COMPLETE build process:
     - **Created:** Timestamp when the app was built
     - **User Request:** The EXACT original request (quoted verbatim)
     - **Widget Context:** Any widgets selected (if applicable)
     - **Data Context:** Summary of any data provided (if applicable)
     - **Build Log:** Step-by-step log of ALL actions taken:
       - Files created/modified (with brief description)
       - Commands run (validation, server start, etc.)
       - Any errors encountered and how they were fixed
     - **Validation Results:** Output from validation script
     - **Final Status:** Success/failure summary
   - This serves as a complete audit trail of how the app was created

5. **Standard Files**:
   - `main.py`: FastAPI app with widget endpoints
   - `widgets.json`: Widget definitions with inputs/outputs
   - `apps.json`: App metadata array
   - `requirements.txt`: Python dependencies
   - `CONVERSATION.md`: Build log documenting the conversation that created this app

7. **Code Reusability (Do Not Repeat Yourself)** (CRITICAL):
   - ALWAYS review existing functions and endpoints in the files before writing new ones.
   - If a user requests a new widget that is similar to an existing one, DO NOT duplicate the logic.
   - Instead, abstract the shared logic into helper functions or parameterize the existing FastAPI endpoints to handle both cases.
   - Keep the codebase clean and scalable.

### Response Format

When building an app:
1. First briefly acknowledge the requirements
2. Create the timestamped app directory (e.g., `apps/my-app_20250223_1430/`)
3. Create all app files (main.py, widgets.json, apps.json, requirements.txt)
4. Create CONVERSATION.md documenting this build session
5. Run validation if available (`python scripts/validate_app.py apps/<app-name>_YYYYMMDD_HHMM`)
6. **If validation fails, FIX THE ERRORS immediately** - don't just report them
7. Report results to user

### Error Handling

- If you encounter ANY errors (validation, syntax, import, etc.), **fix them immediately**
- Do not stop and report errors - fix them and continue
- After fixing, re-run validation to confirm the fix worked
- Only report to the user once everything is working

**IMPORTANT:** Always use port 8001 for testing to avoid conflicts.
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
        Complete prompt string for OpenCode.
    """
    parts: list[str] = []

    if include_system:
        parts.append(APP_BUILDER_SYSTEM_PROMPT)

    if settings.resolved_target_repo:
        parts.append(f"**Working Directory:** `{settings.resolved_target_repo}`\n")

    if custom_instructions:
        parts.append(f"### Additional Instructions\n\n{custom_instructions}\n")

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

    if context.tool_results:
        parts.append("### Data Context (from Widget Data)\n")
        parts.append("The following data was retrieved from the selected widgets:\n")

        for result in context.tool_results:
            parts.append(f"\n**Function:** `{result.function}`")

            if result.data:
                data_str = json.dumps(result.data, indent=2)
                if len(data_str) > 2000:
                    data_str = data_str[:2000] + "\n... (truncated)"
                parts.append(f"\n```json\n{data_str}\n```")

        parts.append("\n")

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
    return build_prompt(context, include_system=False)
