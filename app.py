from flask import Flask, render_template, request, jsonify, send_file, Response
import yt_dlp
import os
import uuid
import threading
import zipfile
import tempfile
import shutil
import time
import json
import shlex
import random
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

tasks = {}
completed_files = {}

SETTINGS_DEFAULTS = {
    "format": "video",
    "audio_format": "mp3",
    "audio_bitrate": "320",
    "video_quality": "best",
    "embed_thumbnail": True,
    "embed_metadata": True,
    "subtitles": False,
    "subtitle_lang": "en",
    "speed_limit": "0",
    "proxy_mode": "none",
    "proxy": "",
    "max_filesize": "0",
    "sponsorblock": False,
    "filename_template": "%(title).80s [%(id)s].%(ext)s",
    "custom_args": "",
}

PROXY_LIST_URLS = [
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/https/data.json",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/all/data.json"
]


def _parse_size(s):
    s = str(s).strip().upper()
    if not s or s == "0":
        return None
    try:
        if s.endswith("G"):
            return int(float(s[:-1]) * 1073741824)
        elif s.endswith("M"):
            return int(float(s[:-1]) * 1048576)
        elif s.endswith("K"):
            return int(float(s[:-1]) * 1024)
        return int(s)
    except ValueError:
        return None


def cleanup_old_files():
    while True:
        time.sleep(300)
        now = time.time()
        to_remove = [
            tid for tid, info in completed_files.items()
            if now - info.get("timestamp", 0) > 3600
        ]
        for tid in to_remove:
            try:
                p = completed_files[tid]["path"]
                if os.path.isfile(p):
                    os.remove(p)
                d = os.path.join(tempfile.gettempdir(), f"ytdl_{tid}")
                if os.path.isdir(d):
                    shutil.rmtree(d)
            except Exception:
                pass
            completed_files.pop(tid, None)
            tasks.pop(tid, None)


threading.Thread(target=cleanup_old_files, daemon=True).start()


# ══════════════════════════════════════════════
# PROXY FETCHING & TESTING (BETA)
# ══════════════════════════════════════════════

def _fetch_proxy_list():
    """Fetch and parse the proxy list from the GitHub repo."""
    for url in PROXY_LIST_URLS:
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            proxies = [f"http://{p['ip']}:{p['port']}" for p in data if p.get('ip') and p.get('port')]
            if proxies:
                return proxies
        except Exception:
            continue
    return []


