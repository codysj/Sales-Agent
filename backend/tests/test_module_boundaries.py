"""Module boundaries are enforced, not merely documented (T-005; specification §18.2, §5.1).

Boundaries here are internal contracts, not separate services. The rules below are transcribed
from the "must not own" column of specification §5.1 and from §6.3, so each one is traceable to a
line in the specification rather than to an invented layering scheme.

The checker parses imports with ``ast`` — no import side effects, no extra dependency.
"""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

#: The thirteen backend modules of specification §18.2.
DOMAIN_MODULES = frozenset(
    {
        "identity",
        "products_and_claims",
        "campaigns",
        "prospects",
        "research_and_evidence",
        "qualification",
        "drafts_and_approvals",
        "outreach_and_replies",
        "jobs_and_outbox",
        "crm",
        "messaging",
        "model_gateway",
        "audit_and_operations",
    }
)

#: Foundation packages. Not domain modules; anything may depend on them.
FOUNDATION = frozenset({"core", "db"})

#: Platform module every domain module may depend on: every consequential action needs an audit
#: event (§3.5).
PLATFORM = frozenset({"audit_and_operations"})

#: Domain modules a generic mechanism must not reach.
_BUSINESS = DOMAIN_MODULES - PLATFORM - {"jobs_and_outbox", "model_gateway", "messaging", "crm"}

#: package -> packages it must not import, with the specification clause that says so.
FORBIDDEN: dict[str, tuple[frozenset[str], str]] = {
    "core": (
        frozenset(DOMAIN_MODULES),
        "foundation must stay free of domain knowledge (§18.2)",
    ),
    "db": (
        frozenset(DOMAIN_MODULES),
        "foundation must stay free of domain knowledge (§18.2)",
    ),
    "model_gateway": (
        frozenset(DOMAIN_MODULES - PLATFORM - {"model_gateway"}),
        "the LLM adapter must not own eligibility, approval, suppression, or execution (§5.1)",
    ),
    "jobs_and_outbox": (
        frozenset(DOMAIN_MODULES - PLATFORM - {"jobs_and_outbox"}),
        "generic mechanism: domain modules register handlers and recheck their own rules (§17.1)",
    ),
    "messaging": (
        frozenset(DOMAIN_MODULES - PLATFORM - {"messaging", "identity"}),
        "the gateway is not an approval authority and not a workflow dependency (§12.4, ADR-006)",
    ),
    "crm": (
        frozenset(_BUSINESS - {"prospects"} | {"jobs_and_outbox", "model_gateway"}),
        "the CRM adapter must not own model runs, evidence, approvals, or job state (§5.1)",
    ),
}

#: Nothing may import the application factory; it wires everything else together.
FORBIDDEN_FOR_ALL = frozenset({"main", "worker"})


def _iter_source_files() -> list[Path]:
    return sorted(APP.rglob("*.py"))


def _package_of(path: Path) -> str:
    """First path segment under ``app/``: ``app/crm/adapters/hubspot.py`` -> ``crm``."""
    relative = path.relative_to(APP)
    return relative.parts[0] if len(relative.parts) > 1 else relative.stem


