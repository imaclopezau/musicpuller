import os
import sys
import time
import json
import soundcard as sc
import soundfile as sf
import subprocess

def write_progress(output_dir, track_id, status, current_time=0.0, duration=0.0, error=None):
    progress_file = os.path.join(output_dir, f"progress_{track_id}.json")
    data = {
        "status": status,
        "currentTime": current_time,
        "duration": duration,
        "error": error
    }
    with open(progress_file, "w") as f:
        json.dump(data, f)

def record_audio(track_id, output_dir, duration, device_name=""):
    wav_filepath = os.path.join(output_dir, f"{track_id}.wav")
    mp3_filepath = os.path.join(output_dir, f"{track_id}.mp3")
    progress_file = os.path.join(output_dir, f"progress_{track_id}.json")
    
    log_file = os.path.join(output_dir, f"debug_{track_id}.log")
    def log(msg):
        print(msg, flush=True)
        with open(log_file, "a") as f:
            f.write(msg + "\n")
            
    try:
        write_progress(output_dir, track_id, "initializing", 0.0, duration)
        log(f"Starting soundcard loopback recording for {duration} seconds...")
        
        # Give the user a moment to click Play
        write_progress(output_dir, track_id, "waiting_for_play", 0.0, duration)
        time.sleep(3)
        
        speaker = sc.default_speaker()
        mics = sc.all_microphones(include_loopback=True)
        loopbacks = [m for m in mics if m.isloopback]
        
        loopback = None
        if device_name:
            loopback = next((m for m in loopbacks if m.name == device_name), None)
            
        if not loopback:
            loopback = next((m for m in loopbacks if m.name == speaker.name), loopbacks[0] if loopbacks else mics[0])
        
        log(f"Using loopback device: {loopback.name}")
        
        # 48000 Hz matches Windows WASAPI & modern browser internal mixer natively
        samplerate = 48000
        total_frames = int(samplerate * duration)
        frames_recorded = 0
        chunk_size = samplerate # 1 second chunks
        
        with loopback.recorder(samplerate=samplerate) as mic:
            import numpy as np
            all_data = []
            
            while frames_recorded < total_frames:
                data = mic.record(numframes=chunk_size)
                all_data.append(data)
                frames_recorded += chunk_size
                
                # Update progress every second
                current_time = frames_recorded / samplerate
                write_progress(output_dir, track_id, "recording", current_time, duration)
                log(f"Recorded {current_time:.1f}/{duration:.1f}s")
                
        audio_data = np.concatenate(all_data, axis=0)
        # Automatic Peak Normalization: Normalize audio to -0.3 dBFS so tracks are full, crisp, and properly loud
        max_val = np.max(np.abs(audio_data))
        if max_val > 0.001:
            target_peak = 0.966
            gain = target_peak / max_val
            audio_data = audio_data * gain

        sf.write(wav_filepath, audio_data, samplerate, subtype='PCM_24')
        log(f"Saved to {wav_filepath}")
        
        write_progress(output_dir, track_id, "completed", duration, duration)
        log("Done!")
        
    except Exception as e:
        log(f"PYTHON ERROR: {e}")
        write_progress(output_dir, track_id, "error", error=str(e))
    finally:
        time.sleep(5)
        if os.path.exists(progress_file):
            try:
                os.remove(progress_file)
            except:
                pass

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python recorder.py <track_id> <output_dir> <duration> [device_name]")
        sys.exit(1)
        
    track_id = sys.argv[1]
    output_dir = sys.argv[2]
    duration = float(sys.argv[3])
    device_name = sys.argv[4] if len(sys.argv) > 4 else ""
    
    os.makedirs(output_dir, exist_ok=True)
    record_audio(track_id, output_dir, duration, device_name)
