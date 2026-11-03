"""외부 MCP 설정 파일 로더·검증(M5-12). 규칙별 허용·거부와 파일 권한 검사, 서버 시작 거부."""

import logging
import os
from pathlib import Path

import pytest
import yaml

from app.external_mcp import (
    ExternalMcpConfigError,
    check_file_permissions,
    load_external_mcp,
    log_address,
    variable_prefix,
)
from app.main import create_app

ENV = {
    "MCP_FOO_API_KEY": "foo-secret-value",
    "MCP_FOO_BAR_TOKEN": "foobar-secret-value",
    "MCP_BAR_TOKEN": "bar-secret-value",
}


def stdio(name="foo", **extra):
    entry = {"name": name, "command": "/usr/bin/true", "allowed_tools": ["search"]}
    entry.update(extra)
    return entry


def http(name="foo", **extra):
    entry = {"name": name, "url": "https://mcp.example.com/v1", "allowed_tools": ["search"]}
    entry.update(extra)
    return entry


@pytest.fixture
def write(tmp_path):
    """설정 파일을 0600 파일·0700 폴더에 쓴다."""
    folder = tmp_path / "cfg"
    folder.mkdir(mode=0o700)
    folder.chmod(0o700)

    def _write(servers, *, raw: str | None = None) -> Path:
        path = folder / "mcp-servers.yaml"
        path.write_text(raw if raw is not None else yaml.safe_dump({"servers": servers}))
        path.chmod(0o600)
        return path

    return _write


def load(write, servers, environ=ENV, **kw):
    return load_external_mcp(write(servers, **kw), environ)


def rejects(write, servers, fragment, environ=ENV):
    with pytest.raises(ExternalMcpConfigError) as excinfo:
        load(write, servers, environ)
    assert fragment in str(excinfo.value)
    return str(excinfo.value)


# 파일 있음·없음


def test_missing_file_means_no_external_servers(tmp_path):
    assert not load_external_mcp(tmp_path / "nope.yaml", {})
    assert not load_external_mcp(None, {})


def test_empty_file_and_empty_list_mean_no_servers(write):
    assert not load_external_mcp(write([], raw=""), {})
    assert not load_external_mcp(write([]), {})


def test_valid_stdio_and_http_servers_load(write):
    mcp = load(
        write,
        [
            stdio(args=["--ro"], env={"KEY": "${MCP_FOO_API_KEY}", "REGION": "kr"}),
            http("bar", headers={"Authorization": "Bearer ${MCP_BAR_TOKEN}"}),
        ],
    )
    foo, bar = mcp.servers
    assert (foo.kind, foo.command, foo.args) == ("stdio", "/usr/bin/true", ("--ro",))
    assert dict(foo.values) == {"KEY": "foo-secret-value", "REGION": "kr"}
    assert (bar.kind, bar.url) == ("http", "https://mcp.example.com/v1")
    assert dict(bar.values) == {"Authorization": "Bearer bar-secret-value"}
    assert mcp.allowed_tool_names() == ["mcp__foo__search", "mcp__bar__search"]


def test_the_committed_example_file_is_valid(tmp_path):
    example = Path(__file__).parent.parent / "mcp-servers.example.yaml"
    folder = tmp_path / "x"
    folder.mkdir(mode=0o700)
    copy = folder / "mcp-servers.yaml"
    copy.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    copy.chmod(0o600)
    env = {"MCP_EXAMPLE_SEARCH_API_KEY": "k-1", "MCP_EXAMPLE_DOCS_TOKEN": "t-1"}
    mcp = load_external_mcp(copy, env)
    assert [s.name for s in mcp.servers] == ["example-search", "example-docs"]
    assert "mcp__example-search__delete_index" in mcp.denied_tool_names()


# 이름


@pytest.mark.parametrize("name", ["a", "a-b-9", "x" * 32])
def test_valid_server_names(write, name):
    env = {variable_prefix(name) + "T": "v"}
    assert load(write, [stdio(name, allowed_tools=["t"])], env).servers[0].name == name


@pytest.mark.parametrize("name", ["", "Foo", "foo_bar", "foo.bar", "x" * 33, "한글", " foo", 7])
def test_bad_server_names_rejected(write, name):
    rejects(write, [stdio(name)], "name은 [a-z0-9-]")


@pytest.mark.parametrize("name", ["trailtalk", "servers"])
def test_reserved_names_rejected(write, name):
    rejects(write, [stdio(name)], "예약어")


