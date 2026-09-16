// Only callable in this extension worker via the local DevTools connection.
// No external messaging or remote code.
async function tekziteFeature(action, payload) {
  if (action === "configure") {
    const sites = [...new Set(payload.sites || [])].filter(s => typeof s === "string" && /^[a-z0-9.-]+$/.test(s));
    const rules = sites.map((host, i) => ({id: i + 1, priority: 10,
      action: {type: "allowAllRequests"},
      condition: {requestDomains: [host], resourceTypes: ["main_frame"]}}));
    const old = await chrome.declarativeNetRequest.getDynamicRules();
    await chrome.declarativeNetRequest.updateDynamicRules({removeRuleIds: old.map(r => r.id), addRules: rules});

    const desired = {
      ads: payload.enabled !== false,
      trackers: payload.tracker_blocking !== false,
      privacy_headers: payload.strip_referrer !== false,
    };
    const enableRulesetIds = Object.entries(desired).filter(([, enabled]) => enabled).map(([id]) => id);
    const disableRulesetIds = Object.entries(desired).filter(([, enabled]) => !enabled).map(([id]) => id);
    await chrome.declarativeNetRequest.updateEnabledRulesets({enableRulesetIds, disableRulesetIds});
    return true;
  }
  if (action === "downloads") {
    return await chrome.downloads.search({orderBy: ["-startTime"], limit: 200});
  }
  if (!["cancel", "retry", "resume", "pause", "show", "open", "erase"].includes(action) || !Number.isInteger(payload.id))
    throw new Error("Unknown download action");
  const [item] = await chrome.downloads.search({id: payload.id});
  if (!item) throw new Error("Download is no longer available");
  if (action === "show") { chrome.downloads.show(item.id); return true; }
  if (action === "open") { await chrome.downloads.open(item.id); return true; }
  if (action === "erase") { await chrome.downloads.erase({id: item.id}); return true; }
  if (action === "pause") { await chrome.downloads.pause(item.id); return true; }
  if (action === "resume") { await chrome.downloads.resume(item.id); return true; }
  if (action === "cancel") { await chrome.downloads.cancel(item.id); return true; }
  if (item.canResume) { await chrome.downloads.resume(item.id); return true; }
  if (item.state !== "interrupted") throw new Error("Only interrupted downloads can be retried");
  if (!/^https?:/i.test(item.finalUrl || item.url)) throw new Error("Reopen the original page to retry this download");
  return await chrome.downloads.download({url: item.finalUrl || item.url, conflictAction: "uniquify"});
}
