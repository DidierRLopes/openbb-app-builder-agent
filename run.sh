#!/bin/bash
# Run the OpenBB App Builder Agent
# Use this script to run without --reload (recommended for app building)

set -e

echo "Starting OpenBB App Builder Agent..."
echo "Server will run on http://localhost:8000"
echo ""
echo "NOTE: Not using --reload to prevent restarts when apps are created."
echo "      Restart manually with Ctrl+C if you change agent code."
echo ""

poetry run python -m openbb_app_builder_agent.main
