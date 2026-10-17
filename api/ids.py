"""Stable ids shared by the API, the stores and the sync jobs."""

import re


def slug(text: str) -> str:
    """Block id from its name: 'Block 1' -> 'block-1'."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "block"
