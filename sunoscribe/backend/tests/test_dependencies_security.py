from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.utils.dependencies import get_current_user
from app.utils.errors import AuthenticationError


class TestDependenciesSecurity(unittest.TestCase):
    def test_invalid_user_uuid_in_access_token_returns_auth_error(self) -> None:
        credentials = SimpleNamespace(credentials="test-token")
        db = MagicMock()

        with patch(
            "app.utils.dependencies.decode_token",
            return_value={"type": "access", "sub": "not-a-uuid"},
        ):
            with self.assertRaises(AuthenticationError):
                get_current_user(credentials=credentials, db=db)

        db.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
