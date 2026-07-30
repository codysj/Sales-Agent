"""Outreach adapters.

**Owns:** implementations of `ExternalEffectAdapter` for the channels §13 describes.

**Must not own:** approval decisions, suppression, eligibility, or retry policy. An adapter performs
an effect that has already been authorized and reports what happened; every decision about whether
the effect *should* happen belongs upstream (§5.1, §11.4).

Only the fake adapter exists during Stage 1. A real provider is gated behind **G-07** (§19.6), and
`tests/test_dispatch.py` fails if a network client appears here before then.
"""

from app.core.settings import Settings
from app.jobs_and_outbox.dispatch import ExternalEffectAdapter
from app.outreach_and_replies.adapters.fake import FakeExternalEffectAdapter


def build_effect_adapter(settings: Settings) -> ExternalEffectAdapter:
    """The adapter the worker dispatches through.

    Returns the fake unconditionally, and takes ``settings`` anyway so the call site does not have
    to change when `G-07` unlocks a real provider. There is deliberately **no branch and no
    configuration switch**: the fake is the only adapter that exists, `Q-004` has chosen no mailbox
    or provider, and a settings field whose sole legal value is `"fake"` would read as though a real
    option were available. Shadow mode needs no branch either — `GuardedAdapter.perform` refuses
    before `_perform` runs, whichever adapter this returns.

    ``is_email=True`` so the narrower `OUTBOUND_EMAIL_DISABLED` switch applies to it (§17.6).
    """
    return FakeExternalEffectAdapter(is_email=True)
