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
   join-runs fallback for tokens that Word split across runs. Runs nested inside
   ``<w:hyperlink>`` (e.g. a clickable email/URL) are included too — python-docx's
   ``paragraph.runs`` omits them, which previously hid hyperlinked text.

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
from docx.oxml.ns import qn
from docx.text.run import Run


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

def _build_pattern(old_text: str, *, ignore_case: bool) -> re.Pattern:
    """Build a boundary-aware regex from a literal old-text string.

    Merge fields in Clio templates are dot-delimited segments optionally
    wrapped in ``<< >>`` with variable whitespace.  A bare field name like
    ``Matter.ResponsibleAttorney`` must NOT match inside the longer
    ``Matter.ResponsibleAttorney.JobTitle.Name``.  We achieve this with
    negative lookaround assertions for dot-or-word characters.

    Whitespace is also made flexible so that ``<< Field >>``,
    ``<<Field>>``, and even ``<<\\nField>>`` all match.
    """
    escaped = re.escape(old_text)
    # Flexible whitespace (space/tab/NBSP/newline) wherever a literal space exists.
    escaped = escaped.replace(r"\ ", r"[\s\u00A0]*")
    # Flexible whitespace inside angle brackets (handles <<Field>> and << Field >>).
    escaped = escaped.replace(r"\<\<", r"<<[\s\u00A0]*")
    escaped = escaped.replace(r"\>\>", r"[\s\u00A0]*>>")
    # Prevent partial matches on dot-delimited merge field names.
    pattern_text = r"(?<![.\w])" + escaped + r"(?![.\w])"
    flags = re.IGNORECASE if ignore_case else 0
    return re.compile(pattern_text, flags=flags)


def _replace_in_text_chunks(
    text: str,
    replacements: list[Replacement],
    *,
    ignore_case: bool,
    counts: list[int],
) -> str:
    """Apply every rule to ``text`` in order, tallying hits into ``counts``.

    Uses boundary-aware regex so ``Matter.Foo`` does not match inside
    ``Matter.Foo.Bar``.  Case-insensitive mode writes the rule's ``new``
    verbatim (no source-casing mirroring).
    """
    if not text:
        return text
    out = text
    for i, rule in enumerate(replacements):
        if not rule.old:
            continue
        pattern = _build_pattern(rule.old, ignore_case=ignore_case)
        out, n = pattern.subn(rule.new, out)
        counts[i] += n
    return out


# ── python-docx pass ────────────────────────────────────────────────────────

def _paragraph_run_entries(paragraph) -> list:
    """``(Run, owning <w:hyperlink> element | None)`` pairs in document order.

    ``python-docx``'s ``paragraph.runs`` only returns direct ``<w:r>`` children
    of ``<w:p>``; runs nested inside ``<w:hyperlink>`` (e.g. a clickable email
    or URL) are silently excluded. Templates frequently store an email as a
    mailto hyperlink, so the display text lived inside ``<w:hyperlink><w:r>`` and
    was invisible to the engine — producing "0 matches" on documents that
    clearly contained the text. We walk the paragraph element directly so those
    runs are included and rewritten like any other, and we remember which
    hyperlink (if any) owns each run so a modified link can be unwrapped.
    """
    out: list = []
    for child in paragraph._p:
        if child.tag == qn("w:r"):
            out.append((Run(child, paragraph), None))
        elif child.tag == qn("w:hyperlink"):
            for r in child.findall(qn("w:r")):
                out.append((Run(r, paragraph), child))
    return out


def _strip_hyperlink_style(run_el) -> None:
    """Remove the ``Hyperlink`` character style from a run's ``<w:rPr>``.

    After unwrapping a hyperlink the text should render as normal text, not keep
    the blue/underlined link styling — this mirrors Word's "Remove Hyperlink".
    """
    rpr = run_el.find(qn("w:rPr"))
    if rpr is None:
        return
    for rstyle in rpr.findall(qn("w:rStyle")):
        if rstyle.get(qn("w:val")) == "Hyperlink":
            rpr.remove(rstyle)


def _unwrap_hyperlink(hyperlink_el) -> None:
    """Promote a hyperlink's children to the paragraph and drop the link wrapper.

    The visible text was replaced with a Clio merge field, which is not a real
    email/URL, so the clickable link is removed (the stakeholders asked to keep
    plain merge-field text). The external relationship in ``*.rels`` is left in
    place but unreferenced, which Word tolerates without a repair prompt.
    """
    parent = hyperlink_el.getparent()
    if parent is None:
        return
    idx = parent.index(hyperlink_el)
    for child in list(hyperlink_el):
        hyperlink_el.remove(child)
        parent.insert(idx, child)
        idx += 1
        if child.tag == qn("w:r"):
            _strip_hyperlink_style(child)
    parent.remove(hyperlink_el)


def _process_paragraph(paragraph, replacements, *, ignore_case, counts) -> None:
    """Rewrite one paragraph's runs, preserving formatting where possible.

    Pass A replaces inside each run individually (keeps per-run formatting for
    tokens contained in a single run — the common case). Pass B is a fallback
    for tokens Word split across runs: the joined text is rewritten and folded
    back into the first run, clearing the rest.

    Hyperlink-nested runs are included (see :func:`_paragraph_run_entries`). When
    a replacement actually changes text inside a hyperlink, that link is
    unwrapped so the merge field is left as plain, non-clickable text.
    """
    entries = _paragraph_run_entries(paragraph)
    if not entries:
        return
    runs = [e[0] for e in entries]
    hyperlink_of = [e[1] for e in entries]
    changed_hyperlinks: list = []

    def _mark(hl) -> None:
        if hl is not None and hl not in changed_hyperlinks:
            changed_hyperlinks.append(hl)

    # Pass A — per-run (formatting-preserving)
    pass_a_counts: list[int] = [0] * len(replacements)
    for idx, run in enumerate(runs):
        if run.text:
            before = run.text
            run.text = _replace_in_text_chunks(
                before, replacements, ignore_case=ignore_case, counts=pass_a_counts
            )
            if run.text != before:
                _mark(hyperlink_of[idx])
    pass_a_total = sum(pass_a_counts)
    for i, c in enumerate(pass_a_counts):
        counts[i] += c

    # Pass B — join fallback ONLY when Pass A found nothing (the token must
    # span multiple runs). Running Pass B after Pass A would re-match old text
    # inside already-replaced new text when old is a substring of new, e.g.
    # "Matter.Case.ID" → "Matter.Case.ID.TEST" → "Matter.Case.ID.TEST.TEST".
    if pass_a_total == 0:
        befores = [r.text for r in runs]
        full = "".join(befores)
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
            for idx, r in enumerate(runs):
                if r.text != befores[idx]:
                    _mark(hyperlink_of[idx])

    for hl in changed_hyperlinks:
        _unwrap_hyperlink(hl)


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
