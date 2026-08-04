document.addEventListener("DOMContentLoaded", function () {
  var board = document.getElementById("draft-board");
  var chime = document.getElementById("draft-turn-chime");
  if (!board || !chime) {
    return;
  }

  // Every poll swaps in a fresh #draft-turn-marker regardless of whether
  // anything changed, so track which pick we last chimed for. Keying off
  // the pick number (not just an on-the-clock boolean) matters when the
  // same person is on the clock in back-to-back turns — e.g. a
  // single-participant test league picks every round, so "on the clock"
  // never toggles off in between and a boolean flip would miss it.
  var lastChimedPickNumber = null;

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
  });
});
