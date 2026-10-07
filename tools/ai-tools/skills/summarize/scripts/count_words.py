"""Count the words in a drafted summary that count toward the word limit.

The session line, the collapsed prompt list, and anything after it (the note to
the user) do not count.  Models are poor at counting their own words, so the
``summarize`` skill runs this instead of estimating.

Usage::

    python3 count_words.py <path to drafted summary>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def count_summary_words(text: str) -> int:
    """Count the words in a summary, excluding the session line, prompt list, and note.

    Parameters
    ----------
    text
        The full drafted summary in markdown.

    Returns
    -------
        The number of words that count toward the limit.
    """
    summary = text.split("<details>")[0]
    summary = re.sub(r"(?m)^\*\*Session:\*\*.*$", "", summary)
    # Bullet markers and other punctuation-only tokens are not words.
    return sum(1 for token in summary.split() if re.search(r"\w", token))


if __name__ == "__main__":
    print(count_summary_words(Path(sys.argv[1]).read_text()))
