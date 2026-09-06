import time
import soundcard as sc
import soundfile as sf
import threading
from playwright.sync_api import sync_playwright

duration = 10 # test for 10 seconds

def record_audio():
    print("Recording started...")
    speaker = sc.default_speaker()
    mics = sc.all_microphones(include_loopback=True)
    loopback = None
    for m in mics:
        if m.name == speaker.name:
            loopback = m
            break
    if not loopback:
        loopback = mics[0] # just pick first if exact match fails

    print(f"Using loopback device: {loopback.name}")
    with loopback.recorder(samplerate=44100) as mic:
        data = mic.record(numframes=44100 * duration)
        sf.write('test_recording.wav', data, 44100)
    print("Recording saved to test_recording.wav")

def play_suno():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        print("Navigating...")
        page.goto("https://suno.com/song/ba3e95c9-0c6d-4de2-96f5-dcc49508d6ad?sh=ObryapSr5ZU6YaZV", wait_until="domcontentloaded")
        print("Clicking play...")
        try:
            # The play button on Suno often has a data-testid="play-button" or aria-label="Play"
            # Let's try a few locators
            page.locator('button[aria-label="Play"]').first.click(timeout=10000)
        except Exception:
            try:
                page.locator('div[role="button"]:has-text("Play")').first.click(timeout=5000)
            except Exception as e:
                print("Could not find play button:", e)
        time.sleep(duration)
        browser.close()

t1 = threading.Thread(target=record_audio)
t1.start()
play_suno()
t1.join()
