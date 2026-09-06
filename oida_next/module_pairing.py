"""One-shot local credential proof; no module credentials leave this request."""

import json

import httpx

from .module_client import ModuleConfig


class PairingDenied(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message


async def pair_account(
    config: ModuleConfig, email: str, password: str, identity_token: str, transport=None
):
    async with httpx.AsyncClient(
        transport=transport, timeout=10, follow_redirects=False, trust_env=False
    ) as client:

        async def post(path, body):
            async with client.stream(
                "POST", config.origin.rstrip("/") + path, json=body
            ) as response:
                content = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    content.extend(chunk)
                    if len(content) > 32768:
                        raise PairingDenied(502, "Invalid module response")
                if response.status_code in {401, 403}:
                    raise PairingDenied(403, "Module credentials or identity denied")
                if response.status_code == 409:
                    raise PairingDenied(409, "Account is already linked to a different identity")
                if response.status_code == 429:
                    raise PairingDenied(429, "Please wait before retrying module pairing")
                if response.status_code != 200:
                    raise PairingDenied(502, "Module pairing unavailable")
                return json.loads(content)

        try:
            user = await post("/api/auth/login", {"email": email, "password": password})
            if not isinstance(user, dict) or user.get("must_change_password") is not False:
                raise PairingDenied(403, "Change your module password before pairing")
            result = await post(
                "/api/auth/link-identity",
                {
                    "current_password": password,
                    "identity_token": identity_token,
                },
            )
            if not isinstance(result, dict) or result.get("linked") is not True:
                raise PairingDenied(502, "Invalid module pairing response")
            return {"linked": True, "module": config.name}
        except (httpx.HTTPError, ValueError, TypeError):
            raise PairingDenied(502, "Module pairing request failed") from None
        finally:
            # Revoke the temporary login's refresh token even on denied pairing.
            # Cookies stay in this short-lived client, never in the browser.
            if client.cookies:
                try:
                    async with client.stream(
                        "POST", config.origin.rstrip("/") + "/api/auth/logout"
                    ):
                        pass
                except httpx.HTTPError:
                    pass
            client.cookies.clear()
