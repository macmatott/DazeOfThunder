// Shared by draft.js (real draft finale) and mock_draft.js (mock draft
// completion) — a self-contained canvas overlay that draws itself,
// animates, and removes itself. No shared state between callers; each
// call owns its own canvas/particles/timers.
(function () {
  var COLORS = ["#e8dc3b", "#4c9eff", "#ff4c4c", "#4cff88", "#ff8c4c", "#c04cff"];
  var GRAVITY = 0.05;
  var SHELL_COUNT = 16;

  function launchFireworks(durationMs) {
    durationMs = durationMs || 8000;

    var canvas = document.createElement("canvas");
    canvas.style.position = "fixed";
    canvas.style.top = "0";
    canvas.style.left = "0";
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.pointerEvents = "none";
    canvas.style.zIndex = "9999";
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    document.body.appendChild(canvas);
    var ctx = canvas.getContext("2d");
    if (!ctx) {
      canvas.remove();
      return;
    }

    var particles = [];

    function spawnShell() {
      var x = canvas.width * (0.15 + Math.random() * 0.7);
      var y = canvas.height * (0.2 + Math.random() * 0.35);
      var color = COLORS[Math.floor(Math.random() * COLORS.length)];
      var count = 60 + Math.floor(Math.random() * 30);
      for (var i = 0; i < count; i++) {
        var angle = (Math.PI * 2 * i) / count;
        var speed = 2 + Math.random() * 3;
        particles.push({
          x: x,
          y: y,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed,
          color: color,
          life: 1,
          decay: 0.008 + Math.random() * 0.01,
        });
      }
    }

    var spawnTimers = [];
    for (var i = 0; i < SHELL_COUNT; i++) {
      spawnTimers.push(setTimeout(spawnShell, i * ((durationMs / SHELL_COUNT) * 0.6)));
    }

    var startTime = null;
    var rafId = null;
    var cleanedUp = false;

    function cleanup() {
      if (cleanedUp) {
        return;
      }
      cleanedUp = true;
      spawnTimers.forEach(clearTimeout);
      if (rafId) {
        cancelAnimationFrame(rafId);
      }
      if (canvas.parentNode) {
        canvas.parentNode.removeChild(canvas);
      }
    }

    function frame(timestamp) {
      if (!startTime) {
        startTime = timestamp;
      }
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      particles = particles.filter(function (p) { return p.life > 0; });
      particles.forEach(function (p) {
        p.vy += GRAVITY;
        p.x += p.vx;
        p.y += p.vy;
        p.life -= p.decay;
        ctx.globalAlpha = Math.max(p.life, 0);
        ctx.fillStyle = p.color;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 2.5, 0, Math.PI * 2);
        ctx.fill();
      });
      ctx.globalAlpha = 1;

      if (timestamp - startTime < durationMs + 1500 || particles.length) {
        rafId = requestAnimationFrame(frame);
      } else {
        cleanup();
      }
    }
    rafId = requestAnimationFrame(frame);

    // Safety net in case the rAF loop's own exit condition never trips
    // (e.g. the tab was backgrounded and timestamps jumped).
    setTimeout(cleanup, durationMs + 3000);
  }

  window.launchFireworks = launchFireworks;
})();
