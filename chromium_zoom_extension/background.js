try { importScripts("features.js"); } catch (error) { console.error("Tekzite services:", error); }
const KEY = "tekziteDesiredZoom";
let desiredZoom = 1.0;
const applying = new Set();

const TRACKING_KEYS = new Set([
  "fbclid","gclid","dclid","msclkid","twclid","ttclid","li_fat_id","igshid",
  "mc_cid","mc_eid","mkt_tok","vero_conv","vero_id","oly_anon_id","oly_enc_id",
  "rb_clickid","s_cid","wickedid","_hsenc","_hsmi","ga_source","ga_medium","ga_term",
  "ga_content","ga_campaign","yclid","gbraid","wbraid","epik","irclickid","ref_src",
  "ref_url","spm","scm","campaign_id","ad_id","adset_id"
]);

function sanitizeTrackingUrl(value) {
  try {
    const url = new URL(String(value || ""));
    if (!/^https?:$/.test(url.protocol)) return String(value || "");
    let changed = false;
    for (const key of [...url.searchParams.keys()]) {
      const lower = String(key).toLowerCase();
      if (TRACKING_KEYS.has(lower) || lower.startsWith("utm_")) {
        url.searchParams.delete(key);
        changed = true;
      }
    }
    return changed ? url.toString() : String(value || "");
  } catch (_) {
    return String(value || "");
  }
}

function usableUrl(url) {
  return /^(https?:|file:|about:)/i.test(String(url || ""));
}

async function loadDesired() {
  try {
    const data = await chrome.storage.local.get(KEY);
    const value = Number(data[KEY]);
    if (Number.isFinite(value) && value >= 0.5 && value <= 3.0) desiredZoom = value;
  } catch (_) {}
  return desiredZoom;
}

async function applyZoom(tabId) {
  try {
    const tab = await chrome.tabs.get(tabId);
    if (!tab || !usableUrl(tab.url)) return false;
    const current = await chrome.tabs.getZoom(tabId);
    if (Math.abs(Number(current) - desiredZoom) < 0.001) return true;
    applying.add(tabId);
    try {
      await chrome.tabs.setZoomSettings(tabId, {mode: "automatic", scope: "per-tab"});
    } catch (_) {}
    await chrome.tabs.setZoom(tabId, desiredZoom);
    setTimeout(() => applying.delete(tabId), 250);
    return true;
  } catch (_) {
    applying.delete(tabId);
    return false;
  }
}

async function applyAll() {
  await loadDesired();
  let tabs = [];
  try { tabs = await chrome.tabs.query({}); } catch (_) { return; }
  await Promise.allSettled(tabs.map(tab => applyZoom(tab.id)));
}

chrome.runtime.onInstalled.addListener(() => { applyAll(); });
chrome.runtime.onStartup.addListener(() => { applyAll(); });
chrome.tabs.onCreated.addListener(tab => { setTimeout(() => applyZoom(tab.id), 80); });
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.url) {
    const clean = sanitizeTrackingUrl(changeInfo.url);
    if (clean && clean !== changeInfo.url) {
      chrome.tabs.update(tabId, {url: clean}).catch(() => {});
      return;
    }
  }
  if (changeInfo.status || changeInfo.url) setTimeout(() => applyZoom(tabId), 40);
});
chrome.tabs.onActivated.addListener(info => { applyZoom(info.tabId); });
chrome.tabs.onZoomChange.addListener(info => {
  if (applying.has(info.tabId)) return;
  if (Math.abs(Number(info.newZoomFactor) - desiredZoom) >= 0.001) {
    setTimeout(() => applyZoom(info.tabId), 0);
  }
});
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local" || !changes[KEY]) return;
  const value = Number(changes[KEY].newValue);
  if (Number.isFinite(value) && value >= 0.5 && value <= 3.0) desiredZoom = value;
  applyAll();
});

loadDesired().then(applyAll);
