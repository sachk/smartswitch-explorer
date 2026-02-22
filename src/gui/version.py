from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib


PACKAGE_NAME = "smartswitch-explorer"


def _version_from_pyproject() -> str:
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return "0.0.0+unknown"
    project = data.get("project") if isinstance(data, dict) else None
    if not isinstance(project, dict):
        return "0.0.0+unknown"
    value = project.get("version")
    return str(value) if value else "0.0.0+unknown"


def get_app_version() -> str:
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return _version_from_pyproject()