def test_duplicate_names_rejected(write):
    rejects(write, [stdio("foo"), http("foo")], "중복")


# 허용 도구


def test_allowed_tools_required(write):
    entry = stdio()
    del entry["allowed_tools"]
    rejects(write, [entry], "allowed_tools(허용 도구 목록)는 필수")


@pytest.mark.parametrize("tools", [[], "search", {"a": 1}])
def test_allowed_tools_must_be_a_non_empty_list(write, tools):
    rejects(write, [stdio(allowed_tools=tools)], "allowed_tools")


@pytest.mark.parametrize("tool", ["*", "mcp__foo__*", "se arch", "a/b", "", "x" * 65, 5])
def test_bad_tool_names_rejected(write, tool):
    rejects(write, [stdio(name="f", allowed_tools=[tool])], "도구 이름은")


def test_wildcard_is_rejected_even_among_valid_tools(write):
    rejects(write, [stdio(allowed_tools=["search", "*"])], "`*` 불가")


def test_full_name_over_64_chars_rejected_and_64_accepted(write):
    server = "s" * 32
    ok_tool = "t" * (64 - len(f"mcp__{server}__"))
    env = {variable_prefix(server) + "X": "v"}
    assert load(write, [stdio(server, allowed_tools=[ok_tool])], env)
    rejects(write, [stdio(server, allowed_tools=[ok_tool + "t"])], "64자를 넘습니다", env)


def test_tool_names_may_contain_double_underscore(write):
    assert load(write, [stdio(allowed_tools=["a__b"])]).allowed_tool_names() == ["mcp__foo__a__b"]


def test_denied_tools_optional_and_must_not_overlap(write):
    mcp = load(write, [stdio(denied_tools=["drop"])])
    assert mcp.denied_tool_names() == ["mcp__foo__drop"]
    rejects(write, [stdio(denied_tools=["search"])], "같은 도구")


# 종류별 필드


def test_exactly_one_of_command_or_url(write):
    both = stdio(url="https://x.example.com")
    rejects(write, [both], "정확히 하나")
    rejects(write, [{"name": "foo", "allowed_tools": ["t"]}], "정확히 하나")


def test_unknown_and_mismatched_keys_rejected(write):
    rejects(write, [stdio(headers={"A": "b"})], "알 수 없거나")
    rejects(write, [http(env={"A": "b"})], "알 수 없거나")
    rejects(write, [stdio(shell=True)], "알 수 없거나")


@pytest.mark.parametrize("command", ["python", "./server", "~/bin/x", "", "npx", 5, None])
def test_command_must_be_an_absolute_path(write, command):
    rejects(write, [stdio(command=command)], "절대 경로")


@pytest.mark.parametrize("args", ["--ro", [1, 2], [["a"]], {"a": 1}])
def test_args_must_be_a_list_of_strings(write, args):
    rejects(write, [stdio(args=args)], "args는 문자열 목록")


def test_secret_in_args_rejected(write):
    rejects(write, [stdio(args=["--key=${MCP_FOO_API_KEY}"])], "args에는 비밀 변수")


@pytest.mark.parametrize(
    "url",
    ["ftp://x.example.com", "mcp.example.com", "https://", "file:///etc/passwd"],
)
def test_url_must_be_http_or_https(write, url):
    rejects(write, [http(url=url)], "http(s) 주소")


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pw@mcp.example.com/",
        "https://tok@mcp.example.com/",
        "https://mcp.example.com/v1?key=${MCP_FOO_API_KEY}",
    ],
)
def test_url_must_not_carry_secrets(write, url):
    rejects(write, [http(url=url)], "url에는 비밀")


def test_log_address_drops_query_userinfo_and_fragment():
    assert (
        log_address("https://u:p@h.example.com:8443/a/b?key=1#x")
        == "https://h.example.com:8443/a/b"
    )


def test_loading_logs_address_without_query_or_secret(write, caplog):
    caplog.set_level(logging.INFO, logger="trailtalk.external_mcp")
    entry = http(url="https://mcp.example.com/v1?mode=ro", headers={"X": "${MCP_FOO_API_KEY}"})
    load(write, [entry])
    assert "https://mcp.example.com/v1" in caplog.text
    assert "mode=ro" not in caplog.text and "foo-secret-value" not in caplog.text


# 비밀 변수


def test_variable_prefix():
    assert variable_prefix("my-server") == "MCP_MY_SERVER_"


