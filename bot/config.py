"""
PassWall 2 Telegram Bot - Configuration (Hardened)
Reads bot token and admin user ID from /etc/config/passwall2_bot on OpenWrt,
or from environment variables for local development.

Fix #6: Safe parsing of environment variables to prevent procd boot loops.
"""
import os
import logging

logger = logging.getLogger("passwall2_bot")

# Paths
CONFIG_PATH = "/etc/config/passwall2_bot"
PASSWALL_CONFIG = "passwall2"
PASSWALL_SERVER_CONFIG = "passwall2_server"
LOG_FILE = "/tmp/log/passwall2.log"
SERVER_LOG_FILE = "/tmp/log/passwall2_server.log"
TMP_PATH = "/tmp/etc/passwall2"
BACKUP_FILES = [
    "/etc/config/passwall2",
    "/etc/config/passwall2_server",
    "/usr/share/passwall2/domains_excluded",
]

# Telegram API
POLL_TIMEOUT = 30  # Long polling timeout in seconds

# Initialize with safe defaults (no int() at module level!)
BOT_TOKEN = ""
ADMIN_ID = 0


def load_config():
    """Load configuration from the OpenWrt UCI config file or environment.
    Safe: wraps int() in try/except to prevent fatal crashes on bad input.
    """
    global BOT_TOKEN, ADMIN_ID

    # Try UCI config file first (OpenWrt)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("option token"):
                        BOT_TOKEN = line.split("'")[1] if "'" in line else line.split()[-1]
                    elif line.startswith("option admin_id"):
                        val = line.split("'")[1] if "'" in line else line.split()[-1]
                        try:
                            ADMIN_ID = int(val)
                        except (ValueError, IndexError):
                            logger.warning("Invalid admin_id in config: '%s', defaulting to 0", val)
                            ADMIN_ID = 0
        except Exception as e:
            logger.error("Failed to read config file %s: %s", CONFIG_PATH, e)

    # Fallback to environment variables
    if not BOT_TOKEN:
        BOT_TOKEN = os.environ.get("PW_BOT_TOKEN", "")

    if not ADMIN_ID:
        env_id = os.environ.get("PW_ADMIN_ID", "0")
        try:
            ADMIN_ID = int(env_id)
        except ValueError:
            logger.warning("Invalid PW_ADMIN_ID env var: '%s', defaulting to 0", env_id)
            ADMIN_ID = 0
