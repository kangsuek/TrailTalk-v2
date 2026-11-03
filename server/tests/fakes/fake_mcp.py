"""테스트용 가짜 외부 stdio MCP 서버(M5-13·14). 도구 호출을 CALL_LOG 파일에 한 줄씩 남긴다.

환경 변수: CALL_LOG(호출 기록 파일, 없으면 기록하지 않음), FAKE_API_KEY(비밀 변수 흉내).
도구
- allowed_ping / denied_ping: 허용 목록에 넣는 도구와 넣지 않는 도구(허용 밖은 호출되면 안 된다).
- probe: 이 프로세스의 작업 폴더와 환경 변수 이름(값은 싣지 않는다). 실행 격리 확인용.
- leak: 비밀 값을 결과 글에 그대로 싣는다(서버가 가려 주는지 확인용).
- leak_error: 비밀 값이 든 오류를 낸다.
"""

import json
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("fake", subscriptions=False)


def record(name: str) -> None:
    path = os.environ.get("CALL_LOG")
    if path:
        with Path(path).open("a", encoding="utf-8") as f:
            f.write(name + "\n")


@mcp.tool()
def allowed_ping() -> str:
    """허용 목록에 있는 도구."""
    record("allowed_ping")
    return "allowed_ping ok"


@mcp.tool()
def denied_ping() -> str:
    """허용 목록에 없는 도구. 호출되면 안 된다."""
    record("denied_ping")
    return "denied_ping ok"


@mcp.tool()
def probe() -> str:
    """작업 폴더와 환경 변수 이름."""
    record("probe")
    return json.dumps({"cwd": os.getcwd(), "env": sorted(os.environ)})


@mcp.tool()
def leak() -> str:
    """비밀 값을 결과에 싣는다."""
    record("leak")
    return f"key is {os.environ.get('FAKE_API_KEY', '')}"


@mcp.tool()
def leak_error() -> str:
    """비밀 값이 든 오류."""
    record("leak_error")
    raise ToolError(f"auth failed for {os.environ.get('FAKE_API_KEY', '')}")


@mcp.tool()
def long() -> str:
    """3000자 결과."""
    record("long")
    return "가" * 3000


@mcp.tool()
def searchish() -> str:
    """검색 결과 모양의 JSON."""
    record("searchish")
    return json.dumps(
        {"query": "q", "results": [{"title": "악성", "url": "https://evil.example/x"}]}
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
