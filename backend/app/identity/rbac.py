"""Server-side authorization for every action (T-062; §12.1, §12.2, §15.1, §7.4).

§15.1 requires "server-side authorization for every action", and the hard part of *every* is not
checking a role — it is making sure no route quietly has no check at all. A decorator you must
remember to apply is a decorator someone will not, and the endpoint that ships without it looks
exactly like one that was deliberately public.

So authorization here has two halves that fail differently:

* **Declaration is mandatory and structural.** Every route names either a `Permission` or
  `PUBLIC`, in `ROUTE_PERMISSIONS`. `undeclared_routes` walks the running application and returns
  anything missing, and `tests/test_authz.py` fails on a non-empty result. A new endpoint is
  therefore refused by the suite until someone has *decided* whether it needs a session — not
  until they remember to add a decorator.
* **The role check is a function, not a decorator.** `authorize(principal, permission)` raises
  unless one of the caller's roles grants it, and returns `None` on success rather than a boolean
  — a caller who forgets to check a returned `False` has authorized everything, and an exception
  cannot be ignored by accident. `T-063` wires it into the first authenticated endpoint as a
  FastAPI dependency; there is no such endpoint yet, and writing the dependency before there is
  anything to depend on it would be scaffolding nothing exercises.

**Permissions map to §7.4's autonomy tiers**, and the tier is what makes the grant reviewable:
`APPROVE_MESSAGE` is tier 4 ("execute exact approved external communication — application only,
after immutable approval"), and reading its row tells you that before you read which roles hold
it. Tier 5 — "destructive actions, permissions, credentials, or policy changes; never delegated
to the agent" — is administrator-only by construction here.

**A service identity can never hold an approval permission**, and that is enforced three times
over rather than asserted once: `T-012`'s composite foreign key stops a service being *granted* a
decision-carrying role, `T-061a`'s session table has a foreign key to `app_user` so a service
cannot hold a session at all, and `APPROVAL_PERMISSIONS` here is checked against the human-only
role set. §3.5's invariant is that no external execution authority is held only by the agent
runtime; one mechanism guarding it would be one edit away from gone.

**What this module does not do.** It does not decide *who* holds which role — that is `Q-005`
(approver assignment) and `Q-026` (the roster), both open, and inventing an answer would be
fabricating an authority. It maps roles to permissions, which is a structural decision the
specification already made in §12.1.
"""

from collections.abc import Iterable
from enum import Enum
from typing import Final

from app.identity.models import RoleKey
from app.identity.sessions import Principal


class Tier(Enum):
    """§7.4's autonomy tiers. The number is the specification's, not an ordering we invented."""

    READ = 0
    INTERNAL_ANALYSIS = 1
    DRAFT = 2
    LOW_RISK_INTERNAL_CHANGE = 3
    EXTERNAL_COMMUNICATION = 4
    ADMINISTRATIVE = 5


class Permission(Enum):
    """One thing a caller may be allowed to do.

    Named for the action rather than the endpoint, so two routes that do the same thing cannot
    drift into two different answers about who may do it.
    """

    #: Tier 0 — read approved internal state.
    VIEW_STATUS = "view_status"
    VIEW_REVIEW_QUEUE = "view_review_queue"
    #: Tier 2 — create drafts. The application drafts; the model never applies anything.
    REQUEST_DRAFT = "request_draft"
    #: Tier 3 — low-risk reversible internal changes.
    CORRECT_CANDIDATE = "correct_candidate"
    MANAGE_CAMPAIGN = "manage_campaign"
    MANAGE_PRODUCT_CLAIMS = "manage_product_claims"
    #: Tier 4 — the approvals that let an external effect happen at all.
    APPROVE_CANDIDATE = "approve_candidate"
    APPROVE_MESSAGE = "approve_message"
    #: Tier 5 — administrative. Never delegated (§7.4).
    #: A *read*, and still tier 5: the operations overview reports dead-job reasons, backlog
    #: depths, and which safety switches are thrown. That is the map an attacker would want and
    #: the detail an operator needs, so it is declared administrative rather than folded into
    #: `VIEW_STATUS`, which every role holds (`T-069a`).
    VIEW_OPERATIONS = "view_operations"
    MANAGE_IDENTITY = "manage_identity"
    MANAGE_INTEGRATIONS = "manage_integrations"
    PAUSE_SYSTEM = "pause_system"


