"""Server-side authorization (T-062; §12.1, §12.2, §15.1, §7.4).

The interesting failure here is not "a viewer approved a message". It is **a route that nobody
gave a permission to**, because that route serves everyone and looks exactly like one somebody
deliberately opened. So the load-bearing test walks the real application and fails on anything
undeclared, and a second test proves that checker can detect a violation — a coverage check that
cannot fail is a coverage check that reports success forever.

The role assertions are parametrized over **every** role rather than one allowed and one denied.
A matrix tested at two points is a matrix with holes in the middle, and the hole that matters is
the one where a role nobody thought about turns out to grant an approval.
"""

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute

from app.identity.dependencies import enforced_permission, requires, requires_mutation
from app.identity.models import HUMAN_ONLY_ROLES, RoleKey
from app.identity.rbac import (
    APPROVAL_PERMISSIONS,
    FRAMEWORK_PATHS,
    PERMISSION_TIERS,
    PUBLIC,
    ROLE_GRANTS,
    ROUTE_PERMISSIONS,
    Forbidden,
    NotAuthenticated,
    Permission,
    Public,
    Tier,
    UndeclaredRoute,
    authorize,
    permission_for,
    roles_granting,
    undeclared_routes,
)
from app.identity.sessions import Principal
from app.main import create_app


class FakePrincipal:
    """Just the roles. `authorize` reads nothing else, and building a real `Principal` would
    need a database for a test about a set-intersection."""

    def __init__(self, *roles: RoleKey) -> None:
        self.roles = frozenset(role.value for role in roles)


def principal(*roles: RoleKey) -> Principal:
    return FakePrincipal(*roles)  # type: ignore[return-value]


def application_routes() -> list[tuple[str, str]]:
    """Every `(method, path)` the real application serves.

    Recursive, because an included router arrives in `app.routes` as a wrapper whose own `path`
    is absent and whose real routes hang off it. A flat walk silently found nothing for the first
    router this repository mounted — and "found nothing" reads exactly like "nothing undeclared",
    which is how a coverage check comes to certify an endpoint it never saw.

    Derived from the route table rather than from `app.openapi()`: a route with
    `include_in_schema=False` is missing from the document and still serves.
    """
    found: list[tuple[str, str]] = []

    def walk(routes: object) -> None:
        for route in routes or ():  # type: ignore[union-attr]
            # An included router arrives as a `_IncludedRouter` wrapper: no `path`, no `methods`,
            # and its real routes reachable only through `original_router`. Both spellings are
            # handled because the attribute is version-specific and a walk that silently found
            # nothing would read exactly like "nothing undeclared".
            nested = getattr(route, "routes", None) or getattr(
                getattr(route, "original_router", None), "routes", None
            )
            if nested:
                walk(nested)
                continue
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if path is None or methods is None:
                continue
            found.extend((method, path) for method in methods if method not in {"HEAD", "OPTIONS"})

    walk(create_app(configure_logs=False).routes)
    return found


# --- the load-bearing one: no route escapes a decision --------------------------------------------


def test_every_route_declares_a_permission() -> None:
    """§15.1: "server-side authorization for every action".

    The hard part of *every* is not the check — it is that a new endpoint added next month has
    one at all. This fails until someone has decided, which is different from failing until
    someone remembers.
    """
    missing = undeclared_routes(application_routes())

    assert missing == [], (
        f"routes with no permission decision: {missing}. Add each to `ROUTE_PERMISSIONS` as a "
        f"`Permission` or as `PUBLIC` — there is no default."
    )


def test_the_coverage_check_can_detect_a_violation() -> None:
    """A guard on the guard. `undeclared_routes` returning `[]` is only reassuring if it can
    return something else."""
    assert undeclared_routes([("POST", "/synthetic/undeclared")]) == [
        ("POST", "/synthetic/undeclared")
    ]


def test_the_coverage_check_ignores_framework_paths() -> None:
    """`/openapi.json` and the docs pages are not application actions. Excluded by name rather
    than by a prefix match, so the exclusion is visible instead of implied."""
    assert undeclared_routes([("GET", path) for path in FRAMEWORK_PATHS]) == []


def test_an_undeclared_route_raises_rather_than_defaulting() -> None:
    """`permission_for` fails closed. A default — public *or* administrator-only — would be a
    decision nobody made, and the public one would be silent."""
    with pytest.raises(UndeclaredRoute, match="no default"):
        permission_for("POST", "/synthetic/undeclared")


