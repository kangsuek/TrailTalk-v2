"""외부 MCP 서버 설정 파일(M5-12, Spec 5.6 "외부 MCP").

`MCP_SERVERS_PATH`(기본 server/mcp-servers.yaml)의 서버 목록을 읽고 검증한다. 파일이 없으면 외부
서버가 없다. 이 파일이 신뢰 경계이므로 틀리면 서버를 시작하지 않는다(ExternalMcpConfigError).
비밀 값은 파일이 아니라 서버 `.env`(또는 환경 변수)의 `MCP_<서버>_<이름>` 변수에만 있고, 읽은 값은
CLI 전용 0600 mcp.json에만 쓴다(app/llm/claude_cli.py). 오류 문구에는 변수 이름만 적고 값은 적지
않는다.
"""

import logging
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import yaml

logger = logging.getLogger("trailtalk.external_mcp")

RESERVED_NAMES = frozenset({"trailtalk", "servers"})
SERVER_NAME = re.compile(r"[a-z0-9-]{1,32}")
TOOL_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
HEADER_NAME = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+")
VARIABLE = re.compile(r"\$\{([^}]*)\}")
VARIABLE_NAME = re.compile(r"[A-Z0-9_]+")
MAX_FULL_NAME = 64  # mcp__<서버>__<도구> 전체(M5-01 ③, 모델 API 규칙)
ALLOWED_KEYS = {
    "stdio": {"name", "command", "args", "env", "allowed_tools", "denied_tools"},
    "http": {"name", "url", "headers", "allowed_tools", "denied_tools"},
}
# 고정(비밀이 아닌) 값은 길이가 이보다 짧으면 가리지 않는다("true"·"1"이 글 곳곳에서 지워지지 않게)
_MIN_PLAIN_REDACT = 6


class ExternalMcpConfigError(Exception):
    """설정 파일이 틀렸다. 서버를 시작하지 않는다. 메시지에 비밀 값은 없다."""


def variable_prefix(server: str) -> str:
    """서버가 참조할 수 있는 비밀 변수의 접두사(서버 이름 대문자, -는 _)."""
    return "MCP_" + server.upper().replace("-", "_") + "_"


def full_tool_name(server: str, tool: str) -> str:
    return f"mcp__{server}__{tool}"


@dataclass(frozen=True)
class ExternalServer:
    name: str
    kind: str  # "stdio" | "http"
    allowed_tools: tuple[str, ...]
    denied_tools: tuple[str, ...] = ()
    command: str = ""
    args: tuple[str, ...] = ()
    url: str = ""
    # env(stdio)·headers(http)의 값. ${MCP_<서버>_<이름>}은 이미 환경 변수 값으로 바뀐 상태다
    values: Mapping[str, str] = field(default_factory=dict)
    secrets: tuple[str, ...] = ()  # 이 서버가 읽은 변수 값(가릴 대상)


@dataclass(frozen=True)
class ExternalMcp:
    servers: tuple[ExternalServer, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.servers)

    def allowed_tool_names(self) -> list[str]:
        return [full_tool_name(s.name, t) for s in self.servers for t in s.allowed_tools]

    def denied_tool_names(self) -> list[str]:
        return [full_tool_name(s.name, t) for s in self.servers for t in s.denied_tools]

    def redact_values(self) -> tuple[str, ...]:
        """로그·오류·결과에서 가릴 값: 변수 값, env·headers 값 전체, Authorization의 토큰 부분."""
        found: set[str] = set()
        for server in self.servers:
            found.update(s for s in server.secrets if s)
            for name, value in server.values.items():
                if not value:
                    continue
                if len(value) >= _MIN_PLAIN_REDACT:
                    found.add(value)
                if name.lower() == "authorization" and " " in value:
                    found.add(value.split(" ", 1)[1])
        return tuple(sorted(found, key=len, reverse=True))  # 긴 값부터 가린다


