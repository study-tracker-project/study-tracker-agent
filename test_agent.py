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


def _mock_flow_returning(mock_installed_app_flow, id_token):
    """agent.InstalledAppFlow.from_client_config(...).run_local_server(...) 가
    주어진 id_token을 가진 credentials를 반환하도록 목킹."""
    mock_credentials = MagicMock(id_token=id_token)
    mock_flow_instance = MagicMock()
    mock_flow_instance.run_local_server.return_value = mock_credentials
    mock_installed_app_flow.from_client_config.return_value = mock_flow_instance


@patch("agent.config.save_device_id")
@patch("agent.config.save_token")
@patch("agent._register_device")
@patch("agent._login_with_id_token")
@patch("agent.InstalledAppFlow")
def test_login_returns_false_when_login_with_id_token_fails(
    mock_installed_app_flow, mock_login_with_id_token, mock_register_device,
    mock_save_token, mock_save_device_id, monkeypatch
):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    _mock_flow_returning(mock_installed_app_flow, "fake-id-token")
    mock_login_with_id_token.return_value = None

    result = agent.login("my-pc")

    assert result is False
    mock_register_device.assert_not_called()
    mock_save_token.assert_not_called()
    mock_save_device_id.assert_not_called()


@patch("agent.config.save_device_id")
@patch("agent.config.save_token")
@patch("agent._register_device")
@patch("agent._login_with_id_token")
@patch("agent.InstalledAppFlow")
def test_login_returns_false_when_register_device_fails(
    mock_installed_app_flow, mock_login_with_id_token, mock_register_device,
    mock_save_token, mock_save_device_id, monkeypatch
):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    _mock_flow_returning(mock_installed_app_flow, "fake-id-token")
    mock_login_with_id_token.return_value = "access-token"
    mock_register_device.return_value = None

    result = agent.login("my-pc")

    assert result is False
    mock_save_token.assert_not_called()
    mock_save_device_id.assert_not_called()


@patch("agent.config.save_device_id")
@patch("agent.config.save_token")
@patch("agent._register_device")
@patch("agent._login_with_id_token")
@patch("agent.InstalledAppFlow")
def test_login_success_saves_token_then_device_id(
    mock_installed_app_flow, mock_login_with_id_token, mock_register_device,
    mock_save_token, mock_save_device_id, monkeypatch
):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    _mock_flow_returning(mock_installed_app_flow, "fake-id-token")
    mock_login_with_id_token.return_value = "access-token"
    mock_register_device.return_value = {"deviceToken": "device-token-xyz", "deviceId": 42}

    call_order = []
    mock_save_token.side_effect = lambda *a, **kw: call_order.append(("save_token", a, kw))
    mock_save_device_id.side_effect = lambda *a, **kw: call_order.append(("save_device_id", a, kw))

    result = agent.login("my-pc")

    assert result is True
    mock_save_token.assert_called_once_with("device-token-xyz")
    mock_save_device_id.assert_called_once_with(42)
    assert [c[0] for c in call_order] == ["save_token", "save_device_id"]


@patch("agent.config.save_device_id")
@patch("agent.config.save_token")
@patch("agent._register_device")
@patch("agent._login_with_id_token")
@patch("agent.InstalledAppFlow")
def test_login_returns_false_when_id_token_missing(
    mock_installed_app_flow, mock_login_with_id_token, mock_register_device,
    mock_save_token, mock_save_device_id, monkeypatch
):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    _mock_flow_returning(mock_installed_app_flow, None)

    result = agent.login("my-pc")

    assert result is False
    mock_login_with_id_token.assert_not_called()
    mock_register_device.assert_not_called()
    mock_save_token.assert_not_called()
    mock_save_device_id.assert_not_called()