def _test_proxy(proxy_url):
    """Test if a proxy can reach YouTube without triggering a bot block immediately."""
    try:
        r = requests.get(
            'https://www.youtube.com',
            proxies={'http': proxy_url, 'https': proxy_url},
            timeout=5,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        # 200 is success, 403 usually means bot block, 429 rate limit
        if r.status_code == 200:
            return proxy_url
    except Exception:
        pass
    return None


def get_working_proxy():
    """Find a working proxy by testing up to 50 concurrently."""
    proxies = _fetch_proxy_list()
    if not proxies:
        return None, "Failed to fetch proxy list from GitHub."

    random.shuffle(proxies)
    
    # Test a batch concurrently to save time
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(_test_proxy, p): p for p in proxies[:50]}
        for future in as_completed(futures):
            result = future.result()
            if result:
                # Found one, return immediately
                return result, None
                
    return None, "Could not find a working proxy. Try again later."


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/info", methods=["POST"])
def get_info():
    try:
        url = (request.get_json(silent=True) or {}).get("url", "").strip()
        if not url:
            return jsonify({"error": "URL is required"}), 400
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        if "entries" in info:
            entries = [e for e in info["entries"] if e]
            return jsonify({
                "is_playlist": True,
                "title": info.get("title"),
                "uploader": info.get("uploader"),
                "count": len(entries),
                "entries": [
                    {"id": e.get("id"), "title": e.get("title", "Untitled"),
                     "duration": e.get("duration")}
                    for e in entries[:80]
                ],
            })
        else:
            return jsonify({
                "is_playlist": False,
                "id": info.get("id"),
                "title": info.get("title"),
                "thumbnail": info.get("thumbnail"),
                "duration": info.get("duration"),
                "uploader": info.get("uploader"),
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _make_hook(task_id):
    def hook(d):
        if task_id not in tasks:
            return
        t = tasks[task_id]
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            done = d.get("downloaded_bytes", 0)
            t["speed"] = d.get("speed", 0)
            t["file_percent"] = min((done / total) * 100, 100) if total > 0 else 0
            t["status"] = "downloading"
            t["current_file"] = os.path.basename(d.get("filename", ""))
        elif d["status"] == "finished":
            t["completed_files"] = t.get("completed_files", 0) + 1
            t["file_percent"] = 100
        elif d["status"] == "processing":
            t["status"] = "processing"
            t["current_file"] = "Processing…"
        elif d["status"] == "error":
            t["status"] = "error"
            t["error"] = str(d.get("error", "Download failed"))
    return hook


def _build_opts(settings, out, task_id):
    fmt = settings.get("format", "video")
    template = settings.get("filename_template", "%(title).80s [%(id)s].%(ext)s")
    opts = {
        "outtmpl": os.path.join(out, template),
        "progress_hooks": [_make_hook(task_id)],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }

    if fmt == "audio":
        opts["format"] = "bestaudio/best"
        bitrate = settings.get("audio_bitrate", "320")
        embed_thumb = settings.get("embed_thumbnail", True)
        embed_meta = settings.get("embed_metadata", True)
        pps = [{"key": "FFmpegExtractAudio",
                "preferredcodec": settings.get("audio_format", "mp3"),
                "preferredquality": bitrate}]
        if embed_meta:
            pps.append({"key": "FFmpegMetadata"})
        if embed_thumb:
            opts["writethumbnail"] = True
            pps.append({"key": "EmbedThumbnail"})
        opts["postprocessors"] = pps
    else:
        q = settings.get("video_quality", "best")
        fmt_map = {
            "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
            "1080p": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]",
            "720p": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]",
            "480p": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480]",
        }
        opts["format"] = fmt_map.get(q, fmt_map["best"])
        opts["merge_output_format"] = "mp4"
        if settings.get("embed_metadata", True):
            opts["add_metadata"] = True

    if settings.get("subtitles"):
        opts["writesubtitles"] = True
        lang = settings.get("subtitle_lang", "en").strip().split(",")[0]
        opts["subtitleslangs"] = [lang] if lang else ["en"]
        opts["subtitlesformat"] = "srt"

    rl = _parse_size(settings.get("speed_limit", "0"))
    if rl:
        opts["ratelimit"] = rl

    mfs = _parse_size(settings.get("max_filesize", "0"))
    if mfs:
        opts["max_filesize"] = mfs

    if settings.get("sponsorblock"):
        opts["sponsorblock_mark"] = {"all"}

    custom = settings.get("custom_args", "").strip()
    if custom:
        try:
            tokens = shlex.split(custom)
            i = 0
            while i < len(tokens):
                tok = tokens[i]
                if tok.startswith("--"):
                    key = tok[2:]
                    if "=" in key:
                        k, v = key.split("=", 1)
                        try:
                            opts[k] = json.loads(v)
                        except (json.JSONDecodeError, ValueError):
                            opts[k] = v
                    elif i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                        val = tokens[i + 1]
                        try:
                            opts[key] = json.loads(val)
                        except (json.JSONDecodeError, ValueError):
                            opts[key] = val
                        i += 1
                    else:
                        opts[key] = True
                i += 1
        except Exception:
            pass

    return opts


def _parse_settings(data):
    return {**SETTINGS_DEFAULTS, **data}


def _new_task():
    tid = uuid.uuid4().hex[:8]
    tasks[tid] = {
        "status": "extracting", "progress": 0, "file_percent": 0,
        "completed_files": 0, "total_files": 1, "current_file": "",
        "speed": 0, "error": None,
    }
    return tid


def _resolve_proxy(settings, task_id):
    """Resolves which proxy to use based on settings."""
    mode = settings.get("proxy_mode", "none")
    if mode == "manual":
        proxy = settings.get("proxy", "").strip()
        if not proxy:
            return None, "Manual proxy is enabled but no URL provided."
        return proxy, None
    elif mode == "auto":
        tasks[task_id]["status"] = "finding_proxy"
        proxy, err = get_working_proxy()
        return proxy, err
    return None, None


