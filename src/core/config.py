# --------------------------------------------------------------------------
# Configuration module
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import json
import secrets
import warnings
from typing import Annotated, Any, Callable, List, Literal, Optional, Sequence, Union
from urllib.parse import urlsplit

from pydantic import BeforeValidator, Field, computed_field, model_validator
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
    """Accept both a comma separated string and a JSON list.

    Blank entries are dropped. Splitting on commas without filtering turned a
    value such as " " into [""], and a trailing comma into a list with an
    empty origin at the end. An empty string is not an origin any browser can
    ever send, so it only made the effective allow list harder to read and
    put a meaningless entry into the Access-Control-Allow-Origin comparison.
    """
    if isinstance(v, str):
        stripped = v.strip()
        if stripped.startswith("["):
            return [item for item in _parse_json_list(stripped) if item.strip()]
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list):
        return [str(item) for item in v if str(item).strip()]
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
DEFAULT_BLOCKED_UPSTREAM_PATHS = ("/metrics",)


def blank_value_keeps_default(
    field_name: str, default: Sequence[str]
) -> Callable[[Any], Any]:
    """Build a list parser that answers a blank value with the safe default.

    `env_ignore_empty` already turns an exactly empty value into "not set",
    but a value made only of whitespace and separators, such as " " or ",",
    slips past it and parses to an empty list. For an ordinary list that is
    merely an odd way of writing "nothing". For a security policy list it
    switches the policy off without saying so: the upstream block list stops
    hiding every operational endpoint, and the destination allowlist stops
    restricting which hosts may be registered as a service.

    Since the 2026-09-19 incident this project answers a blank value on those
    fields with the declared default, so a half written variable keeps the
    policy and only an explicit JSON `[]` turns it off. A warning is emitted
    as well. When the declared default is itself an empty list the substituted
    value cannot be told apart from the blank one, so the warning is the only
    sign the operator gets that the variable never took effect.
    """
    fallback = tuple(default)

    def parser(v: Any) -> Any:
        parsed = parse_string_list(v)
        if isinstance(v, str) and not v.strip().startswith("[") and parsed == []:
            warnings.warn(
                f"{field_name} was set to a blank value ({v!r}) and has been "
                f"ignored. The declared default {list(fallback)!r} applies. "
                "Write an explicit JSON [] to turn this policy off.",
                stacklevel=1,
            )
            return list(fallback)
        return parsed

    return parser


StringList = Annotated[List[str], NoDecode, BeforeValidator(parse_string_list)]
BlockedPathList = Annotated[
    List[str],
    NoDecode,
    BeforeValidator(
        blank_value_keeps_default(
            "PROXY_BLOCKED_UPSTREAM_PATHS", DEFAULT_BLOCKED_UPSTREAM_PATHS
        )
    ),
]
AllowedServiceHostList = Annotated[
    List[str],
    NoDecode,
    BeforeValidator(blank_value_keeps_default("SERVICE_URL_ALLOWED_HOSTS", ())),
]
DeniedServiceHostList = Annotated[
    List[str],
    NoDecode,
    BeforeValidator(blank_value_keeps_default("SERVICE_URL_DENIED_HOSTS", ())),
]
CorsOriginList = Annotated[List[str], NoDecode, BeforeValidator(parse_cors)]

# Base URLs of the observability backends the admin API queries. Only http and
# https are accepted, because the gateway speaks HTTP to them and any other
# scheme would fail at request time instead of at startup.
OBSERVABILITY_URL_SCHEMES = ("http", "https")


def parse_observability_url(field_name: str) -> Callable[[Any], Any]:
    """Build a validator for an optional http(s) base URL.

    A value made only of whitespace means "not set", which matches how
    `env_ignore_empty` treats an exactly empty value and keeps a compose file
    that expands an undefined variable from enabling a half configured
    endpoint. Anything else has to be a usable base URL: a malformed value
    stops the process at startup rather than turning into a 502 the first time
    an operator opens the dashboard.
    """

    def parser(v: Any) -> Any:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError(f"{field_name} must be a string")
        candidate = v.strip()
        if not candidate:
            return None
        try:
            parts = urlsplit(candidate)
        except ValueError as exc:
            raise ValueError(f"{field_name} is not parsable: {exc}") from exc
        if parts.scheme.lower() not in OBSERVABILITY_URL_SCHEMES:
            raise ValueError(
                f"{field_name} must use one of the "
                + ", ".join(OBSERVABILITY_URL_SCHEMES)
                + " schemes"
            )
        try:
            port = parts.port
        except ValueError as exc:
            raise ValueError(f"{field_name} has an invalid port: {exc}") from exc
        if not parts.hostname:
            raise ValueError(f"{field_name} must contain a host")
        if port is not None and not (1 <= port <= 65535):
            raise ValueError(f"{field_name} port is out of range")
        if parts.query or parts.fragment:
            raise ValueError(
                f"{field_name} must not contain a query string or fragment"
            )
        return candidate.rstrip("/")

    return parser


PrometheusUrl = Annotated[
    Optional[str], BeforeValidator(parse_observability_url("PROMETHEUS_URL"))
]
AlertmanagerUrl = Annotated[
    Optional[str], BeforeValidator(parse_observability_url("ALERTMANAGER_URL"))
]


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

    # Upstream paths that must never be reachable through the public gateway.
    # Upstream services expose their Prometheus endpoint without auth because
    # only the internal scrape job is supposed to reach it, so proxying it
    # would publish it. Entries are matched segment by segment against the
    # decoded upstream path, and an entry blocks that path and everything
    # below it. An empty or blank environment value means "not set" here as
    # well, so a compose file that expands an undefined variable falls back to
    # this default instead of silently turning the block list off. Only an
    # explicit JSON [] turns the block list off.
    PROXY_BLOCKED_UPSTREAM_PATHS: BlockedPathList = list(DEFAULT_BLOCKED_UPSTREAM_PATHS)

    # Destination policy for registered services.
    # When SERVICE_URL_ALLOWED_HOSTS is non empty only those hosts may be
    # registered. SERVICE_URL_DENIED_HOSTS is always rejected. A blank value
    # keeps the declared default and warns instead of emptying the list, for
    # the reason written on blank_value_keeps_default above.
    SERVICE_URL_ALLOWED_HOSTS: AllowedServiceHostList = []
    SERVICE_URL_DENIED_HOSTS: DeniedServiceHostList = []

    # Monitoring
    ENABLE_METRICS: bool = True

    # Observability backends read by the admin observability endpoints. Both
    # are optional: when a URL is not set the matching endpoint answers 501
    # rather than pretending to have data. These are internal addresses on the
    # monitoring network, never published through the gateway.
    PROMETHEUS_URL: PrometheusUrl = None
    ALERTMANAGER_URL: AlertmanagerUrl = None

    # Budget for one observability backend call, applied to the whole call and
    # not to each transport stage. The admin dashboard polls every 30 seconds,
    # so a slow backend must fail fast instead of holding a gateway worker.
    # Zero or a negative value would make every call fail before it starts,
    # and NaN or inf would remove the budget altogether, so both are refused
    # at startup rather than at the first request.
    OBSERVABILITY_QUERY_TIMEOUT_SECONDS: float = Field(
        default=2.5, gt=0, allow_inf_nan=False
    )

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
