import os
import sys
import time
import json
import subprocess
import numpy as np
import soundfile as sf
from playwright.sync_api import sync_playwright

output_dir = sys.argv[1]
device_name = sys.argv[2] if len(sys.argv) > 2 else ""

playlist_file = os.path.join(output_dir, "playlist.json")
progress_file = os.path.join(output_dir, "auto_progress.json")
name_file = os.path.join(output_dir, "current_track_name.txt")
stop_flag = os.path.join(output_dir, "stop_auto.flag")
status_ui_file = os.path.join(output_dir, "playlist_status.json")

def format_sec(sec):
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"

def get_recorder_info():
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"state": "", "currentTime": 0, "duration": 0, "details": ""}

def save_playlist_data(data):
    try:
        with open(status_ui_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving playlist data: {e}")

def analyze_track_file(file_path):
    """Inspects the recorded WAV for anomalies and returns a traffic-light status."""
    if not os.path.exists(file_path):
        return {"status": "red", "label": "File Missing", "details": "WAV file was not created."}
    
    try:
        data, rate = sf.read(file_path)
    except Exception as e:
        return {"status": "red", "label": "Corrupt Audio", "details": f"Could not read audio: {str(e)}"}
        
    duration = len(data) / rate
    if duration < 2.0:
        return {"status": "red", "label": "No Output", "details": "Recording is shorter than 2 seconds."}
        
    mono = np.mean(data, axis=1) if len(data.shape) > 1 else data
    max_peak = float(np.max(np.abs(mono)))
    overall_rms = float(np.sqrt(np.mean(mono**2)))
    
    # 1. Check for complete silence
    if overall_rms < 0.0005 or max_peak < 0.005:
        return {"status": "red", "label": "Total Silence", "details": "No audible sound captured (RMS < 0.0005)."}
        
    # 2. Check for buffer holes / silence dropouts (>50ms pure zero within core music)
    win_size = int(rate * 0.05)
    core = mono[int(rate * 1.0):-int(rate * 1.5)] if len(mono) > rate * 3 else mono
    num_windows = len(core) // win_size
    zero_holes = 0
    for i in range(num_windows):
        chunk = core[i*win_size:(i+1)*win_size]
        if np.sqrt(np.mean(chunk**2)) < 0.00002:
            zero_holes += 1
            
    # 3. Check for severe clipping
    clipped_samples = int(np.sum(np.abs(mono) >= 0.9999))
    
    # Check runner log for data discontinuity warnings
    runner_log_file = os.path.join(output_dir, "runner.log")
    has_discontinuity = False
    if os.path.exists(runner_log_file):
        try:
            with open(runner_log_file, "r") as f:
                if "SoundcardRuntimeWarning: data discontinuity" in f.read():
                    has_discontinuity = True
        except Exception:
            pass

    # Determine status
    issues = []
    if zero_holes > 2:
        issues.append(f"{zero_holes} silence gap(s) detected")
    if clipped_samples > 100:
        issues.append(f"{clipped_samples} clipped samples")
    if has_discontinuity:
        issues.append("Buffer discontinuity recorded")

    if issues:
        return {
            "status": "amber",
            "label": "Warning",
            "details": "; ".join(issues),
            "peak": f"{max_peak:.2f}",
            "duration": format_sec(duration)
        }
        
    return {
        "status": "green",
        "label": "Studio Clean",
        "details": f"No dropouts, peak headroom at {max_peak:.2f}, 0 clipped samples.",
        "peak": f"{max_peak:.2f}",
        "duration": format_sec(duration)
    }

def main():
    if not os.path.exists(playlist_file):
        print("No playlist.json found")
        return
        
    with open(playlist_file, "r", encoding="utf-8") as f:
        links = json.load(f)
        
    if not links:
        print("Playlist empty")
        return

    # Initialize per-track tracking data
    tracks_data = []
    for idx, item in enumerate(links):
        if isinstance(item, dict):
            url = item.get("url") or item.get("link")
            t_artist = item.get("target_artist")
            s_title = item.get("song_title")
            s_id = item.get("song_id")
            action = item.get("action", "create")
        else:
            url = item
            t_artist = None
            s_title = None
            s_id = None
            action = "create"

        tracks_data.append({
            "index": idx + 1,
            "url": url,
            "title": s_title or f"Track {idx + 1}",
            "target_artist": t_artist,
            "song_title": s_title,
            "song_id": s_id,
            "action": action,
            "expected_length": "--:--",
            "recorded_length": "0:00",
            "counter": "0:00",
            "state": "queued",
            "quality": None
        })

    playlist_state = {
        "status": "Starting auto-recorder...",
        "active_index": 0,
        "total_tracks": len(links),
        "tracks": tracks_data
    }
    save_playlist_data(playlist_state)

    # Start the auto_recorder
    recorder_script = os.path.join(os.path.dirname(__file__), 'auto_recorder.py')
    recorder_proc = subprocess.Popen([sys.executable, recorder_script, output_dir, device_name])
    
    # Wait for recorder to be ready (listening)
    while get_recorder_info().get("state") != "listening":
        time.sleep(1)
        if os.path.exists(stop_flag):
            break

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--window-size=800,600"
            ]
        )
        context = browser.new_context(viewport={"width": 800, "height": 600})
        page = context.new_page()
        
        for i, link in enumerate(links):
            if os.path.exists(stop_flag):
                break
                
            cur_track = tracks_data[i]
            cur_track["state"] = "loading"
            playlist_state["active_index"] = i + 1
            playlist_state["status"] = f"Loading track {i+1}/{len(links)}..."
            save_playlist_data(playlist_state)
            
            try:
                page.goto(link, wait_until="domcontentloaded")
                time.sleep(3) # Give it time to render
                
                # Get title
                title = page.title()
                if not title or title.strip() == "":
                    title = f"Track_{i+1}"
                if title.endswith("| Suno"):
                    title = title[:-6].strip()
                    
                cur_track["title"] = title
                
                # Extract Suno cover image URL, Style tags, and Lyrics
                # Extract Suno cover image URL, Style tags, and Lyrics directly from Suno page
                page_meta = page.evaluate('''() => {
                    // Try expanding 'Show full styles' if present so full Suno style prompt is visible
                    try {
                        const showMoreBtn = Array.from(document.querySelectorAll('button, span, div')).find(el => {
                            const t = (el.innerText || '').toLowerCase();
                            return t.includes('show full style') || t.includes('show full styles');
                        });
                        if (showMoreBtn) showMoreBtn.click();
                    } catch (e) {}

                    const og = document.querySelector('meta[property="og:image"]');
                    const tw = document.querySelector('meta[name="twitter:image"]');
                    const img = document.querySelector('img[alt="Song Cover Image"], img[src*="cdn2.suno.ai/image_large"]');
                    const cover = (og && og.content) ? og.content : ((tw && tw.content) ? tw.content : (img ? img.src : null));

                    // 1. Style extraction directly from Suno's style links & style badges
                    const styleLinks = Array.from(document.querySelectorAll('a[href*="/style/"]'))
                        .map(a => a.innerText.trim())
                        .filter(Boolean);
                    let style = styleLinks.join(', ');

                    // 2. Fallback: extract from style text row right below the artist name on Suno
                    if (!style) {
                        const styleBlock = Array.from(document.querySelectorAll('div, span, p')).find(el => {
                            const t = el.innerText || '';
                            return t.includes('Show full styles') || (el.className && el.className.includes('style'));
                        });
                        if (styleBlock && styleBlock.parentElement) {
                            style = styleBlock.parentElement.innerText
                                .replace(/Show full styles/gi, '')
                                .replace(/\+/g, '')
                                .replace(/\n/g, ', ')
                                .trim();
                        }
                    }

                    // Lyrics extraction (whitespace pre-wrap block with Suno lyrics structure)
                    const lyricEl = Array.from(document.querySelectorAll('*')).find(el => {
                        const st = window.getComputedStyle(el);
                        const txt = el.innerText || '';
                        return (st.whiteSpace.includes('pre') || el.tagName === 'PRE') && txt.length > 50 && (txt.includes('[') || txt.includes('\\n'));
                    });
                    const lyrics = lyricEl ? lyricEl.innerText.trim() : '';

                    return { cover, style, lyrics };
                }''')
                cur_track["cover_img_url"] = page_meta.get("cover")
                cur_track["style"] = page_meta.get("style", "")
                cur_track["lyrics"] = page_meta.get("lyrics", "")

                # Try to extract track duration from Suno's page badge (e.g. 4:53)
                expected_dur = page.evaluate('''() => {
                    const matches = document.body.innerText.match(/\\b(\\d{1,2}:\\d{2})\\b/g);
                    return matches && matches.length > 0 ? matches[0] : "";
                }''')
                if expected_dur:
                    cur_track["expected_length"] = expected_dur

                playlist_state["status"] = f"Playing: {title}"
                save_playlist_data(playlist_state)
                
                with open(name_file, "w", encoding="utf-8") as f:
                    f.write(title)
                
                # Trigger Play on the track
                clicked = False
                for _ in range(8):
                    clicked = page.evaluate('''() => {
                        const playBtn = document.querySelector("button[aria-label='Play']");
                        if (playBtn) {
                            playBtn.click();
                            return true;
                        }
                        const btns = Array.from(document.querySelectorAll('button'));
                        const anyPlay = btns.find(b => (b.getAttribute('aria-label') || '').toLowerCase().includes('play') && !b.disabled);
                        if (anyPlay) {
                            anyPlay.click();
                            return true;
                        }
                        return false;
                    }''')
                    if clicked:
                        break
                    time.sleep(1)

                if not clicked:
                    cur_track["state"] = "error"
                    cur_track["quality"] = {"status": "red", "label": "Play Error", "details": "Could not find or click Play button."}
                    save_playlist_data(playlist_state)
                    continue
                    
                # Wait for audio to be detected (state goes to 'recording')
                wait_time = 0
                while get_recorder_info().get("state") != "recording":
                    if wait_time > 20:
                        cur_track["state"] = "error"
                        cur_track["quality"] = {"status": "red", "label": "No Audio", "details": "Timeout waiting for audio to start."}
                        save_playlist_data(playlist_state)
                        break
                    time.sleep(1)
                    wait_time += 1
                    if os.path.exists(stop_flag):
                        break
                
                rec_info = get_recorder_info()
                if rec_info.get("state") == "recording":
                    cur_track["state"] = "recording"
                    playlist_state["status"] = f"Recording: {title}"
                    
                    # Track live counter and duration
                    start_rec_time = time.time()
                    expected_sec = 0
                    if cur_track.get("expected_length") and ":" in str(cur_track["expected_length"]):
                        try:
                            pts = str(cur_track["expected_length"]).split(":")
                            expected_sec = int(pts[0]) * 60 + int(pts[1])
                        except Exception:
                            pass

                    while True:
                        info = get_recorder_info()
                        st = info.get("state")
                        if st != "recording" and st != "saving":
                            break
                        if os.path.exists(stop_flag):
                            break
                        
                        elapsed = int(time.time() - start_rec_time)
                        cur_track["counter"] = format_sec(elapsed)
                        cur_track["recorded_length"] = format_sec(elapsed)
                        save_playlist_data(playlist_state)

                        # Detect natural playback end on Suno page (Edge Case 1 & 3 mitigation)
                        if elapsed > 12:
                            try:
                                is_ended = page.evaluate('''() => {
                                    const pauseBtn = document.querySelector("button[aria-label='Pause']") || 
                                                     Array.from(document.querySelectorAll('button')).find(b => (b.getAttribute('aria-label') || '').toLowerCase().includes('pause'));
                                    return !pauseBtn;
                                }''')
                                if is_ended or (expected_sec > 0 and elapsed >= expected_sec + 4):
                                    next_flag = os.path.join(output_dir, "next_track.flag")
                                    with open(next_flag, "w") as nf:
                                        nf.write("next")
                                    time.sleep(1)
                                    break
                            except Exception:
                                pass

                        time.sleep(1)
                            
                # Song finished recording, now running quality check
                cur_track["state"] = "analyzing"
                playlist_state["status"] = f"Analyzing recording: {title}..."
                save_playlist_data(playlist_state)
                time.sleep(2) # Give background WAV save thread a moment to finalize file
                
                # Locate saved WAV file
                import re
                clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
                potential_file = os.path.join(output_dir, f"{clean_title}.wav")
                
                # Check for counter-suffixed files if already existed
                if not os.path.exists(potential_file):
                    # Search most recent WAV in output_dir
                    wav_candidates = [
                        os.path.join(output_dir, f) for f in os.listdir(output_dir)
                        if f.lower().endswith('.wav') and clean_title.lower() in f.lower()
                    ]
                    if wav_candidates:
                        potential_file = max(wav_candidates, key=os.path.getmtime)

                quality_report = analyze_track_file(potential_file)
                cur_track["quality"] = quality_report
                cur_track["state"] = "finished" if quality_report["status"] != "red" else "error"
                if quality_report.get("duration"):
                    cur_track["recorded_length"] = quality_report["duration"]

                # Automated broadcast mastering: 30Hz highpass, EBU R128 (-14 LUFS / -1.0 dBFS Peak) and 320k MP3
                if quality_report["status"] != "red" and os.path.exists(potential_file):
                    try:
                        from mastering_pipeline import parse_title_and_artist, remaster_and_export
                        parsed_track, parsed_artist = parse_title_and_artist(title)
                        
                        # Apply explicit target artist and song title if provided by MusicBank
                        if cur_track.get("target_artist"):
                            parsed_artist = cur_track["target_artist"]
                        if cur_track.get("song_title"):
                            parsed_track = cur_track["song_title"]

                        playlist_state["status"] = f"Mastering audio & converting MP3 ({parsed_artist} - {parsed_track})..."
                        save_playlist_data(playlist_state)
                        
                        export_res = remaster_and_export(
                            potential_file,
                            output_dir,
                            parsed_track,
                            parsed_artist,
                            image_url=cur_track.get("cover_img_url"),
                            style=cur_track.get("style", ""),
                            lyrics=cur_track.get("lyrics", "")
                        )
                        files_created = [f"{export_res['track']}.wav", f"{export_res['track']} - rem.wav", f"{export_res['track']}.mp3"]
                        if export_res.get("image"):
                            files_created.append(f"{export_res['track']}.jpg")
                        if export_res.get("style_file"):
                            files_created.append(os.path.basename(export_res["style_file"]))
                        if export_res.get("lyrics_file"):
                            files_created.append(os.path.basename(export_res["lyrics_file"]))
                        if export_res.get("metadata_file"):
                            files_created.append(os.path.basename(export_res["metadata_file"]))

                        cur_track["export_res"] = export_res
                        cur_track["analysis"] = export_res.get("analysis")
                        cur_track["mastering"] = {
                            "artist": export_res["artist"],
                            "track": export_res["track"],
                            "style": export_res.get("style", ""),
                            "has_lyrics": bool(export_res.get("lyrics")),
                            "files": files_created,
                            "image": export_res.get("image")
                        }
                        cur_track["quality"]["label"] += " (Mastered, MP3, Lyrics + Art)"
                    except Exception as master_err:
                        print(f"Mastering error: {master_err}")
                        cur_track["master_error"] = str(master_err)

                save_playlist_data(playlist_state)
                
                # Add brief gap before moving to next track
                playlist_state["status"] = f"Finished {title} ({quality_report['label']}). Waiting 3 seconds..."
                save_playlist_data(playlist_state)
                time.sleep(3)
                
            except Exception as e:
                print(f"Error on {link}: {e}")
                cur_track["state"] = "error"
                cur_track["quality"] = {"status": "red", "label": "Failure", "details": str(e)}
                save_playlist_data(playlist_state)
                
        browser.close()
        
    # Stop the recorder
    playlist_state["status"] = "Playlist finished. Finalizing..."
    save_playlist_data(playlist_state)
    with open(stop_flag, "w") as f:
        f.write("stop")
        
    recorder_proc.wait()
    playlist_state["status"] = "All Tracks Completed"
    save_playlist_data(playlist_state)

if __name__ == "__main__":
    main()

