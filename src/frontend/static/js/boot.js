// Runs before first paint (blocking, tiny). Marks the page as JS-enabled so
// entrance animations can start hidden; if the motion layer never arrives,
// fx-off shows everything after a short grace period.
(function () {
  var root = document.documentElement;
  root.classList.add("js");
  setTimeout(function () {
    if (!window.__fxReady) root.classList.add("fx-off");
  }, 2500);
})();
