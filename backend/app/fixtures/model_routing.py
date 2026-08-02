"""The fixture-keyed model fake a development process installs (T-172a; §19.2, ADR-017).

`FakeModelAdapter` is a lookup over one directory, and a directory may declare **one**
`match: "default"` entry — so one directory cannot hold both a qualification and a draft
expectation, and the two synthetic campaigns cite different claim keys. Routing on markers the
prompt already carries keeps each expectation in its own reviewable directory.

This lived in `tests/test_shadow_slice.py` until `T-172a` gave `python -m app.cli run_worker` the
same need. It belongs here rather than there because `app/fixtures/` is exactly the package for
"the deliberately fake world the backend is developed against", and because a test and a
development command serving *different* fake output would make the slice prove something the
walkthrough does not do.

**Still development-only.** Nothing under `app/` outside this package may import it
(`tests/test_fixtures.py::test_only_the_cli_imports_the_fixtures`), and installing it is the
CLI's or a test's act — never a domain module's. A deployment installs one adapter for one
configured task, and gate **G-03** says which (`Q-012` has chosen none).
"""

from pathlib import Path
from typing import Any, Final

from app.model_gateway.providers.fake import FakeModelAdapter

MODEL_OUTPUTS: Final = Path(__file__).resolve().parent / "model_outputs"

QUALIFICATION_OUTPUTS: Final = MODEL_OUTPUTS / "slice_qualification"

#: Keyed by the campaign *name*, because that is what a draft prompt carries — the slug never
#: reaches the model. Seeded by `app/fixtures/synthetic.py`.
DRAFT_OUTPUTS_BY_CAMPAIGN_NAME: Final[dict[str, Path]] = {
    "SYNTHETIC-Sodium Battery Campaign": MODEL_OUTPUTS / "slice_draft_sodium",
    "SYNTHETIC-DC Fast Charging Campaign": MODEL_OUTPUTS / "slice_draft_charging",
}

#: The marker a draft prompt carries. Matched literally rather than inferred, so a prompt edit
#: that drops it fails loudly here instead of quietly routing every draft to qualification.
DRAFT_PROMPT_MARKER: Final = "SYNTHETIC-PROMPT draft"


class NoFixtureSetForPrompt(Exception):
    """A draft prompt named no campaign this fixture set knows."""


class TaskRoutingFake:
    """Serves the fixture set belonging to the task — and campaign — the prompt came from."""

    model_name = "deterministic-fake"

    def _directory_for(self, prompt: str) -> Path:
        if DRAFT_PROMPT_MARKER not in prompt:
            return QUALIFICATION_OUTPUTS
        for name, directory in DRAFT_OUTPUTS_BY_CAMPAIGN_NAME.items():
            if name in prompt:
                return directory
        # Raised rather than falling back to qualification output: a draft answered from the
        # wrong fixture set is a §10.4-valid message citing another campaign's claims.
        raise NoFixtureSetForPrompt("a draft prompt named no campaign this fixture set knows")

    def complete(self, *, prompt: str, parameters: dict[str, Any]) -> Any:
        return FakeModelAdapter(directory=self._directory_for(prompt)).complete(
            prompt=prompt, parameters=parameters
        )