@app.route("/api/download", methods=["POST"])
def start_download():
    try:
        data = request.get_json(silent=True) or {}
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"error": "URL is required"}), 400
        settings = _parse_settings(data)
        tid = _new_task()

        def run():
            try:
                # Handle Proxy
                proxy, err = _resolve_proxy(settings, tid)
                if err:
                    tasks[tid].update(status="error", error=err)
                    return

                out = os.path.join(tempfile.gettempdir(), f"ytdl_{tid}")
                os.makedirs(out, exist_ok=True)
                opts = _build_opts(settings, out, tid)
                opts["noplaylist"] = True
                
                if proxy:
                    opts["proxy"] = proxy

                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.extract_info(url, download=True)
                dl_file = None
                for f in os.listdir(out):
                    if not f.endswith((".part", ".temp", ".jpg", ".webp", ".png")):
                        dl_file = os.path.join(out, f)
                        break
                if not dl_file:
                    for f in os.listdir(out):
                        if not f.endswith((".part", ".temp")):
                            dl_file = os.path.join(out, f)
                            break
                if dl_file and os.path.isfile(dl_file):
                    tasks[tid].update(status="completed", progress=100, file_percent=100)
                    completed_files[tid] = {
                        "path": dl_file,
                        "filename": os.path.basename(dl_file),
                        "timestamp": time.time(),
                    }
                else:
                    tasks[tid].update(status="error", error="No file was downloaded")
            except Exception as e:
                tasks[tid].update(status="error", error=str(e))

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"task_id": tid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download/playlist", methods=["POST"])
def start_playlist_download():
    try:
        data = request.get_json(silent=True) or {}
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"error": "URL is required"}), 400
        settings = _parse_settings(data)
        tid = _new_task()

        def run():
            try:
                # Handle Proxy
                proxy, err = _resolve_proxy(settings, tid)
                if err:
                    tasks[tid].update(status="error", error=err)
                    return

                out = os.path.join(tempfile.gettempdir(), f"ytdl_{tid}")
                os.makedirs(out, exist_ok=True)
                
                with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True, "proxy": proxy or None}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    entries = [e for e in info.get("entries", []) if e]
                    total = len(entries)
                    tasks[tid]["total_files"] = total
                    playlist_title = info.get("title", "playlist")

                tasks[tid]["status"] = "downloading"
                opts = _build_opts(settings, out, tid)
                if proxy:
                    opts["proxy"] = proxy

                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])

                tasks[tid]["status"] = "zipping"
                zip_path = os.path.join(tempfile.gettempdir(), f"ytdl_{tid}.zip")
                safe_name = "".join(
                    c for c in playlist_title if c.isalnum() or c in " -_"
                ).strip() or "playlist"

                count = 0
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for f in os.listdir(out):
                        fp = os.path.join(out, f)
                        if os.path.isfile(fp) and not f.endswith((".part", ".temp")):
                            zf.write(fp, f)
                            count += 1

                if count > 0:
                    tasks[tid].update(status="completed", progress=100, file_percent=100)
                    completed_files[tid] = {
                        "path": zip_path,
                        "filename": f"{safe_name}.zip",
                        "timestamp": time.time(),
                    }
                else:
                    tasks[tid].update(status="error", error="No files were downloaded")
                shutil.rmtree(out, ignore_errors=True)
            except Exception as e:
                tasks[tid].update(status="error", error=str(e))

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"task_id": tid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/progress/<tid>")
def progress_stream(tid):
    def generate():
        while True:
            if tid not in tasks:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                break
            t = tasks[tid]
            if t["total_files"] > 1:
                overall = min(
                    ((t["completed_files"] + t["file_percent"] / 100) / t["total_files"]) * 100, 99
                )
            else:
                overall = t["file_percent"]
            payload = {
                "status": t["status"],
                "progress": round(overall, 1),
                "file_percent": round(t["file_percent"], 1),
                "completed_files": t["completed_files"],
                "total_files": t["total_files"],
                "current_file": t["current_file"],
                "speed": t["speed"],
                "error": t["error"],
            }
            yield f"data: {json.dumps(payload)}\n\n"
            if t["status"] in ("completed", "error"):
                break
            time.sleep(0.4)

    return Response(
        generate(), mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/file/<tid>")
def download_file(tid):
    if tid not in completed_files:
        return jsonify({"error": "File not found or expired"}), 404
    fi = completed_files[tid]
    if not os.path.isfile(fi["path"]):
        return jsonify({"error": "File missing from disk"}), 404
    return send_file(fi["path"], as_attachment=True, download_name=fi["filename"])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8195)