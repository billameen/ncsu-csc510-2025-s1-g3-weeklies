"""Printing reports on any console."""

import sys


def console_safe_output() -> None:
    """
    Print characters the console can't show (the tables' "≥" on a Windows code page) as "?"
    instead of crashing. Report files are always written as UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):  # not a text stream that can change, e.g. in tests
            pass
