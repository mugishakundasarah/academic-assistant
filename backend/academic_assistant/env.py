"""Load ``backend/.env`` for the server, the MCP servers and the CLI preview."""

from pathlib import Path

BACKEND_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env_file(path: Path = BACKEND_ENV_FILE) -> bool:
    """Load ``backend/.env`` if python-dotenv is installed. Real environment variables win."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    return load_dotenv(path, override=False)
