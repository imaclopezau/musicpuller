from flask import Flask, render_template, request, Response, flash, redirect, url_for, send_file, jsonify
import re
import requests
import os
import sys
import json
import tempfile

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

def get_download_dir():
    default_dir = os.path.join(app.root_path, 'static', 'music')
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                custom_dir = cfg.get('download_dir', '').strip()
                if custom_dir:
                    return custom_dir
        except Exception:
            pass
    return default_dir

def get_api_key():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                return cfg.get('gemini_api_key', '').strip()
        except Exception:
            pass
    return os.environ.get('GEMINI_API_KEY', '').strip()

def set_config_value(key, value):
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    cfg[key] = value
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)

def set_download_dir(path):
    os.makedirs(path, exist_ok=True)
    set_config_value('download_dir', path)

app = Flask(__name__)
app.secret_key = 'super_secret_key' # Needed for flash messages

active_process = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        new_dir = request.form.get('download_dir', '').strip()
        api_key = request.form.get('gemini_api_key', None)
        if new_dir:
            set_download_dir(new_dir)
        if api_key is not None:
            set_config_value('gemini_api_key', api_key.strip())
        return jsonify({
            "status": "success", 
            "download_dir": get_download_dir(),
            "has_api_key": bool(get_api_key())
        })
    return jsonify({
        "download_dir": get_download_dir(),
        "has_api_key": bool(get_api_key()),
        "gemini_api_key": get_api_key()
    })

@app.route('/clean_with_ai', methods=['POST'])
def clean_with_ai():
    data = request.get_json(silent=True) or {}
    raw_text = data.get('raw_text', '').strip()
    image_b64 = data.get('image_b64', '').strip()
    mime_type = data.get('mime_type', 'image/png').strip()
    user_api_key = data.get('api_key', '').strip() or get_api_key()

    if not raw_text and not image_b64:
        return jsonify({"error": "No image or text provided"}), 400

    if not user_api_key:
        return jsonify({"error": "No Gemini API Key provided. Please enter your Gemini API key in Settings."}), 400

    parts = []
    if image_b64:
        prompt = """You are analyzing a screenshot of a Suno AI music playlist.
For each track card shown in the list from top to bottom:
1. Extract the full song title (e.g. 'Into the Abyss - Aetherblade', 'Dreamscape Descent', etc.).
2. Extract the exact duration shown on the album artwork thumbnail badge (e.g. '3:54', '3:48', etc.) and convert to total integer seconds (e.g. 3:54 -> 234).
3. Do NOT include tags like 'V6', 'COVER', or the prompt style description ('Band Male Lead, Californian accent...').
4. Return ONLY a valid JSON list of objects without markdown formatting or code fences:
[
  {"name": "Song Title", "duration": 234}
]
"""
        # If data URL prefix was included (data:image/png;base64,...), strip it
        if "," in image_b64:
            image_b64 = image_b64.split(",", 1)[1]
        parts.append({"text": prompt})
        parts.append({
            "inline_data": {
                "mime_type": mime_type,
                "data": image_b64
            }
        })
    else:
        prompt = f"""You are an audio tracklist parser. 
The following is raw OCR text scanned from a Suno AI music page screenshot:
---
{raw_text}
---
Task:
1. Identify all music track names and their exact durations (if shown in mm:ss format, e.g. 3:37 -> 217 seconds).
2. Clean away OCR noise, artifacts (e.g. «, », “, ”, ®, ©, Pon, etc.), UI buttons (Play, Remix, Filters, Share, etc.), and tags (Cover, v8, etc.).
3. Return ONLY a valid JSON list of objects without markdown formatting or code fences:
[
  {{"name": "Written In The Stars - BSB (Remastered x2)", "duration": 217}},
  {{"name": "The Words Unspoken - BSB (Remastered)", "duration": 268}}
]
"""
        parts.append({"text": prompt})

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={user_api_key}"
        resp = requests.post(url, json={
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}
        }, timeout=25)
        
        if resp.status_code != 200:
            return jsonify({"error": f"Gemini API error ({resp.status_code}): {resp.text}"}), 400
            
        result_json = resp.json()
        cand = result_json.get("candidates", [])[0]["content"]["parts"][0]["text"]
        parsed = json.loads(cand)
        return jsonify({"tracks": parsed})
    except Exception as e:
        return jsonify({"error": f"AI Parsing failed: {str(e)}"}), 500

