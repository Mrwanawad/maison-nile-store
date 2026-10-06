// Runs before first paint (blocking, tiny). Marks the page as JS-enabled so
// entrance animations can start hidden, and decides whether the home page plays
// its intro curtain (first visit of the session only). If the motion layer never
// arrives, fx-off shows everything after a short grace period.
(function () {
  var root = document.documentElement;
  root.classList.add("js");
  try {
    var home = /^\/(ar\/?)?$/.test(location.pathname);
    var calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (home && !calm && !sessionStorage.getItem("introSeen")) root.classList.add("intro-on");
  } catch (e) { /* storage blocked: skip the intro */ }
  setTimeout(function () {
    if (!window.__fxReady) {
      root.classList.add("fx-off");
      root.classList.remove("intro-on");
    }
  }, 2500);
})();
