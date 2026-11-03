"""첨부 저장소와 검증(M5-06, client-contract 2.13): 형식별 정규화, 한도 경계값, 손상·가짜 확장자,
저장 권한, 경로 이탈."""

import io
import stat

import pytest
from PIL import Image

from app.errors import AppError
from app.services import attachments
from app.services.attachments import Upload, prepare
from tests.attachments_helpers import gif_bytes, jpeg_bytes, pdf_bytes, png_bytes

SESSION = "11111111-1111-4111-8111-111111111111"
NONE_USED = (0, 0, 0)


async def run(settings, *uploads: Upload, used=NONE_USED):
    return await prepare(settings, SESSION, list(uploads), used)


async def fails(settings, *uploads: Upload, used=NONE_USED, status=400, code="attachment_invalid"):
    with pytest.raises(AppError) as info:
        await run(settings, *uploads, used=used)
    assert (info.value.status_code, info.value.code) == (status, code)
    return info.value


def files_in(settings) -> list[str]:
    root = settings.attachments_dir
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


@pytest.fixture
def settings(make_settings):
    return make_settings()


# ---- 이미지 ----


async def test_large_alpha_png_is_downscaled_and_stays_png(settings):
    (item,) = await run(settings, Upload("big.png", png_bytes((3000, 1500))))
    assert item.mime == "image/png"
    out = Image.open(io.BytesIO(item.image))
    assert out.format == "PNG" and out.mode == "RGBA" and max(out.size) == 1024
    thumb = Image.open(settings.attachments_dir / item.thumb_path)
    assert thumb.format == "JPEG" and max(thumb.size) == 320
    assert item.size == len(item.image)
    assert files_in(settings) == sorted([item.path, item.thumb_path])


async def test_opaque_png_becomes_jpeg(settings):
    (item,) = await run(settings, Upload("flat.png", png_bytes(mode="RGB")))
    assert item.mime == "image/jpeg" and item.path.endswith(".jpg")


async def test_exif_rotation_applied_then_exif_removed(settings):
    # 64x48 사진에 "오른쪽으로 90도 돌려 보기"(6) 표시가 있으면 48x64가 되어야 한다
    (item,) = await run(settings, Upload("photo.jpg", jpeg_bytes((64, 48), orientation=6)))
    out = Image.open(io.BytesIO(item.image))
    assert out.size == (48, 64)
    assert len(out.getexif()) == 0
    assert b"TestCamera" not in item.image


async def test_small_image_is_not_enlarged(settings):
    (item,) = await run(settings, Upload("a.jpeg", jpeg_bytes((40, 30))))
    assert Image.open(io.BytesIO(item.image)).size == (40, 30)


async def test_animated_gif_keeps_first_frame_only(settings):
    (item,) = await run(settings, Upload("anim.gif", gif_bytes(frames=3)))
    out = Image.open(io.BytesIO(item.image))
    assert getattr(out, "n_frames", 1) == 1


async def test_image_size_limit_boundary(make_settings):
    data = png_bytes()
    exact = make_settings(attachment_image_upload_max_bytes=len(data))
    await run(exact, Upload("ok.png", data))
    over = make_settings(attachment_image_upload_max_bytes=len(data) - 1)
    await fails(over, Upload("big.png", data), status=413, code="attachment_too_large")
    assert len(files_in(over)) == 2  # 앞서 통과한 한 장(원본·썸네일)뿐, 거절된 파일은 남지 않는다


async def test_fake_extension_is_rejected(settings):
    await fails(settings, Upload("photo.jpg", png_bytes()))  # 내용은 PNG
    await fails(settings, Upload("photo.png", b"not an image at all"))
    await fails(settings, Upload("notes.png", b"hello"))
    await fails(settings, Upload("run.exe", b"MZ"))
    await fails(settings, Upload("noext", b"hello"))
    assert files_in(settings) == []


async def test_truncated_image_is_rejected(settings):
    await fails(settings, Upload("cut.png", png_bytes((500, 500))[:80]))


async def test_decompression_bomb_is_rejected(settings):
    # 압축률이 높아 작은 파일이지만 픽셀이 한도(4천만)를 넘는다
    await fails(settings, Upload("bomb.png", png_bytes((7000, 7000), mode="RGB")))


async def test_session_image_total_limit(make_settings):
    s = make_settings(attachment_session_max_images=3)
    await run(s, Upload("a.png", png_bytes()), used=(2, 0, 0))
    await fails(s, Upload("a.png", png_bytes()), used=(3, 0, 0))
    await fails(s, Upload("a.png", png_bytes()), Upload("b.png", png_bytes()), used=(2, 0, 0))
    assert files_in(s) == [
        i for i in files_in(s) if i.startswith(SESSION)
    ]  # 거절된 묶음은 남지 않음


