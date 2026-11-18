// MusicPuller Background Service Worker
// Intercepts authenticated Suno media streams and forwards them to MusicPuller local server

let lastDetectedTrack = {
  title: "Suno Track",
  streamUrl: "",
  timestamp: 0
};

// Listen for audio stream network requests from Suno CDNs or any audio resource
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    const url = details.url;
    // Check if this is an audio file from Suno CDN or audio mime/extension
    const isAudio = url.includes('.mp3') || url.includes('.wav') || url.includes('.m4a') || 
                    url.includes('.opus') || url.includes('.webm') || url.includes('audiocdn') || 
                    url.includes('cdn1.suno.ai') || url.includes('cdn2.suno.ai') || url.includes('/audio/');

    if (isAudio) {
      console.log("[MusicPuller] Captured direct audio stream:", url);
      lastDetectedTrack.streamUrl = url;
      lastDetectedTrack.timestamp = Date.now();

      // Notify all tabs on suno.com
      chrome.tabs.query({ url: "*://*.suno.com/*" }, (tabs) => {
        tabs.forEach((tab) => {
          chrome.tabs.sendMessage(tab.id, { type: "STREAM_DETECTED", url: url }).catch(() => {});
        });
      });
    }
  },
  { urls: ["<all_urls>"] }
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
