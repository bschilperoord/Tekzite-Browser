(() => {
  // Expose the Global Privacy Control signal to page JavaScript. This runs in
  // the page's MAIN world; the matching HTTP header is also sent through CDP.
  try {
    Object.defineProperty(Navigator.prototype, "globalPrivacyControl", {
      configurable: true,
      enumerable: true,
      get: () => true,
    });
  } catch (_) {}
  try {
    if (!navigator.doNotTrack || navigator.doNotTrack === "unspecified") {
      Object.defineProperty(Navigator.prototype, "doNotTrack", {
        configurable: true,
        enumerable: true,
        get: () => "1",
      });
    }
  } catch (_) {}
})();
