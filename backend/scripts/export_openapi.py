"""Export the OpenAPI document for the frontend type generator (T-060b; §18.1, §23).

Run from `backend/`:

    uv run python -m scripts.export_openapi

**Outside `app/` on purpose.** This has to import `app.main.create_app`, and
`tests/test_module_boundaries.py` forbids *anything* under `app/` from importing the application
factory — `main` wires every module together, so importing it is how a leaf quietly acquires the
whole graph. The first version of this lived in `app/cli.py` and the checker caught it. A build
tool is a different category from application code, and putting it in a different directory says
so; `scripts/` is not scanned because nothing here ships.

**No server, no port.** `FastAPI.openapi()` builds the document from the routes and response
models the app object already holds, so this runs in CI and in a test without binding a port to
ask an application about itself.
"""

import json
import pathlib
import sys
from typing import Any, Final

from app.main import create_app

#: Where the document goes. Under `frontend/` rather than `backend/` because the frontend is its
#: only consumer: the generator reads it, `frontend/tests/api-types.test.ts` regenerates from it,
#: and a reviewer looking at a client type wants the schema it came from next to it.
OPENAPI_EXPORT_PATH: Final = (
    pathlib.Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"
)


def openapi_document() -> dict[str, Any]:
    """The document, from the app object rather than from a running server."""
    return create_app(configure_logs=False).openapi()


def rendered_document() -> str:
    """The exact bytes that belong in the file.

    Sorted keys and a trailing newline, because this file is committed and diffed: a document
    whose key order moved between runs would show as a change nobody made, and a reviewer who
    sees noise stops reading the diff. `test_the_exported_document_is_byte_stable` pins it.
    """
    return json.dumps(openapi_document(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    rendered = rendered_document()
    OPENAPI_EXPORT_PATH.write_text(rendered, encoding="utf-8")
    print(f"wrote {OPENAPI_EXPORT_PATH} ({len(rendered)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
