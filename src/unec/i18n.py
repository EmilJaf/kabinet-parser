"""Tiny i18n helper for backend strings (push notifications, holiday names).

We don't need full gettext machinery — a JSON catalog per language and a
dotted-path lookup with `str.format` substitution is enough. The whole API
is `t(key, lang, **vars)`.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from importlib.resources import files

logger = logging.getLogger(__name__)

DEFAULT_LANG = "az"
SUPPORTED: frozenset[str] = frozenset({"az", "ru", "en"})


def normalize(lang: str | None) -> str:
    """Coerce arbitrary input to a supported language code."""
    if lang and lang in SUPPORTED:
        return lang
    return DEFAULT_LANG


@lru_cache(maxsize=len(SUPPORTED))
def _load(lang: str) -> dict:
    """Read the JSON catalog for `lang` once per process."""
    text = (files("unec.locales") / f"{lang}.json").read_text(encoding="utf-8")
    return json.loads(text)


def _lookup(catalog: dict, dotted: str) -> str | dict | None:
    node: object = catalog
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node  # type: ignore[return-value]


def t(key: str, lang: str | None = None, **vars: object) -> str:
    """Look up `key` in `lang`'s catalog and `str.format` it with `vars`.

    Falls back to DEFAULT_LANG when the key is missing in the requested
    language. If still missing, returns the key itself — so a missing
    translation degrades visibly without crashing.
    """
    target = normalize(lang)
    for try_lang in (target, DEFAULT_LANG):
        node = _lookup(_load(try_lang), key)
        if isinstance(node, str):
            try:
                return node.format(**vars)
            except (KeyError, IndexError):
                return node
    logger.warning("i18n: missing key %r (lang=%s)", key, target)
    return key


def get_map(key: str, lang: str | None = None) -> dict[str, str]:
    """Fetch a sub-tree as a plain dict[str, str]. Used for one-shot lookups
    against many keys (e.g. holiday name translation tables)."""
    target = normalize(lang)
    for try_lang in (target, DEFAULT_LANG):
        node = _lookup(_load(try_lang), key)
        if isinstance(node, dict):
            return {k: v for k, v in node.items() if isinstance(v, str)}
    return {}
