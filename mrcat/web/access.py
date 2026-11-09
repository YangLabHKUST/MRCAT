"""Verify Cloudflare Access identities and select private session stores."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
import re
import threading

import jwt
from fastapi import HTTPException

from .service import Service


@dataclass(frozen=True)
class Identity:
    subject: str
    email: str
    expires_at: float


class CloudflareAccess:
    def __init__(self, team_domain, audience):
        domain = str(team_domain or "").strip().removeprefix("https://").rstrip("/")
        if not re.fullmatch(r"[a-zA-Z0-9-]+\.cloudflareaccess\.com", domain):
            raise ValueError("Set MRCAT_ACCESS_TEAM_DOMAIN to your Cloudflare Access team domain")
        if not isinstance(audience, str) or not audience.strip():
            raise ValueError("Set MRCAT_ACCESS_AUD to the Access application's audience tag")
        self.issuer = "https://" + domain.lower()
        self.audience = audience.strip()
        self.keys = jwt.PyJWKClient(self.issuer + "/cdn-cgi/access/certs", timeout=5)

    def verify(self, token):
        if not token:
            raise HTTPException(401, "Sign in through Cloudflare Access")
        try:
            key = self.keys.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"],
                                issuer=self.issuer, audience=self.audience,
                                options={"require": ["exp", "iat", "iss", "aud", "sub", "email"]})
            subject, email = claims["sub"], claims["email"]
            if not isinstance(subject, str) or not subject.strip() or not isinstance(email, str) or not email.strip():
                raise jwt.InvalidTokenError("A user identity is required")
            return Identity(subject, email, float(claims["exp"]))
        except jwt.PyJWKClientConnectionError as exc:
            raise HTTPException(503, "Sign-in verification is temporarily unavailable") from exc
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
            raise HTTPException(401, "Invalid or expired Cloudflare Access sign-in") from exc


class UserServices:
    """A user's store and view cache never include another user's sessions."""
    def __init__(self, root, artifact_dir, issuer):
        self.root = root
        self.base = Path(artifact_dir).resolve() / ".users"
        self.issuer = issuer
        self.lock = threading.Lock()
        self.services = {}

    def get(self, identity):
        key = sha256(json.dumps([self.issuer, identity.subject]).encode()).hexdigest()
        with self.lock:
            if self.base.is_symlink() or (self.base / key).is_symlink():
                raise HTTPException(403, "Linked user stores are not allowed")
            if key not in self.services:
                self.services[key] = Service(self.root, self.base / key)
            return self.services[key]

    def close(self):
        with self.lock:
            for service in self.services.values():
                service.views.close()
            self.services.clear()
