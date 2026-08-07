document.addEventListener("DOMContentLoaded", function () {
  var board = document.getElementById("draft-board");
  if (!board) {
    return;
  }

  // The board polls every 2s, which would otherwise force-close an open
  // native <select> popup mid-choice (moving a form control's DOM
  // position — even back to an equivalent spot via hx-preserve — closes
  // any dropdown it has open). Skip a poll tick while one's focused,
  // covering both the driver-order and captain-order launch forms since
  // both live inside #draft-board. Defined before the chime/tick lookup
  // below so it's active even pre-launch, when neither audio tag exists
  // yet — draft.js now always loads on this page for exactly that reason.
  window.draftBoardShouldPoll = function () {
    var active = document.activeElement;
    return !(active && active.tagName === "SELECT" && board.contains(active));
  };

  var chime = document.getElementById("draft-turn-chime");
  var tick = document.getElementById("draft-tick-sound");
  if (!chime) {
    return;
  }

  var TICK_THRESHOLD_SECONDS = 8;
  var DEFAULT_INTRO_VOLUME = 0.3;
  var EASTER_EGG_SOUNDS = {
    "Max Verstappen": "draft-verstappen-sound",
    "Charles Leclerc": "draft-leclerc-sound",
    "Fernando Alonso": "draft-alonso-sound",
    "Lewis Hamilton": "draft-hamilton-sound",
    "Nico Hülkenberg": "draft-hulkenberg-sound",
    "Lando Norris": "draft-norris-sound",
    "Sergio Pérez": "draft-perez-sound",
    "Oscar Piastri": "draft-piastri-sound",
    "Lance Stroll": "draft-stroll-sound",
  };

  // Every poll swaps in a fresh #draft-turn-marker regardless of whether
  // anything changed, so track which pick we last chimed/ticked for.
  // Keying off the pick number (not just an on-the-clock boolean) matters
  // when the same person is on the clock in back-to-back turns — e.g. a
  // single-participant test league picks every round, so "on the clock"
  // never toggles off in between and a boolean flip would miss it.
  var lastChimedPickNumber = null;
  var lastTickedPickNumber = null;
  var lastAnnouncedPickNumber = null;

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

    // Broadcast to everyone watching, not just whoever's on the clock —
    // driven purely by "what was the most recent pick", so it fires the
    // same way for every viewer's own poll regardless of who made it.
    var lastPickNumber = marker.dataset.lastPickNumber;
    var soundId = EASTER_EGG_SOUNDS[marker.dataset.lastPickDriver];
    if (soundId && lastPickNumber && lastPickNumber !== lastAnnouncedPickNumber) {
      var easterEggSound = document.getElementById(soundId);
      if (easterEggSound) {
        easterEggSound.currentTime = 0;
        easterEggSound.play().catch(function () {});
      }
      lastAnnouncedPickNumber = lastPickNumber;
    }

    // The intro video sits behind hx-preserve, so this element is the
    // same DOM node across every 2s poll while the intro is playing —
    // only seek/play it the first time it shows up (dataset.synced),
    // otherwise re-seeking would yank playback back every poll.
    if (marker.dataset.inIntro === "true") {
      var introVideo = document.getElementById("draft-intro-video");
      if (introVideo && !introVideo.dataset.synced) {
        var elapsed = parseFloat(marker.dataset.introElapsedSeconds);
        if (!isNaN(elapsed) && elapsed > 0) {
          introVideo.currentTime = elapsed;
        }
        introVideo.volume = DEFAULT_INTRO_VOLUME;
        introVideo.muted = false;
        introVideo.dataset.synced = "true";
        introVideo.play().catch(function () {
          // Autoplay-with-sound blocked by the browser (no prior
          // interaction on this page) — fall back to a muted autoplay so
          // the video still plays; the mute-toggle button lets someone
          // opt in with a real click.
          introVideo.muted = true;
          var toggle = document.getElementById("draft-intro-mute-toggle");
          if (toggle) {
            setMuteToggleState(toggle, true);
          }
          var slider = document.getElementById("draft-intro-volume");
          if (slider) {
            slider.value = 0;
          }
          introVideo.play().catch(function () {});
        });
      }
    }
  });

  function setMuteToggleState(toggle, muted) {
    toggle.dataset.muted = muted ? "true" : "false";
    toggle.setAttribute("aria-label", muted ? "Unmute" : "Mute");
  }

  board.addEventListener("click", function (e) {
    // Clicks on the icon land on the <svg>/<path>, not the button itself.
    var toggle = e.target.closest && e.target.closest("#draft-intro-mute-toggle");
    if (!toggle) {
      return;
    }
    var introVideo = document.getElementById("draft-intro-video");
    if (!introVideo) {
      return;
    }
    introVideo.muted = !introVideo.muted;
    if (!introVideo.muted && introVideo.volume === 0) {
      introVideo.volume = DEFAULT_INTRO_VOLUME;
    }
    setMuteToggleState(toggle, introVideo.muted);
    var slider = document.getElementById("draft-intro-volume");
    if (slider) {
      slider.value = introVideo.muted ? 0 : Math.round(introVideo.volume * 100);
    }
    introVideo.play().catch(function () {});
  });

  board.addEventListener("input", function (e) {
    if (e.target && e.target.id === "draft-intro-volume") {
      var introVideo = document.getElementById("draft-intro-video");
      if (!introVideo) {
        return;
      }
      var vol = parseInt(e.target.value, 10) / 100;
      introVideo.volume = vol;
      introVideo.muted = vol === 0;
      var toggle = document.getElementById("draft-intro-mute-toggle");
      if (toggle) {
        setMuteToggleState(toggle, introVideo.muted);
      }
    }
  });
});
