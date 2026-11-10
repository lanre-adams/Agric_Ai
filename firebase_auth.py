import json
import os
from typing import Optional

from fastapi import HTTPException, Request


DEV_USER_ID = "local-dev-user"

_firebase_ready = False
_firebase_error: Optional[str] = None


def _initialize_firebase_admin():
    """
    Initialize Firebase Admin only once.

    Local development:
    - If firebase-admin is not installed or credentials are missing,
      the app can still run using the fallback dev user.

    Production:
    - Render should have FIREBASE_ADMIN_CREDENTIALS_JSON set.
    - Firebase Admin verifies the real user token.
    """
    global _firebase_ready, _firebase_error

    if _firebase_ready:
        return

    try:
        import firebase_admin
        from firebase_admin import credentials

        if firebase_admin._apps:
            _firebase_ready = True
            return

        raw_credentials = os.getenv("FIREBASE_ADMIN_CREDENTIALS_JSON")

        if not raw_credentials:
            _firebase_error = "FIREBASE_ADMIN_CREDENTIALS_JSON is not set."
            return

        credentials_dict = json.loads(raw_credentials)

        cred = credentials.Certificate(credentials_dict)
        firebase_admin.initialize_app(cred)

        _firebase_ready = True

    except Exception as error:
        _firebase_error = str(error)
        _firebase_ready = False


def get_current_user_id(request: Request) -> str:
    """
    Get the current authenticated Firebase user ID.

    Expected frontend header:
    Authorization: Bearer <firebase_id_token>

    Local development fallback:
    - If no token is sent, use x-user-id if present.
    - If x-user-id is missing, use local-dev-user.
    """
    _initialize_firebase_admin()

    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")

    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "").strip()

        if not token:
            raise HTTPException(status_code=401, detail="Missing Firebase token.")

        if not _firebase_ready:
            raise HTTPException(
                status_code=500,
                detail=f"Firebase Admin is not ready: {_firebase_error}",
            )

        try:
            from firebase_admin import auth

            decoded_token = auth.verify_id_token(token)
            user_id = decoded_token.get("uid")

            if not user_id:
                raise HTTPException(status_code=401, detail="Invalid Firebase token.")

            return user_id

        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired Firebase token.")

    # Local development fallback
    header_user_id = request.headers.get("x-user-id")

    if header_user_id and header_user_id.strip():
        return header_user_id.strip()

    return DEV_USER_ID