def test_the_health_probes_are_deliberately_public() -> None:
    """A probe that needed a session would report the application unhealthy exactly when the
    identity provider was down — the moment an operator most needs the truth."""
    for path in ("/healthz", "/readyz"):
        assert permission_for("GET", path) is PUBLIC


def test_public_is_a_type_not_a_missing_value() -> None:
    """ "Nobody decided" and "somebody decided this is open" must not be the same value."""
    assert isinstance(PUBLIC, Public)
    assert PUBLIC is not None


# --- the maps are total ---------------------------------------------------------------------------


def test_every_permission_has_a_tier() -> None:
    """A permission added without a §7.4 tier would otherwise default to whatever a reader
    assumed — and the safe assumption and the dangerous one look identical in a diff."""
    assert set(PERMISSION_TIERS) == set(Permission)


def test_every_permission_has_a_grant() -> None:
    assert set(ROLE_GRANTS) == set(Permission)


def test_no_permission_is_granted_to_nobody() -> None:
    """A permission no role holds is an action nobody can ever take, which is a bug rather than
    a safety measure — it would be discovered by someone needing it, not by a test."""
    for permission, roles in ROLE_GRANTS.items():
        assert roles, f"{permission.value} is granted to no role"


def test_every_role_grants_something() -> None:
    """§12.1 defines six roles. A role that granted nothing would be a role nobody could
    usefully be given, and its presence in the seed would be misleading."""
    granting = {role for roles in ROLE_GRANTS.values() for role in roles}

    assert granting == set(RoleKey)


# --- approvals stay with humans, and with reviewers -----


@pytest.mark.parametrize("permission", sorted(APPROVAL_PERMISSIONS, key=lambda p: p.value))
def test_an_approval_is_granted_only_by_human_only_roles(permission: Permission) -> None:
    """§3.5 and ADR-008. `T-012` already stops a service being *granted* such a role and
    `T-061a` stops a service holding a session at all; this is the third check, on the grant
    table itself, because one mechanism is one edit away from gone.
    """
    for role in roles_granting(permission):
        assert role in HUMAN_ONLY_ROLES, (
            f"{permission.value} is granted by {role.value}, which a service identity may hold"
        )


@pytest.mark.parametrize("permission", sorted(APPROVAL_PERMISSIONS, key=lambda p: p.value))
def test_an_approval_sits_at_the_external_communication_tier(permission: Permission) -> None:
    """§7.4 tier 4. Reading the tier tells a reviewer what the permission unlocks before they
    read which roles hold it."""
    assert PERMISSION_TIERS[permission] is Tier.EXTERNAL_COMMUNICATION


@pytest.mark.parametrize("role", sorted(RoleKey, key=lambda r: r.value))
@pytest.mark.parametrize("permission", sorted(APPROVAL_PERMISSIONS, key=lambda p: p.value))
def test_only_the_operator_reviewer_may_approve(role: RoleKey, permission: Permission) -> None:
    """Every role against every approval, rather than one allowed and one denied.

    Includes the system administrator, and that denial is the point: administering identity is
    not the same authority as approving an outbound message, which is why §7.4 puts them on
    different tiers.
    """
    caller = principal(role)

    if role is RoleKey.OPERATOR_REVIEWER:
        authorize(caller, permission)
    else:
        with pytest.raises(Forbidden):
            authorize(caller, permission)


def test_administrative_permissions_are_administrator_only() -> None:
    """§7.4 tier 5: "never delegated to the agent"."""
    administrative = [
        permission for permission, tier in PERMISSION_TIERS.items() if tier is Tier.ADMINISTRATIVE
    ]

    assert administrative
    for permission in administrative:
        assert roles_granting(permission) == frozenset({RoleKey.SYSTEM_ADMINISTRATOR})


# --- authorize itself -----------------------------------------------------------------------------


def test_no_session_is_refused_for_anything_but_public() -> None:
    for permission in Permission:
        with pytest.raises(NotAuthenticated):
            authorize(None, permission)


def test_no_session_is_fine_for_a_public_route() -> None:
    authorize(None, PUBLIC)


def test_a_principal_with_no_roles_is_refused_everything() -> None:
    """Authentication is not authorization. Someone signed in with no roles can do nothing,
    which is `T-061a`'s deliberate outcome for a user nobody has granted anything."""
    caller = principal()

    for permission in Permission:
        with pytest.raises(Forbidden):
            authorize(caller, permission)


