"""Which template renders which kind of draft (T-156; §10.5, §11.3, §3.5, §18.2).

Two constants and no behaviour. They were in `drafting.py`, which is also the module that calls
the model gateway — so every module that needed to know *where the boilerplate lives* imported the
module that talks to the model, and the import graph said so.

**That mattered for a reason that is not tidiness.** §11.3 ends "no agent callback is required"
and §3.5 forbids external execution authority held only by the agent runtime. Both are properties
worth asserting structurally, by walking imports — and `T-067a` could not, because
`approve_message → validation → drafting → model_gateway.gateway` made any honest transitive
assertion false. The path never *called* the model; it only knew the name of a text file. Splitting
that knowledge out is what lets the guarantee be stated over the whole path rather than over five
hand-listed modules.

Nothing here imports anything but the draft purpose. That is the property to preserve: the moment
this file needs a provider, a client, or a session, it has stopped being a registry of templates
and the edge is back.
"""

from pathlib import Path
from typing import Final

from app.drafts_and_approvals.models import DraftPurpose

#: Where the template files live. Beside the package, not beside this module's caller.
TEMPLATE_DIR: Final = Path(__file__).resolve().parent / "templates"

#: Which template renders which kind of draft. A purpose with no template cannot be drafted:
#: §10.5 asks for boilerplate "rendered from templates when practical", and the honest reading is
#: that a missing template is a missing decision, not a licence to generate the boilerplate.
PURPOSE_TEMPLATES: Final[dict[DraftPurpose, str]] = {
    DraftPurpose.INITIAL_OUTREACH: "initial_outreach.txt",
}
