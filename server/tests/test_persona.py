import shutil

import pytest
import yaml

from app.config import settings
from app.errors import AppError
from app.persona.loader import load_persona


@pytest.fixture
def persona_dir(tmp_path):
    shutil.copy(settings.persona_dir / "jenny.yaml", tmp_path / "jenny.yaml")
    return tmp_path


def write(persona_dir, name: str, data: dict) -> None:
    (persona_dir / f"{name}.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
    )


def base_data(persona_dir) -> dict:
    return yaml.safe_load((persona_dir / "jenny.yaml").read_text(encoding="utf-8"))


def test_default_persona_is_valid():
    loaded = load_persona(settings.persona_dir, settings.default_persona)
    persona = loaded.persona
    assert persona.id == settings.default_persona
    assert persona.speech_style.max_sentences_voice == 5
    assert persona.voice.tts_voice
    assert len(loaded.version) == 16


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        (lambda d: d.pop("name"), "name"),
        (lambda d: d.update(nmae="오타"), "nmae"),
        (lambda d: d.update(personality=[]), "personality"),
        (
            lambda d: d["speech_style"].update(max_sentences_voice=0),
            "speech_style.max_sentences_voice",
        ),
        (lambda d: d["speech_style"].update(registr="오타"), "speech_style.registr"),
        (lambda d: d["voice"].update(speaking_rate="빠르게"), "voice.speaking_rate"),
        (lambda d: d.update(role="   "), "role"),
        (
            lambda d: d["speech_style"].update(max_sentences_voice=True),
            "speech_style.max_sentences_voice",
        ),
        (lambda d: d["voice"].update(pitch=2), "voice.pitch"),
        (lambda d: d["voice"].pop("instructions"), "voice.instructions"),
        (lambda d: d["voice"].update(speaking_rate=5), "voice.speaking_rate"),
        (lambda d: d.update(role="{호칭}의 친구"), "(전체)"),
        (lambda d: d.pop("ack"), "ack"),
        (lambda d: d.update(ack=[]), "ack"),
        (lambda d: d.pop("offline_notice"), "offline_notice"),
        (lambda d: d.update(offline_notice="  "), "offline_notice"),
    ],
)
def test_invalid_persona_reports_field(persona_dir, mutate, field):
    data = base_data(persona_dir)
    mutate(data)
    write(persona_dir, "jenny", data)
    with pytest.raises(AppError) as excinfo:
        load_persona(persona_dir, "jenny")
    assert excinfo.value.code == "persona_invalid"
    assert excinfo.value.status_code == 500
    reported = excinfo.value.message.split("잘못된 필드: ")[-1].split(", ")
    assert field in reported


def test_missing_or_unsafe_persona_id(persona_dir):
    for persona_id in ("nobody", "../jenny", "Jenny", ""):
        with pytest.raises(AppError) as excinfo:
            load_persona(persona_dir, persona_id)
        assert excinfo.value.code == "persona_not_found"
        assert excinfo.value.status_code == 404


def test_file_name_must_match_id(persona_dir):
    data = base_data(persona_dir)
    write(persona_dir, "other", data)  # 내용의 id는 jenny
    with pytest.raises(AppError) as excinfo:
        load_persona(persona_dir, "other")
    assert "id" in excinfo.value.message


def test_broken_yaml(persona_dir):
    (persona_dir / "jenny.yaml").write_text("name: [닫히지 않음", encoding="utf-8")
    with pytest.raises(AppError) as excinfo:
        load_persona(persona_dir, "jenny")
    assert excinfo.value.code == "persona_invalid"


def test_reload_after_file_change(persona_dir):
    first = load_persona(persona_dir, "jenny")
    assert load_persona(persona_dir, "jenny") is first  # 바뀌지 않았으면 캐시
    data = base_data(persona_dir)
    data["name"] = "새로운이름"
    write(persona_dir, "jenny", data)
    second = load_persona(persona_dir, "jenny")
    assert second.persona.name == "새로운이름"
    assert second.version != first.version


def test_v2_fields_are_loaded():
    persona = load_persona(settings.persona_dir, settings.default_persona).persona
    assert persona.ack
    assert persona.offline_notice
    assert persona.voice.search_notice


def test_default_persona_avoids_its_own_forbidden_style():
    # 맞장구·안내 문구가 페르소나가 쓰지 않겠다고 한 말투(반말 어미)로 끝나지 않는다
    persona = load_persona(settings.persona_dir, settings.default_persona).persona
    for text in (*persona.ack, persona.offline_notice, persona.voice.search_notice):
        assert not text.rstrip("~!?. ").endswith(("구나", "네"))


def test_persona_lists_are_immutable():
    persona = load_persona(settings.persona_dir, settings.default_persona).persona
    assert isinstance(persona.personality, tuple)


def test_unreadable_path_is_persona_invalid(persona_dir):
    (persona_dir / "folder.yaml").mkdir()  # 파일 자리에 디렉터리
    with pytest.raises(AppError) as excinfo:
        load_persona(persona_dir, "folder")
    assert excinfo.value.code == "persona_invalid"
    assert excinfo.value.status_code == 500
