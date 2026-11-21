"""file_reader.py —— 让她看得懂别人发来的文件（2026-11-08 主人要求）

支持：
  .txt / .md / .json / .py / .log / .csv / .ini / .yml / .yaml / .html / .xml → 直接读文本
  .docx                                     → python-docx
  .pdf                                      → pypdf（装了才用）
  .xlsx                                     → openpyxl（装了才用）
  .pptx                                     → python-pptx（装了才用）
  其他                                       → 提示"打不开"
"""

import io
import os
import re
import tempfile

import requests

MAX_BYTES = 10 * 1024 * 1024
MAX_CHARS = 8000

TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".json", ".py", ".log", ".csv", ".ini",
    ".yml", ".yaml", ".html", ".htm", ".xml", ".toml", ".sh", ".bat",
}


def _read_text(data):
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", "replace")


def _strip_html(text):
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text)


def _read_docx(data):
    try:
        import docx
    except ImportError:
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            doc = docx.Document(path)
            parts = [p.text for p in doc.paragraphs if p.text.strip()]
            # 表格
            for t in doc.tables[:5]:
                for row in t.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        parts.append(" | ".join(cells))
            return "\n".join(parts)
        finally:
            os.unlink(path)
    except Exception as e:
        print(f"[file] docx fail: {e}")
        return None


def _read_pdf(data):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages[:20]:
            parts.append(page.extract_text() or "")
        return "\n".join(parts)
    except Exception as e:
        print(f"[file] pdf fail: {e}")
        return None


def _read_xlsx(data):
    try:
        import openpyxl
    except ImportError:
        return None
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        parts = []
        for ws in wb.worksheets[:5]:
            parts.append(f"【{ws.title}】")
            n = 0
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None and str(c).strip()]
                if cells:
                    parts.append(" | ".join(cells))
                    n += 1
                    if n > 200:
                        parts.append("…（后面还有）")
                        break
        return "\n".join(parts)
    except Exception as e:
        print(f"[file] xlsx fail: {e}")
        return None


def _read_pptx(data):
    try:
        from pptx import Presentation
    except ImportError:
        return None
    try:
        prs = Presentation(io.BytesIO(data))
        parts = []
        for i, slide in enumerate(prs.slides[:30]):
            parts.append(f"【第 {i + 1} 页】")
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        t = "".join(r.text for r in para.runs).strip()
                        if t:
                            parts.append(t)
        return "\n".join(parts)
    except Exception as e:
        print(f"[file] pptx fail: {e}")
        return None


def read_remote_file(url, name=""):
    """下载并解析一个文件，返回 (文本, 错误)。"""
    try:
        if str(url).startswith("data://"):
            data = str(url)[7:].encode("utf-8", "replace")
        elif str(url).startswith("file://"):
            with open(str(url)[7:], "rb") as f:
                data = f.read()
        else:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            data = r.content
        if not data:
            return None, "文件是空的"
        if len(data) > MAX_BYTES:
            return None, "文件太大（超过 10MB）"
        ext = os.path.splitext(str(name or url).split("?")[0])[1].lower()
        text = None
        if ext in TEXT_EXTS:
            text = _read_text(data)
            if ext in (".html", ".htm", ".xml"):
                text = _strip_html(text)
        elif ext == ".docx":
            text = _read_docx(data)
        elif ext == ".pdf":
            text = _read_pdf(data)
        elif ext in (".xlsx", ".xlsm"):
            text = _read_xlsx(data)
        elif ext == ".pptx":
            text = _read_pptx(data)
        elif ext == ".doc":
            return None, "老版 .doc 打不开，让对方存成 .docx 或 .txt"
        elif ext == ".xls":
            return None, "老版 .xls 打不开，让对方存成 .xlsx 或 .csv"
        else:
            text = _read_text(data)
            if not text or sum(1 for c in text[:200] if c.isprintable()) < 100:
                return None, f"不认识的文件类型（{ext or '无扩展名'}）"
        if not text or not text.strip():
            return None, "文件里没有可读的文字"
        return text[:MAX_CHARS], None
    except Exception as e:
        return None, str(e)
