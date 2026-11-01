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

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node가 없음(run.sh가 요구)")


def _fake_tailscale(tmp_path: Path, status_json: str) -> Path:
    path = tmp_path / "tailscale"
    path.write_text(f"#!/bin/sh\ncat <<'EOF'\n{status_json}\nEOF\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _run(args: list[str], env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy() | env_extra
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
    fake = _fake_tailscale(tmp_path, '{"Self": {"DNSName": "mac.tail1234.ts.net."}}')
    result = _run(
        ["--phone"], {"TAILSCALE_BIN": str(fake), "PHONE_GUIDE_ONLY": "1", "WEB_PORT": "5173"}
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "https://mac.tail1234.ts.net:8443" in out  # 끝의 점은 뗀다
    assert f"{fake} serve --bg --https=8443 http://127.0.0.1:5173" in out
    assert f"{fake} serve --https=8443 off" in out
    assert "Funnel이 아님" in out  # 공개(Funnel)로 열지 않는다
    # run.sh는 tailscale serve를 직접 실행하지 않는다(안내만): 가짜 실행 파일이 받은 인자가 없다
    assert "--bg" not in result.stderr


def test_phone_https_port_can_be_changed(tmp_path):
    fake = _fake_tailscale(tmp_path, '{"Self": {"DNSName": "mac.tail1234.ts.net."}}')
    result = _run(
        ["--phone"],
        {"TAILSCALE_BIN": str(fake), "PHONE_GUIDE_ONLY": "1", "PHONE_HTTPS_PORT": "10000"},
    )
    assert result.returncode == 0, result.stderr
    assert "https://mac.tail1234.ts.net:10000" in result.stdout


def test_phone_without_tailscale_stops_with_guidance(tmp_path):
    result = _run(["--phone"], {"TAILSCALE_BIN": str(tmp_path / "없음")})
    assert result.returncode == 1
    assert "Tailscale을 찾지 못했습니다" in result.stderr
    assert "tailscale.com/download" in result.stderr


def test_phone_without_login_stops_with_guidance(tmp_path):
    fake = _fake_tailscale(tmp_path, '{"Self": {}}')
    result = _run(["--phone"], {"TAILSCALE_BIN": str(fake), "PHONE_GUIDE_ONLY": "1"})
    assert result.returncode == 1
    assert "Tailscale 주소를 알아내지 못했습니다" in result.stderr
