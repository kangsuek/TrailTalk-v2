"""M5-01 스파이크용 가짜 stdio MCP 서버. 호출된 도구를 CALL_LOG 파일에 한 줄씩 남긴다.

환경 변수: CALL_LOG(필수, 호출 기록 파일), EXTRA_TOOLS(선택, 더미 도구 개수. ④번 지연 측정용).
도구: allowed_ping(허용 대상), denied_ping(허용 목록에 없는 대상), extra_NNN(더미).
"""

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

LOG = Path(os.environ["CALL_LOG"])
mcp = MCPServer("fake", subscriptions=False)


def record(name: str) -> str:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(name + "\n")
    return f"{name} ok"


@mcp.tool()
def allowed_ping() -> str:
    """허용 목록에 있는 도구. 호출하면 'allowed_ping ok'를 돌려준다."""
    return record("allowed_ping")


@mcp.tool()
def denied_ping() -> str:
    """허용 목록에 없는 도구. 호출하면 'denied_ping ok'를 돌려준다."""
    return record("denied_ping")


def _make_extra(index: int) -> None:
    name = f"extra_{index:03d}"

    def tool() -> str:
        return record(name)

    tool.__name__ = name
    tool.__doc__ = f"더미 도구 {index}. 지연 측정용이며 쓰지 않는다."
    mcp.tool()(tool)


for i in range(int(os.environ.get("EXTRA_TOOLS", "0"))):
    _make_extra(i)

if __name__ == "__main__":
    mcp.run(transport="stdio")
