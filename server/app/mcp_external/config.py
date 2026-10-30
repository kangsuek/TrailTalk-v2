"""외부 MCP 앱 설정 검증(Claude 앱 연계). 공개 주소와 소유자 비밀번호가 없으면 시작을 거부한다."""

from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import Settings

MIN_PASSWORD_CHARS = 16
CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")
MCP_PATH = "/mcp"


class McpConfigError(ValueError):
    """외부 MCP 앱을 띄울 수 없는 설정. 메시지는 사용자에게 그대로 보여 준다."""


@dataclass(frozen=True)
class McpConfig:
    public_url: str  # 끝에 /가 없는 공개 주소. OAuth issuer이며 MCP 주소는 public_url + /mcp
    owner_password: str
    allowed_redirects: tuple[str, ...]
    max_clients: int

    @property
    def resource_url(self) -> str:
        return f"{self.public_url}{MCP_PATH}"

    @property
    def public_host(self) -> str:
        return urlparse(self.public_url).netloc

    @classmethod
    def from_settings(cls, settings: Settings) -> "McpConfig":
        url = settings.mcp_public_url.strip()
        if not url:
            raise McpConfigError(
                "MCP_PUBLIC_URL이 필요합니다(예: https://<기기>.<tailnet>.ts.net)."
            )
        parsed = urlparse(url)
        if parsed.scheme != "https" and parsed.hostname not in LOCAL_HOSTS:
            raise McpConfigError("MCP_PUBLIC_URL은 https여야 합니다(로컬 시험은 localhost만 http).")
        if url.endswith("/") or parsed.path or parsed.query or parsed.fragment:
            raise McpConfigError("MCP_PUBLIC_URL에는 경로와 끝 슬래시를 넣지 않습니다.")
        password = (
            settings.mcp_owner_password.get_secret_value() if settings.mcp_owner_password else ""
        )
        if len(password) < MIN_PASSWORD_CHARS:
            raise McpConfigError(f"MCP_OWNER_PASSWORD는 {MIN_PASSWORD_CHARS}자 이상이어야 합니다.")
        return cls(
            public_url=url,
            owner_password=password,
            allowed_redirects=settings.mcp_allowed_redirects or (CLAUDE_CALLBACK,),
            max_clients=settings.mcp_max_clients,
        )
