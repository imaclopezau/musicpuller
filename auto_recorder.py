import os
import sys
import time
import json
import numpy as np
import soundcard as sc
import soundfile as sf
from datetime import datetime

output_dir = sys.argv[1]
device_name = sys.argv[2] if len(sys.argv) > 2 else ""

status_file = os.path.join(output_dir, "auto_progress.json")
stop_flag = os.path.join(output_dir, "stop_auto.flag")

def write_status(state, details=""):
    with open(status_file, "w") as f:
        json.dump({"state": state, "details": details}, f)

# Find device
mics = sc.all_microphones(include_loopback=True)
loopbacks = [m for m in mics if m.isloopback]
loopback = next((m for m in loopbacks if m.name == device_name), None) if device_name else None
if not loopback:
    speaker = sc.default_speaker()
    loopback = next((m for m in loopbacks if m.name == speaker.name), loopbacks[0] if loopbacks else mics[0])

write_status("listening", "Waiting for audio to start...")

samplerate = 44100
chunk_size = 4410 # 0.1 seconds
silence_threshold = 0.001
silence_duration = 3.0
silence_chunks_limit = int(silence_duration / 0.1)

# Ensure stop flag doesn't exist
if os.path.exists(stop_flag):
    os.remove(stop_flag)

try:
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
                    write_status("recording", "Recording... (0s)")
                    break
            
            if not recording:
                continue
                
            # Recording in progress
            frames_recorded = chunk_size
            while not os.path.exists(stop_flag):
                data = mic.record(numframes=chunk_size)
                rms = np.sqrt(np.mean(data**2))
                all_data.append(data)
                frames_recorded += chunk_size
                
                # Update status every second
                if (frames_recorded / samplerate) % 1.0 < 0.1:
                    write_status("recording", f"Recording... ({int(frames_recorded/samplerate)}s)")
                
                if rms < silence_threshold:
                    silence_chunks += 1
                    if silence_chunks > silence_chunks_limit:
                        break # Stop recording this track
                else:
                    silence_chunks = 0
                    
            if len(all_data) > silence_chunks_limit:
                # Strip the trailing silence
                valid_data = all_data[:-silence_chunks_limit]
                audio_data = np.concatenate(valid_data, axis=0)
                
                # If recording is too short (e.g., system beep), discard it
                if len(audio_data) > samplerate * 5: # At least 5 seconds
                    write_status("saving", "Converting to MP3...")
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    wav_file = os.path.join(output_dir, f"Suno_{timestamp}.wav")
                    mp3_file = os.path.join(output_dir, f"Suno_{timestamp}.mp3")
                    
                    sf.write(wav_file, audio_data, samplerate)
                    
                    # Ensure ffmpeg in PATH
                    ffmpeg_bin = r"C:\Users\Art\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin"
                    if ffmpeg_bin not in os.environ["PATH"]:
                        os.environ["PATH"] = ffmpeg_bin + os.pathsep + os.environ["PATH"]
                        
                    try:
                        from pydub import AudioSegment
                        audio = AudioSegment.from_file(wav_file)
                        audio.export(mp3_file, format="mp3", bitrate="192k")
                        os.remove(wav_file)
                    except Exception as e:
                        print(f"Error converting: {e}")
                    
            write_status("listening", "Waiting for next song...")

except Exception as e:
    write_status("error", str(e))
finally:
    if os.path.exists(stop_flag):
        os.remove(stop_flag)
    write_status("stopped", "Auto-recorder stopped.")
