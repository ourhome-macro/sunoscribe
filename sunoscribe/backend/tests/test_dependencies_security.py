from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.utils.dependencies import get_current_user
from app.utils.errors import AuthenticationError


class TestDependenciesSecurity(unittest.TestCase):
    def test_invalid_user_uuid_in_access_token_returns_auth_error(self) -> None:
        db = MagicMock()

        with patch(
            "app.utils.dependencies.decode_token",
            return_value={"type": "access", "sub": "not-a-uuid", "jti": "jti-invalid-uuid"},
        ):
            with self.assertRaises(AuthenticationError):
                get_current_user(token="test-token", db=db)

        db.get.assert_not_called()

    def test_revoked_access_token_returns_auth_error(self) -> None:
        db = MagicMock()

        with patch(
            "app.utils.dependencies.decode_token",
            return_value={"type": "access", "sub": "6ba7b810-9dad-11d1-80b4-00c04fd430c8", "jti": "revoked-jti"},
        ), patch("app.utils.dependencies.is_token_revoked", return_value=True):
            with self.assertRaises(AuthenticationError):
                get_current_user(token="test-token", db=db)


if __name__ == "__main__":
    unittest.main()
