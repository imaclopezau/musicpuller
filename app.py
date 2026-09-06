from flask import Flask, render_template, request, Response, flash, redirect, url_for, send_file, jsonify
import re
import requests
import os
import sys
import tempfile

app = Flask(__name__)
app.secret_key = 'super_secret_key' # Needed for flash messages

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_auto', methods=['POST'])
def start_auto():
    device_name = request.form.get('device_name', '')
    import subprocess
    music_dir = os.path.join(app.root_path, 'static', 'music')
    recorder_script = os.path.join(app.root_path, 'auto_recorder.py')
    
    stop_flag = os.path.join(music_dir, "stop_auto.flag")
    if os.path.exists(stop_flag):
        os.remove(stop_flag)
        
    status_file = os.path.join(music_dir, "auto_progress.json")
    if os.path.exists(status_file):
        os.remove(status_file)
        
    subprocess.Popen([sys.executable, recorder_script, music_dir, device_name])
    return jsonify({"status": "started"})

@app.route('/stop_auto', methods=['POST'])
def stop_auto():
    music_dir = os.path.join(app.root_path, 'static', 'music')
    stop_flag = os.path.join(music_dir, "stop_auto.flag")
    with open(stop_flag, "w") as f:
        f.write("stop")
    return jsonify({"status": "stopping"})

@app.route('/auto_status')
def auto_status():
    import json
    music_dir = os.path.join(app.root_path, 'static', 'music')
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
    devices = [m.name for m in sc.all_microphones(include_loopback=True) if m.isloopback]
    return jsonify({"devices": devices, "default": sc.default_speaker().name})

@app.route('/player')
def player():
    music_dir = os.path.join(app.root_path, 'static', 'music')
    os.makedirs(music_dir, exist_ok=True)
    songs = [f for f in os.listdir(music_dir) if f.endswith('.mp3') or f.endswith('.m4a') or f.endswith('.webm')]
    return render_template('player.html', songs=songs)

if __name__ == '__main__':
    print("Starting Suno Downloader UI...")
    print("Open http://127.0.0.1:5000 in your browser.")
    app.run(debug=True, port=5000)
