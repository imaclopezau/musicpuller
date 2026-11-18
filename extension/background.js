// MusicPuller Background Service Worker
// Intercepts authenticated Suno media streams and forwards them to MusicPuller local server

let lastDetectedTrack = {
  title: "Suno Track",
  streamUrl: "",
  timestamp: 0
};

// Listen for audio stream network requests from Suno CDNs
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    const url = details.url;
    // Check if this is an audio file from Suno CDN
    if (url.includes('.mp3') || url.includes('.wav') || url.includes('.m4a') || url.includes('audiocdn') || url.includes('cdn1.suno.ai') || url.includes('cdn2.suno.ai')) {
      if (details.type === 'media' || details.type === 'xmlhttprequest' || details.type === 'other') {
        console.log("[MusicPuller] Captured direct audio stream:", url);
        lastDetectedTrack.streamUrl = url;
        lastDetectedTrack.timestamp = Date.now();

        // Notify active Suno tabs to pair with current song title
        chrome.tabs.query({ active: true, url: "https://suno.com/*" }, (tabs) => {
          if (tabs && tabs[0]) {
            chrome.tabs.sendMessage(tabs[0].id, { type: "STREAM_DETECTED", url: url });
          }
        });
      }
    }
  },
  { urls: ["https://*.suno.ai/*", "https://*.suno.com/*"] }
);

// Listen for messages from content script or popup
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "SAVE_TRACK_TO_SERVER") {
    const streamUrl = message.streamUrl || lastDetectedTrack.streamUrl;
    const title = message.title || lastDetectedTrack.title || "Suno_Track";

    // Grab Suno authentication cookies to authenticate download
    chrome.cookies.getAll({ domain: "suno.ai" }, (aiCookies) => {
      chrome.cookies.getAll({ domain: "suno.com" }, (comCookies) => {
        const cookieMap = {};
        [...(aiCookies || []), ...(comCookies || [])].forEach((c) => {
          cookieMap[c.name] = c.value;
        });

        // Forward stream URL & cookies to MusicPuller Flask backend
        fetch("http://127.0.0.1:5000/save_stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            stream_url: streamUrl,
            title: title,
            cookies: cookieMap
          })
        })
          .then((res) => res.json())
          .then((data) => {
            console.log("[MusicPuller] Server response:", data);
            sendResponse({ success: true, data: data });
          })
          .catch((err) => {
            console.error("[MusicPuller] Server error:", err);
            // Fallback: download directly in Chrome via chrome.downloads
            chrome.downloads.download({
              url: streamUrl,
              filename: `Musicpuller/${title.replace(/[\/\\:*?"<>|]/g, "")}.mp3`,
              saveAs: false
            }, (downloadId) => {
              sendResponse({ success: true, fallback: true, downloadId: downloadId });
            });
          });
      });
    });
    return true; // Keep message channel open for async response
  }

  if (message.type === "UPDATE_TITLE") {
    lastDetectedTrack.title = message.title;
    sendResponse({ ok: true });
  }

  if (message.type === "GET_LAST_STREAM") {
    sendResponse(lastDetectedTrack);
  }
});
