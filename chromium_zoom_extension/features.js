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
  if (action === "privacyStats") {
    let counters = {ads_blocked: 0, trackers_blocked: 0};
    if (typeof globalThis.tekziteGetPrivacyCounters === "function") {
      try {
        counters = await globalThis.tekziteGetPrivacyCounters();
      } catch (_) {}
    }

    // Heal missed service-worker events from Chromium's own recent matched-rule
    // history. The event counters keep the full session total when available;
    // this snapshot makes Privacy Shield robust when the worker slept through
    // a match or restarted.
    try {
      const details = await chrome.declarativeNetRequest.getMatchedRules();
      const snapshot = {ads_blocked: 0, trackers_blocked: 0};
      for (const info of (details?.rulesMatchedInfo || [])) {
        const ruleset = String(info?.rule?.rulesetId || "");
        if (ruleset === "ads") snapshot.ads_blocked += 1;
        else if (ruleset === "trackers") snapshot.trackers_blocked += 1;
      }
      counters.ads_blocked = Math.max(Number(counters.ads_blocked || 0), snapshot.ads_blocked);
      counters.trackers_blocked = Math.max(Number(counters.trackers_blocked || 0), snapshot.trackers_blocked);
    } catch (_) {}

    return {
      ads_blocked: Number(counters.ads_blocked || 0),
      trackers_blocked: Number(counters.trackers_blocked || 0),
    };
  }
  if (action === "downloads") {
    return await chrome.downloads.search({orderBy: ["-startTime"], limit: 200});
  }
  if (!["cancel", "retry", "resume", "pause", "show", "open", "erase"].includes(action) || !Number.isInteger(payload.id))
    throw new Error("Unknown download action");
  const [item] = await chrome.downloads.search({id: payload.id});
  if (!item) throw new Error("Download is no longer available");
  if (action === "show") { chrome.downloads.show(item.id); return true; }
  if (action === "open") {
    const safeDangerStates = new Set(["safe", "accepted", "deepScannedSafe"]);
    const danger = String(item.danger || "");
    if (item.state !== "complete") throw new Error("Download is not complete");
    if (!safeDangerStates.has(danger))
      throw new Error(`Tekzite blocked opening a download with danger status: ${danger || "unknown"}`);
    await chrome.downloads.open(item.id);
    return true;
  }
  if (action === "erase") { await chrome.downloads.erase({id: item.id}); return true; }
  if (action === "pause") { await chrome.downloads.pause(item.id); return true; }
  if (action === "resume") { await chrome.downloads.resume(item.id); return true; }
  if (action === "cancel") { await chrome.downloads.cancel(item.id); return true; }
  if (item.canResume) { await chrome.downloads.resume(item.id); return true; }
  if (item.state !== "interrupted") throw new Error("Only interrupted downloads can be retried");
  if (!/^https?:/i.test(item.finalUrl || item.url)) throw new Error("Reopen the original page to retry this download");
  return await chrome.downloads.download({url: item.finalUrl || item.url, conflictAction: "uniquify"});
}
