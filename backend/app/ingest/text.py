"""Text helpers: HTML to readable text, normalisation and hashing."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import UTC, datetime

from selectolax.lexbor import LexborHTMLParser as HTMLParser

_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
    "tr", "section", "article", "header", "footer", "table",
}  # fmt: skip
_WS = re.compile(r"[ \t ]+")
_NL = re.compile(r"\n{3,}")


def html_to_text(raw: str | None, unescape: bool = False) -> str:
    """Convert an HTML fragment to plain text that keeps paragraph and bullet breaks."""
    if not raw:
        return ""
    if unescape:
        raw = html.unescape(raw)
    if "<" not in raw:
        return clean_text(html.unescape(raw))
    tree = HTMLParser(raw)
    for tag in ("script", "style", "noscript"):
        for node in tree.css(tag):
            node.decompose()
    for node in tree.css("li"):
        node.insert_before("\n• ")
    for tag in _BLOCK_TAGS:
        for node in tree.css(tag):
            node.insert_after("\n")
    root = tree.body or tree.root
    text = root.text(separator="", deep=True) if root else ""
    return clean_text(text)


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\r", "")
    lines = [_WS.sub(" ", line).strip() for line in text.split("\n")]
    out = "\n".join(lines)
    return _NL.sub("\n\n", out).strip()


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "unknown"


_COMPANY_SUFFIX = re.compile(
    r"\b(inc|llc|ltd|limited|pvt|private|corp|corporation|co|gmbh|technologies|labs?)\b\.?",
    re.I,
)
_TITLE_NOISE = re.compile(r"[\(\[].*?[\)\]]|[-–|,/].*$")


def norm_company(name: str) -> str:
    name = _COMPANY_SUFFIX.sub(" ", name.lower())
    return re.sub(r"[^a-z0-9]+", "", name)


def norm_title(title: str) -> str:
    title = _TITLE_NOISE.sub("", title.lower())
    title = re.sub(r"\b(sr|snr)\b\.?", "senior", title)
    return re.sub(r"[^a-z0-9]+", " ", title).strip()


def sha(*parts: str | None) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def parse_dt(value) -> datetime | None:
    """Parse ISO strings, epoch seconds or epoch milliseconds into aware datetimes."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, int | float):
            ts = value / 1000 if value > 1e11 else value
            return datetime.fromtimestamp(ts, tz=UTC)
        s = str(value).strip()
        if s.isdigit():
            return parse_dt(int(s))
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (ValueError, OverflowError, OSError):
        return None
