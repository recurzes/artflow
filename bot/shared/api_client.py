"""
The bot's only way of talking to the ArtFlow API.

Every endpoint the bot uses has a named method here, so a path or payload shape
lives in one place and tests/bot/test_api_client.py can check each one against
the real API. Cogs never build URLs.
"""
from __future__ import annotations

from typing import Any

import httpx

from shared.config import settings

Json = dict[str, Any]

# Uploads carry up to 25 MB and are forwarded to storage before the API answers.
UPLOAD_TIMEOUT_SECONDS = 120.0

# Which member an action is performed for; the API enforces who may do what.
ACTOR_HEADER = "X-Actor-Discord-Id"
ACTOR_IS_STAFF_HEADER = "X-Actor-Is-Staff"


class APIError(Exception):
    """The API refused the request. `detail` is written for the Discord user."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail

    @property
    def not_found(self) -> bool:
        return self.status == 404


def _detail_from(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(detail, list):  # request validation errors
        parts = [
            f"{'.'.join(str(p) for p in item.get('loc', [])[1:])}: {item.get('msg', '')}"
            for item in detail
            if isinstance(item, dict)
        ]
        if parts:
            return "; ".join(parts)
    if response.status_code >= 500:
        return "Something went wrong on our side. Please try again in a moment"
    return response.reason_phrase or "Request failed"


class APIClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    @classmethod
    def from_settings(cls) -> APIClient:
        return cls(
            httpx.AsyncClient(
                base_url=settings.api_base_url,
                headers={"X-Bot-Secret": settings.bot_secret},
                timeout=httpx.Timeout(15.0),
            )
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def _request(
            self,
            method: str,
            path: str,
            *,
            json: Json | None = None,
            params: Any = None,
            files: Any = None,
            data: Json | None = None,
            timeout: float | None = None,
            actor: int | str | None = None,
            as_staff: bool = False
    ) -> Any:
        headers: dict[str, str] = {}
        if actor is not None:
            headers[ACTOR_HEADER] = str(actor)
        if as_staff:
            headers[ACTOR_IS_STAFF_HEADER] = "true"
        try:
            response = await self._http.request(
                method,
                path,
                json=json,
                params=params,
                files=files,
                data=data,
                headers=headers or None,
                **({"timeout": timeout} if timeout is not None else {})
            )
        except httpx.HTTPError as exc:
            raise APIError(503, "ArtFlow is temporarily unavailable. Please try again") from exc
        if response.status_code >= 400:
            raise APIError(response.status_code, _detail_from(response))
        return response.json()

    async def _upload(
            self,
            path: str,
            filename: str,
            content: bytes,
            content_type: str | None,
            *,
            actor: int | str,
            data: Json | None = None
    ) -> Any:
        """Send a file to the API, which validates, stores and records it."""
        return await self._request(
            "POST",
            path,
            files={"file": (filename, content, content_type or "application/octet-stream")},
            data=data,
            timeout=UPLOAD_TIMEOUT_SECONDS,
            actor=actor
        )

    # ------------------------------------------------------------------ servers
    async def get_server(self, guild_id: int | str) -> Json:
        return await self._request("GET", f"/servers/{guild_id}")

    async def find_server(self, guild_id: int | str) -> Json | None:
        try:
            return await self.get_server(guild_id)
        except APIError as exc:
            if exc.not_found:
                return None
            raise

    async def register_server(self, guild_id: int | str, name: str, settings: Json) -> Json:
        return await self._request(
            "POST",
            "/servers",
            json={"discord_guild_id": str(guild_id), "name": name, "settings": settings},
        )

    async def rename_server(self, guild_id: int | str, name: str) -> Json:
        return await self._request("PATCH", f"/servers/{guild_id}", json={"name": name})

    # -------------------------------------------------------------------- users
    async def upsert_user(
            self,
            discord_user_id: int | str,
            *,
            account_created_at: str | None = None
    ) -> Json:
        return await self._request(
            "POST",
            "/users",
            json={
                "discord_user_id": str(discord_user_id),
                "discord_account_created_at": account_created_at,
            },
        )

    async def get_user(self, discord_user_id: int | str) -> Json:
        return await self._request("GET", f"/users/{discord_user_id}")

    async def submit_age_verification(
            self,
            discord_user_id: int | str,
            *,
            account_created_at: str
    ) -> Json:
        return await self._request(
            "POST",
            "/users/verify-18/submit",
            json={
                "discord_user_id": str(discord_user_id),
                "discord_account_created_at": account_created_at,
            },
        )

    async def approve_age_verification(self, discord_user_id: int | str) -> Json:
        return await self._request(
            "POST",
            "/users/verify-18/approve",
            json={"discord_user_id": str(discord_user_id)},
        )

    # ------------------------------------------------------------------ artists
    async def list_artists(
            self,
            server_id: str,
            *,
            style: str | None = None,
            nsfw_only: bool = False
    ) -> list[Json]:
        params: list[tuple[str, str]] = [("server_id", str(server_id))]
        if style:
            params.append(("styles", style))
        if nsfw_only:
            params.append(("nsfw_only", "true"))
        return await self._request("GET", "/artists", params=params)

    async def get_artist(self, artist_id: str) -> Json:
        return await self._request("GET", f"/artists/{artist_id}")

    async def get_artist_for_member(self, server_id: str, discord_user_id: int | str) -> Json:
        return await self._request(
            "GET",
            f"/artists/by-discord/{discord_user_id}",
            params={"server_id": str(server_id)},
        )

    async def apply_as_artist(
            self,
            *,
            guild_id: int | str,
            discord_user_id: int | str,
            account_created_at: str | None = None,
            **application: Any
    ) -> Json:
        return await self._request(
            "POST",
            "/artists/applications",
            json={
                "discord_guild_id": str(guild_id),
                "discord_user_id": str(discord_user_id),
                "discord_account_created_at": account_created_at,
                **application,
            },
        )

    async def approve_artist(self, artist_id: str, *, moderator: int | str) -> Json:
        return await self._request(
            "POST",
            f"/artists/{artist_id}/approve",
            json={"moderator_discord_user_id": str(moderator)},
        )

    async def reject_artist(self, artist_id: str, *, moderator: int | str, reason: str) -> Json:
        return await self._request(
            "POST",
            f"/artists/{artist_id}/reject",
            json={"moderator_discord_user_id": str(moderator), "reason": reason},
        )

    async def update_artist(self, artist_id: str, *, actor: int | str, **fields: Any) -> Json:
        return await self._request("PATCH", f"/artists/{artist_id}", json=fields, actor=actor)

    async def set_artist_availability(
            self,
            artist_id: str,
            *,
            actor: int | str,
            open: bool
    ) -> Json:
        return await self._request(
            "POST", f"/artists/{artist_id}/availability", json={"open": open}, actor=actor
        )

    async def get_artist_capacity(self, artist_id: str) -> Json:
        return await self._request("GET", f"/artists/{artist_id}/active-commission-count")

    # -------------------------------------------------------------- commissions
    async def get_commission(self, commission_id: str) -> Json:
        return await self._request("GET", f"/commissions/{commission_id}")

    async def get_commission_for_channel(self, channel_id: int | str) -> Json:
        return await self._request("GET", f"/commissions/by-discord-channel/{channel_id}")

    async def get_commission_files(self, commission_id: str) -> Json:
        """Short-lived links: `receipt_url` and `delivery_url` (either may be None)."""
        return await self._request("GET", f"/commissions/{commission_id}/files")

    async def create_commission(
            self,
            *,
            server_id: str,
            artist_id: str,
            client_id: str,
            is_nsfw: bool = False
    ) -> Json:
        return await self._request(
            "POST",
            "/commissions",
            json={
                "server_id": server_id,
                "artist_id": artist_id,
                "client_id": client_id,
                "is_nsfw": is_nsfw,
            },
        )

    async def open_ticket(self, commission_id: str, channel_id: int | str) -> Json:
        return await self._request(
            "POST",
            f"/commissions/{commission_id}/ticket",
            json={"discord_ticket_channel_id": str(channel_id)},
        )

    # Actions on a commission. `actor` is the Discord ID of the member who
    # triggered it; the API decides whether that member may.

    async def submit_intake(self, commission_id: str, notes: str, *, actor: int | str) -> Json:
        return await self._request(
            "POST", f"/commissions/{commission_id}/intake", json={"notes": notes}, actor=actor
        )

    async def quote(
            self,
            commission_id: str,
            *,
            actor: int | str,
            price_php: str,
            revisions_allowed: int = 2
    ) -> Json:
        return await self._request(
            "POST",
            f"/commissions/{commission_id}/quote",
            json={
                "quoted_price_php": price_php,
                "currency_used": "PHP",
                "revisions_allowed": revisions_allowed,
            },
            actor=actor,
        )

    async def counter_offer(self, commission_id: str, notes: str, *, actor: int | str) -> Json:
        return await self._request(
            "POST",
            f"/commissions/{commission_id}/counter-offer",
            json={"notes": notes},
            actor=actor,
        )

    async def accept_quote(self, commission_id: str, *, actor: int | str) -> Json:
        return await self._request(
            "POST", f"/commissions/{commission_id}/accept-quote", actor=actor
        )

    async def accept_tos(self, commission_id: str, tos_hash: str, *, actor: int | str) -> Json:
        return await self._request(
            "POST",
            f"/commissions/{commission_id}/tos-accept",
            json={"tos_version_hash": tos_hash},
            actor=actor,
        )

    async def upload_receipt(
            self,
            commission_id: str,
            *,
            actor: int | str,
            filename: str,
            content: bytes,
            content_type: str | None
    ) -> Json:
        return await self._upload(
            f"/commissions/{commission_id}/receipt", filename, content, content_type, actor=actor
        )

    async def confirm_payment(self, commission_id: str, *, actor: int | str) -> Json:
        return await self._request(
            "POST", f"/commissions/{commission_id}/confirm-payment", actor=actor
        )

    async def post_wip(
            self,
            commission_id: str,
            *,
            actor: int | str,
            filename: str,
            content: bytes,
            content_type: str | None,
            note: str | None = None
    ) -> Json:
        return await self._upload(
            f"/commissions/{commission_id}/wip-update",
            filename,
            content,
            content_type,
            actor=actor,
            data={"note": note} if note else None
        )

    async def deliver(
            self,
            commission_id: str,
            *,
            actor: int | str,
            filename: str,
            content: bytes,
            content_type: str | None
    ) -> Json:
        return await self._upload(
            f"/commissions/{commission_id}/deliver", filename, content, content_type, actor=actor
        )

    async def complete(self, commission_id: str, *, actor: int | str) -> Json:
        return await self._request("POST", f"/commissions/{commission_id}/complete", actor=actor)

    async def cancel(
            self,
            commission_id: str,
            *,
            actor: int | str,
            as_staff: bool = False
    ) -> Json:
        """`as_staff`: the actor is a moderator of the server (only the bot can tell)."""
        return await self._request(
            "POST", f"/commissions/{commission_id}/cancel", actor=actor, as_staff=as_staff
        )

    async def review(
            self,
            commission_id: str,
            *,
            actor: int | str,
            rating: int,
            body: str | None = None
    ) -> Json:
        return await self._request(
            "POST",
            f"/commissions/{commission_id}/review",
            json={"rating": rating, "body": body, "is_public": True},
            actor=actor,
        )

    # ------------------------------------------------------------------- sweeps
    async def sweep_expire_unpaid(self) -> list[Json]:
        """Cancel unpaid commissions past their deadline; returns the ones cancelled."""
        return await self._request("POST", "/commissions/sweeps/expire-unpaid")

    async def sweep_auto_accept(self) -> list[Json]:
        """Complete deliveries nobody responded to; returns the ones completed."""
        return await self._request("POST", "/commissions/sweeps/auto-accept")

    async def sweep_payment_reminders(self) -> list[Json]:
        """Commissions whose payment deadline is near; each is returned only once."""
        return await self._request("POST", "/commissions/sweeps/payment-reminders")

    # ----------------------------------------------------------------- disputes
    async def open_dispute(
            self,
            commission_id: str,
            *,
            raised_by: int | str,
            reason: str
    ) -> Json:
        return await self._request(
            "POST",
            "/disputes",
            json={
                "commission_id": commission_id,
                "raised_by_discord_user_id": str(raised_by),
                "reason": reason,
            },
        )

    async def get_dispute_for_commission(self, commission_id: str) -> Json:
        return await self._request("GET", f"/disputes/by-commission/{commission_id}")

    async def resolve_dispute(
            self,
            dispute_id: str,
            *,
            resolved_by: int | str,
            resolution: str,
            outcome: str
    ) -> Json:
        return await self._request(
            "PATCH",
            f"/disputes/{dispute_id}/resolve",
            json={
                "resolution": resolution,
                "set_commission_status": outcome,
                "resolved_by_discord_user_id": str(resolved_by),
            },
        )

    # -------------------------------------------------------------------- admin
    async def admin_stats(self, server_id: str) -> Json:
        return await self._request("GET", "/admin/stats", params={"server_id": server_id})

    async def admin_artists(self, server_id: str, *, limit: int = 25, offset: int = 0) -> Json:
        return await self._request(
            "GET",
            "/admin/artists",
            params={"server_id": server_id, "limit": limit, "offset": offset},
        )

    async def admin_commission_summary(self, server_id: str) -> Json:
        return await self._request(
            "GET", "/admin/commissions/summary", params={"server_id": server_id}
        )