def test_variable_with_own_prefix_is_substituted_in_the_middle_of_a_value(write):
    mcp = load(write, [http(headers={"Authorization": "Bearer ${MCP_FOO_API_KEY} x"})])
    assert mcp.servers[0].values["Authorization"] == "Bearer foo-secret-value x"
    assert "foo-secret-value" in mcp.redact_values()


@pytest.mark.parametrize(
    "variable",
    [
        "OPENAI_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "MCP_BAR_TOKEN",  # 다른 서버의 변수
        "MCP_FOO_",  # 이름이 없다
        "mcp_foo_api_key",
        "MCP_FOO_A-B",
        "",
    ],
)
def test_variables_outside_own_prefix_rejected(write, variable):
    other = http("bar", headers={"X": "${MCP_BAR_TOKEN}"})
    rejects(write, [stdio(env={"K": "${" + variable + "}"}), other], "접두사")


def test_variable_of_a_longer_named_server_is_rejected(write):
    """foo의 접두사 MCP_FOO_로 시작하지만 서버 foo-bar의 변수(MCP_FOO_BAR_TOKEN)는 읽을 수 없다."""
    rejects(
        write,
        [stdio("foo", env={"K": "${MCP_FOO_BAR_TOKEN}"}), stdio("foo-bar")],
        "쓸 수 없습니다",
    )
    assert load(write, [stdio("foo-bar", env={"K": "${MCP_FOO_BAR_TOKEN}"}), stdio("foo")])


@pytest.mark.parametrize(
    "server, variable",
    [
        ("owner", "MCP_OWNER_PASSWORD"),
        ("public", "MCP_PUBLIC_URL"),
        ("allowed", "MCP_ALLOWED_REDIRECTS"),
        ("call", "MCP_CALL_LOG"),
    ],
)
def test_the_apps_own_mcp_settings_are_not_readable(write, server, variable):
    env = {variable: "app-own-secret"}
    entry = stdio(server, env={"K": "${" + variable + "}"})
    text = rejects(write, [entry], "쓸 수 없습니다", env)
    assert "app-own-secret" not in text


@pytest.mark.parametrize("environ", [{}, {"MCP_FOO_API_KEY": ""}, {"MCP_FOO_API_KEY": "  "}])
def test_missing_or_blank_variable_rejected_without_leaking(write, environ):
    text = rejects(write, [stdio(env={"K": "${MCP_FOO_API_KEY}"})], "MCP_FOO_API_KEY", environ)
    assert "없거나 비어" in text


def test_unclosed_variable_marker_rejected(write):
    rejects(write, [stdio(env={"K": "${MCP_FOO_API_KEY"})], "닫히지 않은")


def test_fixed_values_are_written_as_they_are(write):
    mcp = load(write, [stdio(env={"REGION": "kr", "PRICE": "$5"})], {})
    assert dict(mcp.servers[0].values) == {"REGION": "kr", "PRICE": "$5"}


def test_env_and_header_shapes_are_checked(write):
    rejects(write, [stdio(env={"1BAD": "x"})], "이름 형식")
    rejects(write, [stdio(env={"K": 5})], "한 줄 문자열")
    rejects(write, [stdio(env={"K": "a\nb"})], "한 줄 문자열")
    rejects(write, [http(headers={"Bad Header": "x"})], "이름 형식")
    rejects(write, [stdio(env=["A=b"])], "매핑")


def test_redact_values_cover_secrets_and_whole_values_but_not_short_fixed_ones(write):
    mcp = load(
        write,
        [
            stdio(env={"K": "${MCP_FOO_API_KEY}", "FLAG": "1", "MODE": "readonly-mode"}),
            http("bar", headers={"Authorization": "Bearer ${MCP_BAR_TOKEN}"}),
        ],
    )
    values = mcp.redact_values()
    assert {
        "foo-secret-value",
        "readonly-mode",
        "Bearer bar-secret-value",
        "bar-secret-value",
    } <= set(values)
    assert "1" not in values


def test_all_errors_are_listed_together(write):
    text = rejects(write, [stdio("Bad"), stdio("trailtalk"), stdio(command="x")], "servers[0]")
    assert "servers[1]" in text and "servers[2]" in text


# 구조


@pytest.mark.parametrize(
    "raw",
    ["servers: 5", "- a\n- b", "foo: []", "servers: []\nextra: 1", "servers: [1]", "{{{"],
)
def test_bad_document_shapes_rejected(write, raw):
    with pytest.raises(ExternalMcpConfigError):
        load_external_mcp(write([], raw=raw), ENV)


