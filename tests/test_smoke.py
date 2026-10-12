"""
Smoke tests: everything imports, every cog loads, the schema matches the models.

These are cheap and catch the class of bug where a file was never executed
(bad import path, command registered twice, router never mounted).
"""
import importlib
import os
import pkgutil
import subprocess
import sys

import pytest

from api.main import app
from bot.main import COGS, ArtflowBot
from tests.conftest import ROOT

PACKAGES = ("api", "bot", "shared", "workers")


def _module_names() -> list[str]:
    names: list[str] = []
    for package_name in PACKAGES:
        package = importlib.import_module(package_name)
        names.append(package_name)
        names.extend(
            info.name
            for info in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}.")
        )
    return names


@pytest.mark.parametrize("module_name", _module_names())
def test_module_imports(module_name: str) -> None:
    importlib.import_module(module_name)


async def test_every_cog_loads() -> None:
    bot = ArtflowBot()
    await bot.load_cogs()
    assert set(bot.extensions) == set(COGS)
    # Building the payload validates every command, option and group definition.
    for command in bot.tree.get_commands():
        command.to_dict(bot.tree)


def test_every_router_is_mounted() -> None:
    prefixes = {path.split("/")[1] for path in app.openapi()["paths"]}
    assert {"users", "artists", "commissions", "disputes", "servers", "admin"} <= prefixes


def test_migrations_match_models(_schema) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