def test_holding_several_roles_grants_the_union() -> None:
    """§12.1: "one person may hold multiple roles ... but permissions remain distinct"."""
    caller = principal(RoleKey.VIEWER, RoleKey.CAMPAIGN_SALES_OWNER)

    authorize(caller, Permission.MANAGE_CAMPAIGN)
    authorize(caller, Permission.VIEW_STATUS)
    with pytest.raises(Forbidden):
        authorize(caller, Permission.APPROVE_MESSAGE)


def test_a_refusal_names_what_would_have_been_needed() -> None:
    """An operator reading a 403 in a log should learn which role is missing."""
    with pytest.raises(Forbidden, match="operator_reviewer"):
        authorize(principal(RoleKey.VIEWER), Permission.APPROVE_MESSAGE)


def test_authorize_returns_none_rather_than_a_boolean() -> None:
    """Structural. A caller who forgets to check a returned `False` has authorized everything;
    an exception cannot be ignored by accident."""
    assert authorize(principal(RoleKey.VIEWER), Permission.VIEW_STATUS) is None


@pytest.mark.parametrize("role", sorted(RoleKey, key=lambda r: r.value))
def test_every_role_may_read_status(role: RoleKey) -> None:
    """Tier 0. §12.1's viewer "reads status and reports", and no role is below a viewer."""
    authorize(principal(role), Permission.VIEW_STATUS)


def test_the_declared_routes_are_all_routes_the_app_serves() -> None:
    """The other direction: a declaration for a route that no longer exists is stale, and stale
    entries are how a reviewer comes to distrust the table."""
    served = {(method, path) for method, path in application_routes()}

    stale = sorted(key for key in ROUTE_PERMISSIONS if key not in served)
    assert stale == [], f"declarations for routes that no longer exist: {stale}"


# --- T-162: what a route declares is what it enforces ---------------------------------------------
#
# `ROUTE_PERMISSIONS` is the table a reviewer reads to answer "who may do this", and until now it
# was only *a* statement about the route rather than *the* one the code runs on. A negative
# control on `T-069a` proved it: changing the table to `VIEW_STATUS` — the permission every role
# holds — left every role still refused, because the handler names its own permission in its
# signature. Two independent statements, and nothing compared them.
#
# The checker below is a pure function over `(routes, declared)` so the tests can feed it a
# synthetic application whose two answers differ. A detector only ever run against code that
# already agrees is a detector nobody has seen work.


def route_objects() -> list[APIRoute]:
    """Every `APIRoute` the real application serves, wrappers unwrapped.

    Same recursion as `application_routes`, which learned the hard way that an included router
    arrives as a wrapper whose real routes hang off it — a flat walk finds two health probes and
    reports everything else as compliant.
    """
    found: list[APIRoute] = []

    def walk(routes: object) -> None:
        for route in routes or ():  # type: ignore[union-attr]
            nested = getattr(route, "routes", None) or getattr(
                getattr(route, "original_router", None), "routes", None
            )
            if nested:
                walk(nested)
                continue
            if isinstance(route, APIRoute):
                found.append(route)

    walk(create_app(configure_logs=False).routes)
    return found


def enforced_permissions(route: APIRoute) -> set[Permission]:
    """Every permission this route's dependency tree actually authorizes against.

    The whole tree, not the handler's own parameters: a permission check added through a router
    or an `APIRouter(dependencies=...)` is as real as one in the signature, and a walk that read
    only the top level would report it as enforcing nothing.
    """
    found: set[Permission] = set()

    def visit(dependant: object) -> None:
        permission = enforced_permission(getattr(dependant, "call", None))
        if permission is not None:
            found.add(permission)
        for sub in getattr(dependant, "dependencies", ()):
            visit(sub)

    visit(route.dependant)
    return found


