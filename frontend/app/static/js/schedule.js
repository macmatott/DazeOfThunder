document.addEventListener("DOMContentLoaded", function () {
  // The page's "Next Sim Race" banner is a live-ticking countdown too,
  // but that's handled by countdown_widgets.js now (loaded alongside
  // this file — see ff_schedule.html's scripts block), which generalized
  // this exact logic to work for more than one countdown per page.

  var nextRace = document.querySelector(".race-row--next");
  if (nextRace) {
    nextRace.scrollIntoView({ block: "center" });
  }
});
