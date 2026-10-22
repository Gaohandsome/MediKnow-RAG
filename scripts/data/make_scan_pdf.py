"""造一个「部分页面被栅格化」的测试 PDF，验证多模态兜底链路。

做出来的文件：指定页整页变成 JPEG（没有文字层、只剩一张图），
其余页保持原始文本层。用来模拟「把表格/流程图改成图片」的文档。

用法：
    python scripts/data/make_scan_pdf.py --pages 4,5
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

DEFAULT_SRC = ROOT / "data/uploads/kb_18/39c67d7a3f294628bc834159b9a23d97.pdf"
DEFAULT_OUT = ROOT / "data/samples"


def rasterize_page(page, dpi: int = 200) -> bytes:
    """把一页渲染成 JPEG 字节流。"""
    image = page.to_image(resolution=dpi).original
    if image.mode != "RGB":
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92, optimize=True)
    return buffer.getvalue()


def build(src: Path, out: Path, page_numbers: set[int], dpi: int = 200) -> Path:
    import pdfplumber
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    reader = PdfReader(str(src))
    writer = PdfWriter()
    raster_cache: dict[int, bytes] = {}

    with pdfplumber.open(str(src)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            if index not in page_numbers:
                writer.add_page(reader.pages[index - 1])
                continue

            data = rasterize_page(page, dpi)
            raster_cache[index] = data
            buffer = io.BytesIO()
            pdf_canvas = canvas.Canvas(buffer, pagesize=(page.width, page.height))
            pdf_canvas.drawImage(
                ImageReader(io.BytesIO(data)),
                0,
                0,
                width=page.width,
                height=page.height,
                preserveAspectRatio=False,
                anchor="c",
            )
            pdf_canvas.showPage()
            pdf_canvas.save()
            buffer.seek(0)
            writer.add_page(PdfReader(buffer).pages[0])
            print(f"  第 {index} 页 → 整页图片（{len(data) // 1024} KB）")

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as handle:
        writer.write(handle)
    return out


def verify(path: Path, page_numbers: set[int]) -> None:
    """复核：目标页应当「无文字、有一张图」，其余页仍有文字层。"""
    import pdfplumber

    with pdfplumber.open(str(path)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            chars = len((page.extract_text() or "").strip())
            images = len(page.images or [])
            flag = "栅格化" if index in page_numbers else "文本层"
            print(f"  p{index}\t{flag}\t文字 {chars} 字\t图 {images} 张")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成部分页面为图片的测试 PDF")
    parser.add_argument("--src", default=str(DEFAULT_SRC))
    parser.add_argument("--out", default=str(DEFAULT_OUT / "医院员工培训守则_扫描页版.pdf"))
    parser.add_argument("--pages", default="4,5", help="要栅格化的页码，逗号分隔（1 开始）")
    parser.add_argument("--dpi", type=int, default=200)
    args = parser.parse_args()

    src = Path(args.src)
    if not src.exists():
        print(f"[!] 源文件不存在：{src}")
        return 1
    pages = {int(item) for item in args.pages.split(",") if item.strip()}
    out = Path(args.out)

    print(f"源文件：{src}")
    print(f"栅格化页面：{sorted(pages)}")
    build(src, out, pages, args.dpi)
    print(f"\n已生成：{out}（{out.stat().st_size // 1024} KB）\n复核：")
    verify(out, pages)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