def declaration_mismatches(
    routes: list[APIRoute], declared: dict[tuple[str, str], object]
) -> list[str]:
    """Routes whose declared permission is not the one they enforce.

    Fails closed in both directions. A route declaring a permission and enforcing **none** is the
    dangerous case — the table says "administrator only" and the code lets anyone through. A
    route declared `PUBLIC` that enforces something is the harmless-looking one, and it still
    makes the table a lie, so it is reported too.
    """
    problems: list[str] = []
    for route in routes:
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            decision = declared.get((method, route.path))
            if decision is None:
                # Undeclared routes are `test_every_route_declares_a_permission`'s to report;
                # flagging them here as well would give one fault two voices.
                continue
            enforced = enforced_permissions(route)
            if isinstance(decision, Public):
                if enforced:
                    problems.append(
                        f"{method} {route.path} is declared PUBLIC but enforces "
                        f"{sorted(p.value for p in enforced)}"
                    )
                continue
            if enforced != {decision}:
                problems.append(
                    f"{method} {route.path} declares {decision.value!r} but enforces "
                    f"{sorted(p.value for p in enforced) or 'nothing'}"
                )
    return problems


def test_the_route_walk_finds_permission_bearing_routes() -> None:
    """A guard on the guard: a walk that found no permissions would make the check vacuous, which
    is exactly how a flat walk over `app.routes` would have failed."""
    routes = route_objects()

    assert len(routes) >= 10
    assert sum(1 for route in routes if enforced_permissions(route)) >= 8


def test_every_route_enforces_the_permission_it_declares() -> None:
    """§15.1's "server-side authorization for every action", read as: the table and the code give
    the same answer."""
    problems = declaration_mismatches(route_objects(), dict(ROUTE_PERMISSIONS))

    assert problems == [], (
        "the permission a route declares must be the one it enforces; `ROUTE_PERMISSIONS` is "
        f"what a reviewer reads to answer who may do this: {problems}"
    )


def _one_route_app(dependency: object | None) -> list[APIRoute]:
    """A one-route application, optionally enforcing something."""
    app = FastAPI()

    if dependency is None:

        @app.post("/synthetic/control")
        def handler() -> dict[str, str]:  # pragma: no cover - never called
            return {}

    else:

        @app.post("/synthetic/control")
        def handler_with_permission(  # pragma: no cover - never called
            principal: Annotated[Principal, Depends(dependency)],
        ) -> dict[str, str]:
            return {}

    return [route for route in app.routes if isinstance(route, APIRoute)]


def test_the_check_detects_a_route_enforcing_a_different_permission() -> None:
    """The exact failure `T-069a`'s control exposed, now caught."""
    routes = _one_route_app(requires(Permission.VIEW_STATUS))

    problems = declaration_mismatches(
        routes, {("POST", "/synthetic/control"): Permission.PAUSE_SYSTEM}
    )

    assert len(problems) == 1
    assert "declares 'pause_system' but enforces ['view_status']" in problems[0]


def test_the_check_detects_a_route_that_enforces_nothing() -> None:
    """The dangerous direction: the table promises an administrator and the code asks nobody."""
    routes = _one_route_app(None)

    problems = declaration_mismatches(
        routes, {("POST", "/synthetic/control"): Permission.PAUSE_SYSTEM}
    )

    assert len(problems) == 1
    assert "enforces nothing" in problems[0]


def test_the_check_detects_a_public_route_that_enforces_something() -> None:
    """Harmless-looking and still a lie: a reviewer reading `PUBLIC` would not expect a `403`."""
    routes = _one_route_app(requires(Permission.VIEW_STATUS))

    problems = declaration_mismatches(routes, {("POST", "/synthetic/control"): PUBLIC})

    assert len(problems) == 1
    assert "declared PUBLIC but enforces" in problems[0]


def test_the_check_accepts_agreement() -> None:
    """The other direction. A checker that flagged the correct shape would be noise, and noise is
    what gets a structural test deleted."""
    routes = _one_route_app(requires(Permission.PAUSE_SYSTEM))

    assert (
        declaration_mismatches(routes, {("POST", "/synthetic/control"): Permission.PAUSE_SYSTEM})
        == []
    )


def test_the_check_reads_a_mutation_dependency_too() -> None:
    """`requires_mutation` wraps `requires` and adds CSRF; the enforced permission has to survive
    that wrapping, or every state-changing route would silently read as enforcing nothing."""
    routes = _one_route_app(requires_mutation(Permission.APPROVE_MESSAGE))

    assert (
        declaration_mismatches(routes, {("POST", "/synthetic/control"): Permission.APPROVE_MESSAGE})
        == []
    )
    assert (
        declaration_mismatches(routes, {("POST", "/synthetic/control"): Permission.VIEW_STATUS})
        != []
    )
