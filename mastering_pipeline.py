import os
import re
import subprocess
import soundfile as sf

def sanitize_filename(name):
    """Sanitize string for use as directory or file name."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return clean if clean else "Unknown"

def parse_title_and_artist(raw_name):
    """
    Parses track title and artist name from raw name or Suno page title.
    Examples:
      - 'Dance All Night - LDBarge by FilPopMusic' -> ('Dance All Night', 'LDBarge')
      - 'Dance All Night - LDBarge' -> ('Dance All Night', 'LDBarge')
      - 'Dance All Night by LDBarge' -> ('Dance All Night', 'LDBarge')
      - 'Dance All Night' -> ('Dance All Night', 'Unknown Artist')
    """
    cleaned = (raw_name or "").strip()
    cleaned = re.sub(r'\|\s*Suno\s*$', '', cleaned, flags=re.IGNORECASE).strip()

    # Pattern 1: Title - Artist by User
    m1 = re.match(r'^(.*?)\s*-\s*(.*?)\s+by\s+(.*)$', cleaned, flags=re.IGNORECASE)
    if m1:
        return m1.group(1).strip(), m1.group(2).strip()

    # Pattern 2: Title - Artist
    m2 = re.match(r'^(.*?)\s*-\s*(.*)$', cleaned)
    if m2:
        return m2.group(1).strip(), m2.group(2).strip()

    # Pattern 3: Title by Artist
    m3 = re.match(r'^(.*?)\s+by\s+(.*)$', cleaned, flags=re.IGNORECASE)
    if m3:
        return m3.group(1).strip(), m3.group(2).strip()

    return cleaned, "Unknown Artist"

import requests

def download_cover_image(image_url, dest_path):
    """Downloads high-res cover art from Suno CDN."""
    if not image_url:
        return None
    try:
        resp = requests.get(image_url, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 1000:
            with open(dest_path, "wb") as f:
                f.write(resp.content)
            return dest_path
    except Exception as e:
        print(f"Failed to download cover image: {e}")
    return None

def remaster_and_export(raw_wav_path, output_dir, track_title, artist_name, image_url=None, style="", lyrics=""):
    """
    Given an initial recorded WAV file, creates:
      - <output_dir>/<Artist>/<Track Name>/<track_title>.wav
      - <output_dir>/<Artist>/<Track Name>/<track_title> - rem.wav  (30Hz high-pass + -14 LUFS / -1.0 dBFS True Peak)
      - <output_dir>/<Artist>/<Track Name>/<track_title>.mp3       (320kbps MP3 with ID3 metadata + embedded cover art)
      - <output_dir>/<Artist>/<Track Name>/<track_title>.jpg       (Original high-res cover art image)
      - <output_dir>/<Artist>/<Track Name>/<track_title>.lyrics.txt(Full song lyrics with song structure tags)
      - <output_dir>/<Artist>/<Track Name>/<track_title>.metadata.json (Style, lyrics, and MusicBank-ready schema)
    Returns a dict with paths and status.
    """
    if not os.path.exists(raw_wav_path):
        raise FileNotFoundError(f"Input WAV not found: {raw_wav_path}")

    clean_artist = sanitize_filename(artist_name)
    clean_track = sanitize_filename(track_title)

    # Hierarchical folder: Artist -> Track Name -> files
    artist_dir = os.path.join(output_dir, clean_artist)
    track_dir = os.path.join(artist_dir, clean_track)
    os.makedirs(track_dir, exist_ok=True)

    dest_raw_wav = os.path.join(track_dir, f"{clean_track}.wav")
    dest_rem_wav = os.path.join(track_dir, f"{clean_track} - rem.wav")
    dest_mp3 = os.path.join(track_dir, f"{clean_track}.mp3")
    dest_jpg = os.path.join(track_dir, f"{clean_track}.jpg")
    dest_style = os.path.join(track_dir, f"{clean_track}.style.txt")
    dest_lyrics = os.path.join(track_dir, f"{clean_track}.lyrics.txt")
    dest_json = os.path.join(track_dir, f"{clean_track}.metadata.json")

    # 1. Ensure raw WAV is copied/moved to track folder
    if os.path.abspath(raw_wav_path) != os.path.abspath(dest_raw_wav):
        import shutil
        shutil.copyfile(raw_wav_path, dest_raw_wav)

    # 2. Download cover image if available
    downloaded_cover = None
    if image_url:
        downloaded_cover = download_cover_image(image_url, dest_jpg)

    # 3. Save plain text style file (for 1-click paste into MusicBank Styles & Details)
    has_style = False
    if style and style.strip():
        with open(dest_style, "w", encoding="utf-8") as f:
            f.write(style.strip())
        has_style = True

    # 4. Save lyrics file if available
    has_lyrics = False
    if lyrics and lyrics.strip():
        with open(dest_lyrics, "w", encoding="utf-8") as f:
            f.write(lyrics.strip())
        has_lyrics = True

    # 5. Save metadata JSON (compatible with MusicBank & AIMusic)
    meta_payload = {
        "title": clean_track,
        "artist": clean_artist,
        "style": (style or "").strip(),
        "styles": (style or "").strip(),
        "lyrics": (lyrics or "").strip(),
        "album": "FreshBeats FM",
        "has_cover": bool(downloaded_cover and os.path.exists(dest_jpg)),
        "files": {
            "wav": os.path.basename(dest_raw_wav),
            "rem_wav": os.path.basename(dest_rem_wav),
            "mp3": os.path.basename(dest_mp3),
            "image": os.path.basename(dest_jpg) if (downloaded_cover and os.path.exists(dest_jpg)) else None,
            "style": os.path.basename(dest_style) if has_style else None,
            "lyrics": os.path.basename(dest_lyrics) if has_lyrics else None
        }
    }
    import json
    with open(dest_json, "w", encoding="utf-8") as f:
        json.dump(meta_payload, f, indent=2, ensure_ascii=False)

    # 5. Master to 24-bit PCM WAV: 30Hz highpass filter + EBU R128 loudness normalization
    cmd_wav = [
        "ffmpeg", "-y", "-i", dest_raw_wav,
        "-af", "highpass=f=30,loudnorm=I=-14:TP=-1.0:LRA=11",
        "-ar", "48000",
        "-c:a", "pcm_s24le",
        dest_rem_wav
    ]
    res_wav = subprocess.run(cmd_wav, capture_output=True, text=True)
    if res_wav.returncode != 0:
        raise RuntimeError(f"FFmpeg WAV remaster failed: {res_wav.stderr}")

    # 6. Convert remastered audio to 320 kbps MP3 with metadata and embedded cover art
    meta_tags = [
        "-id3v2_version", "3",
        "-metadata", f"title={clean_track}",
        "-metadata", f"artist={clean_artist}",
        "-metadata", "album=FreshBeats FM"
    ]
    if style:
        meta_tags.extend(["-metadata", f"genre={style.strip()}"])
    if lyrics:
        meta_tags.extend(["-metadata", f"lyrics={lyrics.strip()}"])

    if downloaded_cover and os.path.exists(downloaded_cover):
        cmd_mp3 = [
            "ffmpeg", "-y",
            "-i", dest_rem_wav,
            "-i", downloaded_cover,
            "-map", "0:a",
            "-map", "1:v",
            "-c:a", "libmp3lame",
            "-b:a", "320k",
            "-c:v", "copy",
            "-metadata:s:v", 'title="Album cover"',
            "-metadata:s:v", 'comment="Cover (front)"'
        ] + meta_tags + [dest_mp3]
    else:
        cmd_mp3 = [
            "ffmpeg", "-y", "-i", dest_rem_wav,
            "-c:a", "libmp3lame",
            "-b:a", "320k"
        ] + meta_tags + [dest_mp3]

    res_mp3 = subprocess.run(cmd_mp3, capture_output=True, text=True)
    if res_mp3.returncode != 0:
        raise RuntimeError(f"FFmpeg MP3 export failed: {res_mp3.stderr}")

    return {
        "artist": clean_artist,
        "track": clean_track,
        "style": style,
        "lyrics": lyrics,
        "artist_dir": artist_dir,
        "track_dir": track_dir,
        "raw_wav": dest_raw_wav,
        "rem_wav": dest_rem_wav,
        "mp3": dest_mp3,
        "image": dest_jpg if (downloaded_cover and os.path.exists(dest_jpg)) else None,
        "style_file": dest_style if has_style else None,
        "lyrics_file": dest_lyrics if has_lyrics else None,
        "metadata_file": dest_json
    }
