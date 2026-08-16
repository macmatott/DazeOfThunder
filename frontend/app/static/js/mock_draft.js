document.addEventListener("DOMContentLoaded", function () {
  var setupPanel = document.getElementById("mock-draft-setup");
  var setupFields = document.getElementById("mock-draft-setup-fields");
  var simPanel = document.getElementById("mock-draft-sim");
  if (!setupPanel || !setupFields || !simPanel) {
    return;
  }

  var LEAGUE_SIZE = 11;
  var ROUNDS = 2;
  // Captains are the back half of the draft order, floor(LEAGUE_SIZE/2)
  // of them — an odd league size leaves one teammate over once every
  // captain has picked once, so the last captain (index 4 here) picks
  // a second time instead of that person going captain-less. Mirrors
  // launch_pairing_draft/compute_pairing_status in constructor_draft.py.
  var CAPTAIN_SLOTS = [7, 8, 9, 10, 11];
  var TEAMMATES_NEEDED = LEAGUE_SIZE - CAPTAIN_SLOTS.length;
  var BOT_THINK_MS = 3000;
  var YOUR_TURN_SECONDS = 15;
  var TICK_THRESHOLD_SECONDS = 5;
  var STORAGE_KEY = "ffMockDraftStateV4";

  var allDrivers = JSON.parse(document.getElementById("mock-draft-drivers").textContent);
  var allConstructors = JSON.parse(document.getElementById("mock-draft-constructors").textContent);

  var positionSelect = document.getElementById("mock-draft-position");
  var toggleBtn = document.getElementById("mock-draft-toggle");
  var statusEl = document.getElementById("mock-draft-status");
  var poolEl = document.getElementById("mock-draft-pool");
  var teamEl = document.getElementById("mock-draft-team");
  var picksEl = document.getElementById("mock-draft-picks");
  var constructorSection = document.getElementById("mock-draft-constructor-section");
  var pairsEl = document.getElementById("mock-draft-pairs");
  var chimeEl = document.getElementById("mock-draft-chime");
  var tickEl = document.getElementById("mock-draft-tick");
  var finaleEl = document.getElementById("mock-draft-finale");

  var state = null;
  var pendingTimeout = null;
  var countdownInterval = null;

  function playChime() {
    try {
      chimeEl.currentTime = 0;
      chimeEl.play().catch(function () {});
    } catch (e) {}
  }

  function playTick() {
    try {
      tickEl.currentTime = 0;
      tickEl.play().catch(function () {});
    } catch (e) {}
  }

  function playFinale() {
    try {
      finaleEl.currentTime = 0;
      finaleEl.play().catch(function () {});
    } catch (e) {}
  }

  function stopAudio(el) {
    try {
      el.pause();
      el.currentTime = 0;
    } catch (e) {}
  }

  // Called on every pick (yours or a bot's) and on reset — a tick that's
  // mid-playback when you click shouldn't keep ringing into the next
  // turn, and the chime shouldn't overlap a new one firing right after.
  function stopAllAudio() {
    stopAudio(chimeEl);
    stopAudio(tickEl);
    stopAudio(finaleEl);
  }

  function clearPending() {
    if (pendingTimeout) {
      clearTimeout(pendingTimeout);
      pendingTimeout = null;
    }
    if (countdownInterval) {
      clearInterval(countdownInterval);
      countdownInterval = null;
    }
    stopAllAudio();
  }

  // Same snake math as compute_draft_status in app/services/draft.py,
  // precomputed in full since a mock draft's whole order is knowable up
  // front (unlike the real draft, which only ever needs "who's on the
  // clock right now").
  function buildDriverOrder() {
    var order = [];
    for (var r = 0; r < ROUNDS; r++) {
      var roundSlots = [];
      for (var s = 1; s <= LEAGUE_SIZE; s++) {
        roundSlots.push(s);
      }
      if (r % 2 === 1) {
        roundSlots.reverse();
      }
      order = order.concat(roundSlots);
    }
    return order;
  }

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }

  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (e) {
      // Private browsing / storage disabled — still works for this page
      // view, it just won't survive a refresh.
    }
  }

  function loadState() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  // ---- Row markup (mirrors _draft_board.html / _constructor_draft_board.html) ----

  function driverRowHtml(driver, actionable) {
    var logo = driver.logo_url
      ? '<img src="' + escapeHtml(driver.logo_url) + '" alt="" class="draft-pick-btn__logo">'
      : "";
    var fantasy = driver.fantasy_points_2025 != null ? Math.trunc(driver.fantasy_points_2025) : "";
    var avg = driver.avg_fantasy_points_2025 != null ? driver.avg_fantasy_points_2025.toFixed(1) : "";
    var action = actionable
      ? '<button type="button" class="draft-pick-btn__action" data-driver-id="' +
        escapeHtml(driver.id) +
        '">Draft</button>'
      : "<span></span>";
    return (
      '<div class="draft-pick-btn">' +
      '<span class="draft-pick-btn__rank">' + driver.rank + "</span>" +
      '<span class="driver-photo" style="background-image: url(\'' + escapeHtml(driver.photo_url) + "')\"></span>" +
      "<span>" +
      '<span class="draft-pick-btn__header">' + logo + "<span>" + escapeHtml(driver.full_name) + "</span></span>" +
      '<span class="tower__meta">' + escapeHtml(driver.team_name) + "</span>" +
      "</span>" +
      '<span class="draft-pick-btn__points draft-pick-btn__points--fantasy">' + fantasy + "</span>" +
      '<span class="draft-pick-btn__points">' + avg + "</span>" +
      action +
      "</div>"
    );
  }

  function pickRowHtml(pick) {
    var driver = pick.driver;
    var logo = driver.logo_url
      ? '<img src="' + escapeHtml(driver.logo_url) + '" alt="" class="draft-pick-row__logo">'
      : "";
    var whoLabel = pick.isYou ? "You" : "Pick " + pick.slot;
    return (
      '<div class="draft-pick-row' + (pick.isYou ? " draft-pick-row--you" : "") + '">' +
      '<div class="tower__pos">' + pick.pickNumber + "</div>" +
      '<div class="driver-photo" style="background-image: url(\'' + escapeHtml(driver.photo_url) + "')\"></div>" +
      "<div>" +
      '<div class="tower__name">' + escapeHtml(whoLabel) + "</div>" +
      '<div class="draft-pick-btn__header">' +
      logo +
      '<span class="tower__meta">' + escapeHtml(driver.full_name) + " — " + escapeHtml(driver.team_name) + "</span>" +
      "</div>" +
      "</div>" +
      '<div class="tower__points">R' + pick.round + "</div>" +
      "</div>"
    );
  }

  function partnerRowHtml(slot) {
    return (
      '<div class="draft-pick-btn draft-pick-btn--simple">' +
      '<span class="draft-pick-btn__header"><span>Pick ' + slot + "</span></span>" +
      '<button type="button" class="draft-pick-btn__action" data-partner-slot="' + slot + '">' +
      "Pick as Teammate</button>" +
      "</div>"
    );
  }

  function constructorRowHtml(constructor) {
    var logo = constructor.logo_url
      ? '<img src="' + escapeHtml(constructor.logo_url) + '" alt="" class="draft-pick-btn__logo draft-pick-btn__logo--lg">'
      : "";
    return (
      '<div class="draft-pick-btn draft-pick-btn--simple">' +
      '<span class="draft-pick-btn__header">' + logo + "<span>" + escapeHtml(constructor.name) + "</span></span>" +
      '<button type="button" class="draft-pick-btn__action" data-constructor-name="' +
      escapeHtml(constructor.name) +
      '">Claim Team</button>' +
      "</div>"
    );
  }

  function pairLabel(pair) {
    var slots = [pair.captainSlot].concat(pair.partnerSlots);
    return slots
      .map(function (slot) { return slot === state.yourSlot ? "You" : "Pick " + slot; })
      .join(" & ");
  }

  function pairRowHtml(pair) {
    var constructor = pair.constructorName
      ? allConstructors.find(function (c) { return c.name === pair.constructorName; })
      : null;
    var logo = constructor && constructor.logo_url
      ? '<img src="' + escapeHtml(constructor.logo_url) + '" alt="" class="draft-pick-row__logo draft-pick-row__logo--lg">'
      : "";
    return (
      '<div class="draft-pick-row draft-pick-row--no-photo">' +
      '<div class="tower__pos">' + pair.pickNumber + "</div>" +
      "<div>" +
      '<div class="tower__name">' + escapeHtml(pairLabel(pair)) + "</div>" +
      (pair.constructorName
        ? '<div class="draft-pick-btn__header">' + logo + '<span class="tower__meta">' + escapeHtml(pair.constructorName) + "</span></div>"
        : '<div class="tower__meta">No team name yet</div>') +
      "</div>" +
      '<div class="tower__points"></div>' +
      "</div>"
    );
  }

  // ---- Turn resolution ----

  function isCaptain(slot) {
    return CAPTAIN_SLOTS.indexOf(slot) !== -1;
  }

  function partnersAssigned() {
    return state.pairs.reduce(function (sum, p) { return sum + p.partnerSlots.length; }, 0);
  }

  function remainingPartnerSlots() {
    var paired = {};
    state.pairs.forEach(function (p) {
      p.partnerSlots.forEach(function (slot) { paired[slot] = true; });
    });
    var out = [];
    for (var s = 1; s <= LEAGUE_SIZE; s++) {
      if (!isCaptain(s) && !paired[s]) {
        out.push(s);
      }
    }
    return out;
  }

  function remainingConstructors() {
    var claimed = {};
    state.pairs.forEach(function (p) {
      if (p.constructorName) {
        claimed[p.constructorName] = true;
      }
    });
    return allConstructors.filter(function (c) { return !claimed[c.name]; });
  }

  // {phase, ...} describing whatever needs to happen next — 'complete'
  // once the driver draft, pairing, and naming are all done.
  function getCurrentTurn() {
    if (state.driverPicks.length < state.driverOrder.length) {
      var slot = state.driverOrder[state.driverPicks.length];
      return { phase: "driver", slot: slot, isYou: slot === state.yourSlot };
    }
    var assigned = partnersAssigned();
    if (assigned < TEAMMATES_NEEDED) {
      var numCaptains = CAPTAIN_SLOTS.length;
      var captainSlot;
      if (assigned < numCaptains) {
        captainSlot = CAPTAIN_SLOTS[assigned];
      } else {
        // Extra picks (teammates left over after everyone's picked once)
        // go back through captain order from the end, so whoever picked
        // last in round 1 also picks first for the extras.
        var extraIndex = numCaptains - 1 - ((assigned - numCaptains) % numCaptains);
        captainSlot = CAPTAIN_SLOTS[extraIndex];
      }
      return { phase: "pairing", slot: captainSlot, isYou: captainSlot === state.yourSlot };
    }
    var namedCount = state.pairs.filter(function (p) { return p.constructorName; }).length;
    if (namedCount < state.pairs.length) {
      // Naming order = pairs reversed by formation order (last pair formed
      // picks first) — mirror of get_constructors_desc_by_pick_number.
      var namingOrder = state.pairs.slice().reverse();
      var pair = namingOrder[namedCount];
      var isYou = pair.captainSlot === state.yourSlot || pair.partnerSlots.indexOf(state.yourSlot) !== -1;
      return { phase: "naming", pair: pair, isYou: isYou };
    }
    return { phase: "complete" };
  }

  // ---- Committing picks ----

  function commitDriverPick(driverId, isYou) {
    var idx = state.availableDrivers.findIndex(function (d) { return d.id === driverId; });
    if (idx === -1) {
      return;
    }
    var driver = state.availableDrivers.splice(idx, 1)[0];
    var pickNumber = state.driverPicks.length + 1;
    var round = Math.floor((pickNumber - 1) / LEAGUE_SIZE) + 1;
    var slot = state.driverOrder[pickNumber - 1];
    state.driverPicks.push({ pickNumber: pickNumber, round: round, slot: slot, driver: driver, isYou: isYou });
  }

  function commitPairingPick(captainSlot, partnerSlot) {
    // An odd LEAGUE_SIZE brings the last captain back on the clock a
    // second time (see getCurrentTurn) — that pick joins their existing
    // team instead of starting a new one.
    var existing = state.pairs.filter(function (p) { return p.captainSlot === captainSlot; })[0];
    if (existing) {
      existing.partnerSlots.push(partnerSlot);
      return;
    }
    state.pairs.push({
      pickNumber: state.pairs.length + 1,
      captainSlot: captainSlot,
      partnerSlots: [partnerSlot],
      constructorName: null,
    });
  }

  function commitNamingPick(pair, name) {
    pair.constructorName = name;
  }

  // ---- Rendering ----

  function renderStatus(turn, secondsLeft) {
    var timerHtml = "";
    if (turn.isYou && secondsLeft != null) {
      timerHtml =
        ' <span class="draft-timer' + (secondsLeft <= 10 ? " draft-timer--low" : "") + '">' +
        secondsLeft +
        "s left</span>";
    }

    if (turn.phase === "complete") {
      statusEl.innerHTML = "🏆 Mock draft complete";
      return;
    }

    var pulse = '<span class="pulse" aria-hidden="true"></span> ';

    if (turn.phase === "driver") {
      var pickNumber = state.driverPicks.length + 1;
      var round = Math.floor((pickNumber - 1) / LEAGUE_SIZE) + 1;
      var who = turn.isYou ? "Your pick" : "Pick " + turn.slot + " is drafting";
      statusEl.innerHTML = pulse + who + " — Pick " + pickNumber + ", Round " + round + timerHtml;
    } else if (turn.phase === "pairing") {
      var pn = partnersAssigned() + 1;
      var whoP = turn.isYou ? "Your pick" : "Pick " + turn.slot + " is picking";
      statusEl.innerHTML = pulse + whoP + " a teammate — Teammate " + pn + " of " + TEAMMATES_NEEDED + timerHtml;
    } else if (turn.phase === "naming") {
      var pnn = state.pairs.filter(function (p) { return p.constructorName; }).length + 1;
      var label = pairLabel(turn.pair);
      var whoN = turn.isYou ? "Your team" : label + " is naming their team";
      statusEl.innerHTML = pulse + whoN + " — Naming " + pnn + " of " + CAPTAIN_SLOTS.length + timerHtml;
    }
  }

  function renderPool(turn) {
    if (turn.phase === "driver" && turn.isYou) {
      var header =
        '<div class="draft-pool-header"><span></span><span></span><span></span>' +
        "<span>2025 FPTS</span><span>AVG FPTS</span><span></span></div>";
      poolEl.innerHTML =
        '<div class="draft-pool">' +
        header +
        state.availableDrivers.map(function (d) { return driverRowHtml(d, true); }).join("") +
        "</div>";
      poolEl.querySelectorAll(".draft-pick-btn__action").forEach(function (btn) {
        btn.addEventListener("click", function () {
          onUserDriverPick(btn.dataset.driverId);
        });
      });
    } else if (turn.phase === "pairing" && turn.isYou) {
      poolEl.innerHTML = '<div class="draft-pool">' + remainingPartnerSlots().map(partnerRowHtml).join("") + "</div>";
      poolEl.querySelectorAll(".draft-pick-btn__action").forEach(function (btn) {
        btn.addEventListener("click", function () {
          onUserPairingPick(parseInt(btn.dataset.partnerSlot, 10));
        });
      });
    } else if (turn.phase === "naming" && turn.isYou) {
      poolEl.innerHTML = '<div class="draft-pool">' + remainingConstructors().map(constructorRowHtml).join("") + "</div>";
      poolEl.querySelectorAll(".draft-pick-btn__action").forEach(function (btn) {
        btn.addEventListener("click", function () {
          onUserNamingPick(btn.dataset.constructorName);
        });
      });
    } else if (turn.phase === "complete") {
      poolEl.innerHTML = "";
    } else {
      poolEl.innerHTML = '<div class="tower__empty">Waiting on the rest of the league...</div>';
    }
  }

  function renderLists() {
    var yourPicks = state.driverPicks.filter(function (p) { return p.isYou; });
    teamEl.innerHTML = yourPicks.length
      ? yourPicks.map(pickRowHtml).join("")
      : '<div class="tower__empty">No picks yet.</div>';

    picksEl.innerHTML = state.driverPicks.length
      ? state.driverPicks.slice().reverse().map(pickRowHtml).join("")
      : '<div class="tower__empty">No picks yet.</div>';

    if (state.pairs.length) {
      constructorSection.hidden = false;
      pairsEl.innerHTML = state.pairs.slice().reverse().map(pairRowHtml).join("");
    } else {
      constructorSection.hidden = true;
    }
  }

  function render(turn, secondsLeft) {
    renderStatus(turn, secondsLeft);
    renderPool(turn);
    renderLists();
  }

  // ---- Turn engine ----

  function advance() {
    clearPending();
    saveState();

    var turn = getCurrentTurn();

    if (turn.phase === "complete") {
      render(turn, null);
      // Fire once per completed run — state.finaleShown is persisted, so
      // resuming an already-finished draft from localStorage (e.g. a
      // page refresh) doesn't replay it.
      if (!state.finaleShown) {
        state.finaleShown = true;
        saveState();
        playFinale();
        if (window.launchFireworks) {
          window.launchFireworks();
        }
      }
      return;
    }

    if (turn.isYou) {
      playChime();
      startYourCountdown(turn);
      return;
    }

    render(turn, null);
    pendingTimeout = setTimeout(function () {
      resolveBotTurn(turn);
      advance();
    }, BOT_THINK_MS);
  }

  function startYourCountdown(turn) {
    var secondsLeft = YOUR_TURN_SECONDS;
    render(turn, secondsLeft);
    countdownInterval = setInterval(function () {
      secondsLeft--;
      if (secondsLeft <= 0) {
        clearPending();
        resolveTimeoutForUser(turn);
        advance();
        return;
      }
      renderStatus(turn, secondsLeft);
      if (secondsLeft <= TICK_THRESHOLD_SECONDS) {
        playTick();
      }
    }, 1000);
  }

  function resolveBotTurn(turn) {
    if (turn.phase === "driver") {
      commitDriverPick(state.availableDrivers[0].id, false);
    } else if (turn.phase === "pairing") {
      commitPairingPick(turn.slot, remainingPartnerSlots()[0]);
    } else if (turn.phase === "naming") {
      commitNamingPick(turn.pair, remainingConstructors()[0].name);
    }
  }

  // Same fallback rule as the bot, just used when *your* clock runs out
  // — matches the real draft's auto-pick-on-timeout behavior.
  function resolveTimeoutForUser(turn) {
    if (turn.phase === "driver") {
      commitDriverPick(state.availableDrivers[0].id, true);
    } else if (turn.phase === "pairing") {
      commitPairingPick(turn.slot, remainingPartnerSlots()[0]);
    } else if (turn.phase === "naming") {
      commitNamingPick(turn.pair, remainingConstructors()[0].name);
    }
  }

  function onUserDriverPick(driverId) {
    clearPending();
    commitDriverPick(driverId, true);
    advance();
  }

  function onUserPairingPick(partnerSlot) {
    clearPending();
    var turn = getCurrentTurn();
    commitPairingPick(turn.slot, partnerSlot);
    advance();
  }

  function onUserNamingPick(name) {
    clearPending();
    var turn = getCurrentTurn();
    commitNamingPick(turn.pair, name);
    advance();
  }

  // ---- Setup / lifecycle ----

  function start() {
    var yourSlot = parseInt(positionSelect.value, 10) || 1;
    state = {
      yourSlot: yourSlot,
      driverOrder: buildDriverOrder(),
      driverPicks: [],
      availableDrivers: allDrivers.slice(),
      pairs: [],
    };
    setupFields.hidden = true;
    simPanel.hidden = false;
    toggleBtn.textContent = "Start Over";
    advance();
  }

  function reset() {
    clearPending();
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (e) {}
    state = null;
    simPanel.hidden = true;
    setupFields.hidden = false;
    toggleBtn.textContent = "Start Mock Draft";
  }

  toggleBtn.addEventListener("click", function () {
    if (state) {
      reset();
    } else {
      start();
    }
  });

  var saved = loadState();
  if (saved && saved.driverOrder && saved.availableDrivers) {
    state = saved;
    setupFields.hidden = true;
    simPanel.hidden = false;
    toggleBtn.textContent = "Start Over";
    var turn = getCurrentTurn();
    if (turn.isYou) {
      // Don't resume mid-countdown after a refresh — just let the viewer
      // see the board and act (or a bot turn) rather than silently
      // burning their 15 seconds while the page was reloading.
      render(turn, YOUR_TURN_SECONDS);
    } else {
      advance();
    }
  }
});
