"""正式文件匯出：record.md → docx（封面、目錄、章節編號、圖表編號與圖說、頁碼）→ pdf（LibreOffice headless）。"""
from __future__ import annotations

import asyncio
import csv
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from .config import Settings
from .record import CHAPTERS
from .vault import parse_md

IMG_RE = re.compile(r"^!\[[^\]]*\]\(([^)]+)\)\s*$")
CAP_RE = re.compile(r"^\*(圖 \d+：.+)\*$")
LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
FONT = "Microsoft JhengHei"


def _set_font(doc: Document) -> None:
    for name in ("Normal", "Heading 1", "Heading 2", "Title", "Caption"):
        st = doc.styles[name]
        st.font.name = FONT
        rpr = st.element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        rfonts.set(qn("w:eastAsia"), FONT)
    doc.styles["Normal"].font.size = Pt(10.5)


def _page_number_footer(doc: Document) -> None:
    p = doc.sections[0].footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run("第 ")
    run = p.add_run()
    for tag, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if tag:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tag)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)
    p.add_run(" 頁")


def _inline(text: str) -> str:
    text = LINK_RE.sub(r"\1", text)
    return text.replace("**", "").replace("`", "")


def md_to_docx(record_md: Path, out: Path) -> dict[str, int]:
    fm, body = parse_md(record_md.read_text(encoding="utf-8"))
    doc = Document()
    _set_font(doc)
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Cm(2.2)
    _page_number_footer(doc)

    # 封面
    for _ in range(6):
        doc.add_paragraph()
    t = doc.add_paragraph(style="Title")
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    t.add_run(f"開發紀錄：{fm.get('title', '')}")
    for line in (f"文件編號：{fm.get('id')}", f"版本：{fm.get('version')}", f"任務狀態：{fm.get('state')}",
                 f"文件狀態：{fm.get('doc_status')}", f"匯出日期：{datetime.now():%Y-%m-%d}"):
        p = doc.add_paragraph(line)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if fm.get("approved_by"):
        p = doc.add_paragraph(f"核可人：{fm['approved_by']}（{fm.get('approved_at')}）")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    else:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(str(fm.get("doc_status")))
        r.bold = True
        r.font.color.rgb = RGBColor(0xC0, 0x39, 0x2B)
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # 目錄（靜態；章節與圖表清單）
    doc.add_paragraph("目錄", style="Title")
    for ch in CHAPTERS:
        doc.add_paragraph(ch)
    caps = [m.group(1) for m in (CAP_RE.match(ln.strip()) for ln in body.splitlines()) if m]
    if caps:
        doc.add_paragraph("圖目錄").runs[0].bold = True
        for c in caps:
            doc.add_paragraph(c)
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    base = record_md.parent
    lines = body.splitlines()
    i, n_img, n_tab, n_h1 = 0, 0, 0, 0
    in_code = False
    code: list[str] = []
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if s.startswith("```"):
            if in_code:
                if code and not code[0].startswith("%%mermaid"):
                    p = doc.add_paragraph()
                    r = p.add_run("\n".join(code))
                    r.font.name = "Consolas"
                    r.font.size = Pt(8.5)
                in_code, code = False, []
            else:
                in_code = True
                code = ["%%mermaid"] if s == "```mermaid" else []
            i += 1
            continue
        if in_code:
            code.append(ln)
            i += 1
            continue
        if s.startswith("# ") or s.startswith("> [!"):
            i += 1
            continue
        if s.startswith("## "):
            doc.add_heading(s[3:], level=1)
            n_h1 += 1
        elif s.startswith("### "):
            doc.add_heading(_inline(s[4:]), level=2)
        elif IMG_RE.match(s):
            img = base / IMG_RE.match(s).group(1)  # type: ignore[union-attr]
            doc.add_picture(str(img), width=Cm(15))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            n_img += 1
        elif CAP_RE.match(s):
            p = doc.add_paragraph(CAP_RE.match(s).group(1), style="Caption")  # type: ignore[union-attr]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif s.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= {"-", ":"} for c in cells):
                    rows.append(cells)
                i += 1
            n_tab += 1
            cap = doc.add_paragraph(f"表 {n_tab}：{_table_title(doc)}", style="Caption")
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            ncol = max(len(r) for r in rows)
            tbl = doc.add_table(rows=len(rows), cols=ncol)
            tbl.style = "Table Grid"
            for ri, r in enumerate(rows):
                for ci in range(ncol):
                    cell = tbl.cell(ri, ci)
                    cell.text = _inline(r[ci]) if ci < len(r) else ""
                    for par in cell.paragraphs:
                        for run in par.runs:
                            run.font.size = Pt(7.5 if ncol > 4 else 9)
                            run.bold = ri == 0
            continue
        elif s.startswith(">"):
            p = doc.add_paragraph(_inline(s.lstrip("> ")))
            p.paragraph_format.left_indent = Cm(0.8)
        elif s.startswith("- "):
            doc.add_paragraph(_inline(s[2:]), style="List Bullet")
        elif s:
            doc.add_paragraph(_inline(s))
        i += 1
    doc.add_section(WD_SECTION.CONTINUOUS)
    doc.save(str(out))
    return {"chapters": n_h1, "images": n_img, "tables": n_tab}


