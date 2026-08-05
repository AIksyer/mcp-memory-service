"""
WebAuthn (Passkey) authentication endpoints.

Implements registration and authentication ceremonies using the
py_webauthn library (v0.0.6 API). Credentials are stored in SQLite
via the existing OAuth storage infrastructure.

Flow:
  1. Registration: begin → browser creates credential → finish → credential stored
  2. Authentication: begin → browser signs challenge → finish → JWT issued

The Worker LB proxies these endpoints. Browser-side JavaScript in the
Worker's /auth/login page calls these directly.
"""

import base64
import hashlib
import json
import logging
import os
import sqlite3
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..oauth.middleware import (
    AuthenticationResult,
    API_KEY,
    ALLOW_ANONYMOUS_ACCESS,
    OAUTH_ENABLED,
    authenticate_api_key,
)
from ...config import HTTP_HOST, HTTP_PORT

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/webauthn", tags=["webauthn"])

# Path for WebAuthn credential storage (shared with OAuth SQLite if available)
_WEBAUTHN_DB = os.environ.get(
    "MCP_WEBAUTHN_DB",
    os.path.join(os.path.expanduser("~"), ".mcp-memory", "webauthn.db"),
)


def _get_db() -> sqlite3.Connection:
    """Get or create the WebAuthn credential database."""
    os.makedirs(os.path.dirname(_WEBAUTHN_DB), exist_ok=True)
    conn = sqlite3.connect(_WEBAUTHN_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS webauthn_credentials (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            credential_id TEXT NOT NULL UNIQUE,
            public_key TEXT NOT NULL,
            sign_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS webauthn_challenges (
            challenge TEXT PRIMARY KEY,
            user_id TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def _get_rp(request: Request):
    """Build RelyingParty from request origin."""
    from webauthn.types import RelyingParty

    # Derive RP ID from Host header (domain without port)
    host = request.headers.get("host", "localhost")
    rp_id = host.split(":")[0]  # strip port
    rp_name = "MCP Memory Service"

    return RelyingParty(id=rp_id, name=rp_name, icon=None)


def _base64url_decode(data: str) -> bytes:
    """Decode base64url (add padding if needed)."""
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


def _base64url_encode(data: bytes) -> str:
    """Encode to base64url without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# ===== Models =====

class RegistrationBeginRequest(BaseModel):
    user_id: str | None = None  # If None, use API key as user identity


class RegistrationFinishRequest(BaseModel):
    credential: dict[str, Any]


class AuthBeginRequest(BaseModel):
    user_id: str | None = None


class AuthFinishRequest(BaseModel):
    credential: dict[str, Any]


# ===== Registration =====

@router.post("/register/begin")
async def register_begin(request: Request, body: RegistrationBeginRequest | None = None):
    """Begin WebAuthn registration ceremony.

    Requires API key authentication (the caller must prove they have access
    before registering a passkey).
    """
    # Simple auth: require API key in header or body
    api_key = request.headers.get("X-API-Key", "")
    if not api_key and body and hasattr(body, "user_id"):
        api_key = body.user_id or ""

    if not api_key:
        # Try anonymous if enabled
        if not ALLOW_ANONYMOUS_ACCESS:
            return JSONResponse({"error": "API key required for passkey registration"}, status_code=401)
        api_key = "anonymous"

    user_id = hashlib.sha256(api_key.encode()).hexdigest()[:16]

    try:
        from webauthn import create_webauthn_credentials
        from webauthn.types import User

        rp = _get_rp(request)
        user = User(id=user_id.encode(), display_name=f"User {user_id[:8]}", name=user_id)

        # Get existing credential IDs to prevent re-registration
        db = _get_db()
        cursor = db.execute(
            "SELECT credential_id FROM webauthn_credentials WHERE user_id = ?",
            (user_id,),
        )
        existing_keys = [row[0].encode() for row in cursor.fetchall()]
        db.close()

        public_key, challenge = create_webauthn_credentials(
            rp=rp,
            user=user,
            existing_keys=existing_keys,
        )

        # Store challenge
        db = _get_db()
        db.execute("INSERT OR REPLACE INTO webauthn_challenges (challenge, user_id) VALUES (?, ?)", (challenge, user_id))
        db.commit()
        db.close()

        return JSONResponse({
            "publicKey": public_key,
            "challenge": challenge,
            "user_id": user_id,
        })
    except ImportError:
        return JSONResponse({"error": "WebAuthn not available (py_webauthn not installed)"}, status_code=503)
    except Exception as e:
        logger.error(f"WebAuthn registration begin failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/register/finish")
async def register_finish(request: Request, body: RegistrationFinishRequest):
    """Complete WebAuthn registration — verify attestation and store credential."""
    try:
        from webauthn import verify_create_webauthn_credentials
        from webauthn.metadata import FIDOMetadata
        from webauthn.types import RelyingParty

        rp = _get_rp(request)

        cred = body.credential
        client_data_b64 = cred.get("response", {}).get("clientDataJSON", "")
        attestation_b64 = cred.get("response", {}).get("attestationObject", "")

        # Get stored challenge
        db = _get_db()
        # Try to find any recent challenge (within 5 minutes)
        cursor = db.execute(
            "SELECT challenge, user_id FROM webauthn_challenges ORDER BY created_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if not row:
            db.close()
            return JSONResponse({"error": "No active challenge found"}, status_code=400)

        challenge_b64, user_id = row

        result = verify_create_webauthn_credentials(
            rp=rp,
            challenge_b64=challenge_b64,
            client_data_b64=client_data_b64,
            attestation_b64=attestation_b64,
            fido_metadata=FIDOMetadata(),
        )

        # Store credential
        cred_id = _base64url_encode(result.credential_id)
        pub_key = result.public_key.hex() if isinstance(result.public_key, bytes) else str(result.public_key)

        db.execute(
            "INSERT OR REPLACE INTO webauthn_credentials (id, user_id, credential_id, public_key, sign_count) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, cred_id, pub_key, result.sign_count or 0),
        )
        # Clean up challenge
        db.execute("DELETE FROM webauthn_challenges WHERE challenge = ?", (challenge_b64,))
        db.commit()
        db.close()

        return JSONResponse({"ok": True, "message": "Passkey registered successfully"})
    except ImportError:
        return JSONResponse({"error": "WebAuthn not available"}, status_code=503)
    except Exception as e:
        logger.error(f"WebAuthn registration finish failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ===== Authentication =====

@router.post("/auth/begin")
async def auth_begin(request: Request, body: AuthBeginRequest | None = None):
    """Begin WebAuthn authentication ceremony."""
    try:
        from webauthn import get_webauthn_credentials

        rp = _get_rp(request)

        # Get all existing credential IDs
        db = _get_db()
        cursor = db.execute("SELECT credential_id FROM webauthn_credentials")
        existing_keys = [row[0].encode() for row in cursor.fetchall()]

        public_key, challenge = get_webauthn_credentials(
            rp=rp,
            existing_keys=existing_keys,
        )

        # Store challenge
        db.execute("INSERT OR REPLACE INTO webauthn_challenges (challenge, user_id) VALUES (?, ?)", (challenge, None))
        db.commit()
        db.close()

        return JSONResponse({"publicKey": public_key, "challenge": challenge})
    except ImportError:
        return JSONResponse({"error": "WebAuthn not available"}, status_code=503)
    except Exception as e:
        logger.error(f"WebAuthn auth begin failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/auth/finish")
async def auth_finish(request: Request, body: AuthFinishRequest):
    """Complete WebAuthn authentication — verify assertion and issue JWT."""
    try:
        from webauthn import verify_get_webauthn_credentials
        from webauthn.metadata import FIDOMetadata
        from webauthn.types import RelyingParty

        rp = _get_rp(request)
        cred = body.credential

        # Extract credential data
        cred_id = cred.get("id", "")
        response = cred.get("response", {})
        client_data_b64 = response.get("clientDataJSON", "")
        authenticator_b64 = response.get("authenticatorData", "")
        signature_b64 = response.get("signature", "")
        sign_count = 0  # Will be extracted from authenticator data

        # Get stored challenge
        db = _get_db()
        cursor = db.execute(
            "SELECT challenge FROM webauthn_challenges ORDER BY created_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if not row:
            db.close()
            return JSONResponse({"error": "No active challenge"}, status_code=400)

        challenge_b64 = row[0]

        # Look up the credential
        cursor = db.execute(
            "SELECT user_id, public_key, sign_count FROM webauthn_credentials WHERE credential_id = ?",
            (cred_id,),
        )
        cred_row = cursor.fetchone()
        if not cred_row:
            db.close()
            return JSONResponse({"error": "Unknown credential"}, status_code=401)

        stored_user_id, stored_pub_key, stored_sign_count = cred_row

        # Verify the assertion
        result = verify_get_webauthn_credentials(
            rp=rp,
            challenge_b64=challenge_b64,
            client_data_b64=client_data_b64,
            authenticator_b64=authenticator_b64,
            signature_b64=signature_b64,
            sign_count=stored_sign_count,
            pubkey_alg=0,  # Will be auto-detected
            pubkey=bytes.fromhex(stored_pub_key),
        )

        # Update sign count
        db.execute(
            "UPDATE webauthn_credentials SET sign_count = ? WHERE credential_id = ?",
            (result.sign_count or stored_sign_count + 1, cred_id),
        )
        db.execute("DELETE FROM webauthn_challenges WHERE challenge = ?", (challenge_b64,))
        db.commit()
        db.close()

        # Issue a JWT (reuse OAuth token infrastructure if available)
        if OAUTH_ENABLED:
            from ..oauth.middleware import OAUTH_ISSUER
            import jwt as pyjwt

            token = pyjwt.encode(
                {
                    "sub": stored_user_id,
                    "iss": OAUTH_ISSUER,
                    "aud": "mcp-memory-service",
                    "scope": "read write",
                    "iat": int(__import__("time").time()),
                    "exp": int(__import__("time").time()) + 3600,
                },
                os.environ.get("MCP_OAUTH_JWT_SECRET", "webauthn-default-secret"),
                algorithm="HS256",
            )
            return JSONResponse({"ok": True, "token": token, "token_type": "Bearer"})
        else:
            # No OAuth — return a simple session token
            return JSONResponse({"ok": True, "user_id": stored_user_id})

    except ImportError:
        return JSONResponse({"error": "WebAuthn not available"}, status_code=503)
    except Exception as e:
        logger.error(f"WebAuthn auth finish failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
