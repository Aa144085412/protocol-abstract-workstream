"""
document_parser
===============
Extract plain text from uploaded protocol files. Supports PDF, DOCX, TXT, MD.

Parsing is deliberately cheap and local: NO model calls happen here. This keeps
static document handling free, per the product's low-cost philosophy. Optional
dependencies (pypdf, python-docx) are imported lazily so the module still loads
if only TXT/MD are needed.
"""

from __future__ import annotations

import os
from typing import Optional

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt", ".md", ".xlsx", ".xls", ".csv", ".dna")
_SPREADSHEET_EXTS = (".xlsx", ".xls", ".csv")


def extract_text(path: str, raw_bytes: Optional[bytes] = None, file_name: Optional[str] = None) -> str:
    """Return extracted text for a file.

    Either pass a filesystem ``path``, or pass ``raw_bytes`` + ``file_name``
    (useful for Streamlit's in-memory uploads). Raises ValueError for
    unsupported types and RuntimeError if a needed parser dependency is missing.
    """
    name = file_name or path or ""
    ext = os.path.splitext(name)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )

    if raw_bytes is None:
        with open(path, "rb") as fh:
            raw_bytes = fh.read()

    if ext == ".pdf":
        return _extract_pdf(raw_bytes)
    if ext == ".docx":
        return _extract_docx(raw_bytes)
    if ext in _SPREADSHEET_EXTS:
        return _extract_spreadsheet(raw_bytes, ext, name)
    if ext == ".dna":
        return _extract_snapgene(raw_bytes, name)
    # txt / md
    return raw_bytes.decode("utf-8", errors="replace")


def _extract_snapgene(raw: bytes, name: str) -> str:
    """Summarize a SnapGene .dna plasmid map (sequence, features, primers, cut sites) so the
    agents can design molecular assays against the real construct. Self-contained parser."""
    from .dna_parser import summarize, is_snapgene
    if not is_snapgene(raw):
        return ("[Not a recognizable SnapGene .dna file. If this is a plain-text sequence, "
                "save it as .txt/.fasta instead.]")
    try:
        return summarize(raw, file_name=name)
    except Exception as exc:  # noqa: BLE001
        return f"[Could not parse SnapGene .dna file: {exc}]"


def _extract_pdf(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf not installed. Run: pip install -r requirements.txt") from exc
    import io

    reader = PdfReader(io.BytesIO(raw))
    chunks = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            chunks.append("")
    text = "\n".join(chunks).strip()
    if not text:
        text = "[No extractable text found in PDF — it may be scanned/image-only. " \
               "Consider uploading a text-based version.]"
    return text


def _col_to_idx(ref: str) -> int:
    """'B' -> 1, 'AA' -> 26 (0-indexed). ``ref`` may include the row digits."""
    letters = "".join(ch for ch in ref if ch.isalpha())
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _read_xlsx_stdlib(raw: bytes):
    """Parse an .xlsx into {sheet_name: [rows...]} using only the standard library
    (zipfile + ElementTree), so spreadsheet upload works without pandas/openpyxl."""
    import io
    import zipfile
    from xml.etree import ElementTree as ET

    M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = z.namelist()

    shared = []
    if "xl/sharedStrings.xml" in names:
        sst = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in sst.findall(f"{M}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{M}t")))

    rel_map = {}
    if "xl/_rels/workbook.xml.rels" in names:
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        for rel in rels:
            rel_map[rel.get("Id")] = rel.get("Target")

    wb = ET.fromstring(z.read("xl/workbook.xml"))
    sheets = {}
    for s in wb.find(f"{M}sheets"):
        sname = s.get("name") or f"Sheet{len(sheets)+1}"
        rid = s.get(f"{R}id")
        target = rel_map.get(rid, "")
        path = ("xl/" + target.lstrip("/")) if target and not target.startswith("xl/") else (target or "")
        if path not in names:
            cand = [n for n in names if n.endswith(os.path.basename(target or ""))]
            path = cand[0] if cand else ""
        if not path:
            continue
        ws = ET.fromstring(z.read(path))
        rows = []
        for row in ws.iter(f"{M}row"):
            cells = []
            for c in row.findall(f"{M}c"):
                idx = _col_to_idx(c.get("r", "A1"))
                while len(cells) <= idx:
                    cells.append("")
                t = c.get("t")
                v = c.find(f"{M}v")
                if t == "s" and v is not None:
                    try:
                        cells[idx] = shared[int(v.text)]
                    except (ValueError, IndexError):
                        cells[idx] = ""
                elif t == "inlineStr":
                    istr = c.find(f"{M}is")
                    cells[idx] = "".join(tt.text or "" for tt in (istr.iter(f"{M}t") if istr is not None else []))
                else:
                    cells[idx] = v.text if v is not None and v.text is not None else ""
            rows.append(cells)
        sheets[sname] = rows
    return sheets


