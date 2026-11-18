import os
import sys
import time
import json
import numpy as np
import soundcard as sc
import soundfile as sf
from datetime import datetime

def parse_duration_to_seconds(val):
    if isinstance(val, (int, float)):
        return int(val)
    if not val:
        return 0
    val_str = str(val).strip()
    if ":" in val_str:
        parts = val_str.split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except ValueError:
            return 0
    try:
        return int(float(val_str))
    except ValueError:
        return 0

def format_time(seconds):
    seconds = max(0, int(seconds))
    m = seconds // 60
    s = seconds % 60
    return f"{m}:{s:02d}"

if __name__ == '__main__':
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    device_name = sys.argv[2] if len(sys.argv) > 2 else ""
    max_tracks = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else 0
    gap_seconds = float(sys.argv[4]) if len(sys.argv) > 4 else 1.5

    status_file = os.path.join(output_dir, "auto_progress.json")
    stop_flag = os.path.join(output_dir, "stop_auto.flag")

def write_status(state, details="", recorded_count=0, target_count=0):
    with open(status_file, "w") as f:
        json.dump({
            "state": state, 
            "details": details,
            "recorded_count": recorded_count,
            "target_count": target_count
        }, f)

# Find device
mics = sc.all_microphones(include_loopback=True)
loopbacks = [m for m in mics if m.isloopback]
loopback = next((m for m in loopbacks if m.name == device_name), None) if device_name else None
if not loopback:
    speaker = sc.default_speaker()
    loopback = next((m for m in loopbacks if m.name == speaker.name), loopbacks[0] if loopbacks else mics[0])

limit_str = f" (target: {max_tracks})" if max_tracks > 0 else ""
write_status("listening", f"Waiting for audio to start...{limit_str}", 0, max_tracks)

# 48000 Hz matches Windows WASAPI & modern browser internal mixer natively
samplerate = 48000
chunk_size = 4800 # 0.1 seconds (4800 frames)
# silence_threshold = 0.002 ensures only true silence triggers a cut, not quiet musical passages
silence_threshold = 0.002 
silence_duration = max(0.5, gap_seconds)
silence_chunks_limit = int(silence_duration / 0.1)

# Ensure stop flag doesn't exist
if os.path.exists(stop_flag):
    os.remove(stop_flag)