@app.route('/start_auto', methods=['POST'])
def start_auto():
    global active_process
    device_name = request.form.get('device_name', '')
    max_tracks = request.form.get('max_tracks', '0').strip()
    if not max_tracks.isdigit():
        max_tracks = '0'
    custom_dir = request.form.get('download_dir', '').strip()
    if custom_dir:
        set_download_dir(custom_dir)
        
    music_dir = get_download_dir()
    os.makedirs(music_dir, exist_ok=True)
    import subprocess
    recorder_script = os.path.join(app.root_path, 'auto_recorder.py')
    
    track_names_raw = request.form.get('track_names', '').strip()
    if track_names_raw:
        try:
            track_items = json.loads(track_names_raw)
            if isinstance(track_items, list):
                queue_data = track_items
            else:
                queue_data = [track_names_raw]
        except Exception:
            queue_data = [{"name": line.strip(), "duration": 0} for line in track_names_raw.split('\n') if line.strip()]

        queue_file = os.path.join(music_dir, "track_names_queue.json")
        with open(queue_file, "w", encoding="utf-8") as f:
            json.dump(queue_data, f, indent=2)
    else:
        queue_file = os.path.join(music_dir, "track_names_queue.json")
        if os.path.exists(queue_file):
            os.remove(queue_file)

    stop_flag = os.path.join(music_dir, "stop_auto.flag")
    if os.path.exists(stop_flag):
        os.remove(stop_flag)
        
    status_file = os.path.join(music_dir, "auto_progress.json")
    if os.path.exists(status_file):
        os.remove(status_file)
        
    gap_seconds = request.form.get('gap_seconds', '1.5').strip()
    try:
        float(gap_seconds)
    except ValueError:
        gap_seconds = '1.5'

    active_process = subprocess.Popen([sys.executable, recorder_script, music_dir, device_name, max_tracks, gap_seconds])
    return jsonify({"status": "started", "download_dir": music_dir, "max_tracks": int(max_tracks)})

@app.route('/start_playlist', methods=['POST'])
def start_playlist():
    global active_process
    links_text = request.form.get('links', '')
    device_name = request.form.get('device_name', '')
    custom_dir = request.form.get('download_dir', '').strip()
    if custom_dir:
        set_download_dir(custom_dir)
        
    # parse links
    raw_links = links_text.split('\n')
    links = [l.strip() for l in raw_links if l.strip().startswith('http')]
    links = links[:10] # max 10 links
    
    if not links:
        return jsonify({"error": "No valid links provided"}), 400
        
    import subprocess
    music_dir = get_download_dir()
    os.makedirs(music_dir, exist_ok=True)
    
    playlist_file = os.path.join(music_dir, "playlist.json")
    with open(playlist_file, "w") as f:
        json.dump(links, f)
        
    stop_flag = os.path.join(music_dir, "stop_auto.flag")
    if os.path.exists(stop_flag):
        os.remove(stop_flag)
        
    status_ui_file = os.path.join(music_dir, "playlist_status.json")
    with open(status_ui_file, "w") as f:
        json.dump({"status": "Initializing Playlist..."}, f)
        
    if active_process is not None and active_process.poll() is None:
        active_process.terminate()
        active_process.wait()
        
    runner_script = os.path.join(app.root_path, 'playlist_runner.py')
    log_file = open(os.path.join(music_dir, "runner.log"), "w")
    active_process = subprocess.Popen([sys.executable, runner_script, music_dir, device_name], stdout=log_file, stderr=subprocess.STDOUT)
    
    return jsonify({"status": "started", "count": len(links), "download_dir": music_dir})

@app.route('/playlist_status')
def playlist_status():
    music_dir = get_download_dir()
    status_file = os.path.join(music_dir, "playlist_status.json")
    
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r') as f:
                data = json.load(f)
            return jsonify(data)
        except:
            return jsonify({"status": "Loading..."})
            
@app.route('/clear_playlist', methods=['POST'])
def clear_playlist():
    music_dir = get_download_dir()
    status_file = os.path.join(music_dir, "playlist_status.json")
    if os.path.exists(status_file):
        try:
            os.remove(status_file)
        except Exception:
            with open(status_file, "w") as f:
                json.dump({"status": "Stopped"}, f)
    return jsonify({"status": "cleared"})

@app.route('/stop_auto', methods=['POST'])
def stop_auto():
    global active_process
    music_dir = get_download_dir()
    stop_flag = os.path.join(music_dir, "stop_auto.flag")
    if os.path.exists(music_dir):
        with open(stop_flag, "w") as f:
            f.write("stop")
        
    if active_process is not None and active_process.poll() is None:
        try:
            # Wait up to 5 seconds for auto_recorder to flush audio buffer and write WAV file
            active_process.wait(timeout=5)
        except Exception:
            try:
                active_process.terminate()
            except Exception:
                pass
            
    return jsonify({"status": "stopping"})

