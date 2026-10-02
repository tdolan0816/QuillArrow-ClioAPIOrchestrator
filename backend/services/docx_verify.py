"""
Post-update verification for Word (.docx) templates — pure, in-memory.

Web-app port of the legacy ``verify_template_updates.py``. Given a rewritten
template (bytes) and the rules that were applied, it re-scans the document and
reports how many occurrences of each **old** token remain (should be 0) and how
many of each **new** value are present. Two scans mirror the two rewrite passes:

* ``docx`` — text reachable via python-docx (body, tables, headers/footers).
* ``xml``  — raw text across all XML parts (catches text boxes / shapes).
"""

from __future__ import annotations

import io
import re
import zipfile

from docx import Document

from backend.services.docx_replace import (
    Replacement,
    _iter_block_paragraphs,
    _xml_unescape,
)


_TAG_RE = re.compile(r"<[^>]+>")


def _collect_docx_text(data: bytes, *, include_headers_footers: bool = True) -> str:
    doc = Document(io.BytesIO(data))
    chunks: list[str] = []
    for para in _iter_block_paragraphs(doc):
        chunks.append(para.text)
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
                    chunks.append(para.text)
    return "\n".join(chunks)


def _collect_xml_text(data: bytes) -> str:
    chunks: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data), "r") as zin:
        for name in zin.namelist():
            if name.startswith("word/") and name.endswith(".xml"):
                raw = zin.read(name).decode("utf-8", errors="ignore")
                # Strip tags, THEN decode entities so tokens containing < or >
                # (e.g. "<< Field >>", stored as &lt;&lt; Field &gt;&gt;) match.
                chunks.append(_xml_unescape(_TAG_RE.sub("", raw)))
    return "\n".join(chunks)


def _count(haystack: str, needle: str, *, ignore_case: bool) -> int:
    if not needle:
        return 0
    if ignore_case:
        return len(re.findall(re.escape(needle), haystack, re.IGNORECASE))
    return haystack.count(needle)


def verify_docx_bytes(
    data: bytes,
    replacements: list[Replacement],
    *,
    ignore_case: bool = False,
    include_headers_footers: bool = True,
) -> dict:
    """Re-scan a rewritten template and report remaining/old & present/new hits.

    Returns::

        {
          "clean": bool,                 # no old tokens remain anywhere
          "old_remaining_total": int,
          "new_present_total": int,
          "rules": [
            {"old","new",
             "old_docx","old_xml","new_docx","new_xml"},
            ...
          ],
        }
    """
    docx_text = _collect_docx_text(data, include_headers_footers=include_headers_footers)
    xml_text = _collect_xml_text(data)

    rules_out: list[dict] = []
    old_remaining_total = 0
    new_present_total = 0
    for rule in replacements:
        old_docx = _count(docx_text, rule.old, ignore_case=ignore_case)
        old_xml = _count(xml_text, rule.old, ignore_case=ignore_case)
        new_docx = _count(docx_text, rule.new, ignore_case=ignore_case) if rule.new else 0
        new_xml = _count(xml_text, rule.new, ignore_case=ignore_case) if rule.new else 0
        # xml text is a superset of docx text, so remaining-old uses the xml scan.
        old_remaining_total += old_xml
        new_present_total += new_xml
        rules_out.append(
            {
                "old": rule.old,
                "new": rule.new,
                "old_docx": old_docx,
                "old_xml": old_xml,
                "new_docx": new_docx,
                "new_xml": new_xml,
            }
        )

    return {
        "clean": old_remaining_total == 0,
        "old_remaining_total": old_remaining_total,
        "new_present_total": new_present_total,
        "rules": rules_out,
    }
