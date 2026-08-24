"""OAuth2 PKCE login for a public client, plus silent token refresh."""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from . import config


class AuthError(Exception):
    pass


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for the S256 method."""
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def authorize_url(client_id: str, challenge: str, state: str) -> str:
    query = urllib.parse.urlencode(
        {
            "audience": config.AUDIENCE,
            "scope": config.SCOPES,
            "response_type": "code",
            "client_id": client_id,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "redirect_uri": config.REDIRECT_URI,
            "state": state,
        }
    )
    return f"{config.AUTH_BASE}/authorize?{query}"


def _post_token(payload: dict) -> dict:
    body = urllib.parse.urlencode(payload).encode("ascii")
    req = urllib.request.Request(
        f"{config.AUTH_BASE}/oauth/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise AuthError(f"token request failed ({exc.code}): {detail}") from exc


# --- token storage -----------------------------------------------------------


def load_tokens() -> dict:
    p = config.tokens_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def save_tokens(tokens: dict) -> None:
    config.ensure_home()
    p = config.tokens_path()
    p.write_text(json.dumps(tokens, indent=2) + "\n")
    os.chmod(p, 0o600)


def _store_grant(grant: dict, previous: dict | None = None) -> dict:
    previous = previous or {}
    tokens = {
        "access_token": grant["access_token"],
        # Auth0 rotates refresh tokens; keep the old one if none came back.
        "refresh_token": grant.get("refresh_token") or previous.get("refresh_token"),
        "expires_at": int(time.time()) + int(grant.get("expires_in", 3600)),
        "scope": grant.get("scope", config.SCOPES),
    }
    save_tokens(tokens)
    return tokens


# --- interactive login -------------------------------------------------------


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):  # noqa: N802 - stdlib naming
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != config.CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        type(self).result = {k: v[0] for k, v in params.items()}
        ok = "code" in type(self).result
        message = (
            "Login complete. You can close this tab and return to your terminal."
            if ok
            else f"Login failed: {type(self).result.get('error_description', 'unknown error')}"
        )
        body = f"<html><body style='font-family:sans-serif'><h3>{message}</h3></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args):  # silence the default stderr access log
        pass


def login(client_id: str, open_browser: bool = True, timeout: int = 300) -> dict:
    """Run the loopback PKCE flow and persist the resulting tokens."""
    verifier, challenge = pkce_pair()
    state = _b64url(secrets.token_bytes(16))
    url = authorize_url(client_id, challenge, state)

    _CallbackHandler.result = {}
    try:
        server = http.server.HTTPServer(("127.0.0.1", config.CALLBACK_PORT), _CallbackHandler)
    except OSError as exc:
        raise AuthError(
            f"cannot listen on 127.0.0.1:{config.CALLBACK_PORT} ({exc}). "
            "Close whatever is using that port and retry."
        ) from exc

    print("Open this URL in your browser to sign in:\n")
    print(f"  {url}\n")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    print("Waiting for the callback...")

    server.timeout = timeout
    deadline = time.time() + timeout
    with server:
        while not _CallbackHandler.result and time.time() < deadline:
            server.handle_request()

    result = _CallbackHandler.result
    if not result:
        raise AuthError("timed out waiting for the browser callback")
    if "error" in result:
        raise AuthError(f"{result['error']}: {result.get('error_description', '')}")
    if result.get("state") != state:
        raise AuthError("state mismatch in callback - aborting")

    grant = _post_token(
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code_verifier": verifier,
            "code": result["code"],
            "redirect_uri": config.REDIRECT_URI,
        }
    )
    return _store_grant(grant)


def refresh(client_id: str, tokens: dict) -> dict:
    if not tokens.get("refresh_token"):
        raise AuthError("no refresh token stored - run `yoto-iconer login`")
    grant = _post_token(
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": tokens["refresh_token"],
        }
    )
    return _store_grant(grant, previous=tokens)


def access_token(skew: int = 60) -> str:
    """A currently valid access token, refreshing on the fly when needed."""
    cid = config.client_id()
    if not cid:
        raise AuthError(
            "no client id configured - run `yoto-iconer setup` (or set YOTO_CLIENT_ID)"
        )
    tokens = load_tokens()
    if not tokens:
        raise AuthError("not logged in - run `yoto-iconer login`")
    if tokens.get("expires_at", 0) - skew > time.time():
        return tokens["access_token"]
    return refresh(cid, tokens)["access_token"]
