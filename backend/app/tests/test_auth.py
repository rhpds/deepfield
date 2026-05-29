"""DeepField auth — TDD."""
import pytest
from unittest.mock import MagicMock, patch


class TestAuthModule:
    def test_auth_exists(self):
        from app.auth import require_api_key
        assert callable(require_api_key)

    def test_no_key_configured_allows_all(self):
        from app.auth import require_api_key
        with patch("app.auth.DEEPFIELD_API_KEY", ""):
            require_api_key(request=None, api_key="")

    def test_valid_key_passes(self):
        from app.auth import require_api_key
        with patch("app.auth.DEEPFIELD_API_KEY", "test-key"):
            require_api_key(request=None, api_key="test-key")

    def test_invalid_key_rejected(self):
        from app.auth import require_api_key
        from fastapi import HTTPException
        with patch("app.auth.DEEPFIELD_API_KEY", "real-key"):
            with pytest.raises(HTTPException):
                require_api_key(request=MagicMock(headers={}), api_key="wrong")

    def test_same_origin_bypasses(self):
        from app.auth import require_api_key
        with patch("app.auth.DEEPFIELD_API_KEY", "real-key"):
            req = MagicMock()
            req.headers = {"sec-fetch-site": "same-origin"}
            require_api_key(request=req, api_key="")
