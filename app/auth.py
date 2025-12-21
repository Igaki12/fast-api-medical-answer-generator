from __future__ import annotations

import os
import secrets

from fastapi import Depends, HTTPException, status # type: ignore
from fastapi.security import HTTPBasic, HTTPBasicCredentials # type: ignore


_security = HTTPBasic()


def require_basic_auth(
    credentials: HTTPBasicCredentials = Depends(_security),
) -> str:
    expected_user = os.getenv("BASIC_AUTH_USER", "dev")
    expected_password = os.getenv("BASIC_AUTH_PASSWORD", "dev")

    user_ok = secrets.compare_digest(credentials.username, expected_user)
    password_ok = secrets.compare_digest(credentials.password, expected_password)

    if not (user_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid basic auth credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
