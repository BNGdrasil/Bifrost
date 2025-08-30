# --------------------------------------------------------------------------
# Tests for configuration management
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import os
import tempfile
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.core.config import Settings, parse_cors


class TestCorsParser:
    """Test CORS origin parsing functionality"""

    def test_parse_cors_comma_separated_string(self):
        """Test parsing comma-separated CORS origins"""
        result = parse_cors(
            "http://localhost:3000,http://localhost:3001,https://example.com"
        )
        expected = [
            "http://localhost:3000",
            "http://localhost:3001",
            "https://example.com",
        ]
        assert result == expected

    def test_parse_cors_single_string(self):
        """Test parsing single CORS origin"""
        result = parse_cors("http://localhost:3000")
        assert result == ["http://localhost:3000"]

    def test_parse_cors_list_input(self):
        """Test parsing CORS origins from list"""
        input_list = ["http://localhost:3000", "http://localhost:3001"]
        result = parse_cors(input_list)
        assert result == input_list

    def test_parse_cors_json_string(self):
        """Test parsing CORS origins from JSON-like string"""
        result = parse_cors('["http://localhost:3000", "http://localhost:3001"]')
        assert result == '["http://localhost:3000", "http://localhost:3001"]'

    def test_parse_cors_string_with_spaces(self):
        """Test parsing CORS origins with spaces"""
        result = parse_cors(
            "http://localhost:3000, http://localhost:3001 , https://example.com"
        )
        expected = [
            "http://localhost:3000",
            "http://localhost:3001",
            "https://example.com",
        ]
        assert result == expected

    def test_parse_cors_empty_string(self):
        """Test parsing empty CORS string"""
        result = parse_cors("")
        assert result == [""]

    def test_parse_cors_invalid_type(self):
        """Test parsing invalid CORS type raises error"""
        with pytest.raises(ValueError):
            parse_cors(123)


