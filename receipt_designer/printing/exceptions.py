# receipt_designer/printing/exceptions.py
"""
Consistent error types for the printing subsystem.

No Qt dependencies — this module is pure Python so it can be used
in non-GUI contexts (tests, CLI tools, dry-run pipelines).
"""
from __future__ import annotations


class PrintError(Exception):
    """Base exception for all printing errors."""


class PrinterConnectionError(PrintError):
    """Failed to connect to the printer (network, serial, USB)."""


class PrinterConfigError(PrintError):
    """Invalid or incomplete printer configuration."""


class PrintJobError(PrintError):
    """Error during a print job (image conversion, ESC/POS send, etc.)."""


# ---------------------------------------------------------------------------
# Error-mapping helpers
# ---------------------------------------------------------------------------

_CONNECTION_PATTERNS: list[tuple[type, str]] = [
    (ConnectionRefusedError, "Printer refused the connection. Is it powered on?"),
    (ConnectionResetError, "Connection to printer was reset unexpectedly."),
    (TimeoutError, "Printer connection timed out. Check network/cable."),
    (OSError, "Network error communicating with the printer."),
]


def _chain(new: PrintError, cause: BaseException) -> PrintError:
    """Attach *cause* as ``__cause__`` (mimics ``raise new from cause``)."""
    new.__cause__ = cause
    return new


def map_exception(exc: BaseException) -> PrintError:
    """
    Wrap a low-level exception into the appropriate ``PrintError`` subclass
    with a user-friendly message while preserving the original as ``__cause__``.

    If *exc* is already a ``PrintError`` it is returned unchanged.
    """
    if isinstance(exc, PrintError):
        return exc

    # Connection-level errors
    for exc_type, message in _CONNECTION_PATTERNS:
        if isinstance(exc, exc_type):
            return _chain(PrinterConnectionError(message), exc)

    # Configuration errors (raised by our own code as RuntimeError/ValueError)
    text = str(exc).lower()
    if isinstance(exc, (ValueError, KeyError)):
        return _chain(PrinterConfigError(str(exc)), exc)
    if isinstance(exc, RuntimeError) and any(
        kw in text for kw in ("not installed", "missing", "requires", "unknown interface")
    ):
        return _chain(PrinterConfigError(str(exc)), exc)

    # Everything else is a job-level error
    return _chain(PrintJobError(str(exc)), exc)


def friendly_message(exc: BaseException) -> str:
    """Return a short, UI-safe description for *exc*."""
    mapped = map_exception(exc)
    return str(mapped)