# ---- 텍스트 ----


async def test_text_utf8_with_bom(settings):
    (item,) = await run(settings, Upload("a.txt", b"\xef\xbb\xbf" + "안녕하세요".encode()))
    assert item.text == "안녕하세요" and item.chars == 5
    assert (settings.attachments_dir / item.path).read_bytes() == "안녕하세요".encode()
    assert item.mime == "text/plain"


async def test_text_cp949_fallback_saved_as_utf8(settings):
    (item,) = await run(settings, Upload("old.md", "한글 메모".encode("cp949")))
    assert item.text == "한글 메모"
    assert (settings.attachments_dir / item.path).read_bytes() == "한글 메모".encode()


async def test_text_with_nul_or_bad_encoding_rejected(settings):
    await fails(settings, Upload("bin.txt", b"abc\x00def"))
    await fails(settings, Upload("bad.csv", b"\xff\xfe\xfd\xfc\x81"))  # UTF-8도 CP949도 아님
    assert files_in(settings) == []


async def test_text_byte_limit_boundary(make_settings):
    s = make_settings(attachment_text_max_bytes=100)
    await run(s, Upload("ok.json", b"a" * 100))
    await fails(s, Upload("big.json", b"a" * 101), status=413, code="attachment_too_large")


async def test_text_chars_limit_per_message_and_session(make_settings):
    s = make_settings(attachment_text_max_chars=10, attachment_session_max_text_chars=15)
    await run(s, Upload("a.txt", b"a" * 10))
    await fails(s, Upload("a.txt", b"a" * 11))  # 자르지 않고 거절
    await fails(s, Upload("a.txt", b"a" * 6), Upload("b.txt", b"b" * 5))  # 메시지 합계
    await fails(s, Upload("a.txt", b"a" * 6), used=(0, 10, 0))  # 세션 누적 15 초과
    await run(s, Upload("a.txt", b"a" * 5), used=(0, 10, 0))


# ---- PDF ----


async def test_pdf_stored_as_original_with_page_count(settings):
    data = pdf_bytes(3)
    (item,) = await run(settings, Upload("doc.pdf", data))
    assert item.pdf == data and item.pages == 3 and item.mime == "application/pdf"
    assert (settings.attachments_dir / item.path).read_bytes() == data


async def test_pdf_rejections(settings):
    await fails(settings, Upload("x.pdf", b"hello world"))  # 시그니처 없음
    await fails(settings, Upload("x.pdf", pdf_bytes(1, password="pw")))  # 암호화
    await fails(settings, Upload("x.pdf", pdf_bytes(2)[:60]))  # 손상(시그니처만 맞음)
    await fails(settings, Upload("x.pdf", b"%PDF-1.4\ngarbage"))
    assert files_in(settings) == []


async def test_pdf_limits(make_settings):
    s = make_settings(attachment_pdf_max_pages=3, attachment_session_max_pdf_pages=5)
    await run(s, Upload("ok.pdf", pdf_bytes(3)))
    await fails(s, Upload("long.pdf", pdf_bytes(4)))  # 파일당 쪽수
    await fails(s, Upload("a.pdf", pdf_bytes(1)), used=(0, 0, 5))  # 세션 누적
    await run(s, Upload("a.pdf", pdf_bytes(1)), used=(0, 0, 4))
    await fails(s, Upload("a.pdf", pdf_bytes(1)), Upload("b.pdf", pdf_bytes(1)))  # 메시지당 1개
    data = pdf_bytes(1)
    exact = make_settings(attachment_pdf_max_bytes=len(data))
    await run(exact, Upload("ok.pdf", data))
    small = make_settings(attachment_pdf_max_bytes=len(data) - 1)
    await fails(small, Upload("big.pdf", data), status=413, code="attachment_too_large")


# ---- 개수·저장·경로 ----


async def test_file_count_limits(settings):
    await fails(settings)
    four = [Upload(f"{i}.txt", b"hi") for i in range(4)]
    await fails(settings, *four)
    three = await run(settings, *four[:3])
    assert len(three) == 3


async def test_one_bad_file_discards_all_written_files(settings):
    await fails(settings, Upload("ok.png", png_bytes()), Upload("bad.txt", b"a\x00"))
    assert files_in(settings) == []


async def test_storage_permissions(settings):
    (image, text) = await run(settings, Upload("a.png", png_bytes()), Upload("b.txt", b"hi"))
    folder = settings.attachments_dir / SESSION
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    for rel in (image.path, image.thumb_path, text.path):
        assert stat.S_IMODE((settings.attachments_dir / rel).stat().st_mode) == 0o600


