"""Provider adapters.

One exists: `EchoModelAdapter`, which calls nothing. A real provider adapter may only be added
when gate **G-03** opens with `Q-012` answered and §15.9's data-handling review recorded — and
even then it must be registered in `registry.REAL_PROVIDER_ADAPTERS`, which is the single place
that decides what may be constructed.
"""

from app.model_gateway.providers.echo import EchoModelAdapter

__all__ = ["EchoModelAdapter"]
