// Visible indicator on page showing extension is connected
function ensureIndicator() {
  if (document.getElementById('musicpuller-indicator')) return;
  const indicator = document.createElement('div');
  indicator.id = 'musicpuller-indicator';
  indicator.style.cssText = `
    position: fixed;
    top: 12px;
    right: 180px;
    background: rgba(0, 0, 0, 0.85);
    color: #ff5e00;
    border: 1px solid #ff5e00;
    border-radius: 20px;
    padding: 6px 14px;
    font-size: 12px;
    font-family: sans-serif;
    font-weight: bold;
    z-index: 999999;
    display: flex;
    align-items: center;
    gap: 6px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.5);
    cursor: default;
  `;
  indicator.innerHTML = `<span>🎵</span> MusicPuller: <span id="musicpuller-ind-status" style="color: #00ff88;">Listening</span>`;
  document.body.appendChild(indicator);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', ensureIndicator);
} else {
  ensureIndicator();
}

let currentPlayingTitle = "";

// Helper to get currently playing song title from Suno DOM
function getCurrentPlayingTitle() {
  // Method 1: Bottom player bar title
  const bottomPlayerTitle = document.querySelector('[data-testid="player-title"], [class*="PlayerTitle"], [class*="track-title"]');
  if (bottomPlayerTitle && bottomPlayerTitle.textContent.trim()) {
    return bottomPlayerTitle.textContent.trim();
  }

  // Method 2: Active or highlighted track in library/playlist
  const playingItem = document.querySelector('[aria-label="Pause"], [data-playing="true"]');
  if (playingItem) {
    const parentRow = playingItem.closest('[class*="row"], [class*="track"], [class*="card"], li');
    if (parentRow) {
      const heading = parentRow.querySelector('h3, h4, a[href*="/song/"], [class*="title"]');
      if (heading && heading.textContent.trim()) {
        return heading.textContent.trim();
      }
    }
  }

  // Method 3: Page title fallback
  const docTitle = document.title.replace(/\s*\|\s*Suno.*$/, "").trim();
  return docTitle || "Suno Track";
}

// Receive stream captured by background service worker
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "STREAM_DETECTED") {
    handleCapturedStream(msg.url);
  }
});

let processedUrls = new Set();

function handleCapturedStream(url) {
  if (!url || processedUrls.has(url)) return;
  processedUrls.add(url);

  currentPlayingTitle = getCurrentPlayingTitle();
  console.log(`[MusicPuller] Handling stream for: "${currentPlayingTitle}" -> ${url}`);

  chrome.runtime.sendMessage({
    type: "SAVE_TRACK_TO_SERVER",
    streamUrl: url,
    title: currentPlayingTitle
  }, (res) => {
    showToastNotification(`✓ Grabbed: ${currentPlayingTitle}`);
  });
}

// Active DOM Audio Sniffing: Hook into <audio> tags directly on Suno
setInterval(() => {
  const audios = document.querySelectorAll('audio');
  audios.forEach((audio) => {
    const src = audio.currentSrc || audio.src;
    if (src && !src.startsWith('blob:') && (src.includes('.mp3') || src.includes('.wav') || src.includes('.m4a') || src.includes('cdn'))) {
      if (!audio.__musicpuller_hooked) {
        audio.__musicpuller_hooked = true;
        audio.addEventListener('play', () => {
          handleCapturedStream(audio.currentSrc || audio.src);
        });
      }
      if (!audio.paused) {
        handleCapturedStream(src);
      }
    }
  });
}, 1000);

// Toast notification UI injected on suno.com
function showToastNotification(text) {
  let toast = document.getElementById("musicpuller-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "musicpuller-toast";
    toast.style.cssText = `
      position: fixed;
      bottom: 80px;
      right: 25px;
      background: linear-gradient(135deg, #111, #1e1e1e);
      color: #00ff88;
      border: 1px solid #00ff88;
      box-shadow: 0 4px 18px rgba(0, 255, 136, 0.35);
      border-radius: 8px;
      padding: 12px 18px;
      font-size: 13px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-weight: 600;
      z-index: 999999;
      display: flex;
      align-items: center;
      gap: 8px;
      transition: all 0.3s ease;
      opacity: 0;
      transform: translateY(10px);
    `;
    document.body.appendChild(toast);
  }

  toast.innerHTML = `🎵 <span>${text}</span>`;
  toast.style.opacity = "1";
  toast.style.transform = "translateY(0)";

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
  }, 4000);
}
