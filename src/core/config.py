# --------------------------------------------------------------------------
# Configuration module
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import os
import secrets
import warnings
from typing import Annotated, Any, List, Literal, Union

from pydantic import AnyUrl, BeforeValidator, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


def parse_cors(v: Any) -> Union[List[str], str]:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    elif isinstance(v, (list, str)):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    """Default project configuraion module

    This base module configures your project SECRET_KEY, CORS origins and project name

    **Add your project configurations below**


    For more information, please refer to the following link:

    https://fastapi.tiangolo.com/advanced/settings/?h=config
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    SECRET_KEY: str = secrets.token_urlsafe(32)
    ENVIRONMENT: Literal["development", "production", "test"] = "development"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    CLIENT_ORIGIN: str = ""

    BACKEND_CORS_ORIGINS: Annotated[
        Union[List[AnyUrl], str], BeforeValidator(parse_cors)
    ] = []

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Security
    ALLOWED_HOSTS: List[str] = ["*"]
    ALLOWED_ORIGINS: List[str] = ["*"]

    # Auth Server
    AUTH_SERVER_URL: str = "http://auth-server:8001"

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # Database
    DATABASE_URL: str = "postgresql://bnbong:password@postgres:5432/bnbong"

    # Service Registry
    SERVICES_CONFIG_PATH: str = "/app/config/services.json"

    # Monitoring
    ENABLE_METRICS: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> List[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.CLIENT_ORIGIN
        ]

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

        return self


settings = Settings()
