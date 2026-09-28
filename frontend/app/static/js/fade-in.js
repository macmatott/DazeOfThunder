/*
 * Site-wide page-open/refresh entrance — fades/slides in each of
 * <main>'s direct children, staggered slightly so they cascade top to
 * bottom instead of all popping in at once. Loaded once from base.html
 * rather than per-template, so it applies everywhere automatically
 * without every page needing its own markup for it. Runs once at
 * initial load only (this script only ever runs then, never on an
 * HTMX partial swap), so it never re-triggers on tab switches, RSVP
 * clicks, or the draft board's live polling.
 *
 * CSS animations with fill-mode "both" keep overriding an animated
 * property even after they finish, which would silently break these
 * same elements' own :hover { transform: scale(...) } effects (stat
 * cards, trophy cards, race rows). Dropping the class once each
 * element's animation ends removes the animation and hands `transform`
 * back to the normal cascade, so hover keeps working afterward.
 */
(function () {
  var STEP_SECONDS = 0.08;
  var MAX_DELAY_SECONDS = 0.6;

  var main = document.querySelector("main");
  if (!main) return;

  var index = 0;
  Array.prototype.forEach.call(main.children, function (el) {
    if (el.tagName === "SCRIPT" || el.tagName === "TEMPLATE") return;

    var delay = Math.min(index * STEP_SECONDS, MAX_DELAY_SECONDS);
    index += 1;

    el.style.setProperty("--fade-delay", delay + "s");
    el.classList.add("fade-in-up");
    el.addEventListener(
      "animationend",
      function () {
        el.classList.remove("fade-in-up");
        el.style.removeProperty("--fade-delay");
      },
      { once: true }
    );
  });
})();
