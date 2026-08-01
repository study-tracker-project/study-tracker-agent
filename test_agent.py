import os
import pytest

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
