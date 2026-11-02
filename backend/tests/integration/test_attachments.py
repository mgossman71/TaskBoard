import pytest

pytestmark = pytest.mark.asyncio

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89" + b"\x00" * 64
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


@pytest.fixture
async def task(api, world):
    return await api.task(world["member"], world["project"]["id"], "with files")


async def _upload(client, user, task, name, data, ctype="application/octet-stream"):
    return await client.post(f"/api/v1/tasks/{task['id']}/attachments", files={"file": (name, data, ctype)}, headers=user.h)


async def test_upload_list_download_delete(client, world, task):
    m = world["member"]
    r = await _upload(client, m, task, "pixel.png", PNG, "image/png")
    assert r.status_code == 201, r.text
    att = r.json()
    assert att["content_type"] == "image/png" and att["size_bytes"] == len(PNG) and len(att["sha256"]) == 64
    detail = (await client.get(f"/api/v1/tasks/{task['id']}", headers=world["viewer"].h)).json()
    assert [a["id"] for a in detail["attachments"]] == [att["id"]]
    d = await client.get(f"/api/v1/attachments/{att['id']}/download", headers=world["viewer"].h)
    assert d.status_code == 200 and d.content == PNG
    assert d.headers["content-disposition"].startswith("attachment;")
    assert d.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in d.headers["content-security-policy"]
    # viewers cannot upload or delete; other members cannot delete someone else's file
    assert (await _upload(client, world["viewer"], task, "x.png", PNG)).status_code == 403
    assert (await client.delete(f"/api/v1/attachments/{att['id']}", headers=world["viewer"].h)).status_code == 403
    assert (await client.delete(f"/api/v1/attachments/{att['id']}", headers=m.h)).status_code == 204
    assert (await client.get(f"/api/v1/attachments/{att['id']}/download", headers=m.h)).status_code == 404


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        ("doc.pdf", PDF, 201),
        ("notes.txt", "plain text ✓".encode(), 201),
        ("data.csv", b"a,b\n1,2\n", 201),
        ("evil.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', 415),
        ("page.html", b"<html><script>alert(1)</script></html>", 415),
        ("sneaky.txt", b"<html><body><script>alert(1)</script></body></html>", 415),
        ("fake.png", b"MZ\x90\x00 this is actually an exe", 415),
        ("image.png", PDF, 415),  # extension/content mismatch
        ("binary.txt", b"\xff\xfe\x00\x00garbage", 415),
        ("program.exe", b"MZ\x90\x00\x03", 415),
        ("empty.txt", b"", 422),
    ],
)
async def test_upload_type_validation(client, world, task, name, data, expected):
    r = await _upload(client, world["member"], task, name, data)
    assert r.status_code == expected, r.text


async def test_upload_size_limit(client, world, task, settings, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    big = b"a" * (1024 * 1024 + 10)
    r = await _upload(client, world["member"], task, "big.txt", big, "text/plain")
    assert r.status_code == 413


async def test_filename_is_sanitized(client, world, task):
    r = await _upload(client, world["member"], task, "../../../etc/passwd.txt", b"hello", "text/plain")
    assert r.status_code == 201 and r.json()["filename"] == "passwd.txt"