#: The §7.4 tier each permission sits at. Every permission appears exactly once; a test asserts
#: the map is total, so a permission added without a tier fails rather than defaulting to the
#: least dangerous one.
PERMISSION_TIERS: Final[dict[Permission, Tier]] = {
    Permission.VIEW_STATUS: Tier.READ,
    Permission.VIEW_REVIEW_QUEUE: Tier.READ,
    Permission.REQUEST_DRAFT: Tier.DRAFT,
    Permission.CORRECT_CANDIDATE: Tier.LOW_RISK_INTERNAL_CHANGE,
    Permission.MANAGE_CAMPAIGN: Tier.LOW_RISK_INTERNAL_CHANGE,
    Permission.MANAGE_PRODUCT_CLAIMS: Tier.LOW_RISK_INTERNAL_CHANGE,
    Permission.APPROVE_CANDIDATE: Tier.EXTERNAL_COMMUNICATION,
    Permission.APPROVE_MESSAGE: Tier.EXTERNAL_COMMUNICATION,
    Permission.VIEW_OPERATIONS: Tier.ADMINISTRATIVE,
    Permission.MANAGE_IDENTITY: Tier.ADMINISTRATIVE,
    Permission.MANAGE_INTEGRATIONS: Tier.ADMINISTRATIVE,
    Permission.PAUSE_SYSTEM: Tier.ADMINISTRATIVE,
}

#: Which roles grant which permission, from §12.1's responsibility column.
#:
#: `VIEWER` appears only against reads, and appears there rather than nowhere because §12.1 says
#: a viewer "reads status and reports without making changes" — a role that granted nothing would
#: be a role nobody could be given.
ROLE_GRANTS: Final[dict[Permission, frozenset[RoleKey]]] = {
    Permission.VIEW_STATUS: frozenset(RoleKey),
    Permission.VIEW_REVIEW_QUEUE: frozenset(
        {
            RoleKey.OPERATOR_REVIEWER,
            RoleKey.CAMPAIGN_SALES_OWNER,
            RoleKey.PRODUCT_CLAIM_OWNER,
            RoleKey.REPLY_OWNER,
            RoleKey.SYSTEM_ADMINISTRATOR,
            RoleKey.VIEWER,
        }
    ),
    Permission.REQUEST_DRAFT: frozenset({RoleKey.OPERATOR_REVIEWER, RoleKey.CAMPAIGN_SALES_OWNER}),
    Permission.CORRECT_CANDIDATE: frozenset({RoleKey.OPERATOR_REVIEWER}),
    Permission.MANAGE_CAMPAIGN: frozenset({RoleKey.CAMPAIGN_SALES_OWNER}),
    Permission.MANAGE_PRODUCT_CLAIMS: frozenset({RoleKey.PRODUCT_CLAIM_OWNER}),
    # §12.1 gives candidate and message review to the operator/reviewer. Deliberately *not* the
    # system administrator: administering identity is not the same authority as approving an
    # outbound message, and §7.4 tier 5 is a separate row from tier 4 for that reason.
    Permission.APPROVE_CANDIDATE: frozenset({RoleKey.OPERATOR_REVIEWER}),
    Permission.APPROVE_MESSAGE: frozenset({RoleKey.OPERATOR_REVIEWER}),
    Permission.VIEW_OPERATIONS: frozenset({RoleKey.SYSTEM_ADMINISTRATOR}),
    Permission.MANAGE_IDENTITY: frozenset({RoleKey.SYSTEM_ADMINISTRATOR}),
    Permission.MANAGE_INTEGRATIONS: frozenset({RoleKey.SYSTEM_ADMINISTRATOR}),
    Permission.PAUSE_SYSTEM: frozenset({RoleKey.SYSTEM_ADMINISTRATOR}),
}

#: Permissions that let an external effect happen. Only roles no service may hold can grant these
#: (§3.5, ADR-008); `tests/test_authz.py` checks the grant sets against `HUMAN_ONLY_ROLES`.
APPROVAL_PERMISSIONS: Final = frozenset({Permission.APPROVE_CANDIDATE, Permission.APPROVE_MESSAGE})


