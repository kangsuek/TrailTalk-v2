"""클라이언트 설정값 기본값 파일(규약 7절)."""

import json

import pytest
from pydantic import ValidationError

from app.client_config import load_client_config
from app.config import REPO_DIR, Settings
from app.main import create_app

DEFAULTS = REPO_DIR / "shared" / "client-defaults.json"


def test_repo_defaults_are_valid(make_settings):
    config = load_client_config(make_settings(idle_timeout_s=1800))
    assert config.model_dump() == json.loads(DEFAULTS.read_text(encoding="utf-8"))


def test_v2_turn_defaults_match_contract():
    turn = json.loads(DEFAULTS.read_text(encoding="utf-8"))["turn"]
    assert turn == {
        "ack_delay_ms": 300,
        "ack_min_speech_ms": 1000,
        "ack_overlap_max_ms": 300,
        "merge_min_speech_ms": 600,
    }


def test_file_has_no_server_filled_values():
    # offline_notice는 페르소나 YAML이, 첨부 한도는 서버 설정이 채운다(규약 7절)
    data = json.loads(DEFAULTS.read_text(encoding="utf-8"))
    assert "offline_notice" not in data
    assert "attachments" not in data


def test_file_idle_timeout_matches_server_default():
    # 파일 값은 프로필을 받기 전 클라이언트 대체값이라 서버 기본값과 같아야 한다
    data = json.loads(DEFAULTS.read_text(encoding="utf-8"))
    default_s = Settings.model_fields["idle_timeout_s"].default
    assert data["session"]["idle_timeout_minutes"] == default_s / 60


def test_server_idle_timeout_overrides_file(make_settings):
    config = load_client_config(make_settings(idle_timeout_s=90))
    assert config.session.idle_timeout_minutes == 1.5


def _write(tmp_path, change):
    data = json.loads(DEFAULTS.read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / "client-defaults.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("change", "message"),
    [
        # 순서 규칙은 하나씩만 어긴다
        (lambda d: d["vad"].update(silence_threshold=0.6), "silence_threshold는"),
        (
            lambda d: d["vad"].update(playback_silence_threshold=0.85),
            "playback_silence_threshold는",
        ),
        (
            lambda d: d["vad"].update(
                playback_speech_threshold=0.45, playback_silence_threshold=0.4
            ),
            "재생 중 임계값은",
        ),
        (lambda d: d["vad"].update(playback_silence_threshold=0.2), "재생 중 무음 임계값은"),
        (lambda d: d["vad"].update(speech_threshold=1.5), "speech_threshold"),
        (lambda d: d["vad"].update(end_of_speech_silence_ms=0), "end_of_speech_silence_ms"),
        (lambda d: d["vad"].update(unknown=1), "unknown"),  # 모르는 키
        (lambda d: d["vad"].pop("min_speech_ms"), "min_speech_ms"),
        (lambda d: d["audio"]["upload"].update(codec="aac"), "codec"),
        (lambda d: d["turn"].update(ack_delay_ms=0), "ack_delay_ms"),
        (lambda d: d["turn"].pop("merge_min_speech_ms"), "merge_min_speech_ms"),
        (lambda d: d.pop("turn"), "turn"),
    ],
)
def test_invalid_file_stops_app(tmp_path, make_settings, change, message):
    with pytest.raises(ValidationError, match=message):
        create_app(make_settings(client_defaults_path=_write(tmp_path, change)))


@pytest.mark.parametrize("seconds", [0, -60])
def test_invalid_server_idle_timeout_stops_app(make_settings, seconds):
    # 서버 무발화 기준을 덮어쓴 값도 검증한다
    with pytest.raises(ValidationError, match="idle_timeout_minutes"):
        create_app(make_settings(idle_timeout_s=seconds))


def test_missing_file_stops_app(tmp_path, make_settings):
    with pytest.raises(FileNotFoundError):
        create_app(make_settings(client_defaults_path=tmp_path / "none.json"))
