"""run.sh의 --phone(M3-17): 옵션·도움말·안내 문구.

실제 Tailscale 연결은 사용자 환경이라 가짜 실행 파일로 시험한다.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

RUN_SH = Path(__file__).resolve().parents[2] / "run.sh"
GUIDE_ONLY = {"TRAILTALK_TEST_PHONE_GUIDE_ONLY": "1"}
STATUS = '{"Self": {"DNSName": "mac.tail1234.ts.net."}}'


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run(
        [node, "-p", "process.versions.node.split('.')[0]"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return int(out) if out.isdigit() else 0


# run.sh가 Node 24 이상을 요구하므로 그보다 낮으면 건너뛴다
pytestmark = pytest.mark.skipif(_node_major() < 24, reason="run.sh는 Node 24 이상이 필요")


def _fake_tailscale(tmp_path: Path, status_json: str) -> tuple[Path, Path]:
    """가짜 tailscale과 그것이 받은 인자를 적는 파일."""
    calls = tmp_path / "calls.txt"
    path = tmp_path / "tailscale"
    path.write_text(f"#!/bin/sh\necho \"$@\" >> '{calls}'\ncat <<'EOF'\n{status_json}\nEOF\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path, calls


def _run(args: list[str], env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in {"PHONE_HTTPS_PORT", "WEB_PORT"}}
    env |= env_extra
    return subprocess.run(
        [str(RUN_SH), *args], capture_output=True, text=True, env=env, timeout=60, check=False
    )


def test_help_lists_phone_option():
    result = _run(["--help"], {})
    assert result.returncode == 0
    assert "--phone" in result.stdout
    assert "Tailscale" in result.stdout
    # 도움말이 중간에 잘리지 않고 마지막 안내(종료 방법)까지 나온다
    assert "./stop.sh" in result.stdout


def test_phone_prints_https_address_and_commands(tmp_path):
    fake, calls = _fake_tailscale(tmp_path, STATUS)
    result = _run(["--phone"], {"TAILSCALE_BIN": str(fake)} | GUIDE_ONLY)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "https://mac.tail1234.ts.net:8443" in out  # 끝의 점은 뗀다
    assert f"{fake} serve --bg --https=8443 http://127.0.0.1:5173" in out
    assert f"{fake} serve --https=8443 off" in out
    assert "Funnel이 아님" in out  # 공개(Funnel)로 열지 않는다
    # tailscale에는 상태 조회만 한다. serve는 안내로만 나가고 직접 실행하지 않는다
    assert calls.read_text().split("\n")[:-1] == ["status --json"]


def test_phone_https_port_can_be_changed(tmp_path):
    fake, _ = _fake_tailscale(tmp_path, STATUS)
    result = _run(
        ["--phone"], {"TAILSCALE_BIN": str(fake), "PHONE_HTTPS_PORT": "10000"} | GUIDE_ONLY
    )
    assert result.returncode == 0, result.stderr
    assert "https://mac.tail1234.ts.net:10000" in result.stdout


def test_phone_without_tailscale_stops_with_guidance(tmp_path):
    result = _run(["--phone"], {"TAILSCALE_BIN": str(tmp_path / "없음")})
    assert result.returncode == 1
    assert "Tailscale을 찾지 못했습니다" in result.stderr
    assert "tailscale.com/download" in result.stderr


def test_phone_without_login_stops_with_guidance(tmp_path):
    fake, _ = _fake_tailscale(tmp_path, '{"Self": {}}')
    result = _run(["--phone"], {"TAILSCALE_BIN": str(fake)} | GUIDE_ONLY)
    assert result.returncode == 1
    assert "Tailscale 주소를 알아내지 못했습니다" in result.stderr


# CSRF 방어(M6, 계약 1.5)의 Origin 허용 목록, 운영 빌드(PWA) 옵션, 종료 안내


def test_help_lists_build_option_and_origin_allow_list():
    out = _run(["--help"], {}).stdout
    assert "--build" in out
    assert "ALLOWED_ORIGINS" in out
    assert "./stop.sh" in out  # 늘어난 안내에도 도움말이 끝까지 나온다


def test_phone_adds_its_address_to_the_origin_allow_list(tmp_path):
    fake, _ = _fake_tailscale(tmp_path, STATUS)
    out = _run(["--phone"], {"TAILSCALE_BIN": str(fake), "ALLOWED_ORIGINS": ""} | GUIDE_ONLY).stdout
    origins = next(line for line in out.splitlines() if line.startswith("ALLOWED_ORIGINS=")).split(
        "=", 1
    )[1]
    assert origins.split(",") == [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "https://mac.tail1234.ts.net:8443",
    ]


def test_origin_allow_list_follows_ports_and_user_setting(tmp_path):
    fake, _ = _fake_tailscale(tmp_path, STATUS)
    env = {
        "TAILSCALE_BIN": str(fake),
        "ALLOWED_ORIGINS": "",
        "API_PORT": "8100",
        "WEB_PORT": "5174",
    }
    out = _run(["--phone"], env | GUIDE_ONLY).stdout
    assert "http://127.0.0.1:8100,http://localhost:8100,http://127.0.0.1:5174" in out
    # 직접 지정한 목록은 그대로 두고 폰 주소만 더한다
    mine = "https://custom.example:9000"
    out = _run(
        ["--phone"], {"TAILSCALE_BIN": str(fake), "ALLOWED_ORIGINS": mine} | GUIDE_ONLY
    ).stdout
    assert f"ALLOWED_ORIGINS={mine},https://mac.tail1234.ts.net:8443" in out


def test_phone_guide_explains_how_to_fix_connection_problems(tmp_path):
    fake, _ = _fake_tailscale(tmp_path, STATUS)
    out = _run(["--phone"], {"TAILSCALE_BIN": str(fake)} | GUIDE_ONLY).stdout
    assert "https://mac.tail1234.ts.net:8443" in out
    assert "포트 없는" in out and "README" in out  # 443 주소는 MCP용이라는 안내와 문제 해결 위치


def _stop_copy(tmp_path: Path) -> Path:
    """stop.sh는 자기 위치를 저장소 루트로 삼으므로, 복사본을 임시 폴더에 두고 실행한다."""
    root = tmp_path / "repo"
    (root / ".run").mkdir(parents=True)
    script = root / "stop.sh"
    shutil.copy(RUN_SH.with_name("stop.sh"), script)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return root


def test_stop_reminds_that_the_phone_connection_is_still_open(tmp_path):
    root = _stop_copy(tmp_path)
    (root / ".run" / "phone").write_text("tailscale serve --https=8443 off\n")
    result = subprocess.run(
        [str(root / "stop.sh")], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0
    assert "tailscale serve --https=8443 off" in result.stdout
    assert not (root / ".run" / "phone").exists()  # 한 번 알리면 지운다


def test_stop_stays_quiet_when_phone_mode_was_not_used(tmp_path):
    root = _stop_copy(tmp_path)
    result = subprocess.run(
        [str(root / "stop.sh")], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0
    assert "tailscale" not in result.stdout
