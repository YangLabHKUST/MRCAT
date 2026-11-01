from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


DISABLE_PROXY_ENV = "MRCAT_BENCHMARK_DISABLE_PROXY"
PROXY_ENV_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
TRUTHY_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class DotenvLoadResult:
    found: bool
    loaded: bool
    path: Path


def load_repo_dotenv(*, repo_root: Path) -> DotenvLoadResult:
    dotenv_path = (Path(os.getenv("MRCAT_CONFIG_DIR") or repo_root) / ".env").resolve()
    if not dotenv_path.exists():
        return DotenvLoadResult(found=False, loaded=False, path=dotenv_path)

    # Parse explicitly first so malformed values fail early with a clear startup error.
    dotenv_values(dotenv_path)
    loaded = bool(load_dotenv(dotenv_path=dotenv_path, override=False))
    return DotenvLoadResult(found=True, loaded=loaded, path=dotenv_path)


def benchmark_disable_proxy_enabled() -> bool:
    value = str(os.environ.get(DISABLE_PROXY_ENV) or "").strip().lower()
    return value in TRUTHY_VALUES


def disable_proxy_from_env_if_requested() -> tuple[str, ...]:
    if not benchmark_disable_proxy_enabled():
        return ()
    removed: list[str] = []
    for name in PROXY_ENV_NAMES:
        if name in os.environ:
            removed.append(name)
            os.environ.pop(name, None)
    return tuple(removed)
