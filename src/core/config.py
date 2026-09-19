# --------------------------------------------------------------------------
# Configuration module
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import json
import secrets
import warnings
from typing import Annotated, Any, List, Literal, Union

from pydantic import BeforeValidator, computed_field, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from typing_extensions import Self

# Values that ship in example files and must never be used in production.
EXAMPLE_SECRET_VALUES = frozenset(
    {
        "changethis",
        "your-secret-key-here",
        "secret",
        "secret-key",
        "test-secret-key",
        "thisistestsecretkeyhehe",
    }
)

MINIMUM_PRODUCTION_SECRET_LENGTH = 32

DEFAULT_DATABASE_URL = "postgresql://bnbong:password@postgres:5432/bngdrasil"


def _parse_json_list(value: str) -> List[str]:
    try:
        decoded = json.loads(value)
    except ValueError as exc:
        raise ValueError(f"{value} is not a valid JSON list") from exc
    if not isinstance(decoded, list):
        raise ValueError(f"{value} is not a JSON list")
    return [str(item) for item in decoded]


def parse_cors(v: Any) -> List[str]:
    """Accept both a comma separated string and a JSON list."""
    if isinstance(v, str):
        stripped = v.strip()
        if stripped.startswith("["):
            return _parse_json_list(stripped)
        return [i.strip() for i in v.split(",")]
    elif isinstance(v, list):
        return [str(item) for item in v]
    raise ValueError(v)


def parse_string_list(v: Any) -> Any:
    """Accept both a comma separated string and a JSON list for plain lists."""
    if isinstance(v, str):
        stripped = v.strip()
        if stripped.startswith("["):
            return _parse_json_list(stripped)
        if not stripped:
            return []
        return [item.strip() for item in stripped.split(",") if item.strip()]
    return v


# NoDecode stops pydantic-settings from JSON decoding the environment value
# before validation. Without it a plain comma separated value, or an empty
# value, makes the process fail to start instead of reaching the parser below.
StringList = Annotated[List[str], NoDecode, BeforeValidator(parse_string_list)]
CorsOriginList = Annotated[List[str], NoDecode, BeforeValidator(parse_cors)]


class Settings(BaseSettings):
    """Runtime configuration for the Bifrost API gateway.

    Every value declared here is consumed by the application. Settings that
    are not read anywhere must be removed instead of being kept for display.

    For more information, please refer to the following link:

    https://fastapi.tiangolo.com/advanced/settings/?h=config
    """

    # env_ignore_empty makes an empty environment value mean "not set", so a
    # compose file that expands an unset variable into ENABLE_METRICS= or
    # MAX_REQUEST_BODY_BYTES= falls back to the default instead of failing to
    # parse. The production checks below still refuse an empty required value,
    # because "not set" reaches them as the empty default.
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_ignore_empty=True,
    )

    SECRET_KEY: str = ""
    ENVIRONMENT: Literal["development", "production", "test"] = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    CLIENT_ORIGIN: str = ""

    # CORS. This is the single source of truth for the CORS middleware.
    # Accepts a comma separated string or a JSON list.
    BACKEND_CORS_ORIGINS: CorsOriginList = ["*"]

    # Server. Binding to all interfaces is intentional inside the container;
    # external exposure is restricted by the host firewall and the reverse
    # proxy, not by the bind address.
    HOST: str = "0.0.0.0"  # nosec B104
    PORT: int = 8000

    # Host header allowlist for TrustedHostMiddleware. Production must name
    # the hosts it serves: neither an empty list nor a wildcard is accepted
    # there, because both turn the host check off without saying so.
    ALLOWED_HOSTS: StringList = []

    # Reverse proxy addresses uvicorn accepts forwarded headers from. This is
    # the single source for both the console entry point and the container
    # command, so a typo cannot silently widen the trusted set.
    FORWARDED_ALLOW_IPS: str = "127.0.0.1"

    # Auth Server
    AUTH_SERVER_URL: str = "http://auth-server:8001"

    # Base path of the user management API on the auth server. The admin
    # proxy calls AUTH_SERVER_URL + this path, so the default needs no extra
    # configuration. Override it only when the auth server moves the router.
    AUTH_SERVER_USERS_PATH: str = "/users"

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_EXEMPT_PATHS: StringList = ["/health", "/ready", "/metrics"]

    # Database
    DATABASE_URL: str = ""

    # Proxy
    # Buffered proxy: the whole request and response body is held in memory.
    MAX_REQUEST_BODY_BYTES: int = 10 * 1024 * 1024
    PROXY_TIMEOUT_SECONDS: float = 30.0
    PROXY_MAX_CONNECTIONS: int = 100

    # Destination policy for registered services.
    # When SERVICE_URL_ALLOWED_HOSTS is non empty only those hosts may be
    # registered. SERVICE_URL_DENIED_HOSTS is always rejected.
    SERVICE_URL_ALLOWED_HOSTS: StringList = []
    SERVICE_URL_DENIED_HOSTS: StringList = []

    # Monitoring
    ENABLE_METRICS: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> List[str]:
        origins = [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS]
        if self.CLIENT_ORIGIN:
            origins.append(self.CLIENT_ORIGIN.rstrip("/"))
        return origins

    PROJECT_NAME: str = "bifrost"

    def _check_default_secret(self, var_name: str, value: Union[str, None]) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "development":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)

        if self.ENVIRONMENT == "production":
            if not self.SECRET_KEY:
                raise ValueError("SECRET_KEY must be set in production.")
            if self.SECRET_KEY in EXAMPLE_SECRET_VALUES:
                raise ValueError(
                    "SECRET_KEY is an example value and cannot be used in production."
                )
            if len(self.SECRET_KEY) < MINIMUM_PRODUCTION_SECRET_LENGTH:
                raise ValueError(
                    "SECRET_KEY must be at least "
                    f"{MINIMUM_PRODUCTION_SECRET_LENGTH} characters in production."
                )
            if not self.DATABASE_URL:
                raise ValueError("DATABASE_URL must be set in production.")
            if not self.ALLOWED_HOSTS:
                raise ValueError(
                    "ALLOWED_HOSTS must list the host names served in "
                    "production. Host header checking is not optional there."
                )
            if "*" in self.ALLOWED_HOSTS:
                raise ValueError(
                    "ALLOWED_HOSTS must not contain '*' in production. "
                    "List the host names this gateway serves instead."
                )
            if "*" in self.all_cors_origins:
                warnings.warn(
                    "BACKEND_CORS_ORIGINS contains '*' in production. "
                    "Credentialed browser requests will be rejected by browsers.",
                    stacklevel=1,
                )

        if not self.ALLOWED_HOSTS:
            warnings.warn(
                "ALLOWED_HOSTS is empty; falling back to '*' outside "
                "production. Set it explicitly to enable host checking.",
                stacklevel=1,
            )
            self.ALLOWED_HOSTS = ["*"]

        if not self.SECRET_KEY:
            # Outside production an ephemeral key keeps local runs working.
            self.SECRET_KEY = secrets.token_urlsafe(32)
        if not self.DATABASE_URL:
            self.DATABASE_URL = DEFAULT_DATABASE_URL

        return self


settings = Settings()
