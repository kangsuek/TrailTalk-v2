"""첨부 시험용 파일 만들기(Pillow·pypdf로 즉석 생성)."""

import io

from PIL import Image
from pypdf import PdfWriter


def png_bytes(size=(64, 48), color=(10, 120, 200, 255), mode="RGBA") -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, color if mode == "RGBA" else color[:3]).save(out, "PNG")
    return out.getvalue()


def jpeg_bytes(size=(64, 48), orientation: int | None = None, color=(200, 30, 30)) -> bytes:
    im = Image.new("RGB", size, color)
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    exif[0x010F] = "TestCamera"  # 제작사: 제거돼야 한다
    out = io.BytesIO()
    im.save(out, "JPEG", exif=exif)
    return out.getvalue()


def mpo_bytes(size=(64, 48), color=(30, 160, 90)) -> bytes:
    """폰 사진처럼 MPF(멀티 픽처) 표지가 붙은 JPEG. Pillow는 이를 format "MPO"로 연다."""
    first = Image.new("RGB", size, color)
    second = Image.new("RGB", size, (0, 0, 0))
    out = io.BytesIO()
    first.save(out, "MPO", save_all=True, append_images=[second])
    return out.getvalue()


def gif_bytes(size=(32, 32), frames=2) -> bytes:
    images = [Image.new("P", size, i) for i in range(frames)]
    out = io.BytesIO()
    images[0].save(out, "GIF", save_all=True, append_images=images[1:], duration=50, loop=0)
    return out.getvalue()


def pdf_bytes(pages=1, password: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    if password:
        writer.encrypt(password)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
