from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.exc import IntegrityError

from app.models.token_revocation import TokenRevocation
from app.models.user import User
from app.services.auth_service import logout, refresh_access_token
from app.utils.errors import AuthenticationError


class _FakeSession:
    def __init__(self, user_id: uuid.UUID):
        self.user_id = user_id
        self.revoked_jti: set[str] = set()
        self._pending: list[object] = []

    def get(self, model, key):
        if model is User and key == self.user_id:
            return SimpleNamespace(id=key)
        return None

    def add(self, obj: object) -> None:
        self._pending.append(obj)

    def commit(self) -> None:
        for obj in self._pending:
            if isinstance(obj, TokenRevocation):
                if obj.jti in self.revoked_jti:
                    self._pending = []
                    raise IntegrityError("duplicate jti", None, Exception("duplicate jti"))
                self.revoked_jti.add(obj.jti)
        self._pending = []

    def rollback(self) -> None:
        self._pending = []


class TestAuthTokenRotation(unittest.TestCase):
    def test_refresh_token_is_rotated_and_old_jti_is_revoked(self) -> None:
        user_id = uuid.uuid4()
        db = _FakeSession(user_id)
        payload = {
            "type": "refresh",
            "sub": str(user_id),
            "jti": "refresh-jti-1",
            "exp": datetime.now(timezone.utc).timestamp() + 3600,
        }

        with patch("app.services.auth_service.decode_token", return_value=payload), patch(
            "app.services.auth_service.create_access_token",
            return_value="new-access-token",
        ), patch(
            "app.services.auth_service.create_refresh_token",
            return_value="new-refresh-token",
        ), patch(
            "app.services.auth_service.is_token_revoked",
            return_value=False,
        ):
            data = refresh_access_token(db, "dummy-refresh-token")

        self.assertEqual(data["access_token"], "new-access-token")
        self.assertEqual(data["refresh_token"], "new-refresh-token")
        self.assertIn("refresh-jti-1", db.revoked_jti)

    def test_refresh_token_replay_is_rejected(self) -> None:
        user_id = uuid.uuid4()
        db = _FakeSession(user_id)
        payload = {
            "type": "refresh",
            "sub": str(user_id),
            "jti": "refresh-jti-replay",
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        }

        with patch("app.services.auth_service.decode_token", return_value=payload), patch(
            "app.services.auth_service.create_access_token",
            return_value="access-token",
        ), patch(
            "app.services.auth_service.create_refresh_token",
            return_value="refresh-token",
        ), patch(
            "app.services.auth_service.is_token_revoked",
            return_value=False,
        ):
            refresh_access_token(db, "dummy-refresh-token")
            with self.assertRaises(AuthenticationError):
                refresh_access_token(db, "dummy-refresh-token")

    def test_logout_is_idempotent_for_same_refresh_token(self) -> None:
        user_id = uuid.uuid4()
        db = _FakeSession(user_id)
        access_payload = {
            "type": "access",
            "sub": str(user_id),
            "jti": "access-jti-logout",
            "exp": (datetime.now(timezone.utc) + timedelta(minutes=30)).timestamp(),
        }
        refresh_payload = {
            "type": "refresh",
            "sub": str(user_id),
            "jti": "refresh-jti-logout",
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        }

        with patch(
            "app.services.auth_service.decode_token",
            side_effect=[access_payload, refresh_payload, access_payload, refresh_payload],
        ):
            logout(db, "dummy-access-token", "dummy-refresh-token")
            logout(db, "dummy-access-token", "dummy-refresh-token")

        self.assertIn("access-jti-logout", db.revoked_jti)
        self.assertIn("refresh-jti-logout", db.revoked_jti)

    def test_logout_rejects_wrong_refresh_token_type(self) -> None:
        user_id = uuid.uuid4()
        db = _FakeSession(user_id)
        access_payload = {
            "type": "access",
            "sub": str(user_id),
            "jti": "access-jti-2",
            "exp": (datetime.now(timezone.utc) + timedelta(minutes=30)).timestamp(),
        }
        invalid_refresh_payload = {
            "type": "access",
            "sub": str(user_id),
            "jti": "not-refresh-jti",
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        }

        with patch(
            "app.services.auth_service.decode_token",
            side_effect=[access_payload, invalid_refresh_payload],
        ):
            with self.assertRaises(AuthenticationError):
                logout(db, "dummy-access-token", "dummy-refresh-token")


if __name__ == "__main__":
    unittest.main()
