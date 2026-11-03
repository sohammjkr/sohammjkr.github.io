"""Stamp a diagonal watermark on every page of one or more PDFs, in place.

    python tools/watermark_pdf.py files/FA26_Resume.pdf files/archive/*.pdf

Skips a PDF that already carries the mark (checked via its metadata keywords),
so running it twice is harmless. Text and links are left intact.
"""
import sys
import pymupdf

TEXT = "SOHAM MANJREKAR"
FLAG = "watermarked"


def mark(path: str) -> bool:
    doc = pymupdf.open(path)
    if FLAG in (doc.metadata.get("keywords") or ""):
        doc.close()
        return False
    for pg in doc:
        r = pg.rect
        c = pymupdf.Point(r.width / 2, r.height / 2)
        pg.insert_text(
            pymupdf.Point(c.x - 215, c.y + 20), TEXT, fontsize=64,
            fontname="helv", color=(0.5, 0.5, 0.5), fill_opacity=0.16,
            morph=(c, pymupdf.Matrix(-38)), overlay=True)
    meta = doc.metadata
    meta["keywords"] = ((meta.get("keywords") or "") + " " + FLAG).strip()
    doc.set_metadata(meta)
    doc.save(path + ".tmp", garbage=3, deflate=True)
    doc.close()
    import os
    os.replace(path + ".tmp", path)
    return True


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(("marked  " if mark(p) else "skipped ") + p)
