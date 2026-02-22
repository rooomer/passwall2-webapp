#!/bin/sh
# ═══════════════════════════════════════════════════════════════
#  PassWall 2 Telegram Bot - OpenWrt Installer (Hardened)
#  Supports: ARMv7 / MIPS / x86 running OpenWrt 22.03+
#
#  Fix #7: Supports command-line flags for non-interactive SSH:
#    ./install.sh -t BOT_TOKEN -a ADMIN_ID
# ═══════════════════════════════════════════════════════════════

set -e

INSTALL_DIR="/usr/share/passwall2_bot"
CONFIG_FILE="/etc/config/passwall2_bot"
INIT_SCRIPT="/etc/init.d/passwall2_bot"

# ─── Parse CLI Flags ───────────────────────────────────────────
BOT_TOKEN=""
ADMIN_ID=""

while [ $# -gt 0 ]; do
    case "$1" in
        -t|--token)
            BOT_TOKEN="$2"
            shift 2
            ;;
        -a|--admin)
            ADMIN_ID="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [-t BOT_TOKEN] [-a ADMIN_ID]"
            echo ""
            echo "Options:"
            echo "  -t, --token   Telegram Bot Token (from @BotFather)"
            echo "  -a, --admin   Your Telegram numeric User ID"
            echo ""
            echo "If not provided, the script will prompt interactively."
            exit 0
            ;;
        *)
            echo "[!] Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "========================================"
echo "  PassWall 2 Telegram Bot Installer"
echo "========================================"
echo ""

# Determine script directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ─── Check for Python 3 ────────────────────────────────────────
needs_python=0

if ! command -v python3 > /dev/null 2>&1; then
    needs_python=1
elif ! python3 -c "import json, urllib.request; print('Python3 OK')" > /dev/null 2>&1; then
    needs_python=1
fi

if [ "$needs_python" -eq 1 ]; then
    echo "[*] Python3 or urllib is missing."
    if [ -d "$SCRIPT_DIR/offline_pkgs" ] && ls "$SCRIPT_DIR/offline_pkgs/"*.ipk >/dev/null 2>&1; then
        echo "[*] Found offline packages in $SCRIPT_DIR/offline_pkgs/."
        echo "[*] Installing offline packages..."
        opkg install "$SCRIPT_DIR/offline_pkgs/"*.ipk
    else
        echo "[*] No offline packages found. Attempting online installation..."
        opkg update
        opkg install python3-light python3-urllib
    fi
fi

echo "[✓] Python 3 is ready."

# ─── Ask for Bot Token ──────────────────────────────────────────
echo ""
if [ -z "$BOT_TOKEN" ] && [ -f "$CONFIG_FILE" ]; then
    EXISTING_TOKEN=$(grep "option token" "$CONFIG_FILE" 2>/dev/null | awk -F"'" '{print $2}')
    if [ -n "$EXISTING_TOKEN" ]; then
        echo "Existing Bot Token found: $(echo "$EXISTING_TOKEN" | cut -c1-10)..."
        if [ -t 0 ]; then
            printf "Keep existing token? [Y/n]: "
            read -r KEEP_TOKEN
            if [ "$KEEP_TOKEN" != "n" ] && [ "$KEEP_TOKEN" != "N" ]; then
                BOT_TOKEN="$EXISTING_TOKEN"
            fi
        else
            echo "[*] Non-interactive mode: keeping existing token."
            BOT_TOKEN="$EXISTING_TOKEN"
        fi
    fi
fi

if [ -z "$BOT_TOKEN" ]; then
    if [ -t 0 ]; then
        printf "Enter your Telegram Bot Token: "
        read -r BOT_TOKEN
    fi
    if [ -z "$BOT_TOKEN" ]; then
        echo "[!] Bot Token is required. Use -t flag or run interactively."
        echo "    Usage: $0 -t YOUR_BOT_TOKEN -a YOUR_ADMIN_ID"
        exit 1
    fi
fi

