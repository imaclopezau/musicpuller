// MusicPuller Popup script
document.addEventListener('DOMContentLoaded', () => {
  const trackNameEl = document.getElementById('track-name');
  const saveBtn = document.getElementById('save-btn');

  let currentStream = null;

  // Query background for last detected track
  chrome.runtime.sendMessage({ type: "GET_LAST_STREAM" }, (response) => {
    if (response && response.streamUrl) {
      currentStream = response;
      trackNameEl.textContent = response.title || response.streamUrl.split('/').pop().split('?')[0];
      saveBtn.disabled = false;
    }
  });

  saveBtn.addEventListener('click', () => {
    if (!currentStream) return;
    saveBtn.disabled = true;
    saveBtn.textContent = '⏳ Saving...';

    chrome.runtime.sendMessage({
      type: "SAVE_TRACK_TO_SERVER",
      streamUrl: currentStream.streamUrl,
      title: currentStream.title
    }, (res) => {
      saveBtn.textContent = '✓ Saved to Musicpuller!';
      setTimeout(() => {
        saveBtn.disabled = false;
        saveBtn.textContent = '⬇ Grab This Track Lossless';
      }, 3000);
    });
  });
});
