/*
 * Standings page charts (Chart.js) — points progression on the
 * Drivers'/Fantasy/Overall tabs, a team-breakdown bar on Constructors',
 * and a per-driver "best 9 of 12" bar inside each Drivers' tab row's
 * dropdown. All three read their data from a sibling <script
 * type="application/json"> tag rendered by _standings_tab.html rather
 * than a fetch — the data's already in the page.
 *
 * #standings-wrap gets outerHTML-swapped on every tab click (see
 * _standings_tab.html's hx-swap), so charts are (re-)built on both
 * DOMContentLoaded and htmx:afterSwap rather than once at load.
 */
(function () {
  // Rotates for however many rows a chart needs (up to 11 members
  // today) — starts with the site's own accent colors, then fills out
  // with a few more hues distinct enough to tell apart on a dark
  // background.
  var PALETTE = [
    "#e8dc3b", // --color-accent
    "#2272f1", // --color-accent-blue
    "#5fb87a", // --color-positive
    "#d9634a", // --color-negative
    "#a855f7", // --color-fastest-lap
    "#e8985a",
    "#4ac4d9",
    "#c14ac1",
    "#8bd94a",
    "#d94aa0",
    "#4a7fd9",
  ];
  var TEXT_DIM = "#8b90a3";
  var RULE = "#2e3242";
  var DROPPED_COLOR = "#3a3f52";

  function hexToRgba(hex, alpha) {
    var r = parseInt(hex.slice(1, 3), 16);
    var g = parseInt(hex.slice(3, 5), 16);
    var b = parseInt(hex.slice(5, 7), 16);
    return "rgba(" + r + "," + g + "," + b + "," + alpha + ")";
  }

  function readJson(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (err) {
      console.error("standings-charts: couldn't parse " + id, err);
      return null;
    }
  }

  function baseAxis() {
    return {
      ticks: { color: TEXT_DIM },
      grid: { color: RULE },
    };
  }

  // Every htmx tab swap brings in a brand new <canvas id="progression-
  // chart"> (etc.) — a different DOM element each time, even though the
  // id is the same one as before. Chart.js's own Chart.getChart(canvas)
  // lookup is keyed by that live element, so it can never find (and
  // therefore never destroys) the PREVIOUS tab's chart still sitting on
  // the now-detached old canvas — every swap just leaked another
  // instance. That pile-up of abandoned instances (and whatever
  // ResizeObservers/timers they still held) was the real cause of a
  // second bug this app hit: charts on a revisited tab occasionally
  // rendering at the wrong size. Tracking charts by their stable id
  // string instead — and always destroying whatever was last registered
  // under that id before creating the next one — closes the leak
  // regardless of DOM node churn.
  var chartsById = {};

  // Confirmed directly in DevTools: Chart.js's own responsive-mode
  // sizing sometimes applies only ONE of the canvas's width/height
  // attributes and leaves the other completely unset (falling back to
  // the bare <canvas> default of 300/150) — inconsistently, not tied to
  // any one dimension. The CSS `.chart-canvas-wrap canvas` rule forces
  // the element's *displayed box* to the right size regardless, but
  // that doesn't fix what happens underneath it: Chart.js still lays
  // out and draws the chart's contents (legend, axes, points) assuming
  // whatever drawing-buffer resolution it thinks the canvas has, and
  // that undersized drawing then gets stretched by the CSS box to fill
  // the visibly-correct container — exactly the "zoomed in"/distorted
  // look reported. Rather than chase Chart.js's own sizing further,
  // responsive is turned off entirely and both dimensions (in real
  // device pixels, for a crisp result on high-DPI screens) are set
  // directly, synchronously, right here, immediately before AND after
  // construction — so there's no window during which Chart.js's own
  // logic can leave either one unset.
  function cssSize(canvas) {
    var parent = canvas.parentElement;
    return parent ? { w: parent.clientWidth, h: parent.clientHeight } : null;
  }

  function sizeCanvas(canvas, size) {
    var dpr = window.devicePixelRatio || 1;
    canvas.style.width = size.w + "px";
    canvas.style.height = size.h + "px";
    canvas.width = Math.round(size.w * dpr);
    canvas.height = Math.round(size.h * dpr);
  }

  var observersById = {};

  // Confirmed with a MutationObserver: something inside Chart.js itself
  // — not this app's own code, and not tied to its animation system
  // (still happens with animation: false) — reaches back into the
  // canvas well after construction (~150-400ms later) and strips its
  // width attribute and part of its inline style, on top of whatever
  // responsive/resize options are set. Rather than chase Chart.js's
  // internals further, a MutationObserver watches the canvas for the
  // rest of its life and immediately re-applies the correct size the
  // instant anything changes it away — a MutationObserver callback runs
  // as a microtask, before the next paint, so this wins the race
  // regardless of what triggers the drift or when.
  function enforceSize(canvas, size, chart) {
    var enforcing = false;
    var observer = new MutationObserver(function () {
      if (enforcing) return; // don't react to our own corrective writes
      var dpr = window.devicePixelRatio || 1;
      var wantW = Math.round(size.w * dpr);
      var wantH = Math.round(size.h * dpr);
      if (canvas.width === wantW && canvas.height === wantH && canvas.style.width === size.w + "px") {
        return;
      }
      enforcing = true;
      // chart.resize() (not a raw canvas.width/height reassignment) —
      // both correct the size AND repaint. Assigning canvas.width/height
      // directly, even to an unchanged value, clears the canvas's whole
      // bitmap per the HTML spec, so a bare sizeCanvas() call here would
      // "fix" the size but leave the chart blank until something else
      // happened to trigger a redraw — resize() does both in one step.
      chart.resize(size.w, size.h);
      enforcing = false;
    });
    observer.observe(canvas, { attributes: true, attributeFilter: ["width", "height", "style"] });
    return observer;
  }

  function createChart(id, config) {
    var canvas = document.getElementById(id);
    if (!canvas) return null;
    if (chartsById[id]) {
      chartsById[id].destroy();
      delete chartsById[id];
    }
    if (observersById[id]) {
      observersById[id].disconnect();
      delete observersById[id];
    }
    var size = cssSize(canvas);
    if (!size) return null;
    config.options = config.options || {};
    config.options.responsive = false;
    config.options.devicePixelRatio = window.devicePixelRatio || 1;
    config.options.animation = false;
    // Sized once, before construction, and left alone — reassigning
    // canvas.width/height again right after (even to the same values)
    // clears whatever the constructor just drew, and calling resize()
    // with a size that already matches looks like a no-op to Chart.js,
    // so it skips redrawing — a real bug this exact sequence caused:
    // a correctly-sized but permanently blank chart on first page load.
    sizeCanvas(canvas, size);
    var chart = new Chart(canvas, config);
    chartsById[id] = chart;
    observersById[id] = enforceSize(canvas, size, chart);
    return chart;
  }

  // responsive:false means Chart.js no longer auto-adapts to a genuine
  // window resize on its own — re-measure and re-apply every tracked
  // chart's size by hand when that happens (debounced; a resize can
  // fire continuously while dragging).
  var resizeDebounce;
  window.addEventListener("resize", function () {
    clearTimeout(resizeDebounce);
    resizeDebounce = setTimeout(function () {
      Object.keys(chartsById).forEach(function (id) {
        var chart = chartsById[id];
        if (!chart.canvas || !chart.canvas.isConnected) return;
        var size = cssSize(chart.canvas);
        if (!size) return;
        sizeCanvas(chart.canvas, size);
        chart.resize(size.w, size.h);
      });
    }, 150);
  });

  function renderProgression() {
    var data = readJson("progression-chart-data");
    if (!data) return;

    createChart("progression-chart", {
      type: "line",
      data: {
        labels: data.rounds.map(function (r) {
          return "R" + r;
        }),
        datasets: data.series.map(function (s, i) {
          var color = PALETTE[i % PALETTE.length];
          return {
            label: s.label + (s.car_number ? " #" + s.car_number : ""),
            data: s.points,
            borderColor: color,
            backgroundColor: color,
            tension: 0.25,
            pointRadius: 3,
            borderWidth: 2,
            // Not real Chart.js dataset options — read back by
            // updateProgressionFocus() below to know which line belongs
            // to which standings row, and what color to return to once
            // it's no longer dimmed.
            participantId: s.participant_id,
            _baseColor: color,
          };
        }),
      },
      options: {
        interaction: { mode: "nearest", intersect: false },
        scales: { x: baseAxis(), y: baseAxis() },
        plugins: {
          legend: { position: "bottom", labels: { color: TEXT_DIM, boxWidth: 12 } },
        },
      },
    });
    updateProgressionFocus();
  }

  var DIM_ALPHA = 0.12;
  var FOCUS_BORDER_WIDTH = 4;
  var FOCUS_POINT_RADIUS = 5;

  // Expanding a row's own dropdown pins that row's line as "focused" on
  // the progression chart above — dimming every other line so it's easy
  // to pick out one (or several) people's line out of what's otherwise
  // an eleven-way tangle. Collapsing it un-pins that line; with nothing
  // expanded, every line goes back to its normal look.
  function updateProgressionFocus() {
    var chart = chartsById["progression-chart"];
    if (!chart) return;

    var openIds = new Set();
    document.querySelectorAll(".tower-row-toggle[data-participant-id]").forEach(function (details) {
      if (details.open) openIds.add(details.dataset.participantId);
    });
    var anyFocused = openIds.size > 0;

    chart.data.datasets.forEach(function (ds) {
      var isFocused = openIds.has(ds.participantId);
      if (!anyFocused || isFocused) {
        ds.borderColor = ds._baseColor;
        ds.backgroundColor = ds._baseColor;
        ds.borderWidth = isFocused ? FOCUS_BORDER_WIDTH : 2;
        ds.pointRadius = isFocused ? FOCUS_POINT_RADIUS : 3;
      } else {
        ds.borderColor = hexToRgba(ds._baseColor, DIM_ALPHA);
        ds.backgroundColor = hexToRgba(ds._baseColor, DIM_ALPHA);
        ds.borderWidth = 1;
        ds.pointRadius = 2;
      }
    });
    chart.update("none");
  }

  // One toggle listener per row, attached fresh every render (htmx
  // swaps replace every row's <details>, so there's never a stale one
  // left over to double-fire).
  function initProgressionFocus() {
    document.querySelectorAll(".tower-row-toggle[data-participant-id]").forEach(function (details) {
      details.addEventListener("toggle", updateProgressionFocus);
    });
  }

  function renderTeamBreakdown() {
    var teams = readJson("team-breakdown-chart-data");
    if (!teams) return;

    // One dataset per "seat" (1st/2nd/3rd member) rather than per named
    // person — a grouped bar per team, each bar showing that member's
    // own best-9 total. Not stacked: the team's actual total isn't the
    // sum of these bars (the non-top members are averaged, not added —
    // see constructor_round_points), so stacking would misleadingly
    // imply it is.
    var maxMembers = Math.max.apply(
      null,
      teams.map(function (t) {
        return t.members.length;
      })
    );
    var datasets = [];
    for (var seat = 0; seat < maxMembers; seat++) {
      datasets.push({
        label: seat === 0 ? "Top scorer" : "Other member",
        data: teams.map(function (t) {
          return t.members[seat] ? t.members[seat].total : null;
        }),
        backgroundColor: teams.map(function (t) {
          var m = t.members[seat];
          if (!m) return "transparent";
          // Each team's own real F1 livery colors (see draft.py's
          // CONSTRUCTOR_*_COLORS dicts) once it's been named, falling
          // back to the site accent for a still-unnamed team — ranked
          // by each member's own total (1st/2nd/3rd, not seat position),
          // so the team's still instantly recognizable while keeping
          // "who scored what, relative to their own teammates" visible.
          var tiers = [t.color || PALETTE[0], t.secondary_color || PALETTE[1], t.tertiary_color || PALETTE[2]];
          return tiers[m.rank] || tiers[tiers.length - 1];
        }),
      });
    }

    createChart("team-breakdown-chart", {
      type: "bar",
      data: {
        labels: teams.map(function (t) {
          return t.team;
        }),
        datasets: datasets,
      },
      options: {
        scales: { x: baseAxis(), y: baseAxis() },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var team = teams[ctx.dataIndex];
                var member = team.members[ctx.datasetIndex];
                if (!member) return "";
                var suffix = member.averaged ? " (averaged into the team total)" : " (counts in full)";
                return member.name + ": " + member.total + suffix;
              },
            },
          },
        },
      },
    });
  }

  function renderDroppedRoundChart(script) {
    var id = script.dataset.canvas;
    if (chartsById[id]) return; // already rendered for this row
    var rounds;
    try {
      rounds = JSON.parse(script.textContent);
    } catch (err) {
      console.error("standings-charts: couldn't parse dropped-round data", err);
      return;
    }
    if (!rounds.length) return;

    createChart(id, {
      type: "bar",
      data: {
        labels: rounds.map(function (r) {
          return "R" + r.round;
        }),
        datasets: [
          {
            data: rounds.map(function (r) {
              return r.points;
            }),
            backgroundColor: rounds.map(function (r) {
              return r.dropped ? DROPPED_COLOR : PALETTE[0];
            }),
          },
        ],
      },
      options: {
        scales: { x: baseAxis(), y: baseAxis() },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var r = rounds[ctx.dataIndex];
                return r.points + " pts" + (r.dropped ? " — dropped, outside best 9" : "");
              },
            },
          },
        },
      },
    });
  }

  // A driver's "best 9 of 12" chart lives inside that row's own
  // collapsed <details> dropdown — a closed <details> hides its body
  // via the UA stylesheet, same as display:none, so a chart created in
  // there at that point would measure a 0x0 container. Rather than
  // fight that (and, worse, risk a hidden chart's garbage sizing
  // contaminating Chart.js's shared cross-instance layout/animation
  // batching — the likely reason the always-visible progression chart
  // above was *also* occasionally rendering distorted on this tab),
  // each row's chart is built lazily, the first time its dropdown is
  // actually opened and therefore has a real size to measure.
  function initDroppedRoundCharts() {
    document.querySelectorAll(".dropped-round-chart-data").forEach(function (script) {
      var details = script.closest(".tower-row-toggle");
      if (!details) return;
      if (details.open) renderDroppedRoundChart(script);
      details.addEventListener("toggle", function () {
        if (details.open) renderDroppedRoundChart(script);
      });
    });
  }

  // Charts not present on the current tab (e.g. team-breakdown-chart
  // outside Constructors') need their old instance torn down too, or
  // it just leaks the same as the id-collision case above — a tab that
  // doesn't re-render a given id has to actively clean it up itself.
  function destroyOrphans() {
    Object.keys(chartsById).forEach(function (id) {
      if (!document.getElementById(id)) {
        chartsById[id].destroy();
        delete chartsById[id];
        if (observersById[id]) {
          observersById[id].disconnect();
          delete observersById[id];
        }
      }
    });
  }

  // Each chart type renders independently — one throwing shouldn't take
  // the other two down with it.
  function safely(fn) {
    try {
      fn();
    } catch (err) {
      console.error("standings-charts: " + fn.name + " failed", err);
    }
  }

  function renderAll() {
    if (typeof Chart === "undefined") return;
    destroyOrphans();
    safely(renderProgression);
    safely(renderTeamBreakdown);
    safely(initDroppedRoundCharts);
    safely(initProgressionFocus);
  }

  document.addEventListener("DOMContentLoaded", renderAll);
  document.body.addEventListener("htmx:afterSwap", renderAll);
})();
