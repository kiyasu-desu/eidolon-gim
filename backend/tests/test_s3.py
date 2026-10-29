"""Generic S3 signing and fake bucket shared by backup and greeting tests."""
import hashlib
from datetime import UTC, datetime
from urllib.parse import parse_qs, unquote, urlsplit
from xml.sax.saxutils import escape
import httpx
import pytest
from eidolon.s3 import Bucket, S3Error, S3Settings, sign

EXAMPLE_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
EXAMPLE_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
EXAMPLE_TIME = datetime(2013, 5, 24, tzinfo=UTC)


def example_signature(method: str, url: str, headers: dict[str, str], payload_hash: str) -> str:
    signed = sign(
        method, httpx.URL(url), headers, payload_hash,
        key_id=EXAMPLE_KEY_ID, secret=EXAMPLE_SECRET, region="us-east-1", now=EXAMPLE_TIME,
    )
    return signed["Authorization"]


def test_signing_matches_amazons_example_of_getting_an_object():
    authorization = example_signature(
        "GET", "https://examplebucket.s3.amazonaws.com/test.txt", {"Range": "bytes=0-9"}, EMPTY_SHA256
    )

    assert authorization == (
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
        "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )


def test_signing_matches_amazons_example_of_putting_an_object():
    body = b"Welcome to Amazon S3."
    authorization = example_signature(
        "PUT",
        "https://examplebucket.s3.amazonaws.com/test$file.text",
        {"Date": "Fri, 24 May 2013 00:00:00 GMT", "x-amz-storage-class": "REDUCED_REDUNDANCY"},
        hashlib.sha256(body).hexdigest(),
    )

    assert authorization.endswith(
        "SignedHeaders=date;host;x-amz-content-sha256;x-amz-date;x-amz-storage-class, "
        "Signature=98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd"
    )


def test_signing_matches_amazons_example_of_listing_a_bucket():
    authorization = example_signature(
        "GET", "https://examplebucket.s3.amazonaws.com/?max-keys=2&prefix=J", {}, EMPTY_SHA256
    )

    assert authorization.endswith(
        "Signature=34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7"
    )


class FakeBucket:
    """An S3-compatible bucket at http://storage.test/<name> (path-style) that keeps what
    it is sent, lists two keys a page (those under the prefix asked for), and refuses
    unsigned requests."""

    def __init__(self, name: str = "stands") -> None:
        self.name = name
        self.objects: dict[str, tuple[bytes, dict[str, str]]] = {}
        self.puts: list[str] = []
        self.deletes: list[str] = []
        self.down = False
        self.lists_by_marker = False
        """List as the original List Objects does (Tencent COS): pages by `marker`,
        whatever `list-type` asks for."""

    def bucket(self, **settings) -> Bucket:
        return Bucket(
            S3Settings("http://storage.test", self.name, "key-id", "secret", **settings),
            transport=httpx.MockTransport(self.handle),
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            return httpx.Response(503, text="<Error><Code>SlowDown</Code></Error>")
        if not request.headers.get("Authorization", "").startswith("AWS4-HMAC-SHA256 Credential=key-id/"):
            return httpx.Response(403, text="<Error><Code>AccessDenied</Code></Error>")
        path = urlsplit(str(request.url)).path
        assert path == f"/{self.name}" or path.startswith(f"/{self.name}/"), path
        key = unquote(path.removeprefix(f"/{self.name}").removeprefix("/"))
        if request.method == "PUT":
            body = request.read()
            assert request.headers["x-amz-content-sha256"] == hashlib.sha256(body).hexdigest()
            assert request.headers["Content-Length"] == str(len(body))
            assert "Transfer-Encoding" not in request.headers
            self.objects[key] = (body, dict(request.headers))
            self.puts.append(key)
            return httpx.Response(200, headers={"ETag": f'"{hashlib.md5(body).hexdigest()}"'})
        if request.method == "DELETE":
            self.objects.pop(key, None)
            self.deletes.append(key)
            return httpx.Response(204)
        query = parse_qs(urlsplit(str(request.url)).query)
        assert request.method == "GET" and query["list-type"] == ["2"]
        prefix = query.get("prefix", [""])[0]
        keys = sorted(key for key in self.objects if key.startswith(prefix))
        if self.lists_by_marker:
            marker = query.get("marker", [""])[0]
            start = sum(1 for key in keys if key <= marker) if marker else 0
        else:
            start = int(query.get("continuation-token", ["0"])[0])
        page = keys[start : start + 2]
        more = start + 2 < len(keys)
        contents = "".join(
            f"<Contents><Key>{escape(key)}</Key>"
            f"<ETag>&quot;{hashlib.md5(self.objects[key][0]).hexdigest()}&quot;</ETag>"
            f"<Size>{len(self.objects[key][0])}</Size></Contents>"
            for key in page
        )
        token = f"<NextContinuationToken>{start + 2}</NextContinuationToken>" if more else ""
        if self.lists_by_marker:
            token = f"<NextMarker>{escape(page[-1])}</NextMarker>" if more else ""
        return httpx.Response(
            200,
            text='<?xml version="1.0" encoding="UTF-8"?>'
            '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f"<IsTruncated>{'true' if more else 'false'}</IsTruncated>{token}{contents}</ListBucketResult>",
        )


@pytest.fixture
def storage() -> FakeBucket:
    return FakeBucket()



async def test_a_bucket_listed_by_marker_is_listed_whole(storage: FakeBucket):
    storage.objects = {f"item-{i}": (b"payload", {}) for i in range(5)}
    storage.lists_by_marker = True
    bucket = storage.bucket()
    try:
        assert set(await bucket.objects()) == set(storage.objects)
    finally:
        await bucket.aclose()


async def test_a_bucket_that_fails_is_an_error(storage: FakeBucket):
    storage.down = True
    bucket = storage.bucket()
    try:
        with pytest.raises(S3Error, match="503"):
            await bucket.objects()
    finally:
        await bucket.aclose()


async def test_a_virtual_hosted_bucket_is_addressed_by_its_host():
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200)

    bucket = Bucket(
        S3Settings("https://oss-cn-hangzhou.aliyuncs.com", "stands", "key-id", "secret", virtual_host=True),
        transport=httpx.MockTransport(handle),
    )
    try:
        await bucket.put("outfits/1.json", b"{}", "application/json", "no-cache")
    finally:
        await bucket.aclose()

    assert seen == ["https://stands.oss-cn-hangzhou.aliyuncs.com/outfits/1.json"]


def test_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EIDOLON_STAND_S3_ENDPOINT", "https://account.r2.cloudflarestorage.com/")
    monkeypatch.setenv("EIDOLON_STAND_S3_BUCKET", "stands")
    monkeypatch.setenv("EIDOLON_STAND_S3_ACCESS_KEY_ID", "key-id")
    monkeypatch.setenv("EIDOLON_STAND_S3_SECRET_ACCESS_KEY", "secret")

    assert S3Settings.from_env() == S3Settings(
        "https://account.r2.cloudflarestorage.com", "stands", "key-id", "secret", region="us-east-1"
    )

    monkeypatch.setenv("EIDOLON_STAND_S3_REGION", "ap-shanghai")
    monkeypatch.setenv("EIDOLON_STAND_S3_ADDRESSING", "virtual")
    assert S3Settings.from_env() == S3Settings(
        "https://account.r2.cloudflarestorage.com", "stands", "key-id", "secret",
        region="ap-shanghai", virtual_host=True,
    )


def test_settings_missing_from_the_environment_are_an_error(monkeypatch: pytest.MonkeyPatch):
    missing = "EIDOLON_STAND_S3_SECRET_ACCESS_KEY"
    for name, value in {
        "EIDOLON_STAND_S3_ENDPOINT": "https://storage.example",
        "EIDOLON_STAND_S3_BUCKET": "stands",
        "EIDOLON_STAND_S3_ACCESS_KEY_ID": "key-id",
        "EIDOLON_STAND_S3_SECRET_ACCESS_KEY": "secret",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(missing)

    with pytest.raises(RuntimeError, match=missing):
        S3Settings.from_env()
