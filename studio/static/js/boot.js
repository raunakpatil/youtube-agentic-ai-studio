/* ═══════════════════════════ boot ═══════════════════════════ */
Object.assign(loaders, {
  home: loadLibrary,
  review: loadReview,
  library: loadLibrary,
  settings: loadSettings,
});
setHero("form");
route();
pollStatus();
loadTrends();
loadHealth();
loadSettings().catch(() => {});
document.fonts && document.fonts.ready.then(moveIndicator);
