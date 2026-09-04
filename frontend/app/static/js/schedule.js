document.addEventListener("DOMContentLoaded", function () {
  // Live-ticking countdown to the next sim race — the server renders an
  // initial value (see ff_schedule.html's sim_countdown) so there's
  // correct content on first paint, then this takes over every second.
  // The target itself (data-target) is computed server-side once, in
  // the league's own timezone with the DST offset already resolved —
  // this only ever does arithmetic on a fixed instant, never re-derives
  // "when is the next Thursday" itself, so it can't drift or get a
  // DST transition wrong the way re-computing that in JS could.
  (function initSimCountdown() {
    var el = document.getElementById("sim-countdown");
    if (!el) return;
    var target = new Date(el.dataset.target).getTime();
    var clock = document.getElementById("sim-countdown-clock");
    var soon = document.getElementById("sim-countdown-soon");
    var values = {
      days: clock.querySelector('[data-unit="days"]'),
      hours: clock.querySelector('[data-unit="hours"]'),
      minutes: clock.querySelector('[data-unit="minutes"]'),
      seconds: clock.querySelector('[data-unit="seconds"]'),
    };

    function pad(n) {
      return String(n).padStart(2, "0");
    }

    function tick() {
      var remaining = target - Date.now();
      if (remaining <= 0) {
        clock.hidden = true;
        soon.hidden = false;
        clearInterval(intervalId);
        return;
      }
      var totalSeconds = Math.floor(remaining / 1000);
      values.days.textContent = pad(Math.floor(totalSeconds / 86400));
      values.hours.textContent = pad(Math.floor((totalSeconds % 86400) / 3600));
      values.minutes.textContent = pad(Math.floor((totalSeconds % 3600) / 60));
      values.seconds.textContent = pad(totalSeconds % 60);
    }

    tick();
    var intervalId = setInterval(tick, 1000);
  })();

  // Every race row carries id="round-N" (see ff_schedule.html) — past
  // rounds are collapsed behind two nested toggles (the "Past Races"
  // section, then the round's own results dropdown), so jumping to one
  // means opening both before scrolling, not just finding the element.
  function openRound(round) {
    var target = document.getElementById("round-" + round);
    if (!target) return null;
    var pastToggle = target.closest(".past-events-toggle");
    if (pastToggle) pastToggle.open = true;
    if (target.tagName === "DETAILS") target.open = true;
    return target;
  }

  var params = new URLSearchParams(window.location.search);
  var requestedRound = params.get("round");
  var jumpSelect = document.getElementById("round-jump");
  var jumped = null;

  if (requestedRound) {
    jumped = openRound(requestedRound);
    if (jumped && jumpSelect) {
      jumpSelect.value = requestedRound;
    }
  }

  if (jumped) {
    jumped.scrollIntoView({ block: "center" });
  } else {
    var nextRace = document.querySelector(".race-row--next");
    if (nextRace) {
      nextRace.scrollIntoView({ block: "center" });
    }
  }

  if (jumpSelect) {
    jumpSelect.addEventListener("change", function () {
      var round = jumpSelect.value;
      if (!round) return;
      var target = openRound(round);
      if (target) target.scrollIntoView({ block: "center" });

      var url = new URL(window.location.href);
      url.searchParams.set("round", round);
      window.history.replaceState(null, "", url);
    });
  }
});
