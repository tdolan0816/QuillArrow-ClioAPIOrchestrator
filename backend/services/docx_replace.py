"""
Word (.docx) find/replace engine — pure, in-memory, no Clio / FastAPI coupling.

This is the web-app port of the legacy ``mass_update_templates.py`` engine.
Everything operates on ``bytes`` (never on disk paths) so a route can hand it a
template downloaded straight from Clio and get the rewritten bytes back to
re-upload, without temp files.

Two complementary passes cover everything a Word template can hide text in:

1. **python-docx pass** — body paragraphs, table cells, and header/footer
   paragraphs. Runs are find/replaced in place so character formatting is
   preserved for the common case where a token lives inside one run, with a
   join-runs fallback for tokens that Word split across runs.

2. **XML splice pass** — text inside ``<w:txbxContent>`` (DrawingML *and* VML
   text boxes / shapes), which python-docx's paragraph API cannot reach. This
   runs only inside text-box regions so body paragraphs are never processed
   twice.

Both passes share :func:`_replace_in_text_chunks`, the single source of truth
for "how one string is rewritten and counted".
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Iterable

from docx import Document


# ── Lookup model ────────────────────────────────────────────────────────────

@dataclass
class Replacement:
    """One find→replace rule."""
    old: str
    new: str


@dataclass
class ReplaceResult:
    """Outcome of processing a single document."""
    changed: bool
    total: int
    per_rule: list[int]  # occurrences replaced, aligned to the replacements list
    data: bytes          # rewritten bytes when changed, else the original bytes


_HEADER_ALIASES_OLD = {"old", "old_text", "find", "search", "from", "token", "original"}
_HEADER_ALIASES_NEW = {"new", "new_text", "replace", "replacement", "to", "value"}


def parse_lookup_csv(content: str) -> list[Replacement]:
    """Parse a two-column lookup CSV into ordered :class:`Replacement` rules.

    Accepts a header row naming the columns (``old,new`` and common synonyms
    like ``find,replace`` / ``old_text,new_text``). If no recognizable header
    is present, the first two columns are treated as old/new positionally.

    Blank ``old`` cells are skipped (there is nothing to search for). Duplicate
    ``old`` keys keep their first occurrence. Order is preserved so longer,
    more-specific tokens can be listed before the substrings they contain.
    """
    rules: list[Replacement] = []
    seen: set[str] = set()

    reader = csv.reader(io.StringIO(content))
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if not rows:
        return rules

    old_idx, new_idx = 0, 1
    start = 0
    header = [(_c or "").strip().lower() for _c in rows[0]]
    if any(h in _HEADER_ALIASES_OLD for h in header) and any(
        h in _HEADER_ALIASES_NEW for h in header
    ):
        old_idx = next(i for i, h in enumerate(header) if h in _HEADER_ALIASES_OLD)
        new_idx = next(i for i, h in enumerate(header) if h in _HEADER_ALIASES_NEW)
        start = 1

    for row in rows[start:]:
        if len(row) <= max(old_idx, new_idx):
            continue
        old = (row[old_idx] or "").strip()
        new = (row[new_idx] or "")  # keep intentional trailing/leading spaces in value
        if not old or old in seen:
            continue
        seen.add(old)
        rules.append(Replacement(old=old, new=new))

    return rules


# ── Core string rewrite (single source of truth) ───────────────────────────

def _replace_in_text_chunks(
    text: str,
    replacements: list[Replacement],
    *,
    ignore_case: bool,
    counts: list[int],
) -> str:
    """Apply every rule to ``text`` in order, tallying hits into ``counts``.

    Case-insensitive mode still writes the rule's ``new`` verbatim (we do not
    try to mirror the source casing — template tokens are fixed strings).
    """
    if not text:
        return text
    out = text
    for i, rule in enumerate(replacements):
        if not rule.old:
            continue
        if ignore_case:
            pattern = re.compile(re.escape(rule.old), re.IGNORECASE)
            out, n = pattern.subn(lambda _m, _v=rule.new: _v, out)
        else:
            n = out.count(rule.old)
            if n:
                out = out.replace(rule.old, rule.new)
        counts[i] += n
    return out


# ── python-docx pass ────────────────────────────────────────────────────────

def _process_paragraph(paragraph, replacements, *, ignore_case, counts) -> None:
    """Rewrite one paragraph's runs, preserving formatting where possible.

    Pass A replaces inside each run individually (keeps per-run formatting for
    tokens contained in a single run — the common case). Pass B is a fallback
    for tokens Word split across runs: the joined text is rewritten and folded
    back into the first run, clearing the rest.
    """
    runs = paragraph.runs
    if not runs:
        return

    # Pass A — per-run (formatting-preserving)
    for run in runs:
        if run.text:
            run.text = _replace_in_text_chunks(
                run.text, replacements, ignore_case=ignore_case, counts=counts
            )

    # Pass B — join fallback only if a token still spans runs
    full = "".join(r.text for r in runs)
    probe: list[int] = [0] * len(replacements)
    rewritten = _replace_in_text_chunks(
        full, replacements, ignore_case=ignore_case, counts=probe
    )
    if rewritten != full:
        runs[0].text = rewritten
        for r in runs[1:]:
            r.text = ""
        for i, c in enumerate(probe):
            counts[i] += c


def _iter_block_paragraphs(container) -> Iterable:
    """Yield paragraphs from a body/cell/header/footer, recursing into tables."""
    for para in getattr(container, "paragraphs", []):
        yield para
    for table in getattr(container, "tables", []):
        for row in table.rows:
            for cell in row.cells:
                yield from _iter_block_paragraphs(cell)


def _docx_pass(
    data: bytes,
    replacements: list[Replacement],
    *,
    ignore_case: bool,
    include_headers_footers: bool,
    counts: list[int],
    apply_changes: bool,
) -> bytes:
    """Run the python-docx pass; return possibly-rewritten bytes."""
    doc = Document(io.BytesIO(data))

    for para in _iter_block_paragraphs(doc):
        _process_paragraph(para, replacements, ignore_case=ignore_case, counts=counts)

    if include_headers_footers:
        for section in doc.sections:
            for hf in (
                section.header,
                section.footer,
                section.first_page_header,
                section.first_page_footer,
                section.even_page_header,
                section.even_page_footer,
            ):
                for para in _iter_block_paragraphs(hf):
                    _process_paragraph(
                        para, replacements, ignore_case=ignore_case, counts=counts
                    )

    if not apply_changes:
        return data
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── XML splice pass (text boxes / shapes) ───────────────────────────────────

_TXBX_RE = re.compile(r"(<w:txbxContent\b[^>]*>)(.*?)(</w:txbxContent>)", re.DOTALL)
_PARA_RE = re.compile(r"(<w:p\b[^>]*>)(.*?)(</w:p>)", re.DOTALL)
_WT_RE = re.compile(r"(<w:t\b[^>]*>)(.*?)(</w:t>)", re.DOTALL)
_XML_TARGET_RE = re.compile(r"^word/(document\.xml|header\d*\.xml|footer\d*\.xml)$")


def _xml_unescape(s: str) -> str:
    return (
        s.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _rewrite_paragraph_xml(para_inner: str, replacements, *, ignore_case, counts) -> str:
    """Join the ``<w:t>`` chunks in one XML paragraph, rewrite, redistribute."""
    matches = list(_WT_RE.finditer(para_inner))
    if not matches:
        return para_inner

    joined = "".join(_xml_unescape(m.group(2)) for m in matches)
    probe: list[int] = [0] * len(replacements)
    rewritten = _replace_in_text_chunks(
        joined, replacements, ignore_case=ignore_case, counts=probe
    )
    if rewritten == joined:
        return para_inner

    for i, c in enumerate(probe):
        counts[i] += c

    # Fold the whole rewritten string into the first <w:t>, empty the others.
    first = matches[0]
    open_tag = first.group(1)
    if "xml:space" not in open_tag:
        open_tag = open_tag[:-1] + ' xml:space="preserve">'
    new_first = open_tag + _xml_escape(rewritten) + "</w:t>"

    pieces: list[str] = []
    cursor = 0
    for idx, m in enumerate(matches):
        pieces.append(para_inner[cursor:m.start()])
        if idx == 0:
            pieces.append(new_first)
        else:
            pieces.append(m.group(1) + "" + m.group(3))
        cursor = m.end()
    pieces.append(para_inner[cursor:])
    return "".join(pieces)


def _rewrite_txbx_region(region_inner: str, replacements, *, ignore_case, counts) -> str:
    def _para_sub(pm: re.Match) -> str:
        return (
            pm.group(1)
            + _rewrite_paragraph_xml(
                pm.group(2), replacements, ignore_case=ignore_case, counts=counts
            )
            + pm.group(3)
        )

    return _PARA_RE.sub(_para_sub, region_inner)


def _xml_pass(
    data: bytes,
    replacements: list[Replacement],
    *,
    ignore_case: bool,
    counts: list[int],
    apply_changes: bool,
) -> bytes:
    """Rewrite text-box content across document/header/footer XML parts."""
    src = io.BytesIO(data)
    with zipfile.ZipFile(src, "r") as zin:
        names = zin.namelist()
        parts = {n: zin.read(n) for n in names}
        infos = {n: zin.getinfo(n) for n in names}

    changed_any = False
    for name in list(parts):
        if not _XML_TARGET_RE.match(name):
            continue
        xml = parts[name].decode("utf-8")

        def _region_sub(rm: re.Match) -> str:
            return (
                rm.group(1)
                + _rewrite_txbx_region(
                    rm.group(2), replacements, ignore_case=ignore_case, counts=counts
                )
                + rm.group(3)
            )

        new_xml = _TXBX_RE.sub(_region_sub, xml)
        if new_xml != xml:
            changed_any = True
            parts[name] = new_xml.encode("utf-8")

    if not apply_changes or not changed_any:
        return data

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            info = infos[name]
            zi = zipfile.ZipInfo(name, date_time=info.date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr
            zout.writestr(zi, parts[name])
    return out.getvalue()


# ── Public entry point ──────────────────────────────────────────────────────

def process_docx_bytes(
    data: bytes,
    replacements: list[Replacement],
    *,
    ignore_case: bool = False,
    include_headers_footers: bool = True,
    include_textboxes: bool = True,
    apply_changes: bool = True,
) -> ReplaceResult:
    """Find/replace across a .docx given as bytes.

    Args:
        data: the original .docx bytes.
        replacements: ordered find→replace rules.
        ignore_case: case-insensitive matching (value still written verbatim).
        include_headers_footers: also process header/footer paragraphs.
        include_textboxes: also run the XML splice pass for text boxes/shapes.
        apply_changes: when ``False`` this is a dry run — occurrences are counted
            but the returned ``data`` is the untouched original (preview mode).

    Returns:
        :class:`ReplaceResult` with total hits, per-rule hits, and the bytes
        (rewritten when ``apply_changes`` and something changed, else original).
    """
    if not replacements:
        return ReplaceResult(changed=False, total=0, per_rule=[], data=data)

    counts = [0] * len(replacements)

    working = _docx_pass(
        data,
        replacements,
        ignore_case=ignore_case,
        include_headers_footers=include_headers_footers,
        counts=counts,
        apply_changes=apply_changes,
    )

    if include_textboxes:
        working = _xml_pass(
            working,
            replacements,
            ignore_case=ignore_case,
            counts=counts,
            apply_changes=apply_changes,
        )

    total = sum(counts)
    return ReplaceResult(
        changed=(total > 0 and apply_changes),
        total=total,
        per_rule=counts,
        data=working if apply_changes else data,
    )
