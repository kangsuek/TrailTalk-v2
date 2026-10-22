"""NFR-08: 캐릭터 이름은 코드가 아닌 personas/*.yaml에만 둔다."""

from app.config import SERVER_DIR, settings
from app.persona.loader import load_persona

APP_DIR = SERVER_DIR / "app"


def persona_names() -> set[str]:
    """personas 폴더의 모든 캐릭터 이름(로더로 검증된 값)."""
    ids = [path.stem for path in settings.persona_dir.glob("*.yaml")]
    return {load_persona(settings.persona_dir, persona_id).persona.name for persona_id in ids}


def test_persona_names_are_found():
    names = persona_names()
    assert "제니" in names
    assert all(len(name) >= 2 for name in names)  # 한 글자 이름은 부분 일치 검사가 오탐한다


def test_no_character_name_in_app_code():
    offenders = []
    for path in sorted(APP_DIR.rglob("*")):
        if path.suffix not in {".py", ".mako", ".ini", ".json", ".yaml"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        offenders += [
            f"{path.relative_to(SERVER_DIR)}: {name}" for name in persona_names() if name in text
        ]
    assert not offenders, "캐릭터 이름이 코드에 있습니다:\n" + "\n".join(offenders)