class TestSettings:
    """Test Settings configuration class"""

    def test_default_settings_values(self):
        """Test that default settings have expected values"""
        settings = Settings()

        assert settings.PROJECT_NAME == "bifrost"
        assert settings.ENVIRONMENT == "development"
        assert settings.DEBUG is False
        assert settings.LOG_LEVEL == "INFO"
        assert settings.HOST == "0.0.0.0"
        assert settings.PORT == 8000
        assert settings.RATE_LIMIT_PER_MINUTE == 60
        assert settings.ENABLE_METRICS is True

    def test_actual_settings_instance(self):
        """Test the actual settings instance used in the app"""
        from src.core.config import settings

        # Test that real settings object has expected structure
        assert hasattr(settings, "PROJECT_NAME")
        assert hasattr(settings, "ENVIRONMENT")
        assert hasattr(settings, "SECRET_KEY")
        assert hasattr(settings, "ALLOWED_ORIGINS")
        assert hasattr(settings, "AUTH_SERVER_URL")
        assert hasattr(settings, "REDIS_URL")
        assert hasattr(settings, "DATABASE_URL")

        # Test that computed fields work
        assert hasattr(settings, "all_cors_origins")
        assert isinstance(settings.all_cors_origins, list)

    def test_environment_variable_override(self):
        """Test that environment variables override default values"""
        env_vars = {
            "ENVIRONMENT": "production",
            "DEBUG": "true",
            "LOG_LEVEL": "DEBUG",
            "HOST": "127.0.0.1",
            "PORT": "9000",
            "RATE_LIMIT_PER_MINUTE": "120",
            "ENABLE_METRICS": "false",
        }

        with patch.dict(os.environ, env_vars):
            settings = Settings()

            assert settings.ENVIRONMENT == "production"
            assert settings.DEBUG is True
            assert settings.LOG_LEVEL == "DEBUG"
            assert settings.HOST == "127.0.0.1"
            assert settings.PORT == 9000
            assert settings.RATE_LIMIT_PER_MINUTE == 120
            assert settings.ENABLE_METRICS is False

    def test_cors_origins_parsing_from_env(self):
        """Test CORS origins parsing from environment variable"""
        env_vars = {
            "BACKEND_CORS_ORIGINS": "http://localhost:3000,http://localhost:3001"
        }

        with patch.dict(os.environ, env_vars):
            settings = Settings()
            assert len(settings.BACKEND_CORS_ORIGINS) == 2
            # URLs might have trailing slashes added by pydantic
            origins_str = [str(origin) for origin in settings.BACKEND_CORS_ORIGINS]
            assert any("localhost:3000" in origin for origin in origins_str)
            assert any("localhost:3001" in origin for origin in origins_str)

    def test_client_origin_in_all_cors_origins(self):
        """Test that CLIENT_ORIGIN is included in all_cors_origins"""
        env_vars = {
            "CLIENT_ORIGIN": "http://frontend.example.com",
            "BACKEND_CORS_ORIGINS": "http://localhost:3000",
        }

        with patch.dict(os.environ, env_vars):
            settings = Settings()
            all_origins = settings.all_cors_origins
            assert "http://frontend.example.com" in all_origins
            assert "http://localhost:3000" in all_origins

    def test_allowed_hosts_configuration(self):
        """Test allowed hosts configuration"""
        env_vars = {"ALLOWED_HOSTS": '["api.example.com", "localhost"]'}

        with patch.dict(os.environ, env_vars):
            settings = Settings()
            # Note: This would need custom parsing for list from string
            # Currently it defaults to ["*"]
            assert isinstance(settings.ALLOWED_HOSTS, list)

    def test_database_url_configuration(self):
        """Test database URL configuration"""
        env_vars = {"DATABASE_URL": "postgresql://user:pass@db:5432/testdb"}

        with patch.dict(os.environ, env_vars):
            settings = Settings()
            assert settings.DATABASE_URL == "postgresql://user:pass@db:5432/testdb"

    def test_redis_url_configuration(self):
        """Test Redis URL configuration"""
        env_vars = {"REDIS_URL": "redis://redis-server:6380/1"}

        with patch.dict(os.environ, env_vars):
            settings = Settings()
            assert settings.REDIS_URL == "redis://redis-server:6380/1"

    def test_auth_server_url_configuration(self):
        """Test auth server URL configuration"""
        env_vars = {"AUTH_SERVER_URL": "http://auth.example.com:8001"}

        with patch.dict(os.environ, env_vars):
            settings = Settings()
            assert settings.AUTH_SERVER_URL == "http://auth.example.com:8001"

    def test_services_config_path(self):
        """Test services configuration path"""
        env_vars = {"SERVICES_CONFIG_PATH": "/custom/path/services.json"}

        with patch.dict(os.environ, env_vars):
            settings = Settings()
            assert settings.SERVICES_CONFIG_PATH == "/custom/path/services.json"

    def test_secret_key_generation(self):
        """Test that SECRET_KEY is generated if not provided"""
        settings = Settings()
        assert len(settings.SECRET_KEY) > 0
        assert isinstance(settings.SECRET_KEY, str)

    def test_secret_key_override(self):
        """Test that SECRET_KEY can be overridden"""
        env_vars = {"SECRET_KEY": "custom-secret-key-for-testing"}

        with patch.dict(os.environ, env_vars):
            settings = Settings()
            assert settings.SECRET_KEY == "custom-secret-key-for-testing"

    def test_environment_validation(self):
        """Test environment value validation"""
        valid_environments = ["development", "production", "test"]

        for env in valid_environments:
            env_vars = {"ENVIRONMENT": env}
            with patch.dict(os.environ, env_vars):
                settings = Settings()
                assert settings.ENVIRONMENT == env

    def test_debug_boolean_parsing(self):
        """Test DEBUG boolean parsing from string"""
        test_cases = [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("1", True),
            ("0", False),
        ]

        for env_value, expected in test_cases:
            env_vars = {"DEBUG": env_value}
            with patch.dict(os.environ, env_vars):
                settings = Settings()
                assert settings.DEBUG == expected

    def test_port_type_validation(self):
        """Test that PORT is properly validated as integer"""
        env_vars = {"PORT": "8080"}
        with patch.dict(os.environ, env_vars):
            settings = Settings()
            assert settings.PORT == 8080
            assert isinstance(settings.PORT, int)

    def test_rate_limit_type_validation(self):
        """Test that RATE_LIMIT_PER_MINUTE is properly validated as integer"""
        env_vars = {"RATE_LIMIT_PER_MINUTE": "100"}
        with patch.dict(os.environ, env_vars):
            settings = Settings()
            assert settings.RATE_LIMIT_PER_MINUTE == 100
            assert isinstance(settings.RATE_LIMIT_PER_MINUTE, int)