def _table_title(doc: Document) -> str:
    for p in reversed(doc.paragraphs):
        if p.style.name.startswith("Heading"):
            return p.text
    return "表格"


async def docx_to_pdf(settings: Settings, docx: Path, outdir: Path) -> Path:
    if not settings.soffice.exists():
        raise FileNotFoundError(f"找不到 LibreOffice：{settings.soffice}")
    with tempfile.TemporaryDirectory(prefix="legion-lo-") as prof:
        cmd = [str(settings.soffice), f"-env:UserInstallation={Path(prof).as_uri()}", "--headless",
               "--convert-to", "pdf", "--outdir", str(outdir), str(docx)]

        def go() -> subprocess.CompletedProcess[str]:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        proc = await asyncio.to_thread(go)
    pdf = outdir / (docx.stem + ".pdf")
    if proc.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"PDF 轉檔失敗：{proc.stderr[-400:]}")
    return pdf


async def export(settings: Settings, task_id: str, fmt: str) -> Path:
    rec = settings.record_dir(task_id) / "record.md"
    if not rec.exists():
        raise FileNotFoundError(rec)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    docx = settings.output_dir / f"record_{task_id}.docx"
    md_to_docx(rec, docx)
    if fmt == "docx":
        return docx
    if fmt == "pdf":
        with tempfile.TemporaryDirectory(prefix="legion-pdf-") as td:
            tmp = Path(td) / docx.name
            shutil.copy(docx, tmp)
            pdf = await docx_to_pdf(settings, tmp, settings.output_dir)
        return pdf
    raise ValueError(f"不支援的格式：{fmt}")


# ---------------------------------------------------------------- 讀回驗證
def read_back(path: Path) -> dict[str, object]:
    if path.suffix == ".docx":
        d = Document(str(path))
        heads = [p.text for p in d.paragraphs if p.style.name == "Heading 1"]
        texts = "\n".join(p.text for p in d.paragraphs)
        return {"chapters": sum(1 for c in CHAPTERS if c in heads), "images": len(d.inline_shapes),
                "has_toc": "目錄" in texts, "pages": None}
    if path.suffix == ".pdf":
        from pypdf import PdfReader

        r = PdfReader(str(path))
        text = "\n".join(pg.extract_text() or "" for pg in r.pages)
        # LibreOffice 會把圖片放在共用資源，逐頁計數會重複；改算不重複的影像物件
        img_refs: set[int] = set()
        for pg in r.pages:
            xobjs = pg.get("/Resources", {}).get("/XObject", {})
            for ref in xobjs.values():
                obj = ref.get_object()
                if obj.get("/Subtype") == "/Image" and hasattr(ref, "idnum"):
                    img_refs.add(ref.idnum)
        # 章節以 PDF 書籤（由 Heading 1 產生）判定，避免文字擷取斷行誤差
        top = [o.title for o in r.outline if not isinstance(o, list)]
        chapters = sum(1 for c in CHAPTERS if c in top)
        return {"chapters": chapters, "images": len(img_refs), "has_toc": "目錄" in text, "pages": len(r.pages)}
    raise ValueError(path)


EXPORT_FIELDS = ["time", "task", "format", "file", "chapters", "expected_chapters", "images", "expected_images",
                 "has_toc", "pages", "ok"]


def append_export_check(out: Path, task_id: str, path: Path, expected_images: int) -> dict[str, object]:
    rb = read_back(path)
    row = {
        "time": datetime.now().astimezone().isoformat(timespec="seconds"), "task": task_id,
        "format": path.suffix[1:], "file": str(path), "chapters": rb["chapters"], "expected_chapters": len(CHAPTERS),
        "images": rb["images"], "expected_images": expected_images, "has_toc": rb["has_toc"], "pages": rb["pages"],
    }
    row["ok"] = (rb["chapters"] == len(CHAPTERS) and rb["images"] == expected_images and bool(rb["has_toc"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    new = not out.exists()
    with out.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EXPORT_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    return row
