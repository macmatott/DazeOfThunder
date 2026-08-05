document.addEventListener("DOMContentLoaded", function () {
  var board = document.getElementById("draft-board");
  var chime = document.getElementById("draft-turn-chime");
  var tick = document.getElementById("draft-tick-sound");
  if (!board || !chime) {
    return;
  }

  var TICK_THRESHOLD_SECONDS = 8;

  // Every poll swaps in a fresh #draft-turn-marker regardless of whether
  // anything changed, so track which pick we last chimed/ticked for.
  // Keying off the pick number (not just an on-the-clock boolean) matters
  // when the same person is on the clock in back-to-back turns — e.g. a
  // single-participant test league picks every round, so "on the clock"
  // never toggles off in between and a boolean flip would miss it.
  var lastChimedPickNumber = null;
  var lastTickedPickNumber = null;

  board.addEventListener("htmx:afterSwap", function () {
    var marker = document.getElementById("draft-turn-marker");
    if (!marker) {
      return;
    }
    var isOnTheClock = marker.dataset.onTheClock === "true";
    var pickNumber = marker.dataset.pickNumber;

    if (isOnTheClock && pickNumber && pickNumber !== lastChimedPickNumber) {
      chime.currentTime = 0;
      chime.play().catch(function () {
        // Autoplay blocked (no user interaction yet on this page) — fine,
        // the visible countdown still shows it's their turn.
      });
      lastChimedPickNumber = pickNumber;
    }

    if (tick && isOnTheClock && pickNumber) {
      var secondsRemaining = parseInt(marker.dataset.secondsRemaining, 10);
      var alreadyTickedThisPick = pickNumber === lastTickedPickNumber;
      if (!isNaN(secondsRemaining) && secondsRemaining <= TICK_THRESHOLD_SECONDS && !alreadyTickedThisPick) {
        tick.currentTime = 0;
        tick.play().catch(function () {});
        lastTickedPickNumber = pickNumber;
      }
    }
  });
});
