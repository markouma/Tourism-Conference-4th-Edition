"""WeasyPrint access that does not take the whole site down when GTK is missing.

WeasyPrint renders the tickets, invoices and receipts. It needs native
GTK/Pango libraries that pip cannot install: on Linux they usually come with
the distro, on macOS via Homebrew, and on Windows they are a separate GTK
runtime download. Without them ``import weasyprint`` raises OSError.

That import used to sit at module level in events/utils.py, events/views.py
and controlpanel/views.py, all of which are imported during startup, so a
missing system library stopped Django from loading at all - including the
pages that have nothing to do with PDFs.

Importing HTML from here instead keeps the site running. Only the PDF features
fail, and they fail with a message that says what to install.
"""

import logging

logger = logging.getLogger(__name__)

INSTALL_HINT = (
    "WeasyPrint could not load its native GTK/Pango libraries, so PDF "
    "generation (tickets, invoices, receipts) is unavailable. Install them "
    "for your platform: Debian/Ubuntu 'apt install libpango-1.0-0 "
    "libpangoft2-1.0-0', macOS 'brew install pango', Windows - install the "
    "GTK3 runtime, see https://doc.courtbouillon.org/weasyprint/stable/first_steps.html"
)

try:
    from weasyprint import HTML
except (ImportError, OSError) as exc:  # pragma: no cover - depends on the host
    logger.warning("%s (%s)", INSTALL_HINT, exc)

    _IMPORT_ERROR = exc

    class HTML:  # noqa: N801 - deliberately mimics weasyprint.HTML
        """Stand-in that raises only if something actually tries to make a PDF."""

        def __init__(self, *args, **kwargs):
            raise RuntimeError(INSTALL_HINT) from _IMPORT_ERROR
