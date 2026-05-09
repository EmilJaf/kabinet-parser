"""Cookie dump/restore round-trip on UnecClient — pure in-memory, no I/O."""
from __future__ import annotations

from unec.scraper.client import UnecClient


def test_cookies_round_trip():
    a = UnecClient(base_url="https://kabinet.unec.edu.az")
    a.set_cookies({"PHPSESSID": "abc123", "SERVERID": "s3kab", "lang": "az"})
    snapshot = a.dump_cookies()
    assert snapshot == {"PHPSESSID": "abc123", "SERVERID": "s3kab", "lang": "az"}

    b = UnecClient(base_url="https://kabinet.unec.edu.az")
    b.set_cookies(snapshot)
    assert b.dump_cookies() == snapshot


def test_set_cookies_replaces_old_ones():
    client = UnecClient(base_url="https://kabinet.unec.edu.az")
    client.set_cookies({"PHPSESSID": "old"})
    client.set_cookies({"PHPSESSID": "new", "lang": "az"})
    assert client.dump_cookies() == {"PHPSESSID": "new", "lang": "az"}
