// Shared "sound effects volume" control for both the real draft
// (draft.js) and the mock draft (mock_draft.js) — one slider, one
// localStorage key, so a level set on either page carries to the
// other. Scales every <audio> clip's volume (chimes, ticks, easter
// eggs, celebrations, finale) and the intro video's volume — the only
// control for all of it, no separate dedicated intro-video slider.
(function () {
  var STORAGE_KEY = "ffDraftClipVolume";
  var DEFAULT_VOLUME = 0.6;

  function loadVolume() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      var v = raw !== null ? parseFloat(raw) : NaN;
      return isNaN(v) ? DEFAULT_VOLUME : Math.min(1, Math.max(0, v));
    } catch (e) {
      return DEFAULT_VOLUME;
    }
  }

  function saveVolume(v) {
    try {
      localStorage.setItem(STORAGE_KEY, String(v));
    } catch (e) {}
  }

  function applyVolume(v) {
    document.querySelectorAll("audio, video").forEach(function (el) {
      el.volume = v;
      // A video that fell back to muted autoplay (see draft.js) needs
      // an explicit unmute, not just a volume bump — .volume alone is
      // silent while .muted is true. Moving the slider is a real user
      // gesture, so unmuting here is never autoplay-policy-blocked.
      el.muted = v === 0;
    });
  }

  function init() {
    var slider = document.getElementById("clip-volume-slider");
    if (!slider) {
      return;
    }
    var volume = loadVolume();
    slider.value = Math.round(volume * 100);
    applyVolume(volume);

    slider.addEventListener("input", function () {
      var v = parseInt(slider.value, 10) / 100;
      applyVolume(v);
      saveVolume(v);
    });

    // New <audio> tags appear mid-draft (the Constructor Draft's clips
    // don't exist in the DOM until pairing starts, for example), each
    // arriving via an htmx swap — re-apply the current level whenever
    // one happens so newly-added clips pick it up too. No-op on the
    // mock draft page, which has no htmx and all its clips up front.
    document.body.addEventListener("htmx:afterSwap", function () {
      applyVolume(parseInt(slider.value, 10) / 100);
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
