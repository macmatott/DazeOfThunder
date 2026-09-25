/*
 * Live-ticking countdown widgets (see _macros.html's stat_card_countdown)
 * — used by the dashboard's Next League Race / Next Team Event cards and
 * the Team Events page's next-event card. Same target-computed-server-
 * side-once, tick-client-side-every-second pattern as the schedule
 * page's sim countdown (schedule.js's initSimCountdown), generalized to
 * handle any number of instances via a shared data attribute instead of
 * fixed ids.
 *
 * The Team Events page outerHTML-swaps a card on every RSVP click (see
 * _team_event_card.html's hx-swap), so this (re-)scans on both
 * DOMContentLoaded and htmx:afterSwap, same as standings-charts.js's
 * chart rendering — and, like that file's destroyOrphans, clears any
 * interval whose element got replaced by a swap rather than leaving it
 * ticking against a detached node forever.
 */
(function () {
  var timers = new Map(); // countdown container element -> interval id

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function tick(el, target, clock, soon, values) {
    var remaining = target - Date.now();
    if (remaining <= 0) {
      clock.hidden = true;
      soon.hidden = false;
      clearInterval(timers.get(el));
      timers.delete(el);
      return;
    }
    var totalSeconds = Math.floor(remaining / 1000);
    if (values.days) values.days.textContent = pad(Math.floor(totalSeconds / 86400));
    if (values.hours) values.hours.textContent = pad(Math.floor((totalSeconds % 86400) / 3600));
    if (values.minutes) values.minutes.textContent = pad(Math.floor((totalSeconds % 3600) / 60));
    if (values.seconds) values.seconds.textContent = pad(totalSeconds % 60);
  }

  function initCountdownWidgets() {
    timers.forEach(function (intervalId, el) {
      if (!document.body.contains(el)) {
        clearInterval(intervalId);
        timers.delete(el);
      }
    });

    document.querySelectorAll("[data-countdown-target]").forEach(function (el) {
      if (timers.has(el)) return; // already ticking
      var target = new Date(el.dataset.countdownTarget).getTime();
      var clock = el.querySelector("[data-countdown-clock]");
      var soon = el.querySelector("[data-countdown-soon]");
      if (!clock || !soon) return;

      var values = {};
      clock.querySelectorAll("[data-unit]").forEach(function (span) {
        values[span.dataset.unit] = span;
      });

      tick(el, target, clock, soon, values);
      timers.set(
        el,
        setInterval(function () {
          tick(el, target, clock, soon, values);
        }, 1000)
      );
    });
  }

  document.addEventListener("DOMContentLoaded", initCountdownWidgets);
  document.body.addEventListener("htmx:afterSwap", initCountdownWidgets);
})();