def imported_app_packages(source: str) -> set[str]:
    """Top-level ``app.*`` packages referenced by ``source``.

    Relative imports are resolved to the empty string and ignored: they cannot cross a package
    boundary at depth 1, which is the only level these rules constrain.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "app" and len(parts) > 1:
                    found.add(parts[1])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            parts = node.module.split(".")
            if parts[0] == "app" and len(parts) > 1:
                found.add(parts[1])
    return found


def find_violations(files: dict[Path, str]) -> list[str]:
    """Return one human-readable violation per forbidden edge."""
    violations: list[str] = []
    for path, source in files.items():
        package = _package_of(path)
        imported = imported_app_packages(source)

        for target in sorted(imported & FORBIDDEN_FOR_ALL):
            if package != target:
                violations.append(f"{path.name}: {package} must not import {target}")

        forbidden, reason = FORBIDDEN.get(package, (frozenset(), ""))
        for target in sorted(imported & forbidden):
            violations.append(f"{path.name}: {package} must not import {target} — {reason}")
    return violations


def find_cycles(files: dict[Path, str]) -> list[list[str]]:
    """Detect import cycles between top-level ``app`` packages."""
    graph: dict[str, set[str]] = {}
    for path, source in files.items():
        package = _package_of(path)
        graph.setdefault(package, set()).update(imported_app_packages(source) - {package})

    cycles: list[list[str]] = []
    visiting: list[str] = []

    def walk(node: str) -> None:
        if node in visiting:
            cycles.append([*visiting[visiting.index(node) :], node])
            return
        visiting.append(node)
        for neighbour in sorted(graph.get(node, ())):
            if neighbour in graph:
                walk(neighbour)
        visiting.pop()

    for start in sorted(graph):
        walk(start)
    return cycles


@pytest.fixture(scope="module")
def sources() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in _iter_source_files()}


def test_all_thirteen_modules_exist(sources: dict[Path, str]) -> None:
    missing = sorted(name for name in DOMAIN_MODULES if not (APP / name / "__init__.py").is_file())

    assert not missing, f"missing module packages: {missing}"


def test_every_module_documents_what_it_owns_and_must_not_own() -> None:
    """A boundary nobody can read is a boundary nobody will keep."""
    for name in sorted(DOMAIN_MODULES):
        docstring = ast.get_docstring(ast.parse((APP / name / "__init__.py").read_text("utf-8")))

        assert docstring, f"{name} has no module docstring"
        assert "Owns" in docstring or "owns" in docstring, f"{name} does not say what it owns"
        assert "Must not own" in docstring, f"{name} does not say what it must not own"
        assert "§" in docstring, f"{name} cites no specification section"


def test_no_forbidden_imports(sources: dict[Path, str]) -> None:
    violations = find_violations(sources)

    assert not violations, "module boundary violations:\n  " + "\n  ".join(violations)


def test_no_import_cycles(sources: dict[Path, str]) -> None:
    cycles = find_cycles(sources)

    assert not cycles, f"import cycles between packages: {cycles}"


# --- the checker must be able to fail ------------------------------------------------------
# A boundary test that cannot detect a violation is worse than none: it reports success forever.
# These feed synthetic sources through the same functions the real checks use.


def test_checker_detects_a_forbidden_domain_import() -> None:
    offending = {APP / "model_gateway" / "tasks.py": "from app.drafts_and_approvals import x\n"}

    violations = find_violations(offending)

    assert violations, "checker failed to flag model_gateway -> drafts_and_approvals"
    assert "must not import drafts_and_approvals" in violations[0]
    assert "§5.1" in violations[0]


def test_checker_detects_a_plain_import_statement_too() -> None:
    offending = {APP / "jobs_and_outbox" / "dispatch.py": "import app.qualification.rules\n"}

    assert find_violations(offending), "checker missed `import app.x` form"


def test_checker_detects_an_import_of_the_app_factory() -> None:
    offending = {APP / "campaigns" / "service.py": "from app.main import create_app\n"}

    assert find_violations(offending), "checker missed an import of the application factory"


def test_checker_allows_permitted_imports() -> None:
    """Guard against a checker so strict it would flag legitimate dependencies."""
    permitted = {
        APP / "qualification" / "rules.py": (
            "from app.core.settings import get_settings\n"
            "from app.audit_and_operations import record\n"
            "from app.prospects import Contact\n"
        ),
        APP / "model_gateway" / "gateway.py": "from app.audit_and_operations import record\n",
    }

    assert find_violations(permitted) == []


def test_documentation_matches_the_enforced_rules() -> None:
    """docs/architecture/modules.md must not drift from the checker it documents."""
    doc = (APP.parents[1] / "docs" / "architecture" / "modules.md").read_text(encoding="utf-8")
    block = doc.split("<!-- BEGIN ENFORCED RULES -->")[1].split("<!-- END ENFORCED RULES -->")[0]

    documented = {
        line.split(" -/-> ")[0].strip(): {t.strip() for t in line.split(" -/-> ")[1].split(",")}
        for line in block.splitlines()
        if " -/-> " in line
    }
    expected = {package: set(targets) for package, (targets, _) in FORBIDDEN.items()}
    expected["*"] = set(FORBIDDEN_FOR_ALL)

    assert documented == expected, (
        "docs/architecture/modules.md is out of date with FORBIDDEN; "
        "regenerate the enforced-rules block"
    )


def test_checker_detects_a_cycle() -> None:
    offending = {
        APP / "campaigns" / "a.py": "from app.prospects import x\n",
        APP / "prospects" / "b.py": "from app.campaigns import y\n",
    }

    assert find_cycles(offending), "checker missed a two-module import cycle"