class Public:
    """A route that deliberately needs no session.

    A distinct type rather than `None`, so "nobody decided" and "somebody decided this is open"
    cannot be the same value. `undeclared_routes` treats the first as a failure and the second as
    an answer.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "PUBLIC"


PUBLIC: Final = Public()

#: Every route this application serves, keyed by `(method, path)`.
#:
#: Liveness and readiness are `PUBLIC` on purpose: a probe that needed a session would report the
#: application unhealthy exactly when the identity provider was down, which is the moment an
#: operator most needs the truth. Neither reveals anything but a status and a version.
ROUTE_PERMISSIONS: Final[dict[tuple[str, str], Permission | Public]] = {
    ("GET", "/healthz"): PUBLIC,
    ("GET", "/readyz"): PUBLIC,
    # Obtaining a session cannot itself require one. `T-151a` keeps this from being a hole by
    # refusing it outside `local` at the route, before the body is read — see `identity.api`.
    ("POST", "/api/auth/stub-sign-in"): PUBLIC,
    # Reading and ending your own session need a session, not a permission: every role may ask
    # who they are, and signing out is not an action anyone can be unauthorized for.
    ("GET", "/api/auth/session"): PUBLIC,
    ("DELETE", "/api/auth/session"): PUBLIC,
    ("GET", "/api/review/candidates"): Permission.VIEW_REVIEW_QUEUE,
    ("GET", "/api/review/revisions"): Permission.VIEW_REVIEW_QUEUE,
    ("GET", "/api/review/attention/approvals"): Permission.VIEW_REVIEW_QUEUE,
    # Tier 5 for a read: see . The overview reports dead-job reasons and which
    # safety switches are thrown.
    ("GET", "/api/operations/overview"): Permission.VIEW_OPERATIONS,
    # Tier 5, and the same permission that names the authority: these are the switches that
    # stop the system. Never a reuse of a lower tier.
    ("POST", "/api/operations/flags/{key}"): Permission.PAUSE_SYSTEM,
    # Revoking is the same authority as approving: a role that could withdraw but not grant
    # could stop any outreach it disliked, and one that could grant but not withdraw could not
    # undo its own mistake.
    ("POST", "/api/review/approvals/{approval_id}/revoke"): Permission.APPROVE_MESSAGE,
    ("GET", "/api/review/candidates/{candidate_id}"): Permission.VIEW_REVIEW_QUEUE,
    ("POST", "/api/review/revisions/{revision_id}/edit"): Permission.CORRECT_CANDIDATE,
    # Rejecting and deferring are tier-3 corrections: reversible internal state, no external
    # effect. Approving is tier 4 and is a different permission — and a different task.
    ("POST", "/api/review/candidates/{candidate_id}/reject"): Permission.CORRECT_CANDIDATE,
    ("POST", "/api/review/candidates/{candidate_id}/defer"): Permission.CORRECT_CANDIDATE,
    # Also tier 3: ADR-022 makes requesting more research add evidence without moving the
    # candidate, so it changes less than a deferral does.
    (
        "POST",
        "/api/review/candidates/{candidate_id}/request-research",
    ): Permission.CORRECT_CANDIDATE,
    # Tier 4, deliberately a different permission from the two above: this is the approval
    # that lets an external effect happen at all (§7.4), and a role that may tidy the review
    # queue must not be able to start outreach.
    ("POST", "/api/review/candidates/{candidate_id}/approve"): Permission.APPROVE_CANDIDATE,
    # Also tier 4, and a *different* tier-4 permission: §12.1 separates approving a candidate
    # for outreach from approving the exact words that go out, and §11.3 is the transaction for
    # the second one.
    ("POST", "/api/review/revisions/{revision_id}/approve"): Permission.APPROVE_MESSAGE,
}

#: Paths FastAPI adds for its own documentation. Not application actions, and excluded from the
#: coverage check by name so the exclusion is visible rather than implied by a prefix match.
FRAMEWORK_PATHS: Final = frozenset({"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"})


class AuthorizationError(Exception):
    """The caller may not do this."""


class NotAuthenticated(AuthorizationError):
    """No usable session. Distinct from `Forbidden` so a caller can be told to sign in."""


class Forbidden(AuthorizationError):
    """Authenticated, but no role grants this permission."""


class UndeclaredRoute(AuthorizationError):
    """A route with no permission decision recorded.

    Fails closed and loudly: the alternative is a route that serves anyone because nobody said
    otherwise, which is the failure mode this module exists to make impossible.
    """


def roles_granting(permission: Permission) -> frozenset[RoleKey]:
    """Which roles grant ``permission``. Raises for a permission nobody mapped."""
    try:
        return ROLE_GRANTS[permission]
    except KeyError:  # pragma: no cover - a test asserts the map is total
        raise AuthorizationError(f"no roles mapped for {permission}") from None


def permission_for(method: str, path: str) -> Permission | Public:
    """The declared permission for a route, or raise :class:`UndeclaredRoute`."""
    try:
        return ROUTE_PERMISSIONS[(method.upper(), path)]
    except KeyError:
        raise UndeclaredRoute(
            f"{method.upper()} {path} declares no permission. Every route names a `Permission` "
            f"or `PUBLIC` in `ROUTE_PERMISSIONS`; there is no default, because a default would "
            f"be a decision nobody made (§15.1)."
        ) from None


def authorize(principal: Principal | None, permission: Permission | Public) -> None:
    """Raise unless ``principal`` may exercise ``permission``.

    Returns `None` on success rather than a boolean: a caller that forgets to check a returned
    `False` is a caller that authorized everything, and an exception cannot be ignored by
    accident.
    """
    if isinstance(permission, Public):
        return
    if principal is None:
        raise NotAuthenticated("this action needs a signed-in user")

    granted = {role.value for role in roles_granting(permission)}
    if not (principal.roles & granted):
        raise Forbidden(
            f"{permission.value} needs one of {sorted(granted)}; this session holds "
            f"{sorted(principal.roles) or 'no roles'}"
        )


def undeclared_routes(paths: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Routes with no permission decision. The coverage check `tests/test_authz.py` runs.

    Takes `(method, path)` pairs rather than a FastAPI app so the rule is testable against a
    synthetic route list — a checker that can only be run against the real application is a
    checker nobody can prove detects anything.
    """
    return sorted(
        (method.upper(), path)
        for method, path in paths
        if path not in FRAMEWORK_PATHS and (method.upper(), path) not in ROUTE_PERMISSIONS
    )