def test_yaml_error_message_has_no_file_content(write):
    path = write([], raw="servers: [\n  secret-token-xyz: : :")
    with pytest.raises(ExternalMcpConfigError) as excinfo:
        load_external_mcp(path, ENV)
    assert "secret-token-xyz" not in str(excinfo.value)


# 파일·폴더 권한


def test_group_or_other_writable_file_rejected(write):
    path = write([stdio()])
    for mode in (0o620, 0o602, 0o666):
        path.chmod(mode)
        with pytest.raises(ExternalMcpConfigError, match="쓸 수 있습니다"):
            load_external_mcp(path, ENV)


def test_group_or_other_writable_folder_rejected(write):
    path = write([stdio()])
    path.parent.chmod(0o770)
    try:
        with pytest.raises(ExternalMcpConfigError, match="폴더"):
            load_external_mcp(path, ENV)
    finally:
        path.parent.chmod(0o700)


def test_symlinked_file_rejected(write, tmp_path):
    real = write([stdio()])
    link = real.parent / "link.yaml"
    link.symlink_to(real)
    with pytest.raises(ExternalMcpConfigError, match="심볼릭 링크"):
        load_external_mcp(link, ENV)


def test_symlinked_folder_rejected(write, tmp_path):
    real = write([stdio()])
    folder_link = tmp_path / "folder-link"
    folder_link.symlink_to(real.parent)
    with pytest.raises(ExternalMcpConfigError, match="심볼릭 링크"):
        load_external_mcp(folder_link / real.name, ENV)


def test_dangling_symlink_is_not_silently_ignored(tmp_path):
    folder = tmp_path / "d"
    folder.mkdir(mode=0o700)
    (folder / "mcp-servers.yaml").symlink_to(folder / "missing")
    with pytest.raises(ExternalMcpConfigError):
        load_external_mcp(folder / "mcp-servers.yaml", ENV)


def test_file_owned_by_another_user_rejected(write, monkeypatch):
    path = write([stdio()])
    monkeypatch.setattr(os, "geteuid", lambda: 99999)
    problems = check_file_permissions(path)
    assert any("소유자" in p for p in problems)


def test_readable_by_others_is_only_a_warning(write, caplog):
    path = write([stdio()])
    path.chmod(0o644)
    caplog.set_level(logging.WARNING, logger="trailtalk.external_mcp")
    assert load_external_mcp(path, ENV)
    assert "읽을 수 있습니다" in caplog.text


def test_private_file_does_not_warn(write, caplog):
    caplog.set_level(logging.WARNING, logger="trailtalk.external_mcp")
    load_external_mcp(write([stdio()]), ENV)
    assert not caplog.records


# 서버 시작


def test_server_refuses_to_start_with_a_bad_file(make_settings, write):
    path = write([stdio("trailtalk")])
    with pytest.raises(ExternalMcpConfigError, match="예약어"):
        create_app(make_settings(mcp_servers_path=path))


def test_server_refuses_to_start_when_a_secret_variable_is_missing(
    make_settings, write, monkeypatch
):
    monkeypatch.delenv("MCP_FOO_API_KEY", raising=False)
    path = write([stdio(env={"K": "${MCP_FOO_API_KEY}"})])
    with pytest.raises(ExternalMcpConfigError, match="MCP_FOO_API_KEY"):
        create_app(make_settings(mcp_servers_path=path))


def test_server_refuses_to_start_with_a_writable_file(make_settings, write):
    path = write([stdio()])
    path.chmod(0o666)
    with pytest.raises(ExternalMcpConfigError, match="쓸 수 있습니다"):
        create_app(make_settings(mcp_servers_path=path))


def test_server_starts_with_a_valid_file_and_without_one(make_settings, write, tmp_path):
    app = create_app(make_settings(mcp_servers_path=write([stdio()])))
    assert [s.name for s in app.state.external_mcp.servers] == ["foo"]
    app = create_app(make_settings(mcp_servers_path=tmp_path / "none.yaml"))
    assert not app.state.external_mcp


def test_secret_variables_come_from_the_process_environment(make_settings, write, monkeypatch):
    monkeypatch.setenv("MCP_FOO_API_KEY", "from-process-env")
    app = create_app(
        make_settings(mcp_servers_path=write([stdio(env={"K": "${MCP_FOO_API_KEY}"})]))
    )
    assert app.state.external_mcp.servers[0].values["K"] == "from-process-env"


def test_non_string_url_rejected(write):
    rejects(write, [http(url=7)], "url은 문자열")
