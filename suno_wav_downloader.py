import re
import requests

# NOTE: This is a proof-of-concept scaffold.
# Suno's internal API changes frequently. You will need to obtain your session cookie
# from your browser's Developer Tools (Network tab -> look for requests to studio-api.suno.ai)

SUNO_COOKIE = "YOUR_BROWSER_SESSION_COOKIE_HERE"
HEADERS = {
    "Cookie": SUNO_COOKIE,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

def extract_track_id(url: str) -> str:
    """Extracts the UUID track ID from a Suno share link."""
    # Example: https://suno.com/song/d7f1b95b-3b4e-4b47-832f-abcdef123456
    match = re.search(r"/song/([a-f0-9\-]{36})", url)
    if not match:
        raise ValueError("Could not find a valid Suno track ID in the URL.")
    return match.group(1)

def get_track_info(track_id: str):
    """Fetches track metadata from Suno's internal API."""
    url = f"https://studio-api.suno.ai/api/external/clips/?ids={track_id}"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    data = response.json()
    
    if not data:
        raise ValueError("No data returned for this track ID.")
    
    return data[0]

def download_wav(track_id: str, output_filename: str):
    """
    Attempts to download the WAV file.
    Note: Suno often requires a POST request to generate the WAV first,
    followed by polling to get the actual download URL. 
    """
    print(f"Fetching metadata for track: {track_id}")
    track_info = get_track_info(track_id)
    
    # The JSON response usually contains an 'audio_url' (MP3/MP4) 
    # For WAV, Suno's web app typically makes a request to generate it if not already cached.
    # If a direct WAV url exists in the metadata, it might be under 'wav_url' or similar,
    # but typically requires polling an endpoint like /api/external/clips/{track_id}/download/
    
    audio_url = track_info.get("audio_url")
    wav_url = track_info.get("wav_url") # Hypothetical key, depends on current API structure
    
    # Fallback to standard audio if WAV is not immediately available
    download_url = wav_url if wav_url else audio_url
    
    if not download_url:
        print("Could not find a download URL in the track metadata.")
        return

    print(f"Downloading from: {download_url}")
    
    # Download the file
    audio_response = requests.get(download_url, headers=HEADERS, stream=True)
    audio_response.raise_for_status()
    
    with open(output_filename, 'wb') as f:
        for chunk in audio_response.iter_content(chunk_size=8192):
            f.write(chunk)
            
    print(f"Successfully downloaded to {output_filename}")

if __name__ == "__main__":
    suno_link = input("Enter Suno link: ")
    try:
        track_id = extract_track_id(suno_link)
        download_wav(track_id, f"{track_id}.wav")
    except Exception as e:
        print(f"Error: {e}")
