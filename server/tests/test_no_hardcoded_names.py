"""NFR-08: 캐릭터 이름은 코드가 아닌 personas/*.yaml에만 둔다."""

from pathlib import Path

import yaml

from app.config import SERVER_DIR, settings

APP_DIR = SERVER_DIR / "app"


def persona_names() -> set[str]:
    names = set()
    for path in Path(settings.persona_dir).glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        names.add(data["name"])
    return names


def test_persona_names_are_found():
    assert "제니" in persona_names()


def test_no_character_name_in_app_code():
    offenders = []
    for path in sorted(APP_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for name in persona_names():
            if name in text:
                offenders.append(f"{path.relative_to(SERVER_DIR)}: {name}")
    assert not offenders, "캐릭터 이름이 코드에 있습니다:\n" + "\n".join(offenders)
