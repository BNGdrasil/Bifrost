# --------------------------------------------------------------------------
# Tests for the upstream destination policy
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import pytest
from pydantic import ValidationError

from src.core.urlpolicy import ServiceUrlPolicyError, validate_service_url
from src.schemas.service import ServiceCreate, ServiceUpdate

ALLOWED_URLS = [
    "http://qshing-server:8080",
    "https://api.internal.example.com",
    "http://10.0.0.5:8000",
    "http://172.16.3.4",
    "http://192.168.1.10:9000/base",
    "http://bifrost-test:8000/api",
]

REJECTED_URLS = [
    "ftp://example.com",
    "file:///etc/passwd",
    "http://",
    "https://",
    "http://user:pass@internal:8000",
    "http://127.0.0.1:8000",
    "http://127.30.1.2",
    "https://localhost:8443",
    "http://service.localhost",
    "http://[::1]:8000",
    "http://169.254.169.254/latest/meta-data",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://0.0.0.0:8000",
    "http://example.com:99999",
    "http://example.com/path?query=1",
]


class TestServiceUrlPolicy:
    """Destination policy for registered upstream services"""

    @pytest.mark.parametrize("url", ALLOWED_URLS)
    def test_allowed_urls(self, url: str):
        assert validate_service_url(url) == url.rstrip("/")

    @pytest.mark.parametrize("url", REJECTED_URLS)
    def test_rejected_urls(self, url: str):
        with pytest.raises(ServiceUrlPolicyError):
            validate_service_url(url)

    def test_trailing_slash_is_normalised(self):
        assert validate_service_url("http://svc:8080/") == "http://svc:8080"

    def test_denylist_from_settings(self, monkeypatch):
        from src.core.config import settings

        monkeypatch.setattr(settings, "SERVICE_URL_DENIED_HOSTS", ["blocked-host"])
        with pytest.raises(ServiceUrlPolicyError):
            validate_service_url("http://blocked-host:8080")

    def test_allowlist_from_settings(self, monkeypatch):
        from src.core.config import settings

        monkeypatch.setattr(settings, "SERVICE_URL_ALLOWED_HOSTS", ["only-this"])
        assert validate_service_url("http://only-this:8080")
        with pytest.raises(ServiceUrlPolicyError):
            validate_service_url("http://other-host:8080")


class TestServiceSchemaValidation:
    """The policy must be enforced by the write schemas"""

    def test_create_rejects_loopback(self):
        with pytest.raises(ValidationError):
            ServiceCreate(name="bad", url="http://127.0.0.1:8000")

    def test_create_rejects_metadata_address(self):
        with pytest.raises(ValidationError):
            ServiceCreate(name="bad", url="http://169.254.169.254")

    def test_create_accepts_private_network(self):
        service = ServiceCreate(name="ok", url="http://10.1.2.3:8080")
        assert service.url == "http://10.1.2.3:8080"

    def test_update_rejects_loopback(self):
        with pytest.raises(ValidationError):
            ServiceUpdate(url="https://localhost:9000")

    def test_update_allows_none(self):
        assert ServiceUpdate().url is None

    def test_health_check_path_must_be_relative(self):
        with pytest.raises(ValidationError):
            ServiceCreate(
                name="ok", url="http://svc:8080", health_check_path="http://evil/health"
            )

    def test_health_check_path_rejects_traversal(self):
        with pytest.raises(ValidationError):
            ServiceCreate(
                name="ok", url="http://svc:8080", health_check_path="/../secret"
            )


class TestAddressLiteralForms:
    """Shortened, octal and hexadecimal literals must be resolved, not trusted"""

    @pytest.mark.parametrize(
        "url",
        [
            "http://2130706433/x",
            "http://0x7f000001",
            "http://127.1",
            "http://0177.0.0.1",
            "http://017700000001",
            "http://[::ffff:127.0.0.1]",
            "http://2852039166",
            "http://0xa9fea9fe",
        ],
    )
    def test_obfuscated_forbidden_addresses_are_rejected(self, url: str):
        with pytest.raises(ServiceUrlPolicyError):
            validate_service_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://10.0.0.5:8080",
            "http://[::ffff:10.0.0.5]",
            "http://172.16.0.1",
            "http://192.168.1.10",
        ],
    )
    def test_private_addresses_stay_allowed(self, url: str):
        assert validate_service_url(url) == url

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost./a",
            "http://LOCALHOST.",
            "http://metadata.google.internal.",
        ],
    )
    def test_trailing_dot_does_not_bypass_the_blocklist(self, url: str):
        with pytest.raises(ServiceUrlPolicyError):
            validate_service_url(url)

    def test_undecidable_numeric_host_is_rejected(self):
        with pytest.raises(ServiceUrlPolicyError):
            validate_service_url("http://999.999.999.999")

    def test_hostname_with_digits_is_still_allowed(self):
        assert validate_service_url("http://svc-1.internal:8080")
        assert validate_service_url("http://a1b2c3:9000")
