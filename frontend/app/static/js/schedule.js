document.addEventListener("DOMContentLoaded", function () {
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
