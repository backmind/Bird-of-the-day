"""Atomic, content-addressed file writes.

The site went from two generated pages to one per month plus one per
species. Two properties matter at that scale: a crash mid-run must not
leave a half-written page behind, and a page whose bytes did not change
must not be rewritten, because every rewrite is a diff in the publishing
repository.

Newlines are written verbatim (``newline=""``) so a run on Windows and a
run on Linux produce byte-identical files. ``Path.write_text`` does not:
it translates to the platform line ending and would flip every page in
git depending on where the run happened.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_text_if_changed(path: Path, text: str, encoding: str = "utf-8") -> bool:
    """Write ``text`` to ``path`` unless the file already holds exactly it.

    Returns ``True`` when the file was written, ``False`` when it was
    already up to date. The write lands on a temporary file in the same
    directory and is moved into place with :func:`os.replace`, which is
    atomic on POSIX and on Windows.
    """
    path = Path(path)
    try:
        # Path.read_text() only gained a ``newline`` argument in Python 3.13;
        # this project runs 3.12, so the file is opened directly instead.
        with open(path, "r", encoding=encoding, newline="") as handle:
            if handle.read() == text:
                return False
    except (OSError, UnicodeDecodeError):
        # Missing, unreadable or not valid UTF-8: treat as "must write".
        pass

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return True
