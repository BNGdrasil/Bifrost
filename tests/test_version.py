# --------------------------------------------------------------------------
# Tests for version management.
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import re

import src


def test_version_format() -> None:
    """Test that version follows semantic versioning format."""
    version = src.__version__

    # Check semantic versioning format (e.g., "0.1.0", "1.2.3", "2.0.0-alpha.1")
    semver_pattern = r"^\d+\.\d+\.\d+(?:-[a-zA-Z0-9\-\.]+)?$"
    assert re.match(
        semver_pattern, version
    ), f"Version '{version}' does not follow semantic versioning"


def test_version_is_string() -> None:
    """Test that version is a string."""
    assert isinstance(src.__version__, str)


def test_version_not_empty() -> None:
    """Test that version is not empty."""
    assert len(src.__version__.strip()) > 0
