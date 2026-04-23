# 🛠️ Setup Guide

Complete step-by-step instructions to get YouTube AI Agent Studio running from scratch.

> **Time required:** ~10 minutes

---

## Prerequisites

- Python **3.10 or newer** — [python.org/downloads](https://www.python.org/downloads/)
- `ffmpeg` installed and on your PATH (see [Step 1b](#1b-install-ffmpeg))
- A Google account (for Gemini + YouTube)
- A Pexels account (free image API)

---

## Step 1 — Clone and install

### 1a. Clone the repository

```bash
git clone https://github.com/yourusername/youtube-ai-agent.git
cd youtube-ai-agent
```

### 1b. Install ffmpeg

ffmpeg is required by MoviePy for video rendering.

| OS | Command |
|---|---|
| **Windows** | Download from [ffmpeg.org](https://ffmpeg.org/download.html) → extract → add `bin/` folder to PATH |
| **Mac** | `brew install ffmpeg` |
| **Ubuntu/Debian** | `sudo apt install ffmpeg` |

Verify: `ffmpeg -version` should print version info.

### 1c. Install Python dependencies

```bash
pip install -r requirements.txt
```

> ⚠️ **Do not upgrade** `moviepy` or `numpy` — they are pinned intentionally. See [FAQ in README](README.md#-faq).

---

## Step 2 — Get your API keys

### 2a. Google Gemini API Key (required — free)

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Sign in with your Google account
3. Click **Create API Key**
4. Copy the key

### 2b. Pexels API Key (required — free)

1. Go to [pexels.com/api](https://www.pexels.com/api/)
2. Create a free account and click **Your API Key**
3. Copy the key

---

## Step 3 — Configure your keys

### Option A — Environment variables (recommended)

```bash
# Mac / Linux
export GEMINI_API_KEY="your_key_here"
export PEXELS_API_KEY="your_key_here"

# Windows (Command Prompt)
set GEMINI_API_KEY=your_key_here
set PEXELS_API_KEY=your_key_here

# Windows (PowerShell)
$env:GEMINI_API_KEY="your_key_here"
$env:PEXELS_API_KEY="your_key_here"
```

To make these permanent, add them to your shell profile (`~/.bashrc`, `~/.zshrc`) or use a `.env` file:

```bash
cp .env.example .env
# Now edit .env and fill in your keys
```

### Option B — Edit config.py directly

Open `config.py` and replace the placeholder values:

```python
GEMINI_API_KEY = "AIza..."     # your Gemini key
PEXELS_API_KEY = "abc123..."   # your Pexels key
```

---

## Step 4 — Set up YouTube upload (optional)

Skip this step if you just want to generate videos locally without uploading.

### 4a. Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click **Select a project → New Project**
3. Name it (e.g. "YouTube AI Agent") and click **Create**

### 4b. Enable the YouTube Data API

1. In your new project, go to **APIs & Services → Library**
2. Search for **YouTube Data API v3**
3. Click **Enable**

### 4c. Create OAuth credentials

1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth client ID**
3. If prompted, configure the consent screen first:
   - User Type: **External**
   - Fill in app name, support email, and developer email
   - Scopes: click **Add or remove scopes** → search "youtube" → select `youtube.upload`
   - Test users: add your own Gmail address
4. Back in Credentials → **Create Credentials → OAuth client ID**
   - Application type: **Desktop app**
   - Name: anything (e.g. "YT Agent Desktop")
5. Click **Download JSON**
6. Rename the downloaded file to `client_secret.json`
7. Place it in the root of the project (replacing the placeholder)

### 4d. First-time authentication

On your first run, a browser window will open asking you to sign in with Google and grant permission. This only happens once — the token is saved locally as `youtube_token.pickle`.

> If you see a "Google hasn't verified this app" warning, click **Advanced → Go to (app name) (unsafe)**. This is expected for personal OAuth apps in testing mode.

---

## Step 5 — Customise your channel

Open `config.py` and edit:

```python
CHANNEL_DESCRIPTION = """
Describe your channel clearly here.
The more specific, the better the AI's topic and script quality.
Example: "Educational science channel for curious adults, style of Veritasium."
"""
CHANNEL_NAME = "Your Channel Name"
```

---

## Step 6 — Launch

### GUI mode (recommended)

```bash
python gui.py
```

Opens at **http://localhost:7842** — configure everything visually and click Generate.

### CLI mode

```bash
python pipeline.py
```

Runs the full pipeline in the terminal. The review dashboard opens automatically in your browser when the video is ready.

---

## Step 7 — Add background music (optional)

Drop any `.mp3` or `.wav` files into the `music library/` folder.  
The pipeline will automatically shuffle and loop them to match the video duration.

The repo includes a few dark cinematic tracks to get you started. Replace or add to them freely.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `No module named 'moviepy'` | Run `pip install -r requirements.txt` again |
| `ffmpeg not found` | Install ffmpeg and ensure it's on your PATH |
| `RESOURCE_EXHAUSTED` / 429 | Gemini quota hit — wait until midnight Pacific or switch starting model |
| `youtube_token.pickle` auth error | Delete the file and re-run to re-authenticate |
| Tiny/ugly video text | Install DejaVu fonts: `sudo apt install fonts-dejavu` (Linux) |
| Flask port already in use | Change `REVIEW_PORT` in `config.py` |
| `client_secret.json` error | Ensure you replaced the placeholder with your real Google credentials |
| Captions out of sync | Switch to a different `VOICE_ID` in `config.py` (see voice list in file) |

---

## Optional: Run as a background service

To keep the studio running continuously (e.g. on a home server):

```bash
# Using nohup (Linux/Mac)
nohup python gui.py > studio.log 2>&1 &

# Using screen
screen -S yt-studio
python gui.py
# Detach: Ctrl+A then D
```

---

If you get stuck, [open an issue](https://github.com/yourusername/youtube-ai-agent/issues) with your error message and OS.
