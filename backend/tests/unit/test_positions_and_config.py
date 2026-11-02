import pytest
from pydantic import ValidationError

from forgeboard.config import Settings
from forgeboard.domain.positions import STEP, position_between, rebalanced
from forgeboard.security.passwords import hash_password, verify_password
from forgeboard.services.attachments import sanitize_filename


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
