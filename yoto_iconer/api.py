"""Minimal Yoto REST client built on urllib."""

from __future__ import annotations

import json
import mimetypes
import secrets
import urllib.error
import urllib.parse
import urllib.request

from . import config


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"Yoto API {status}: {message}")
        self.status = status
        self.message = message


def _request(
    method: str,
    path: str,
    token: str,
    *,
    query: dict | None = None,
    json_body: dict | None = None,
    raw_body: bytes | None = None,
    content_type: str | None = None,
    timeout: int = 60,
):
    url = config.API_BASE + path
    if query:
        url += "?" + urllib.parse.urlencode(query)

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    data = raw_body
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif content_type:
        headers["Content-Type"] = content_type

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        if exc.code == 401:
            detail += "  (token rejected - try `yoto-iconer login` again)"
        raise ApiError(exc.code, detail) from exc

    if not payload:
        return {}
    try:
        return json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError:
        return {"raw": payload.decode("utf-8", "replace")}


# --- content -----------------------------------------------------------------


def list_cards(token: str) -> list[dict]:
    payload = _request("GET", "/content/mine", token)
    if isinstance(payload, list):
        return payload
    return payload.get("cards") or payload.get("content") or []


def get_card(token: str, card_id: str) -> dict:
    payload = _request("GET", f"/content/{card_id}", token)
    if isinstance(payload, dict) and "card" in payload:
        return payload["card"]
    return payload


def update_card(token: str, card: dict) -> dict:
    """Round-trip a full card object back to the API (there is no partial update)."""
    return _request("POST", "/content", token, json_body=card)


# --- icons -------------------------------------------------------------------


def _icons_from(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    for key in ("displayIcons", "icons", "results"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []


def list_public_icons(token: str) -> list[dict]:
    return _icons_from(_request("GET", "/media/displayIcons/user/yoto", token))


def list_user_icons(token: str) -> list[dict]:
    return _icons_from(_request("GET", "/media/displayIcons/user/me", token))


def _multipart(field: str, filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = "----yotoiconer" + secrets.token_hex(16)
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode(),
            f"Content-Type: {mime}\r\n\r\n".encode(),
            data,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    return body, f"multipart/form-data; boundary={boundary}"


def upload_icon(token: str, data: bytes, filename: str, auto_convert: bool = True) -> str:
    """Upload a PNG/GIF as a custom display icon; returns its mediaId."""
    body, content_type = _multipart("file", filename, data)
    payload = _request(
        "POST",
        "/media/displayIcons/user/me/upload",
        token,
        query={"autoConvert": "true" if auto_convert else "false", "filename": filename},
        raw_body=body,
        content_type=content_type,
    )
    icon = payload.get("displayIcon", payload)
    media_id = icon.get("mediaId") or icon.get("id")
    if not media_id:
        raise ApiError(200, f"upload succeeded but no mediaId in response: {payload}")
    return media_id