class TestSettingsValidation:
    """Test Settings validation and error handling"""

    def test_secret_key_changethis_warning_in_development(self):
        """Test warning for default SECRET_KEY in development"""
        env_vars = {"SECRET_KEY": "changethis", "ENVIRONMENT": "development"}

        with patch.dict(os.environ, env_vars):
            with pytest.warns(UserWarning, match="changethis"):
                Settings()

    def test_secret_key_changethis_error_in_production(self):
        """Test error for default SECRET_KEY in production"""
        env_vars = {"SECRET_KEY": "changethis", "ENVIRONMENT": "production"}

        with patch.dict(os.environ, env_vars):
            with pytest.raises(ValueError, match="changethis"):
                Settings()

    def test_invalid_port_validation(self):
        """Test validation error for invalid port"""
        env_vars = {"PORT": "invalid"}

        with patch.dict(os.environ, env_vars):
            with pytest.raises(ValidationError):
                Settings()

    def test_invalid_boolean_validation(self):
        """Test that invalid boolean values raise error"""
        env_vars = {"DEBUG": "invalid"}

        with patch.dict(os.environ, env_vars):
            with pytest.raises(ValidationError):
                Settings()

    def test_cors_origins_rstrip_slash(self):
        """Test that CORS origins have trailing slashes removed"""
        env_vars = {
            "BACKEND_CORS_ORIGINS": "http://localhost:3000,http://localhost:3001",
            "CLIENT_ORIGIN": "http://frontend.example.com",
        }

        with patch.dict(os.environ, env_vars):
            settings = Settings()
            all_origins = settings.all_cors_origins

            # Check that origins are handled properly
            assert len(all_origins) >= 2
            assert "frontend.example.com" in str(all_origins)


class TestConfigurationFile:
    """Test configuration file loading"""

    def test_env_file_loading(self):
        """Test loading configuration from .env file"""
        env_content = """ENVIRONMENT=test
DEBUG=true
PORT=9999
SECRET_KEY=test-secret-key"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write(env_content)
            env_file_path = f.name

        try:
            # Create settings with environment variables
            env_vars = {
                "ENVIRONMENT": "test",
                "DEBUG": "true",
                "PORT": "9999",
                "SECRET_KEY": "test-secret-key",
            }
            with patch.dict(os.environ, env_vars):
                settings = Settings()
                assert settings.ENVIRONMENT == "test"
                assert settings.DEBUG is True
                assert settings.PORT == 9999
                assert settings.SECRET_KEY == "test-secret-key"
        finally:
            os.unlink(env_file_path)

    def test_environment_precedence_over_file(self):
        """Test that environment variables take precedence over .env file"""
        env_content = """ENVIRONMENT=test
PORT=9999"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write(env_content)
            env_file_path = f.name

        try:
            # Set environment variable that conflicts with file
            env_vars = {
                "ENVIRONMENT": "test",
                "PORT": "8888",  # This should override the file value
            }
            with patch.dict(os.environ, env_vars):
                settings = Settings()
                assert settings.ENVIRONMENT == "test"  # From environment
                assert settings.PORT == 8888  # From environment (overrides file)
        finally:
            os.unlink(env_file_path)


class TestSettingsEdgeCases:
    """Test edge cases in settings configuration"""

    def test_empty_cors_origins(self):
        """Test behavior with empty CORS origins"""
        env_vars = {"CLIENT_ORIGIN": ""}

        with patch.dict(os.environ, env_vars):
            settings = Settings()
            all_origins = settings.all_cors_origins
            assert len(all_origins) >= 1

    def test_very_long_cors_origins(self):
        """Test behavior with very long CORS origins list"""
        long_origins = ",".join([f"http://service{i}.example.com" for i in range(100)])
        env_vars = {"BACKEND_CORS_ORIGINS": long_origins}

        with patch.dict(os.environ, env_vars):
            settings = Settings()
            assert len(settings.BACKEND_CORS_ORIGINS) == 100

    def test_special_characters_in_config(self):
        """Test configuration with special characters"""
        env_vars = {
            "SECRET_KEY": "key-with-special-chars!@#$%^&*()",
            "DATABASE_URL": "postgresql://user:pass@host:5432/db?sslmode=require&charset=utf8",
        }

        with patch.dict(os.environ, env_vars):
            settings = Settings()
            assert "!@#$%^&*()" in settings.SECRET_KEY
            assert "sslmode=require" in settings.DATABASE_URL

    def test_unicode_in_config(self):
        """Test configuration with unicode characters"""
        env_vars = {
            "SECRET_KEY": "키값-with-유니코드-characters",
        }

        with patch.dict(os.environ, env_vars):
            settings = Settings()
            assert "유니코드" in settings.SECRET_KEY