def _load_tables(raw: bytes, ext: str) -> dict:
    """Return {sheet_name: [rows]} (each row a list of cell strings, first row = header)."""
    if ext == ".csv":
        import csv
        import io
        text = raw.decode("utf-8", errors="replace")
        return {"data": [list(r) for r in csv.reader(io.StringIO(text))]}
    if ext == ".xlsx":
        return _read_xlsx_stdlib(raw)
    # legacy .xls — needs pandas+xlrd if available
    try:
        import io
        import pandas as pd
        out = {}
        xl = pd.ExcelFile(io.BytesIO(raw))
        for sn in xl.sheet_names:
            df = xl.parse(sn, header=None)
            out[sn] = df.astype(object).where(df.notna(), "").values.tolist()
        return out
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Reading legacy .xls needs pandas+xlrd; please re-save as .xlsx "
                           f"or .csv. ({exc})") from exc


def _extract_spreadsheet(raw: bytes, ext: str, name: str = "") -> str:
    """Turn a spreadsheet (gRNA library, oligo order, sample sheet, etc.) into a
    compact text the agents can read. Front-loads the detected gene/target list and
    any key/value facts so they survive later truncation; long cells (e.g. 312-nt
    oligo sequences) are shortened so the gene list isn't drowned out."""
    try:
        tables = _load_tables(raw, ext)
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001
        return f"[Could not read spreadsheet: {exc}]"
    if not tables:
        return "[Spreadsheet had no readable sheets.]"

    def _trunc(x, n=44):
        s = "" if x is None else str(x)
        return s if len(s) <= n else s[: n - 1] + "…"

    base = os.path.basename(name) or "spreadsheet"
    lines = [f"[SPREADSHEET] {base}", f"Sheets: {', '.join(tables.keys())}", ""]

    gene_cols = {"gene", "genes", "target", "targets", "target_gene", "symbol",
                 "gene_symbol", "gene_name"}
    kv_cols = {"item", "value", "parameter", "key", "field"}

    # 1) front-load gene/target lists so the model sees what's being targeted
    for sn, rows in tables.items():
        if not rows:
            continue
        header = [str(c).strip() for c in rows[0]]
        gidx = next((i for i, c in enumerate(header) if c.lower() in gene_cols), None)
        if gidx is not None:
            seen, vals = set(), []
            for r in rows[1:]:
                v = str(r[gidx]).strip() if gidx < len(r) else ""
                if v and v not in seen:
                    seen.add(v)
                    vals.append(v)
            if vals:
                lines.append(f"Targets in '{sn}' (column '{header[gidx]}', n={len(vals)}): "
                             + ", ".join(vals[:300]))
    # 2) front-load 2-column key/value config sheets
    for sn, rows in tables.items():
        if not rows or len(rows[0]) != 2:
            continue
        low = {str(c).strip().lower() for c in rows[0]}
        if low & kv_cols:
            lines.append(f"\nKey facts [{sn}]:")
            for r in rows[1:51]:
                if r and str(r[0]).strip():
                    lines.append(f"  - {_trunc(r[0])}: {_trunc(r[1] if len(r) > 1 else '')}")
    lines.append("")

    # 3) compact per-sheet dump (rows capped, long cells shortened)
    for sn, rows in tables.items():
        ncol = max((len(r) for r in rows), default=0)
        lines.append(f"## Sheet: {sn} ({max(len(rows) - 1, 0)} rows × {ncol} cols)")
        if rows:
            lines.append("Columns: " + ", ".join(str(c) for c in rows[0]))
        cap = 60 if len(rows) > 200 else len(rows)
        for r in rows[1:cap]:
            lines.append("\t".join(_trunc(v) for v in r))
        if len(rows) > cap:
            lines.append(f"... (+{len(rows) - cap} more rows)")
        lines.append("")
    return "\n".join(lines).strip()


def _extract_docx(raw: bytes) -> str:
    try:
        import docx  # python-docx
    except ImportError as exc:
        raise RuntimeError("python-docx not installed. Run: pip install -r requirements.txt") from exc
    import io

    document = docx.Document(io.BytesIO(raw))
    parts = [p.text for p in document.paragraphs]
    # include simple table text too
    for table in document.tables:
        for row in table.rows:
            parts.append("\t".join(cell.text for cell in row.cells))
    return "\n".join(parts).strip()
