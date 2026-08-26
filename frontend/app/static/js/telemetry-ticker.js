/*
 * Live telemetry ticker — polls an external Worker for who's currently
 * streaming iRacing and scrolls their driver/car/track/lap across a bar
 * under the header. Hides itself (via the --active class) when nobody's
 * live.
 *
 * Entries are built with createElement/textContent, not innerHTML —
 * the fetched fields (driver_name, car, track) come from a third-party
 * Worker outside this repo, so they're treated as untrusted text, never
 * as HTML.
 */
(function () {
  var TELEMETRY_URL = "https://thunder-chief.hallpm11.workers.dev/telemetry/live";
  var POLL_MS = 5000;

  var wrap = document.getElementById("telemetry-ticker");
  var trackEl = document.getElementById("telemetry-ticker-track");
  if (!wrap || !trackEl) return;

  function buildItem(d) {
    var el = document.createElement("span");
    el.className = "telemetry-ticker-item";

    var pos = document.createElement("span");
    pos.className = "pos";
    pos.textContent = d.position ? "P" + d.position : "P—";
    el.appendChild(pos);

    var name = document.createElement("b");
    name.textContent = d.driver_name || "Unknown";
    el.appendChild(name);

    var car = document.createElement("span");
    car.textContent = d.car || "";
    el.appendChild(car);

    var trackName = document.createElement("span");
    trackName.textContent = "at " + (d.track || "Unknown track");
    el.appendChild(trackName);

    if (d.lap) {
      var lap = document.createElement("span");
      lap.textContent = "Lap " + d.lap;
      el.appendChild(lap);
    }

    var sep = document.createElement("span");
    sep.className = "telemetry-ticker-sep";
    sep.textContent = "✦";
    el.appendChild(sep);

    return el;
  }

  function render(drivers) {
    trackEl.innerHTML = "";
    trackEl.style.animation = "none";

    if (!drivers || drivers.length === 0) {
      wrap.classList.remove("telemetry-ticker--active");
      return;
    }
    wrap.classList.add("telemetry-ticker--active");

    // Duplicate the list so the marquee loop is seamless (scrolls -50%,
    // i.e. exactly one full copy, then snaps back unnoticed).
    var frag = document.createDocumentFragment();
    drivers.concat(drivers).forEach(function (d) {
      frag.appendChild(buildItem(d));
    });
    trackEl.appendChild(frag);

    // Speed scales with content length so it never feels rushed with 1
    // driver or glacial with 10.
    var duration = Math.max(15, drivers.length * 6);
    trackEl.style.animation = "telemetry-ticker-scroll " + duration + "s linear infinite";
  }

  function poll() {
    fetch(TELEMETRY_URL)
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        render(data.drivers || []);
      })
      .catch(function (err) {
        console.error("telemetry ticker: fetch failed", err);
      });
  }

  poll();
  setInterval(poll, POLL_MS);

  // No hover on touch devices — let a press-and-hold pause the scroll so
  // someone can actually read an entry instead of chasing scrolling text.
  wrap.addEventListener(
    "touchstart",
    function () {
      trackEl.style.animationPlayState = "paused";
    },
    { passive: true }
  );
  wrap.addEventListener(
    "touchend",
    function () {
      trackEl.style.animationPlayState = "running";
    },
    { passive: true }
  );
})();
