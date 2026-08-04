document.addEventListener("DOMContentLoaded", function () {
  var nextRace = document.getElementById("next-race");
  if (nextRace) {
    nextRace.scrollIntoView({ block: "center" });
  }

  // Session detail popouts: each row's info button opens its own
  // server-rendered <dialog>.
  document.querySelectorAll(".race-info-btn").forEach(function (button) {
    button.addEventListener("click", function () {
      var dialog = document.getElementById(button.dataset.modalTarget);
      if (dialog) {
        dialog.showModal();
      }
    });
  });

  document.querySelectorAll(".session-modal").forEach(function (dialog) {
    dialog.querySelectorAll("[data-modal-close]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        dialog.close();
      });
    });

    // Click on the backdrop (the dialog element itself, outside its
    // content box) closes it.
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) {
        dialog.close();
      }
    });
  });
});
