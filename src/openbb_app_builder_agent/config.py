"""Configuration for OpenBB App Builder Agent."""

import os
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Agent configuration settings."""

    host: str = "0.0.0.0"
    port: int = 7778

    target_repo_path: Optional[str] = None

    session_dir: str = ".agent_sessions"
    session_ttl_hours: int = 24

    opencode_binary: Optional[str] = None
    opencode_timeout: float = 600.0

    log_level: str = "INFO"

    model_config = {
        "env_prefix": "OPENBB_APP_BUILDER_",
        "env_file": ".env",
        "extra": "ignore",
    }

    @property
    def resolved_target_repo(self) -> Optional[Path]:
        """Get resolved target repo path."""
        if self.target_repo_path:
            path = Path(self.target_repo_path).expanduser().resolve()
            if path.exists():
                return path
        return None

    @property
    def resolved_session_dir(self) -> Path:
        """Get resolved session directory path."""
        if self.resolved_target_repo:
            return self.resolved_target_repo / self.session_dir
        return Path(self.session_dir).resolve()


settings = Settings()


def find_opencode_binary() -> Optional[str]:
    """Find the OpenCode CLI binary.

    Returns:
        Path to opencode binary if found, None otherwise.
    """
    import shutil

    if settings.opencode_binary:
        if os.path.isfile(settings.opencode_binary) and os.access(
            settings.opencode_binary, os.X_OK
        ):
            return settings.opencode_binary

    opencode_path = shutil.which("opencode")
    if opencode_path:
        return opencode_path

    common_paths = [
        os.path.expanduser("~/.local/bin/opencode"),
        os.path.expanduser("~/go/bin/opencode"),
        "/usr/local/bin/opencode",
        "/opt/homebrew/bin/opencode",
    ]

    for path in common_paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    return None


def check_opencode_installed() -> tuple[bool, str]:
    """Check if OpenCode CLI is installed and accessible.

    Returns:
        Tuple of (is_installed, message).
    """
    binary = find_opencode_binary()
    if binary:
        return True, f"OpenCode CLI found at: {binary}"
    return False, (
        "OpenCode CLI not found. Please install it from: https://opencode.ai"
    )


def check_target_repo() -> tuple[bool, str]:
    """Check if target repo is configured and exists.

    Returns:
        Tuple of (exists, message).
    """
    if not settings.target_repo_path:
        return (
            False,
            "Target repo not configured (set OPENBB_APP_BUILDER_TARGET_REPO_PATH)",
        )

    path = settings.resolved_target_repo
    if path and path.exists():
        return True, f"Target repo found at: {path}"

    return False, f"Target repo not found at: {settings.target_repo_path}"
