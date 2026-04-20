from __future__ import annotations

import unittest

from app.main import app


class TestOpenApiRequiredEndpoints(unittest.TestCase):
    def test_prd_required_routes_exist(self) -> None:
        actual = set()
        for route in app.routes:
            methods = getattr(route, "methods", None)
            if not methods:
                continue
            for method in methods:
                if method in {"HEAD", "OPTIONS"}:
                    continue
                actual.add((method, route.path))

        required = {
            ("POST", "/api/auth/register"),
            ("POST", "/api/auth/login"),
            ("POST", "/api/auth/logout"),
            ("POST", "/api/auth/refresh"),
            ("POST", "/api/auth/forgot-password"),
            ("POST", "/api/auth/reset-password"),
            ("GET", "/api/users/me"),
            ("PUT", "/api/users/me"),
            ("GET", "/api/users/me/settings"),
            ("PUT", "/api/users/me/settings"),
            ("POST", "/api/projects"),
            ("GET", "/api/projects"),
            ("GET", "/api/projects/{project_id}"),
            ("PUT", "/api/projects/{project_id}"),
            ("DELETE", "/api/projects/{project_id}"),
            ("POST", "/api/upload/audio"),
            ("POST", "/api/upload/video"),
            ("GET", "/api/projects/{project_id}/score"),
            ("POST", "/api/projects/{project_id}/score"),
            ("PUT", "/api/scores/{score_id}"),
            ("GET", "/api/scores/{score_id}/export"),
            ("GET", "/api/projects/{project_id}/lyrics"),
            ("PUT", "/api/lyrics/{lyrics_id}"),
            ("GET", "/api/tasks/{task_id}"),
        }

        missing = required - actual
        self.assertFalse(missing, f"Missing required routes: {sorted(missing)}")


if __name__ == "__main__":
    unittest.main()
