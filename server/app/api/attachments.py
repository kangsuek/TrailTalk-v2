"""첨부 파일 내려받기(규약 2.13). 앱에는 로그인이 없어 보호는 ID(UUID) 추측 불가성과 네트워크
경계뿐이다(`<img>`가 헤더를 붙일 수 없어 토큰은 쓰지 않는다)."""

from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app.db.models import Attachment
from app.db.session import DbSession
from app.errors import AppError
from app.services import attachments

router = APIRouter(tags=["attachments"])


def _not_found() -> AppError:
    return AppError("attachment_not_found", "첨부를 찾지 못했어요.", 404)


@router.get("/attachments/{attachment_id}", response_class=FileResponse)
async def get_attachment(
    attachment_id: str, request: Request, db: DbSession, thumb: bool = False
) -> FileResponse:
    """이미지는 바로 보이게(inline), 텍스트·PDF는 내려받기(attachment)로 준다. thumb=1은 320px
    썸네일(썸네일이 없는 첨부는 원본). 항상 nosniff."""
    row = await db.get(Attachment, attachment_id)
    if row is None:
        raise _not_found()
    use_thumb = thumb and row.thumb_path is not None
    relative = row.thumb_path if use_thumb and row.thumb_path else row.path
    path = attachments.resolve(request.app.state.settings.attachments_dir, relative)
    if path is None or not path.is_file():
        raise _not_found()
    if row.mime.startswith("image/"):
        media_type = "image/jpeg" if use_thumb else row.mime
        disposition = "inline"
    elif row.mime == "application/pdf":
        media_type = "application/pdf"  # 브라우저 내장 뷰어로 렌더하지 않고 내려받게 한다
        disposition = "attachment"
    else:
        media_type = "text/plain; charset=utf-8"
        disposition = "attachment"
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=3600",
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(row.name, safe='')}",
    }
    return FileResponse(path, media_type=media_type, headers=headers)