@app.route('/cut_track', methods=['POST'])
def cut_track():
    music_dir = get_download_dir()
    flag = os.path.join(music_dir, "next_track.flag")
    if os.path.exists(music_dir):
        with open(flag, "w") as f:
            f.write("next")
    return jsonify({"status": "cutting"})

@app.route('/auto_status')
def auto_status():
    music_dir = get_download_dir()
    progress_file = os.path.join(music_dir, "auto_progress.json")
    
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r') as f:
                data = json.load(f)
            return jsonify(data)
        except:
            return jsonify({"state": "loading", "details": ""})
            
    return jsonify({"state": "stopped", "details": ""})

@app.route('/devices')
def get_devices():
    import soundcard as sc
    import ctypes
    ctypes.windll.ole32.CoInitialize(None)
    devices = [m.name for m in sc.all_microphones(include_loopback=True) if m.isloopback]
    return jsonify({"devices": devices, "default": sc.default_speaker().name})

@app.route('/audio_file/<path:filename>')
def serve_audio(filename):
    music_dir = get_download_dir()
    # Normalize and ensure no directory traversal outside music_dir
    safe_rel_path = os.path.normpath(filename).lstrip('\\/')
    target_path = os.path.abspath(os.path.join(music_dir, safe_rel_path))
    if not target_path.startswith(os.path.abspath(music_dir)):
        return jsonify({"error": "Forbidden"}), 403
    return send_file(target_path)

@app.route('/delete_audio', methods=['POST'])
def delete_audio():
    music_dir = get_download_dir()
    filename = request.form.get('filename', '').strip()
    if not filename:
        return jsonify({"error": "No filename provided"}), 400
    safe_rel_path = os.path.normpath(filename).lstrip('\\/')
    target_path = os.path.abspath(os.path.join(music_dir, safe_rel_path))
    if not target_path.startswith(os.path.abspath(music_dir)):
        return jsonify({"error": "Forbidden"}), 403
    if os.path.exists(target_path):
        try:
            os.remove(target_path)
            return jsonify({"status": "deleted", "filename": filename})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "File not found"}), 404

@app.route('/player')
def player():
    music_dir = get_download_dir()
    os.makedirs(music_dir, exist_ok=True)
    valid_exts = ('.mp3', '.m4a', '.webm', '.wav')
    songs = []
    for root, dirs, files in os.walk(music_dir):
        # Exclude Archive directory from main player view
        if "Archive" in root:
            continue
        for f in files:
            if f.lower().endswith(valid_exts):
                rel_path = os.path.relpath(os.path.join(root, f), music_dir).replace('\\', '/')
                # Check for corresponding cover image and metadata in same folder
                base = os.path.splitext(f)[0]
                clean_base = re.sub(r'\s*-\s*rem$', '', base, flags=re.IGNORECASE)
                img_path = None
                for ext in ['.jpg', '.jpeg', '.png', '.webp']:
                    candidate = os.path.join(root, f"{clean_base}{ext}")
                    if os.path.exists(candidate):
                        img_path = os.path.relpath(candidate, music_dir).replace('\\', '/')
                        break
                
                # Check metadata JSON or lyrics text
                style_val = ""
                lyrics_val = ""
                meta_json_path = os.path.join(root, f"{clean_base}.metadata.json")
                if os.path.exists(meta_json_path):
                    try:
                        with open(meta_json_path, 'r', encoding='utf-8') as mf:
                            mdata = json.load(mf)
                            style_val = mdata.get("style", "")
                            lyrics_val = mdata.get("lyrics", "")
                    except Exception:
                        pass
                if not lyrics_val:
                    lyr_txt_path = os.path.join(root, f"{clean_base}.lyrics.txt")
                    if os.path.exists(lyr_txt_path):
                        try:
                            with open(lyr_txt_path, 'r', encoding='utf-8') as lf:
                                lyrics_val = lf.read()
                        except Exception:
                            pass

                songs.append({
                    "filename": rel_path,
                    "image": img_path,
                    "style": style_val,
                    "lyrics": lyrics_val
                })
    # Sort with newest or alphabetical
    songs.sort(key=lambda s: s["filename"])
    return render_template('player.html', songs=songs, download_dir=music_dir)

if __name__ == '__main__':
    print("Starting Suno Downloader UI...")
    print("Open http://127.0.0.1:5000 in your browser.")
    app.run(debug=True, port=5000)
