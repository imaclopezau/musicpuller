import re
import requests
import sys

def download_suno_track(url: str):
    """Fetches the Suno page and extracts the direct audio download link."""
    print(f"Fetching page: {url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        # Search the HTML for the media URL. Suno embeds it in the page's Next.js data.
        # Extract track ID to use in search
        track_id_match = re.search(r"/song/([a-f0-9\-]{36})", url)
        if not track_id_match:
            print("Error: Could not find a valid Suno track ID in the URL.")
            return
            
        track_id = track_id_match.group(1)
        
        # Search the HTML for the media URL containing the track ID.
        match = re.search(rf'(https://[^\\]+{track_id}\.(?:m4a|mp3))', response.text)
        
        if not match:
            print("Error: Could not find the audio download link in the page source.")
            print("The song might be private, or Suno's page structure may have changed.")
            return
            
        direct_audio_url = match.group(1)
        
        # Use the correct extension based on the direct URL
        extension = direct_audio_url.split('.')[-1]
        output_filename = f"{track_id}.{extension}"
        
        print(f"Found audio link: {direct_audio_url}")
        print(f"Downloading to {output_filename} ...")
        
        # Download the actual audio file
        audio_response = requests.get(direct_audio_url, headers=headers, stream=True)
        audio_response.raise_for_status()
        
        with open(output_filename, 'wb') as f:
            for chunk in audio_response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        print("Download complete!")
        
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        suno_link = sys.argv[1]
    else:
        suno_link = input("Enter Suno link: ")
        
    download_suno_track(suno_link)
