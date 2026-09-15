(async () => {
  const KEY = "tekziteDesiredZoom";
  const params = new URLSearchParams(location.search);
  let zoom = Number(params.get("zoom"));
  if (!Number.isFinite(zoom)) zoom = 1.0;
  zoom = Math.max(0.5, Math.min(3.0, zoom));
  let applied = 0;
  let verified = 0;
  let eligible = 0;

  try { await chrome.storage.local.set({[KEY]: zoom}); } catch (_) {}
  try {
    const tabs = await chrome.tabs.query({});
    for (const tab of tabs) {
      if (!tab || !/^(https?:|file:|about:)/i.test(String(tab.url || ""))) continue;
      eligible++;
      try {
        // "automatic" is essential here: Chromium itself must perform the
        // visual page scaling. "manual" only reports/controls zoom state and
        // leaves visual scaling to the extension.
        await chrome.tabs.setZoomSettings(tab.id, {mode: "automatic", scope: "per-tab"});
      } catch (_) {}
      try {
        await chrome.tabs.setZoom(tab.id, zoom);
        applied++;
        const actual = Number(await chrome.tabs.getZoom(tab.id));
        if (Number.isFinite(actual) && Math.abs(actual - zoom) < 0.001) verified++;
      } catch (_) {}
    }
  } catch (_) {}

  document.title = `TEKZITE_ZOOM_DONE:${zoom}:${applied}:${verified}:${eligible}`;
  document.body.textContent = document.title;
})();
