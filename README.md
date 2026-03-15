# OpenBB App Builder Agent

A FastAPI agent that bridges OpenBB Copilot with OpenCode CLI, enabling AI-powered generation of OpenBB Workspace backend apps.

## Features

- Receives requirements from OpenBB Copilot UI
- Extracts widget context and tool-result data from requests
- Invokes OpenCode CLI to build complete FastAPI backends
- Streams progress and results back to OpenBB Workspace
- Creates timestamped app directories with conversation logs

## Prerequisites

- Python 3.11+
- [OpenCode CLI](https://opencode.ai) installed and configured
- A target repository for generated apps (e.g., `backend-examples-for-openbb-workspace`)

## Installation

```bash
# Clone the repository
git clone https://github.com/OpenBB-finance/openbb-app-builder-agent.git
cd openbb-app-builder-agent

# Install dependencies
pip install -e .
# or with poetry
poetry install
```

## Configuration

Set the target repository path where apps will be created:

```bash
export OPENBB_APP_BUILDER_TARGET_REPO_PATH=/path/to/backend-examples-for-openbb-workspace
```

Optional environment variables:
- `OPENBB_APP_BUILDER_HOST` - Server host (default: `0.0.0.0`)
- `OPENBB_APP_BUILDER_PORT` - Server port (default: `7778`)
- `OPENBB_APP_BUILDER_LOG_LEVEL` - Log level (default: `INFO`)
- `OPENBB_APP_BUILDER_OPENCODE_BINARY` - Path to OpenCode binary (auto-detected if not set)
- `OPENBB_APP_BUILDER_OPENCODE_TIMEOUT` - Timeout in seconds (default: `600`)

## Running the Agent

```bash
python -m openbb_app_builder_agent.main
```

The agent will start on `http://localhost:7778` (or configured port).

## Connecting to OpenBB Workspace

### Step 1: Connect the Agent (AI Tab)

The App Builder Agent is an **agent** (not a widget backend), so connect it via the AI interface:

1. Go to [OpenBB Workspace](https://pro.openbb.co)
2. Navigate to **AI** in the sidebar
3. Add the agent URL: `http://localhost:7778`
4. The agent will appear as "OpenBB App Builder Agent"

### Step 2: Create Apps via Copilot

1. Open Copilot in OpenBB Workspace
2. Select the App Builder Agent
3. Describe the app you want to build (optionally select widgets for context)
4. The agent will create the app in your target repository

### Step 3: Test Created Apps (Connections Page)

Apps created by the agent are standard widget backends:

1. Run the created app:
   ```bash
   cd /path/to/target-repo/apps/my-app_20250223_1430
   pip install -r requirements.txt
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

2. Connect in OpenBB Workspace:
   - Go to **Connections** page
   - Click **Connect Backend**
   - Enter name and URL (e.g., `http://localhost:8000`)
   - Click **Test**, then **Add**

3. Open the app from the **Apps** page to verify widgets render correctly

## Generated App Structure

Each created app includes:

```
apps/my-app_20250223_1430/
├── main.py           # FastAPI app with widget endpoints
├── widgets.json      # Widget definitions
├── apps.json         # App metadata
├── requirements.txt  # Python dependencies
└── CONVERSATION.md   # Build log documenting the creation
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check with dependency status |
| `GET /agents.json` | Agent configuration for OpenBB discovery |
| `POST /v1/query` | Process queries from OpenBB Copilot |
| `POST /v1/terminate` | Terminate running OpenCode process |
| `POST /v1/clear-sessions` | Clear session tracking data |
| `GET /v1/sessions` | List active sessions (debug) |

## Development

```bash
# Run tests
pytest -v

# Run the agent
python -m openbb_app_builder_agent.main
```

**Warning:** Do NOT use `uvicorn --reload` - it will restart when OpenCode creates `.py` files in `apps/`, interrupting the generation process.

## Architecture

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────┐
│  OpenBB Copilot │────▶│  App Builder Agent   │────▶│  OpenCode   │
│       UI        │◀────│   (FastAPI + SSE)    │◀────│    CLI      │
└─────────────────┘     └──────────────────────┘     └─────────────┘
                                   │
                                   ▼
                        ┌──────────────────────┐
                        │   Target Repository  │
                        │  (Generated Apps)    │
                        └──────────────────────┘
```

## Migrating from Claude Code CLI

This agent now uses OpenCode CLI instead of Claude Code CLI. Key differences:

- **Model Selection**: OpenCode handles model selection via its own configuration (`~/.opencode.json`)
- **Session Management**: OpenCode manages sessions natively
- **No Browser Automation**: Browser automation features have been removed

To configure OpenCode, run:
```bash
opencode auth login
```

Or edit `~/.opencode.json` to configure your preferred LLM provider.

## License

MIT
