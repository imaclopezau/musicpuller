import os
import sys
import time
import json
import subprocess
from playwright.sync_api import sync_playwright

output_dir = sys.argv[1]
device_name = sys.argv[2] if len(sys.argv) > 2 else ""

playlist_file = os.path.join(output_dir, "playlist.json")
progress_file = os.path.join(output_dir, "auto_progress.json")
name_file = os.path.join(output_dir, "current_track_name.txt")
stop_flag = os.path.join(output_dir, "stop_auto.flag")

def get_recorder_state():
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r") as f:
                return json.load(f).get("state", "")
        except:
            pass
    return ""

def write_playlist_status(status_text):
    print(f"PLAYLIST: {status_text}")
    # Write to a special playlist status file for the UI
    status_ui_file = os.path.join(output_dir, "playlist_status.json")
    with open(status_ui_file, "w") as f:
        json.dump({"status": status_text}, f)

def main():
    if not os.path.exists(playlist_file):
        print("No playlist.json found")
        return
        
    with open(playlist_file, "r") as f:
        links = json.load(f)
        
    if not links:
        print("Playlist empty")
        return

    # Start the auto_recorder
    write_playlist_status("Starting auto-recorder...")
    recorder_script = os.path.join(os.path.dirname(__file__), 'auto_recorder.py')
    recorder_proc = subprocess.Popen([sys.executable, recorder_script, output_dir, device_name])
    
    # Wait for recorder to be ready (listening)
    while get_recorder_state() != "listening":
        time.sleep(1)
        if os.path.exists(stop_flag):
            break

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        
        for i, link in enumerate(links):
            if os.path.exists(stop_flag):
                break
                
            write_playlist_status(f"Loading track {i+1}/{len(links)}...")
            
            try:
                page.goto(link, wait_until="domcontentloaded")
                time.sleep(3) # Give it time to render
                
                # Get title
                title = page.title()
                if not title or title.strip() == "":
                    title = f"Track_{i+1}"
                    
                # Clean up Suno suffix
                if title.endswith("| Suno"):
                    title = title[:-6].strip()
                    
                write_playlist_status(f"Playing: {title}")
                
                with open(name_file, "w", encoding="utf-8") as f:
                    f.write(title)
                
                # Try to click play
                locs = page.locator("button[aria-label='Play'], button[aria-label='Play song'], .play-button").all()
                if locs:
                    locs[0].click()
                else:
                    write_playlist_status(f"Could not find Play button for {title}")
                    continue
                    
                # Wait for audio to be detected (state goes to 'recording')
                wait_time = 0
                while get_recorder_state() != "recording":
                    if wait_time > 15: # wait 15 seconds max for audio to start
                        write_playlist_status(f"Timeout waiting for audio to start: {title}")
                        break
                    time.sleep(1)
                    wait_time += 1
                    if os.path.exists(stop_flag):
                        break
                
                if get_recorder_state() == "recording":
                    write_playlist_status(f"Recording: {title}")
                    # Wait for song to finish (state goes back to 'listening')
                    while get_recorder_state() == "recording" or get_recorder_state() == "saving":
                        time.sleep(1)
                        if os.path.exists(stop_flag):
                            break
                            
                # Add gap before next track
                write_playlist_status(f"Finished {title}. Waiting 3 seconds...")
                time.sleep(3)
                
            except Exception as e:
                print(f"Error on {link}: {e}")
                
        browser.close()
        
    # Stop the recorder
    write_playlist_status("Playlist finished. Stopping recorder...")
    with open(stop_flag, "w") as f:
        f.write("stop")
        
    recorder_proc.wait()
    write_playlist_status("Done")

if __name__ == "__main__":
    main()