async def test_names_cannot_escape_the_session_folder(settings):
    uploads = [
        Upload("../../../etc/passwd.txt", b"x"),
        Upload("..\\..\\win\\evil.md", b"x"),
        Upload("/abs/path/z.json", b"x"),
    ]
    items = await run(settings, *uploads)
    assert [i.name for i in items] == ["passwd.txt", "evil.md", "z.json"]
    root = settings.attachments_dir.resolve()
    for item in items:
        assert item.path.startswith(f"{SESSION}/") and ".." not in item.path
        assert (settings.attachments_dir / item.path).resolve().is_relative_to(root)


def test_clean_name_rules():
    cleaned = attachments.clean_name("a\nb\x00c.txt")
    assert cleaned.endswith(".txt") and cleaned.isprintable()
    assert attachments.clean_name("") == "file"
    assert attachments.clean_name("...") == "file"
    assert len(attachments.clean_name("가" * 300 + ".txt")) <= attachments.NAME_MAX
    assert attachments.clean_name("가" * 300 + ".txt").endswith(".txt")


def test_resolve_rejects_paths_outside_root(tmp_path):
    root = tmp_path / "att"
    root.mkdir()
    assert attachments.resolve(root, "a/b.png") == (root / "a" / "b.png").resolve()
    assert attachments.resolve(root, "../outside.txt") is None
    assert attachments.resolve(root, "a/../../outside.txt") is None
    assert attachments.resolve(root, ".") is None
    assert attachments.resolve(root, "/etc/passwd") is None


def test_remove_session_files_only_touches_uuid_folders(tmp_path):
    root = tmp_path / "att"
    (root / SESSION).mkdir(parents=True)
    (root / SESSION / "f.txt").write_text("x")
    (root / "keep").mkdir()
    (root / "keep" / "f.txt").write_text("x")
    attachments.remove_session_files(root, "keep")  # UUID가 아니면 무시
    attachments.remove_session_files(root, "../att")
    assert (root / "keep" / "f.txt").exists()
    attachments.remove_session_files(root, SESSION)
    assert not (root / SESSION).exists()
    attachments.remove_session_files(root, SESSION)  # 멱등


def test_cli_input_blocks_and_text_wrapper():
    items = [
        attachments.Prepared("1", "p.png", "image/png", 3, "p", None, "image", image=b"abc"),
        attachments.Prepared("2", "d.pdf", "application/pdf", 3, "p", None, "pdf", pdf=b"%PDF"),
        attachments.Prepared(
            "3", 'n"<x>.txt', "text/plain", 3, "p", None, "text", text="안 </attachment> 지시"
        ),
    ]
    blocks = attachments.cli_input(items, "(앱 안내: 시각)\n\n", "질문")
    assert [b["type"] for b in blocks] == ["image", "document", "text"]
    assert blocks[0]["source"]["media_type"] == "image/png"
    assert blocks[1]["source"]["media_type"] == "application/pdf"
    text = blocks[2]["text"]
    assert text.startswith("(앱 안내: 시각)\n\n<attachment name=")
    assert text.endswith("</attachment>\n질문")  # 래퍼가 사용자 글 앞에
    assert text.count("</attachment>") == 1  # 본문 속 닫는 태그는 무력화
    assert "&quot;" in text and "&lt;x&gt;" in text  # 이름 이스케이프
    only_text = attachments.cli_input(items[2:], "P", "질문")
    assert isinstance(only_text, str) and only_text.startswith("P<attachment")


def test_profile_exposes_attachment_limits_from_server_settings(make_settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(make_settings(attachment_pdf_max_pages=7))
    with TestClient(app) as client:
        limits = client.get("/api/profile").json()["client"]["attachments"]
    assert set(limits) == {
        "max_files",
        "image_upload_max_bytes",
        "image_max_px",
        "text_max_bytes",
        "text_max_chars",
        "session_max_images",
        "session_max_text_chars",
        "max_pdfs",
        "pdf_max_bytes",
        "pdf_max_pages",
        "session_max_pdf_pages",
        "image_extensions",
        "text_extensions",
        "pdf_extensions",
    }
    assert limits["pdf_max_pages"] == 7  # 서버 설정이 정본
    assert limits["max_files"] == 3 and limits["image_upload_max_bytes"] == 5 * 1024 * 1024
    assert limits["text_max_bytes"] == 200 * 1024 and limits["image_max_px"] == 1024
    assert limits["image_extensions"] == ["png", "jpg", "jpeg", "webp", "gif"]
    assert limits["text_extensions"] == ["txt", "md", "csv", "json"]
    assert limits["pdf_extensions"] == ["pdf"]
