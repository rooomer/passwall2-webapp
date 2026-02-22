# PassWall 2 Telegram Bot - Complete Deployment Guide

This guide will walk you through deploying the PassWall 2 Telegram Bot and its WebApp (Mini App) from scratch. The process is divided into three simple steps.

---

## Prerequisites
Before you begin, you need:
1. **An OpenWrt Router** running PassWall 2.
2. **A Telegram Bot Token**: Talk to [@BotFather](https://t.me/botfather) on Telegram, create a new bot, and copy the HTTP API Token.
3. **Your Telegram User ID**: Talk to [@userinfobot](https://t.me/userinfobot) to get your numeric ID (e.g., `123456789`).
4. **Internet Access**: The router needs internet to communicate with Telegram API.
5. **A GitHub Account**: (Optional but recommended) to host the WebApp UI for free.

---

## Step 1: Host the WebApp (Telegram Mini App)
The graphical Web Panel (WebApp) is pure HTML/JS/CSS. It doesn't need a backend server; it runs directly inside the Telegram app. You can host it anywhere (like GitHub Pages or Cloudflare Pages) for free.

### Using GitHub Pages (Recommended)
1. Go to [GitHub](https://github.com/) and create a new public repository named `passwall2-webapp`.
2. Upload the 3 files from the `webapp/` folder of this project into the repository:
   - `index.html`
   - `app.js`
   - `style.css`
3. In your repository, go to **Settings > Pages**.
4. Under "Source", select the `main` branch and save.
5. After a minute or two, GitHub will give you a live URL (e.g., `https://yourusername.github.io/passwall2-webapp/`).
6. **Important:** Copy this URL. You will need it in Step 2.

---

## Step 2: Install and Configure the Bot on OpenWrt
Now we will install the Python bot directly on your OpenWrt router.

### 1. Update the WebApp URL in `main.py`
Before copying the files to the router, open `bot/main.py` locally and find line `32`:
```python
WEBAPP_BASE_URL = os.environ.get("PW_WEBAPP_URL", "https://example.github.io/passwall2-panel")
```
Replace the default URL with the GitHub Pages URL you got in Step 1.

### 2. Transfer Files to the Router
You need to transfer the `install.sh` script and the `bot/` folder to your OpenWrt router. You can use `scp` or a tool like WinSCP/FileZilla.

Assuming you use `scp` (Secure Copy):
```bash
# From your computer's terminal:
scp -r ./install.sh ./bot root@192.168.1.1:/root/
```

### 3. Run the Installer
SSH into your router:
```bash
ssh root@192.168.1.1
```

Once inside the router, execute the automated install script. It supports interactive or command-line flags.

**Interactive Mode:**
```bash
sh /root/install.sh
```
It will ask you to type or paste your Bot Token and your Admin User ID.

**Command-Line Mode (Faster):**
```bash
sh /root/install.sh -t "YOUR_BOT_TOKEN_HERE" -a "YOUR_USER_ID_HERE"
```

The script will automatically:
1. Ensure Python 3 (`python3-light`, `python3-urllib`) is installed.
2. Save your Bot Token securely in `/etc/config/passwall2_bot`.
3. Copy the bot python files to `/usr/share/passwall2_bot/bot/`.
4. Create an auto-start `procd` service.
5. Start the bot running in the background.

---

## Step 3: Link the WebApp to the Telegram Bot Button (Optional)
To make the "Web Panel" button appear seamlessly in the chat menu of your bot:

1. Open Telegram and message [@BotFather](https://t.me/botfather).
2. Send the command: `/setmenubutton`
3. Select your bot from the list.
4. Provide the exact HTTPS URL of the WebApp you hosted in Step 1 (e.g., `https://yourusername.github.io/passwall2-webapp/`).
5. Choose a title for the button (e.g., **Panel** or **WebApp**).

Now, instead of the regular keyboard icon near the text box, a **Panel** button will appear for quick access!

---

## How to Use the Bot

Open Telegram, search for your bot username, and tap **START** (or type `/start`).

### Main Features
- **Start/Stop/Restart:** Instantly toggle the PassWall service.
- **Node Switching:** Go to `Nodes > Switch Main Node`. The bot will show paginated lists of all available nodes. Tap one to activate it instantly.
- **DNS Settings:** Change DNS strategies, switch to DoH, toggle FakeDNS, or set custom Domain Overrides directly from the chat.
- **Web Panel:** Tap the `🖥️ Web Panel` button. The bot will encrypt your current router config into a URL and open the beautiful graphical web interface without asking you to log in (since it verifies your Admin ID).
- **Tools Menu:**
  - **Ping:** Test node latencies.
  - **GeoView:** Send an IP or Domain (e.g., `google.com`) and the bot will tell you which GeoIP/Geosite list routes it.
  - **Logs:** View the latest 30 lines of client/server logs directly in the chat.
  - **Backup:** Tap `Download Backup` to get a `passwall2-xxxx-backup.tar.gz` file. To restore, simply send that file back to the bot chat!

## Advanced: Troubleshooting

**If the bot isn't responding:**
SSH into the router and check the background service:
```bash
/etc/init.d/passwall2_bot status
```

**If you need to change your Admin ID or Token later:**
Edit the config file directly on the router:
```bash
vi /etc/config/passwall2_bot
```
Then restart the bot:
```bash
/etc/init.d/passwall2_bot restart
```

Enjoy your fully autonomous, highly secure PassWall 2 Telegram Controller!
