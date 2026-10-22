"""캐릭터 YAML 로더. 매번 파일을 읽어 내용 해시가 같으면 파싱 결과를 재사용한다."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.errors import AppError
from app.persona.schema import Persona

_PERSONA_ID = re.compile(r"[a-z0-9_-]{1,64}")


@dataclass(frozen=True)
class LoadedPersona:
    persona: Persona
    version: str  # 파일 내용 해시(DB persona.version)
    path: Path


_cache: dict[Path, LoadedPersona] = {}


def _invalid(path: Path, detail: str) -> AppError:
    return AppError("persona_invalid", f"페르소나 파일 오류({path.name}): {detail}", 500)


def load_persona(persona_dir: Path, persona_id: str) -> LoadedPersona:
    if not _PERSONA_ID.fullmatch(persona_id):
        raise AppError("persona_not_found", "페르소나를 찾을 수 없습니다.", 404)
    path = persona_dir / f"{persona_id}.yaml"
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise AppError(
            "persona_not_found", f"페르소나를 찾을 수 없습니다: {persona_id}", 404
        ) from None
    except OSError as exc:  # 디렉터리·권한 문제
        raise _invalid(path, f"파일을 읽을 수 없습니다({type(exc).__name__})") from exc

    version = hashlib.sha256(raw).hexdigest()[:16]
    cached = _cache.get(path)
    if cached is not None and cached.version == version:
        return cached

    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise _invalid(path, f"YAML을 읽을 수 없습니다({type(exc).__name__})") from exc
    if not isinstance(data, dict):
        raise _invalid(path, "최상위가 키-값 형식이 아닙니다")
    try:
        persona = Persona.model_validate(data)
    except ValidationError as exc:
        fields = ", ".join(
            ".".join(str(part) for part in err["loc"]) or "(전체)" for err in exc.errors()
        )
        raise _invalid(path, f"잘못된 필드: {fields}") from exc
    if persona.id != persona_id:
        raise _invalid(path, f"파일 이름과 id가 다릅니다(id={persona.id})")

    loaded = LoadedPersona(persona, version, path)
    _cache[path] = loaded
    return loaded