def log_address(url: str) -> str:
    """로그에 남길 주소(쿼리·조각·사용자 정보를 뺀다)."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    return f"{parts.scheme}://{host}{parts.path}"


def check_file_permissions(path: Path) -> list[str]:
    """파일과 그 폴더가 신뢰할 만한가. 거부 사유 목록(비면 통과). 읽기 가능은 경고만 남긴다."""
    problems: list[str] = []
    uid = os.geteuid()
    for kind, target in (("파일", path), ("폴더", path.parent)):
        try:
            info = target.lstat()
        except OSError as exc:
            problems.append(f"{kind} {target}을 읽을 수 없습니다({type(exc).__name__})")
            continue
        if stat.S_ISLNK(info.st_mode):
            problems.append(f"{kind} {target}이 심볼릭 링크입니다")
            continue
        if info.st_uid != uid:
            problems.append(f"{kind} {target}의 소유자가 서버 실행 사용자가 아닙니다")
        if info.st_mode & 0o022:
            problems.append(
                f"{kind} {target}을 그룹이나 다른 사용자가 쓸 수 있습니다(권한 필요: 0644 이하)"
            )
    if not problems:
        mode = path.lstat().st_mode
        if mode & 0o044:
            logger.warning(
                "외부 MCP 설정 파일을 그룹·다른 사용자가 읽을 수 있습니다(%s). chmod 600 권장",
                path,
            )
    return problems


def _default_environ() -> Mapping[str, str]:
    """비밀 변수를 찾는 곳: 프로세스 환경 변수가 우선이고, 없으면 저장소 루트 .env(`${}` 보간은 하지
    않는다. 간접 참조로 서버 자신의 비밀 변수 차단을 우회하지 못하게)."""
    from dotenv import dotenv_values

    from app.config import REPO_DIR

    merged: dict[str, str] = {
        k: v for k, v in dotenv_values(REPO_DIR / ".env", interpolate=False).items() if v
    }
    merged.update(os.environ)
    return merged


def load_external_mcp(path: Path | None, environ: Mapping[str, str] | None = None) -> ExternalMcp:
    """설정 파일을 읽어 검증한다. 파일이 없으면 외부 서버 없음. 틀리면 ExternalMcpConfigError."""
    if path is None or not (path.exists() or path.is_symlink()):
        return ExternalMcp()
    problems = check_file_permissions(path)
    if problems:
        raise ExternalMcpConfigError(_format("외부 MCP 설정 파일을 믿을 수 없습니다", problems))
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ExternalMcpConfigError(
            f"외부 MCP 설정 파일({path})을 읽을 수 없습니다: {type(exc).__name__}"
        ) from exc
    if document is None:
        return ExternalMcp()
    errors: list[str] = []
    items = _server_items(document, errors)
    names = [i.get("name") for i in items if isinstance(i, dict)]
    parsed: list[ExternalServer] = []
    seen: set[str] = set()
    lookup = _Lookup(environ)
    for index, item in enumerate(items):
        label = _label(item, index)
        server = _parse_server(item, label, names, seen, lookup, errors)
        if server is not None:
            parsed.append(server)
    if errors:
        raise ExternalMcpConfigError(
            _format(f"외부 MCP 설정({path.name})이 올바르지 않습니다", errors)
        )
    for server in parsed:
        logger.info(
            "외부 MCP 서버 등록(name=%s, type=%s, 허용 도구 %d개%s)",
            server.name,
            server.kind,
            len(server.allowed_tools),
            f", url={log_address(server.url)}" if server.url else "",
        )
    return ExternalMcp(tuple(parsed))


def _format(title: str, problems: list[str]) -> str:
    return title + ":\n" + "\n".join(f"  - {p}" for p in problems)


def _label(item: object, index: int) -> str:
    name = item.get("name") if isinstance(item, dict) else None
    return f"servers[{index}]" + (f"({name})" if isinstance(name, str) and name else "")


def _server_items(document: object, errors: list[str]) -> list:
    if not isinstance(document, dict) or set(document) != {"servers"}:
        errors.append("최상위는 `servers` 목록 하나여야 합니다")
        return []
    items = document["servers"]
    if items is None:
        return []
    if not isinstance(items, list):
        errors.append("`servers`는 목록이어야 합니다")
        return []
    return items


class _Lookup:
    """비밀 변수 값 조회. 환경은 필요할 때 처음 한 번만 만든다(.env는 변수를 쓸 때만 읽는다)."""

    def __init__(self, environ: Mapping[str, str] | None) -> None:
        self._environ = environ

    def get(self, name: str) -> str | None:
        if self._environ is None:
            self._environ = _default_environ()
        return self._environ.get(name)


def _app_variable_names() -> frozenset[str]:
    """서버 자신의 설정(Settings의 mcp_*)이 쓰는 환경 변수 이름. 외부 서버가 읽을 수 없다."""
    from app.config import Settings

    return frozenset(n.upper() for n in Settings.model_fields if n.startswith("mcp_"))


def _parse_server(
    item: object,
    label: str,
    all_names: list,
    seen: set[str],
    lookup: _Lookup,
    errors: list[str],
) -> ExternalServer | None:
    before = len(errors)
    if not isinstance(item, dict):
        errors.append(f"{label}: 항목은 매핑이어야 합니다")
        return None
    name = item.get("name")
    if not isinstance(name, str) or not SERVER_NAME.fullmatch(name):
        errors.append(f"{label}: name은 [a-z0-9-]{{1,32}} 형식이어야 합니다")
        return None
    if name in RESERVED_NAMES:
        errors.append(f"{label}: 예약어 이름({name})은 쓸 수 없습니다")
    if name in seen:
        errors.append(f"{label}: 이름이 중복입니다")
    seen.add(name)
    kind = _kind(item, label, errors)
    if kind is None:
        return None
    unknown = sorted(str(k) for k in set(item) - ALLOWED_KEYS[kind])
    if unknown:
        errors.append(f"{label}: 알 수 없거나 {kind} 서버에 맞지 않는 키 {unknown}")
    allowed = _tools(item, "allowed_tools", name, label, errors, required=True)
    denied = _tools(item, "denied_tools", name, label, errors, required=False)
    overlap = sorted(set(allowed) & set(denied))
    if overlap:
        errors.append(f"{label}: allowed_tools와 denied_tools에 같은 도구가 있습니다 {overlap}")
    command, args, url = "", (), ""
    templates: Mapping = {}
    if kind == "stdio":
        command, args = _stdio(item, label, errors)
        templates = _mapping(item, "env", label, errors, ENV_NAME)
    else:
        url = _http_url(item, label, errors)
        templates = _mapping(item, "headers", label, errors, HEADER_NAME)
    values, secrets = _resolve(name, templates, all_names, label, lookup, errors)
    if len(errors) > before:
        return None
    return ExternalServer(
        name=name,
        kind=kind,
        allowed_tools=tuple(allowed),
        denied_tools=tuple(denied),
        command=command,
        args=args,
        url=url,
        values=values,
        secrets=tuple(secrets),
    )


def _kind(item: dict, label: str, errors: list[str]) -> str | None:
    has_command, has_url = "command" in item, "url" in item
    if has_command == has_url:
        errors.append(f"{label}: stdio(command) 또는 http(url) 중 정확히 하나여야 합니다")
        return None
    return "stdio" if has_command else "http"


def _tools(
    item: dict, key: str, server: str, label: str, errors: list[str], *, required: bool
) -> list[str]:
    tools = item.get(key)
    if tools is None:
        if required:
            errors.append(f"{label}: {key}(허용 도구 목록)는 필수입니다")
        return []
    if not isinstance(tools, list) or (required and not tools):
        errors.append(f"{label}: {key}는 비어 있지 않은 목록이어야 합니다")
        return []
    result: list[str] = []
    for tool in tools:
        if not isinstance(tool, str) or not TOOL_NAME.fullmatch(tool):
            # `*`와 접두사 포함 이름(mcp__…)도 여기서 걸린다
            errors.append(
                f"{label}: {key}의 도구 이름은 [A-Za-z0-9_-]{{1,64}}여야 합니다(`*` 불가)"
            )
            continue
        if len(full_tool_name(server, tool)) > MAX_FULL_NAME:
            errors.append(
                f"{label}: 전체 이름 mcp__{server}__{tool}이 {MAX_FULL_NAME}자를 넘습니다"
            )
        if tool in result:
            errors.append(f"{label}: {key}에 도구 {tool}이 중복입니다")
        result.append(tool)
    return result


def _stdio(item: dict, label: str, errors: list[str]) -> tuple[str, tuple[str, ...]]:
    command = item.get("command")
    if not isinstance(command, str) or not command.startswith("/") or "\x00" in command:
        errors.append(f"{label}: command는 절대 경로 문자열이어야 합니다(PATH 탐색 안 함)")
        command = ""
    args = item.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        errors.append(f"{label}: args는 문자열 목록이어야 합니다")
        return command, ()
    if any("${" in a for a in args):
        errors.append(f"{label}: args에는 비밀 변수를 쓸 수 없습니다(프로세스 목록에 보입니다)")
    return command, tuple(args)


def _http_url(item: dict, label: str, errors: list[str]) -> str:
    url = item.get("url")
    if not isinstance(url, str):
        errors.append(f"{label}: url은 문자열이어야 합니다")
        return ""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        parts, host = None, None
    if parts is None or parts.scheme not in {"http", "https"} or not host:
        errors.append(f"{label}: url은 http(s) 주소여야 합니다")
        return ""
    if "${" in url or parts.username is not None or parts.password is not None:
        errors.append(f"{label}: url에는 비밀(사용자 정보·변수)을 쓸 수 없습니다")
    return url


def _mapping(
    item: dict, key: str, label: str, errors: list[str], key_pattern: re.Pattern
) -> Mapping[str, str]:
    value = item.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label}: {key}는 매핑이어야 합니다")
        return {}
    result: dict[str, str] = {}
    for k, v in value.items():
        if not isinstance(k, str) or not key_pattern.fullmatch(k):
            errors.append(f"{label}: {key}의 이름 형식이 올바르지 않습니다")
        elif not isinstance(v, str) or "\n" in v or "\r" in v or "\x00" in v:
            errors.append(f"{label}: {key}.{k}의 값은 한 줄 문자열이어야 합니다")
        else:
            result[k] = v
    return result


def _resolve(
    server: str,
    templates: Mapping[str, str],
    all_names: list,
    label: str,
    lookup: _Lookup,
    errors: list[str],
) -> tuple[dict[str, str], list[str]]:
    """${MCP_<서버>_<이름>}을 환경 변수 값으로 바꾼다."""
    prefix = variable_prefix(server)
    # 이 서버 접두사로 시작하더라도 더 긴 접두사를 가진 다른 서버의 변수는 쓸 수 없다
    other_prefixes = [
        variable_prefix(n)
        for n in all_names
        if isinstance(n, str) and n != server and SERVER_NAME.fullmatch(n)
    ]
    reserved = _app_variable_names()
    values: dict[str, str] = {}
    secrets: list[str] = []
    for key, template in templates.items():
        failed = False

        def substitute(match: re.Match, key: str = key) -> str:
            nonlocal failed
            var = match.group(1)
            if not VARIABLE_NAME.fullmatch(var) or not var.startswith(prefix) or var == prefix:
                errors.append(
                    f"{label}: {key}의 변수 ${{{var}}}는 접두사 {prefix}로 시작하는 "
                    f"${{{prefix}<이름>}} 형식이어야 합니다"
                )
            elif var in reserved or any(
                var.startswith(p) and len(p) > len(prefix) for p in other_prefixes
            ):
                errors.append(f"{label}: {key}의 변수 ${{{var}}}는 이 서버가 쓸 수 없습니다")
            else:
                value = lookup.get(var)
                if value is not None and value.strip():
                    secrets.append(value)
                    return value
                errors.append(f"{label}: 환경 변수 {var}가 없거나 비어 있습니다")
            failed = True
            return ""

        resolved = VARIABLE.sub(substitute, template)
        if not failed and "${" in resolved:
            errors.append(f"{label}: {key}에 닫히지 않은 ${{ 표기가 있습니다")
        values[key] = resolved
    return values, secrets


LAUNCHER = Path(__file__).with_name("mcp_launch.py")