# ─── Ask for Admin User ID ──────────────────────────────────────
if [ -z "$ADMIN_ID" ] && [ -f "$CONFIG_FILE" ]; then
    EXISTING_ID=$(grep "option admin_id" "$CONFIG_FILE" 2>/dev/null | awk -F"'" '{print $2}')
    if [ -n "$EXISTING_ID" ]; then
        echo "Existing Admin ID found: $EXISTING_ID"
        if [ -t 0 ]; then
            printf "Keep existing Admin ID? [Y/n]: "
            read -r KEEP_ID
            if [ "$KEEP_ID" != "n" ] && [ "$KEEP_ID" != "N" ]; then
                ADMIN_ID="$EXISTING_ID"
            fi
        else
            echo "[*] Non-interactive mode: keeping existing Admin ID."
            ADMIN_ID="$EXISTING_ID"
        fi
    fi
fi

if [ -z "$ADMIN_ID" ]; then
    if [ -t 0 ]; then
        printf "Enter your Telegram User ID (numeric): "
        read -r ADMIN_ID
    fi
    if [ -z "$ADMIN_ID" ]; then
        echo "[!] Admin ID is required. Use -a flag or run interactively."
        echo "    Usage: $0 -t YOUR_BOT_TOKEN -a YOUR_ADMIN_ID"
        exit 1
    fi
fi

# ─── Validate Admin ID ─────────────────────────────────────────
case "$ADMIN_ID" in
    ''|*[!0-9]*)
        echo "[!] Admin ID must be a numeric value. Got: $ADMIN_ID"
        exit 1
        ;;
esac

# ─── Write Config ───────────────────────────────────────────────
echo "[*] Writing config to $CONFIG_FILE..."
cat > "$CONFIG_FILE" << EOF
config passwall2_bot 'main'
    option token '$BOT_TOKEN'
    option admin_id '$ADMIN_ID'
EOF

# ─── Copy Bot Files ─────────────────────────────────────────────
echo "[*] Installing bot to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR/bot"

if [ -d "$SCRIPT_DIR/bot" ]; then
    cp -f "$SCRIPT_DIR/bot/"*.py "$INSTALL_DIR/bot/"
else
    echo "[!] Bot source files not found in $SCRIPT_DIR/bot/"
    echo "    Please copy the bot/ directory to $INSTALL_DIR/bot/ manually."
fi

# ─── Create procd Init Script ──────────────────────────────────
echo "[*] Creating init script at $INIT_SCRIPT..."
cat > "$INIT_SCRIPT" << 'INITEOF'
#!/bin/sh /etc/rc.common
# PassWall 2 Telegram Bot - procd service

START=99
STOP=10
USE_PROCD=1

PROG="/usr/share/passwall2_bot/bot/main.py"
NAME="passwall2_bot"

start_service() {
    procd_open_instance "$NAME"
    procd_set_param command python3 "$PROG"
    procd_set_param respawn 3600 5 0
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}

stop_service() {
    # procd tracks the PID internally via the instance name.
    # Calling service_stop ensures it kills the right process.
    service_stop "$PROG" 2>/dev/null

    # Belt-and-suspenders: also kill any leftover python running main.py
    local pids
    pids=$(pgrep -f "python3.*main\\.py" 2>/dev/null)
    if [ -n "$pids" ]; then
        kill $pids 2>/dev/null
        sleep 1
        kill -9 $pids 2>/dev/null
    fi
}

service_triggers() {
    procd_add_reload_trigger "passwall2_bot"
}
INITEOF

chmod +x "$INIT_SCRIPT"

# ─── Enable & Start ────────────────────────────────────────────
echo "[*] Enabling and starting the bot service..."
"$INIT_SCRIPT" enable
"$INIT_SCRIPT" start

echo ""
echo "========================================"
echo "  ✅ Installation Complete!"
echo "========================================"
echo ""
echo "Bot Token:  $(echo "$BOT_TOKEN" | cut -c1-10)..."
echo "Admin ID:   $ADMIN_ID"
echo "Install:    $INSTALL_DIR"
echo "Config:     $CONFIG_FILE"
echo "Service:    $INIT_SCRIPT"
echo ""
echo "Commands:"
echo "  /etc/init.d/passwall2_bot start"
echo "  /etc/init.d/passwall2_bot stop"
echo "  /etc/init.d/passwall2_bot restart"
echo ""
echo "Open Telegram and send /start to your bot!"
echo "========================================"
