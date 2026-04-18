# REEL

A modern, self-hosted WebUI for [yt-dlp](https://github.com/yt-dlp/yt-dlp). Download single videos or entire playlists directly from your browser with a clean, responsive interface.

---

## Features

**Single File Downloads**: Fetch video info, choose your format, and download.

**Playlist Downloads**: Automatically downloads all videos in a playlist and compresses them into a .zip file for easy saving.

**Inline Format Toggle**: Switch between Video+Audio and Audio-only instantly right next to the URL bar.

**High-Quality Audio Defaults**: Audio downloads default to 320kbps with embedded thumbnails and metadata.

**Persistent Settings**: All preferences (quality, bitrate, subtitles, proxy, filename templates) are saved in your browser's local storage.

**Auto-Proxy Mode**: Built-in integration with the [Proxifly Free Proxy List](https://github.com/proxifly/free-proxy-list). It automatically fetches and tests proxies concurrently until it finds one that works, bypassing IP blocks.

**Docker Ready**: Simple one-command deployment.

## Installation (Docker - Recommended)

Docker is the easiest way to run REEL because it automatically installs Python, FFmpeg, and all dependencies.

1. Clone the repository:
```bash
git clone https://github.com/Nazky/reel.gitcd reel
```

2. Build and run the container: 
```bash
docker compose up -d --build
```

3. Open your browser and navigate to:
```
http://localhost:8195 
```

## Native Installation (Windows, macOS, Linux) 

If you prefer to run the app natively without Docker, you must install [Python 3](https://www.python.org/downloads/) and [FFmpeg](https://ffmpeg.org/) on your machine first.

[FFmpeg](https://ffmpeg.org/) is required for merging video/audio and converting audio formats.

1. Clone the repository: 
```bash
git clone https://github.com/Nazky/reel.git
cd reel
```
2. Install Python dependencies: 
```bash
pip install -r requirements.txt
```

3. Run REEL
```bash
python app.py
```

## How to Use 

**Single File**: Paste a video URL, choose V+A (Video+Audio) or Audio, click "Get Info", then "click Download". Once finished, click "Save File".
 
**Playlist**: Paste a playlist URL, choose your format, click "Get Info"" to see the video list, then click "Download All as ZIP". Once finished, click "Save ZIP". 

**Settings**: Go to the Settings tab to configure default formats, audio bitrate, subtitles, network speed limits, filename templates, and proxy modes. Click "Save Settings", your preferences will be remembered even if you close your browser. 

### Proxy Modes 

**Disabled**: Use your server's default IP.

**Manual**: Enter a specific proxy URL (e.g., socks5://ip:port).

**Auto (Free Proxy)**: The server will automatically fetch a list of free proxies, test up to 50 of them concurrently and use the first one that successfully connects without triggering a bot block.
     
## Credits 

Made by [Nazky](https://github.com/Nazky) 

Powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp)

Auto-proxy feature powered by [Proxifly Free Proxy List](https://github.com/proxifly/free-proxy-list) 
     