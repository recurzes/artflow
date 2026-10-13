"""
The layering rules from the architecture guide, checked against the imports.

    routes  ->  service  ->  repository  ->  database

- routes and services do not build queries
- routes do not reach past the service into a repository
- a feature uses another feature through its service, never its repository
- the bot talks to the API over HTTP and imports none of its code
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "api"
FEATURES = sorted(p.name for p in API.iterdir() if (p / "__init__.py").exists())


def _imports(path: Path) -> set[str]:
    """Every module a file imports, as dotted names (`from a.b import c` -> a.b and a.b.c)."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _files(name: str) -> list[Path]:
    return sorted(API.glob(f"*/{name}"))


def test_features_were_found():
    assert {"users", "artists", "commissions", "disputes", "reviews", "servers", "admin"} <= set(
        FEATURES
    )


@pytest.mark.parametrize("path", _files("routes.py") + _files("service.py"), ids=str)
def test_routes_and_services_do_not_build_queries(path: Path):
    sqlalchemy = {m for m in _imports(path) if m.split(".")[0] == "sqlalchemy"}
    allowed = {"sqlalchemy.ext.asyncio", "sqlalchemy.ext.asyncio.AsyncSession"}
    assert sqlalchemy <= allowed, f"{path.relative_to(ROOT)} imports {sorted(sqlalchemy - allowed)}"


@pytest.mark.parametrize("path", _files("routes.py"), ids=str)
def test_routes_do_not_import_repositories(path: Path):
    offenders = {m for m in _imports(path) if m.endswith(".repository")}
    assert not offenders, f"{path.relative_to(ROOT)} imports {sorted(offenders)}"


@pytest.mark.parametrize("path", sorted(API.glob("*/*.py")), ids=str)
def test_a_feature_never_imports_another_features_repository(path: Path):
    feature = path.parent.name
    offenders = {
        m for m in _imports(path)
        if m.startswith("api.") and m.endswith(".repository") and m.split(".")[1] != feature
    }
    assert not offenders, f"{path.relative_to(ROOT)} imports {sorted(offenders)}"


@pytest.mark.parametrize("path", _files("repository.py"), ids=str)
def test_repositories_do_not_call_services(path: Path):
    offenders = {m for m in _imports(path) if m.startswith("api.") and m.endswith(".service")}
    assert not offenders, f"{path.relative_to(ROOT)} imports {sorted(offenders)}"


@pytest.mark.parametrize("path", sorted((ROOT / "bot").rglob("*.py")), ids=str)
def test_the_bot_imports_nothing_from_the_api(path: Path):
    offenders = {m for m in _imports(path) if m == "api" or m.startswith("api.")}
    assert not offenders, f"{path.relative_to(ROOT)} imports {sorted(offenders)}"


# What the bot may use from the shared package: its own settings and the names
# of the channels and roles it manages. No database, cache, storage or queue.
BOT_MAY_IMPORT_FROM_SHARED = ("shared.config", "shared.discord_layout")


@pytest.mark.parametrize("path", sorted((ROOT / "bot").rglob("*.py")), ids=str)
def test_the_bot_reaches_infrastructure_only_through_the_api(path: Path):
    imports = _imports(path)
    shared = {
        m for m in imports
        if m.split(".")[0] == "shared" and not m.startswith(BOT_MAY_IMPORT_FROM_SHARED)
    }
    infrastructure = {
        m for m in imports
        if m.split(".")[0] in {"workers", "celery", "redis", "sqlalchemy", "supabase", "asyncpg"}
    }
    assert not shared | infrastructure, (
        f"{path.relative_to(ROOT)} imports {sorted(shared | infrastructure)}"
    )
