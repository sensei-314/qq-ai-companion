"""
file_reader.py —— 让她看得懂别人发来的文件（2026-11-08 主人要求）

支持：
  .txt / .md / .json / .py / .log / .csv   → 直接读文本
  .docx                                     → python-docx
  .pdf                                      → pypdf（装了才用）
  其他                                       → 提示"打不开"
"""

import io
import os
import tempfile

import requests

MAX_BYTES = 10 * 1024 * 1024
MAX_CHARS = 8000

TEXT_EXTS = {".txt", ".md", ".markdown", ".json", ".py", ".log", ".csv", ".ini", ".yml", ".yaml"}


def _read_text(data):
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", "replace")


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


def read_remote_file(url, name=""):
    """下载并解析一个文件，返回 (文本, 错误)。"""
    try:
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
        elif ext == ".docx":
            text = _read_docx(data)
        elif ext == ".pdf":
            text = _read_pdf(data)
        elif ext == ".doc":
            return None, "老版 .doc 打不开，让对方存成 .docx 或 .txt"
        else:
            text = _read_text(data)
            if not text or sum(1 for c in text[:200] if c.isprintable()) < 100:
                return None, f"不认识的文件类型（{ext or '无扩展名'}）"
        if not text or not text.strip():
            return None, "文件里没有可读的文字"
        return text[:MAX_CHARS], None
    except Exception as e:
        return None, str(e)
