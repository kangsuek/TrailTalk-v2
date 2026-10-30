"""단일 소유자 OAuth 2.1 인가 서버(Claude 앱 연계). SDK(mcp.server.auth)의 핸들러가 프로토콜
(PKCE S256, 코드 교환, 갱신, 폐기)을 처리하고, 이 모듈은 저장소와 정책(허용 리다이렉트,
state·resource 검증, 토큰 수명, 회전, DCR 상한)을 맡는다.
`trailTalk-MCP/app/oauth.py`를 v2 규약으로 옮겼다.

- 등록은 DCR(Claude가 자동 등록). redirect_uri는 허용 목록에 있는 것만 받는다.
- /authorize는 자동 승인하지 않는다. 소유자 비밀번호 로그인(login.py)을 거쳐야 코드가 나온다.
- 코드와 토큰은 SHA-256 해시만 DB에 둔다. 리프레시는 쓸 때마다 회전한다.
"""

import hashlib
import json
import secrets
import time
from collections.abc import Callable
from typing import Any

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import OAuthClient, OAuthCode, OAuthPending
from app.db.models import OAuthToken as TokenRow

SCOPE_MCP = "mcp"
SCOPES = [SCOPE_MCP, "offline_access"]
ACCESS_TTL_S = 3600
REFRESH_TTL_S = 30 * 24 * 3600
CODE_TTL_S = 300
PENDING_TTL_S = 600
MAX_PENDING = 100  # 로그인 대기 요청 상한(익명 /authorize가 DB를 채우지 못하게)
SUBJECT = "owner"


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class OwnerOAuthProvider:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        resource_url: str,
        allowed_redirects: tuple[str, ...],
        max_clients: int = 50,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.resource_url = resource_url
        self.allowed_redirects = allowed_redirects
        self.max_clients = max_clients
        # 시험에서 시계를 바꿔 끼울 수 있게 늦게 묶는다
        self.now = now or (lambda: time.time())

    # --- 클라이언트 등록(DCR) ---------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with self.session_factory() as db:
            row = await db.get(OAuthClient, client_id)
        return OAuthClientInformationFull.model_validate_json(row.info) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(u) for u in client_info.redirect_uris or []]
        if not uris or any(u not in self.allowed_redirects for u in uris):
            raise RegistrationError(
                error="invalid_redirect_uri", error_description="허용되지 않은 redirect_uri입니다."
            )
        # Claude가 어떤 scope로 등록하든 /authorize가 거부하지 않게, 우리 범위를 항상 더한다
        requested = (client_info.scope or "").split()
        client_info.scope = " ".join(dict.fromkeys([*SCOPES, *requested]))
        async with self.session_factory() as db:
            await self._prune_clients(db)
            db.add(OAuthClient(client_id=client_info.client_id, info=client_info.model_dump_json()))
            await db.commit()

    async def _prune_clients(self, db: AsyncSession) -> None:
        """익명 등록이 DB를 채우지 못하게, 한도를 넘으면 토큰 없는 오래된 클라이언트부터 지운다."""
        count = (await db.execute(select(func.count()).select_from(OAuthClient))).scalar_one()
        if count < self.max_clients:
            return
        in_use = select(TokenRow.client_id).distinct()
        stale = (
            await db.scalars(
                select(OAuthClient.client_id)
                .where(OAuthClient.client_id.not_in(in_use))
                .order_by(OAuthClient.created_at)
                .limit(count - self.max_clients + 1)
            )
        ).all()
        if not stale:
            raise RegistrationError(
                error="invalid_client_metadata", error_description="등록 한도에 도달했습니다."
            )
        await db.execute(delete(OAuthClient).where(OAuthClient.client_id.in_(stale)))

    # --- 인가: 로그인 대기 → 코드 발급 ------------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """코드를 바로 주지 않고 로그인 요청만 저장한다. 돌려주는 URL은 로그인 페이지다."""
        if str(params.redirect_uri) not in self.allowed_redirects:
            raise AuthorizeError(
                error="invalid_request", error_description="허용되지 않은 redirect_uri"
            )
        if not params.state:
            raise AuthorizeError(error="invalid_request", error_description="state가 필요합니다")
        if params.resource is not None and params.resource != self.resource_url:
            raise AuthorizeError(error="invalid_target", error_description="알 수 없는 resource")
        pending_id = secrets.token_urlsafe(32)
        data = {
            "state": params.state,
            "scopes": list(dict.fromkeys([SCOPE_MCP, *(params.scopes or [])])),  # mcp는 항상 포함
            "code_challenge": params.code_challenge,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
        }
        async with self.session_factory() as db:
            await db.execute(delete(OAuthPending).where(OAuthPending.expires_at < self.now()))
            waiting = (
                await db.execute(select(func.count()).select_from(OAuthPending))
            ).scalar_one()
            if waiting >= MAX_PENDING:
                raise AuthorizeError(
                    error="temporarily_unavailable",
                    error_description="로그인 대기 요청이 너무 많습니다. 잠시 뒤에 다시 하세요.",
                )
            db.add(
                OAuthPending(
                    id=pending_id,
                    client_id=client.client_id,
                    params=json.dumps(data),
                    expires_at=self.now() + PENDING_TTL_S,
                )
            )
            await db.commit()
        return f"/login?req={pending_id}"

    async def pending_request(self, pending_id: str) -> dict[str, Any] | None:
        """로그인 화면에 보일 정보. 없거나 만료되면 None."""
        async with self.session_factory() as db:
            row = await db.get(OAuthPending, pending_id)
        if row is None or row.expires_at < self.now():
            return None
        info = await self.get_client(row.client_id)
        data = json.loads(row.params)
        data["client_name"] = (info.client_name if info else None) or row.client_id
        return data

    async def complete_login(self, pending_id: str) -> str | None:
        """소유자 확인이 끝난 요청에 코드를 발급하고 클라이언트로 돌아갈 URL을 돌려준다."""
        async with self.session_factory() as db:
            row = await db.get(OAuthPending, pending_id)
            if row is None or row.expires_at < self.now():
                return None
            # 한 번만 쓸 수 있게 먼저 지운다(동시 제출 방지)
            deleted = await db.execute(delete(OAuthPending).where(OAuthPending.id == pending_id))
            if deleted.rowcount != 1:
                return None
            data = json.loads(row.params)
            code = secrets.token_urlsafe(32)
            db.add(
                OAuthCode(
                    code_hash=hash_token(code),
                    data=json.dumps({**data, "client_id": row.client_id}),
                    expires_at=self.now() + CODE_TTL_S,
                )
            )
            await db.execute(delete(OAuthCode).where(OAuthCode.expires_at < self.now()))
            await db.commit()
        return construct_redirect_uri(data["redirect_uri"], code=code, state=data["state"])

    # --- 토큰 -------------------------------------------------------------------------------

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        async with self.session_factory() as db:
            row = await db.get(OAuthCode, hash_token(authorization_code))
        if row is None:
            return None
        data = json.loads(row.data)
        if data["client_id"] != client.client_id:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=data["scopes"],
            expires_at=row.expires_at,
            client_id=data["client_id"],
            code_challenge=data["code_challenge"],
            redirect_uri=data["redirect_uri"],
            redirect_uri_provided_explicitly=data["redirect_uri_provided_explicitly"],
            resource=self.resource_url,
            subject=SUBJECT,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        async with self.session_factory() as db:
            deleted = await db.execute(
                delete(OAuthCode).where(OAuthCode.code_hash == hash_token(authorization_code.code))
            )
            if deleted.rowcount != 1:  # 이미 쓴 코드(동시 교환 포함)
                raise TokenError(error="invalid_grant", error_description="이미 사용한 코드입니다.")
            token = await self._issue(db, client.client_id, authorization_code.scopes)
            await db.commit()
        return token

    async def _issue(self, db: AsyncSession, client_id: str, scopes: list[str]) -> OAuthToken:
        now = self.now()
        await db.execute(delete(TokenRow).where(TokenRow.expires_at < now))
        family = secrets.token_hex(16)
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        for kind, value, ttl in (
            ("access", access, ACCESS_TTL_S),
            ("refresh", refresh, REFRESH_TTL_S),
        ):
            db.add(
                TokenRow(
                    token_hash=hash_token(value),
                    kind=kind,
                    family_id=family,
                    client_id=client_id,
                    scopes=" ".join(scopes),
                    resource=self.resource_url,
                    expires_at=now + ttl,
                )
            )
        return OAuthToken(
            access_token=access,
            expires_in=ACCESS_TTL_S,
            scope=" ".join(scopes),
            refresh_token=refresh,
        )

    async def _load(self, token: str, kind: str, client_id: str | None = None) -> TokenRow | None:
        async with self.session_factory() as db:
            row = await db.get(TokenRow, hash_token(token))
        if row is None or row.kind != kind or row.expires_at < self.now():
            return None
        if client_id is not None and row.client_id != client_id:
            return None
        return row

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        row = await self._load(refresh_token, "refresh", client.client_id)
        if row is None:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=row.client_id,
            scopes=row.scopes.split(),
            expires_at=int(row.expires_at),
            resource=row.resource,
            subject=SUBJECT,
        )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        if not set(scopes) <= set(refresh_token.scopes):
            raise TokenError(
                error="invalid_scope", error_description="처음 허용된 범위를 넘습니다."
            )
        async with self.session_factory() as db:
            row = await db.get(TokenRow, hash_token(refresh_token.token))
            if row is None:
                raise TokenError(error="invalid_grant", error_description="이미 회전된 토큰입니다.")
            deleted = await db.execute(delete(TokenRow).where(TokenRow.family_id == row.family_id))
            if deleted.rowcount < 1:
                raise TokenError(error="invalid_grant", error_description="이미 회전된 토큰입니다.")
            token = await self._issue(db, client.client_id, scopes or refresh_token.scopes)
            await db.commit()
        return token

    async def load_access_token(self, token: str) -> AccessToken | None:
        row = await self._load(token, "access")
        if row is None:
            return None
        return AccessToken(
            token=token,
            client_id=row.client_id,
            scopes=row.scopes.split(),
            expires_at=int(row.expires_at),
            resource=row.resource,
            subject=SUBJECT,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        async with self.session_factory() as db:
            row = await db.get(TokenRow, hash_token(token.token))
            if row is not None:
                await db.execute(delete(TokenRow).where(TokenRow.family_id == row.family_id))
            await db.commit()


async def revoke_all(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """발급한 토큰·인가 코드·로그인 대기 요청과 등록 클라이언트를 모두 지운다(분실 대응).
    지운 토큰 수를 돌려준다. 앱은 다시 연결해야 한다."""
    async with session_factory() as db:
        count = (await db.execute(select(func.count()).select_from(TokenRow))).scalar_one()
        for table in (TokenRow, OAuthCode, OAuthPending, OAuthClient):
            await db.execute(delete(table))
        await db.commit()
    return count


__all__ = ["OwnerOAuthProvider", "hash_token", "revoke_all"]