try:
    recorded_count = 0
    with loopback.recorder(samplerate=samplerate) as mic:
        while not os.path.exists(stop_flag):
            recording = False
            all_data = []
            silence_chunks = 0
            
            # Wait for audio to start
            while not os.path.exists(stop_flag):
                data = mic.record(numframes=chunk_size)
                rms = np.sqrt(np.mean(data**2))
                if rms > silence_threshold:
                    recording = True
                    all_data.append(data)
                    curr_track_num = recorded_count + 1
                    track_info = f"Track #{curr_track_num}" + (f" of {max_tracks}" if max_tracks > 0 else "")
                    write_status("recording", f"Recording {track_info}... (0:00)", recorded_count, max_tracks)
                    break
            
            if not recording:
                continue
                
            # Recording in progress
            frames_recorded = chunk_size
            curr_track_num = recorded_count + 1
            track_info = f"Track #{curr_track_num}" + (f" of {max_tracks}" if max_tracks > 0 else "")
            next_flag = os.path.join(output_dir, "next_track.flag")
            stopped_by_user = False
            track_cut_requested = False

            # Peek current track target duration from queue if available
            queue_file = os.path.join(output_dir, "track_names_queue.json")
            target_track_sec = 0
            current_track_label = track_info
            if os.path.exists(queue_file):
                try:
                    with open(queue_file, "r", encoding="utf-8") as f:
                        q_peek = json.load(f)
                    if q_peek and isinstance(q_peek, list) and len(q_peek) > 0:
                        first_item = q_peek[0]
                        if isinstance(first_item, dict):
                            target_track_sec = parse_duration_to_seconds(first_item.get("duration", 0))
                            current_track_label = f"'{first_item.get('name', track_info)}'"
                except Exception:
                    pass

            while True:
                if os.path.exists(stop_flag):
                    stopped_by_user = True
                    break
                if os.path.exists(next_flag):
                    track_cut_requested = True
                    try:
                        os.remove(next_flag)
                    except Exception:
                        pass
                    break

                data = mic.record(numframes=chunk_size)
                rms = np.sqrt(np.mean(data**2))
                all_data.append(data)
                frames_recorded += chunk_size
                elapsed_sec = int(frames_recorded / samplerate)
                
                # Update status every second
                if (frames_recorded / samplerate) % 1.0 < 0.1:
                    elapsed_str = format_time(elapsed_sec)
                    dur_display = f" / {format_time(target_track_sec)}" if target_track_sec > 0 else ""
                    write_status("recording", f"Recording {current_track_label}... ({elapsed_str}{dur_display})", recorded_count, max_tracks)
                
                # Check for natural silence gap
                # Only check silence if audio has been playing for at least 30 seconds or if no target duration was set,
                # to prevent a quiet song intro from triggering an early track cut!
                if rms < silence_threshold:
                    silence_chunks += 1
                    can_silence_cut = (target_track_sec == 0) or (elapsed_sec > 30)
                    if silence_chunks > silence_chunks_limit and can_silence_cut:
                        break # Track finished naturally by silence
                else:
                    silence_chunks = 0

                # AUTOMATIC DURATION CUT: If Suno plays back-to-back with 0 gap,
                # automatically cut when song reaches its exact duration!
                if target_track_sec > 0 and elapsed_sec >= target_track_sec:
                    track_cut_requested = True
                    break
                    
            if len(all_data) > silence_chunks_limit or track_cut_requested or (stopped_by_user and len(all_data) > samplerate * 3):
                # Strip trailing silence chunks if stopped naturally
                valid_data = all_data[:-silence_chunks_limit] if (not stopped_by_user and not track_cut_requested) else all_data
                audio_data = np.concatenate(valid_data, axis=0)
                
                # Save if audio is at least 4 seconds long
                if len(audio_data) > samplerate * 4:
                    write_status("saving", f"Saving {current_track_label} to WAV...", recorded_count, max_tracks)
                    
                    track_name_file = os.path.join(output_dir, "current_track_name.txt")
                    base_name = ""
                    
                    if os.path.exists(track_name_file):
                        with open(track_name_file, "r", encoding="utf-8") as f:
                            base_name = f.read().strip()
                        os.remove(track_name_file)
                    elif os.path.exists(queue_file):
                        try:
                            with open(queue_file, "r", encoding="utf-8") as f:
                                queue = json.load(f)
                            if queue and isinstance(queue, list) and len(queue) > 0:
                                popped_item = queue.pop(0)
                                if isinstance(popped_item, dict):
                                    base_name = popped_item.get("name", "").strip()
                                else:
                                    base_name = str(popped_item).strip()
                                with open(queue_file, "w", encoding="utf-8") as f:
                                    json.dump(queue, f, indent=2)
                        except Exception:
                            pass
                            
                    # Sanitize filename
                    import re
                    base_name = re.sub(r'[\\/*?:"<>|]', "", base_name).strip()
                    if not base_name:
                        base_name = "Suno_" + datetime.now().strftime("%Y%m%d_%H%M%S")
                        
                    wav_file = os.path.join(output_dir, f"{base_name}.wav")
                    
                    # Prevent overwriting if a file with the same name already exists
                    counter = 2
                    unique_name = base_name
                    while os.path.exists(wav_file):
                        unique_name = f"{base_name}_{counter}"
                        wav_file = os.path.join(output_dir, f"{unique_name}.wav")
                        counter += 1

                    import threading
                    def save_track_async(file_path, data, rate):
                        try:
                            # Save as 24-bit PCM WAV (studio master quality, no clipping)
                            sf.write(file_path, data, rate, subtype='PCM_24')
                        except Exception as err:
                            with open(os.path.join(output_dir, "error.log"), "a") as f:
                                f.write(f"Save error: {err}\n")

                    threading.Thread(target=save_track_async, args=(wav_file, audio_data, samplerate), daemon=True).start()
                    recorded_count += 1

                    # Check if reached target count or user stopped
                    if max_tracks > 0 and recorded_count >= max_tracks:
                        write_status("completed", f"Finished! All {recorded_count} tracks recorded and saved.", recorded_count, max_tracks)
                        # Give background save thread a moment to finish before exiting
                        time.sleep(1.0)
                        break

            if stopped_by_user:
                # Wait for any active background save to finish
                time.sleep(1.5)
                break

            next_track_info = f"Waiting for next song (Recorded: {recorded_count}" + (f"/{max_tracks})" if max_tracks > 0 else ")...")
            write_status("listening", next_track_info, recorded_count, max_tracks)

except Exception as e:
    with open(os.path.join(output_dir, "error.log"), "a") as f:
        f.write(f"Error: {e}\n")
    write_status("error", str(e))
finally:
    if os.path.exists(stop_flag):
        os.remove(stop_flag)
    # Only write stopped if we didn't just write an error
    try:
        with open(status_file, "r") as f:
            if "error" not in f.read():
                write_status("stopped", "Auto-recorder stopped.")
    except:
        pass
