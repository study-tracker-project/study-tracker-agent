import os
import pytest
from unittest.mock import patch, MagicMock

import agent


def test_require_oauth_env_missing_client_id(monkeypatch, capsys):
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        agent._require_oauth_env()

    assert exc_info.value.code == 1
    assert "GOOGLE_OAUTH_CLIENT_ID" in capsys.readouterr().out


def test_require_oauth_env_missing_client_secret(monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        agent._require_oauth_env()

    assert exc_info.value.code == 1
    assert "GOOGLE_OAUTH_CLIENT_SECRET" in capsys.readouterr().out


def test_require_oauth_env_present(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")

    client_id, client_secret = agent._require_oauth_env()

    assert client_id == "test-client-id"
    assert client_secret == "test-client-secret"


def test_build_client_config_structure():
    client_config = agent._build_client_config("cid", "csecret")

    installed = client_config["installed"]
    assert installed["client_id"] == "cid"
    assert installed["client_secret"] == "csecret"
    assert installed["auth_uri"] == "https://accounts.google.com/o/oauth2/auth"
    assert installed["token_uri"] == "https://oauth2.googleapis.com/token"
    assert installed["redirect_uris"] == ["http://localhost"]


@patch("agent.requests.post")
def test_login_with_id_token_success(mock_post):
    mock_post.return_value = MagicMock(status_code=200, json=lambda: {"accessToken": "abc123"})

    result = agent._login_with_id_token("fake-id-token")

    assert result == "abc123"
    mock_post.assert_called_once_with(
        f"{agent.config.SERVER_URL}/api/auth/google",
        json={"idToken": "fake-id-token"},
        timeout=10
    )


@patch("agent.requests.post")
def test_login_with_id_token_failure_status(mock_post):
    mock_post.return_value = MagicMock(status_code=401)

    result = agent._login_with_id_token("bad-token")

    assert result is None


@patch("agent.requests.post")
def test_login_with_id_token_network_error(mock_post):
    mock_post.side_effect = agent.requests.RequestException("connection refused")

    result = agent._login_with_id_token("token")

    assert result is None


@patch("agent.requests.post")
def test_register_device_success(mock_post):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"deviceToken": "device-token-xyz", "deviceId": 42}
    )

    result = agent._register_device("access-token", "my-pc")

    assert result == {"deviceToken": "device-token-xyz", "deviceId": 42}
    mock_post.assert_called_once_with(
        f"{agent.config.SERVER_URL}/api/auth/device",
        json={"deviceName": "my-pc", "deviceType": "PC"},
        headers={"Authorization": "Bearer access-token"},
        timeout=10
    )


@patch("agent.requests.post")
def test_register_device_failure_status(mock_post):
    mock_post.return_value = MagicMock(status_code=400)

    result = agent._register_device("access-token", "my-pc")

    assert result is None


@patch("agent.requests.post")
def test_register_device_network_error(mock_post):
    mock_post.side_effect = agent.requests.RequestException("timeout")

    result = agent._register_device("access-token", "my-pc")

    assert result is None
