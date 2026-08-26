document.addEventListener("DOMContentLoaded", function () {
  var board = document.getElementById("draft-board");
  if (!board) {
    return;
  }

  // The board polls every 2s, which would otherwise force-close an open
  // native <select>/<input> popup mid-choice (moving a form control's
  // DOM position — even back to an equivalent spot via hx-preserve —
  // closes any dropdown/picker it has open, e.g. a <select> mid-choice
  // or a datetime-local's calendar). Skip a poll tick while any form
  // control inside #draft-board is focused. Defined before the
  // chime/tick lookup below so it's active even pre-launch, when
  // neither audio tag exists yet — draft.js now always loads on this
  // page for exactly that reason.
  window.draftBoardShouldPoll = function () {
    var active = document.activeElement;
    if (!active || !board.contains(active)) {
      return true;
    }
    return active.tagName !== "SELECT" && active.tagName !== "INPUT";
  };

  // Desktop and mobile browsers alike only allow an <audio>/<video>
  // .play() call to succeed when it happens synchronously within a real
  // user gesture (a click/tap) — or, afterward, anywhere on a page the
  // browser has already seen that gesture on. A poll picking up someone
  // ELSE's pick (or your own turn starting, which fires from a poll
  // just the same) has no such gesture behind it, so without this,
  // celebration/chime audio would only ever play right as you click
  // something yourself — matches the reported "I can hear my own picks
  // but not others'" bug, and the broader "nothing plays until I've
  // clicked something" version of it. Fix: the first click ANYWHERE on
  // the page (not just inside the board — someone could be sitting on
  // their own turn's chime before ever clicking a Draft button)
  // play-and-immediately-pauses every <audio> tag once, which "unlocks"
  // it for the rest of the page's life so later programmatic .play()
  // calls (triggered by polls) go through normally. Re-checked on every
  // click since new <audio> tags keep appearing as the draft progresses
  // (driver picks, then constructor pairing, then naming) — defined
  // before the chime lookup below so it's active even pre-launch.
  document.addEventListener("click", function () {
    document.querySelectorAll("audio").forEach(function (el) {
      if (el.dataset.unlocked) {
        return;
      }
      el.dataset.unlocked = "true";
      var playPromise = el.play();
      if (playPromise && playPromise.then) {
        playPromise
          .then(function () {
            el.pause();
            el.currentTime = 0;
          })
          .catch(function (err) {
            delete el.dataset.unlocked;
            console.warn("Audio unlock failed for #" + el.id + ":", err && err.name);
          });
      }
    });
  });

  var chime = document.getElementById("draft-turn-chime");
  var tick = document.getElementById("draft-tick-sound");
  if (!chime) {
    return;
  }

  var TICK_THRESHOLD_SECONDS = 8;
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
    "Andrea Kimi Antonelli": "draft-antonelli-sound",
    "George Russell": "draft-russell-sound",
    "Liam Lawson": "draft-lawson-sound",
    "Isack Hadjar": "draft-hadjar-sound",
    "Carlos Sainz": "draft-sainz-sound",
    "Valtteri Bottas": "draft-bottas-sound",
    "Oliver Bearman": "draft-bearman-sound",
    "Franco Colapinto": "draft-colapinto-sound",
    "Arvid Lindblad": "draft-lindblad-sound",
    "Pierre Gasly": "draft-gasly-sound",
    "Esteban Ocon": "draft-ocon-sound",
    "Gabriel Bortoleto": "draft-bortoleto-sound",
    "Alexander Albon": "draft-albon-sound",
  };
  // Same idea as EASTER_EGG_SOUNDS, but for the Constructor Draft's
  // naming phase — keyed by constructor name instead of driver name.
  // Seven teams share one generic "team claimed" clip (no dedicated
  // recording for those yet).
  var CONSTRUCTOR_EASTER_EGG_SOUNDS = {
    "Ferrari": "draft-ferrari-sound",
    "McLaren": "draft-mclaren-sound",
    "Mercedes": "draft-mercedes-sound",
    "Red Bull Racing": "draft-red-bull-sound",
    "Alpine F1 Team": "draft-constructor-generic-sound",
    "Aston Martin": "draft-constructor-generic-sound",
    "Audi": "draft-constructor-generic-sound",
    "Cadillac F1 Team": "draft-constructor-generic-sound",
    "Haas F1 Team": "draft-constructor-generic-sound",
    "Racing Bulls": "draft-constructor-generic-sound",
    "Williams": "draft-constructor-generic-sound",
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
  var lastAnnouncedNamingPickNumber = null;
  var lastAnnouncedPairingMarker = null;
  var lastAnnouncedFinaleMarker = null;

  // Broadcast sounds (as opposed to the unlock trick above) fail
  // silently by design when the browser blocks them — logging why here
  // means a report of "I can't hear X" turns into a concrete browser
  // console error instead of a guessing game.
  function playWithDiagnostics(el) {
    el.currentTime = 0;
    el.play().catch(function (err) {
      console.warn("Playback blocked for #" + el.id + ":", err && err.name);
    });
  }

  board.addEventListener("htmx:afterSwap", function () {
    var marker = document.getElementById("draft-turn-marker");
    if (!marker) {
      return;
    }
    var isOnTheClock = marker.dataset.onTheClock === "true";
    var pickNumber = marker.dataset.pickNumber;

    if (isOnTheClock && pickNumber && pickNumber !== lastChimedPickNumber) {
      playWithDiagnostics(chime);
      lastChimedPickNumber = pickNumber;
    }

    if (tick && isOnTheClock && pickNumber) {
      var secondsRemaining = parseInt(marker.dataset.secondsRemaining, 10);
      var alreadyTickedThisPick = pickNumber === lastTickedPickNumber;
      if (!isNaN(secondsRemaining) && secondsRemaining <= TICK_THRESHOLD_SECONDS && !alreadyTickedThisPick) {
        playWithDiagnostics(tick);
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
        playWithDiagnostics(easterEggSound);
      }
      lastAnnouncedPickNumber = lastPickNumber;
    }

    // Same broadcast idea for the Constructor Draft's naming phase.
    var lastNamedPickNumber = marker.dataset.lastNamedPickNumber;
    var namingSoundId = CONSTRUCTOR_EASTER_EGG_SOUNDS[marker.dataset.lastNamedTeam];
    if (namingSoundId && lastNamedPickNumber && lastNamedPickNumber !== lastAnnouncedNamingPickNumber) {
      var namingEasterEggSound = document.getElementById(namingSoundId);
      if (namingEasterEggSound) {
        playWithDiagnostics(namingEasterEggSound);
      }
      lastAnnouncedNamingPickNumber = lastNamedPickNumber;
    }

    // Every teammate pairing (not just special ones) gets a broadcast
    // celebration, randomly picked from a fixed set of clips — the
    // server picks the clip (deterministically, keyed by the pair's own
    // id) so every viewer plays the same one; this just reads which
    // index it chose.
    var pairingMarker = marker.dataset.pairingCelebrationMarker;
    var pairingClipIndex = marker.dataset.pairingCelebrationClipIndex;
    if (pairingClipIndex && pairingMarker && pairingMarker !== lastAnnouncedPairingMarker) {
      var pairingSound = document.getElementById("draft-pairing-clip-" + pairingClipIndex);
      if (pairingSound) {
        playWithDiagnostics(pairingSound);
      }
      lastAnnouncedPairingMarker = pairingMarker;
    }

    // Plays once, for everyone watching live, the moment the entire
    // draft (both phases) finishes — server bounds this to a short
    // window after completion so it doesn't replay for someone loading
    // the already-finished results page later.
    var finaleMarker = marker.dataset.draftFinaleMarker;
    if (finaleMarker && finaleMarker !== lastAnnouncedFinaleMarker) {
      var finaleSound = document.getElementById("draft-finale-sound");
      if (finaleSound) {
        playWithDiagnostics(finaleSound);
      }
      if (window.launchFireworks) {
        window.launchFireworks();
      }
      lastAnnouncedFinaleMarker = finaleMarker;
    }

    // The intro video sits behind hx-preserve, so this element is the
    // same DOM node across every 2s poll while the intro is playing —
    // only seek/play it the first time it shows up (dataset.synced),
    // otherwise re-seeking would yank playback back every poll. Volume
    // comes from the shared "Sound effects" slider (audio_volume.js
    // re-applies to this element too on every swap, including live
    // drags of the slider), so there's no separate intro-specific
    // volume control to keep in sync here — just try to play at
    // whatever level that slider's already set.
    if (marker.dataset.inIntro === "true") {
      var introVideo = document.getElementById("draft-intro-video");
      if (introVideo && !introVideo.dataset.synced) {
        var elapsed = parseFloat(marker.dataset.introElapsedSeconds);
        if (!isNaN(elapsed) && elapsed > 0) {
          introVideo.currentTime = elapsed;
        }
        introVideo.dataset.synced = "true";
        introVideo.play().catch(function () {
          // Autoplay-with-sound blocked by the browser (no prior
          // interaction on this page yet) — fall back to a muted
          // autoplay so the video still plays; the audio-unlock click
          // listener above (or moving the shared volume slider, a real
          // gesture) un-mutes it for real once either happens.
          introVideo.muted = true;
          introVideo.play().catch(function () {});
        });
      }
    }
  });
});
