import pytest
import os
from unittest.mock import patch, mock_open
import importlib

# We need to test the module
from bot import config

@pytest.fixture(autouse=True)
def reset_config_state():
    """Reset the module variables before each test."""
    config.BOT_TOKEN = ""
    config.ADMIN_ID = 0
    yield

def test_load_config_from_env():
    """Test loading config from environment variables when file doesn't exist."""
    with patch("os.path.exists", return_value=False):
        with patch.dict(os.environ, {"PW_BOT_TOKEN": "123:ENV_TOKEN", "PW_ADMIN_ID": "987654"}, clear=True):
            config.load_config()
            assert config.BOT_TOKEN == "123:ENV_TOKEN"
            assert config.ADMIN_ID == 987654

def test_load_config_from_file():
    """Test loading from OpenWrt UCI config format."""
    mock_file_content = "config passwall2_bot 'main'\n    option token '123:FILE_TOKEN'\n    option admin_id '112233'\n"
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=mock_file_content)):
            config.load_config()
            assert config.BOT_TOKEN == "123:FILE_TOKEN"
            assert config.ADMIN_ID == 112233

def test_load_config_invalid_admin_id_file():
    """Test resilience against invalid admin_id in file (Fix #6)."""
    mock_file_content = "config passwall2_bot 'main'\n    option token '123:FILE'\n    option admin_id 'INVALID_STRING'\n"
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=mock_file_content)):
            config.load_config()
            assert config.BOT_TOKEN == "123:FILE"
            # Should fallback to 0 instead of crashing procd
            assert config.ADMIN_ID == 0

def test_load_config_invalid_admin_id_env():
    """Test resilience against invalid admin_id in env vars."""
    with patch("os.path.exists", return_value=False):
        with patch.dict(os.environ, {"PW_BOT_TOKEN": "123:ENV", "PW_ADMIN_ID": "NOT_A_NUMBER"}, clear=True):
            config.load_config()
            assert config.BOT_TOKEN == "123:ENV"
            assert config.ADMIN_ID == 0
