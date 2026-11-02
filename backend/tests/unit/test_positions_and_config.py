import pytest
from pydantic import ValidationError

from taskboard.config import Settings
from taskboard.domain.positions import STEP, position_between, rebalanced
from taskboard.security.passwords import hash_password, verify_password
from taskboard.services.attachments import sanitize_filename


def test_position_between():
    assert position_between(None, None) == STEP
    assert position_between(None, 100.0) == 100.0 - STEP
    assert position_between(100.0, None) == 100.0 + STEP
    assert position_between(1.0, 2.0) == 1.5
    assert position_between(1.0, 1.0 + 1e-9) is None


def test_rebalanced():
    assert rebalanced(3) == [STEP, 2 * STEP, 3 * STEP]


def test_production_refuses_placeholder_secrets():
    with pytest.raises(ValidationError) as exc:
        Settings(app_env="production", jwt_secret="change-me", postgres_password="change-me")
    assert "generate-secrets" in str(exc.value)
    with pytest.raises(ValidationError):
        Settings(app_env="production", jwt_secret="x" * 20, postgres_password="good-password-123")


def test_production_accepts_strong_secrets():
    s = Settings(app_env="production", jwt_secret="x" * 40, postgres_password="good-password-123")
    assert s.app_env == "production"


def test_argon2id_hash_and_verify():
    h = hash_password("S3cret-password!")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "S3cret-password!")
    assert not verify_password(h, "wrong")
    assert not verify_password(None, "anything")
    assert not verify_password("not-a-hash", "anything")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Windows\\evil.exe", "evil.exe"),
        ("  .hidden  ", "hidden"),
        ("a<b>c.txt", "abc.txt"),
        ("", "file"),
        (None, "file"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


@pytest.mark.parametrize(
    ("base_url", "explicit", "expected"),
    [
        ("http://localhost:8080", None, False),
        ("https://board.example.com", None, True),
        ("https://board.example.com", "", True),  # empty env value = automatic
        ("https://board.example.com", False, False),
        ("http://10.0.0.5:8080", True, True),
    ],
)
def test_cookie_secure_derived_from_public_url(base_url, explicit, expected):
    kwargs = {"app_env": "test", "jwt_secret": "x" * 40, "public_base_url": base_url}
    if explicit is not None:
        kwargs["cookie_secure"] = explicit
    assert Settings(**kwargs).secure_cookies is expected


def test_server_trusts_no_forwarded_headers_by_default(monkeypatch):
    import taskboard.serve as serve

    captured = {}
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    monkeypatch.setattr(serve.uvicorn, "run", lambda *a, **kw: captured.update(kw))
    serve.main()
    assert captured["forwarded_allow_ips"] == "127.0.0.1" and captured["proxy_headers"] is True


@pytest.mark.parametrize(
    ("origin", "host", "allowed"),
    [
        ("http://testserver", None, True),  # configured
        ("http://docker0:8090", "docker0:8090", True),  # same-origin, not configured
        ("https://board.example.com", "board.example.com", True),
        ("http://docker0:8090", "docker0:8091", False),
        ("http://evil.example", "docker0:8090", False),
        ("http://evil.example", None, False),
        ("null", "null", False),
        ("", "docker0", False),
        (None, "docker0", False),
    ],
)
def test_origin_allowed_same_origin_rule(origin, host, allowed):
    from taskboard.security.csrf import origin_allowed

    assert origin_allowed(origin, host) is allowed
