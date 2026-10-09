// Motion layer. Small on purpose: no library, only the browser's own IntersectionObserver
// and Web Animations API. Purely decorative: the store works the same without it, and
// nothing moves under reduced motion (boot.js / CSS also fall back to fully visible).
(function () {
  "use strict";
  const root = document.documentElement;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.__fxReady = true;

  // ------------------------------------------------------------ header scroll edge
  // A hairline under the glass bar only once content is underneath it. Runs even under
  // reduced motion: it is a state, not an animation.
  const header = document.querySelector("[data-header]");
  if (header) {
    let ticking = false;
    const sync = () => {
      header.toggleAttribute("data-scrolled", window.scrollY > 4);
      ticking = false;
    };
    window.addEventListener("scroll", () => {
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(sync);
      }
    }, { passive: true });
    sync();
  }

  if (reduce || !("IntersectionObserver" in window) || !Element.prototype.animate) {
    root.classList.add("fx-off");
    return;
  }

  // ------------------------------------------------------------ scroll reveals
  // One quiet move: fade up 12px as a section enters. CSS holds the hidden state.
  const io = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.setAttribute("data-shown", "");
      io.unobserve(entry.target);
    });
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });

  function reveal(scope) {
    scope.querySelectorAll("[data-reveal]:not([data-shown])").forEach((el) => io.observe(el));
  }
  reveal(document);
  document.addEventListener("htmx:afterSettle", (e) => reveal(e.target));

  // ------------------------------------------------------------ cart feedback
  // The badge is swapped out-of-band after add/update: a single brief pulse.
  let lastCount = (document.getElementById("cart-badge") || {}).textContent;
  document.addEventListener("htmx:oobAfterSwap", (e) => {
    const badge = e.detail && e.detail.target;
    if (!badge || badge.id !== "cart-badge" || badge.textContent === lastCount) return;
    lastCount = badge.textContent;
    badge.animate([{ transform: "scale(0.6)" }, { transform: "scale(1.15)" }, { transform: "scale(1)" }], { duration: 320, easing: "cubic-bezier(0.22, 1, 0.36, 1)" });
  });

  // ------------------------------------------------------------ toasts
  const box = document.getElementById("toasts");
  if (box) {
    new MutationObserver((list) => {
      list.forEach((m) => m.addedNodes.forEach((n) => {
        if (n.nodeType === 1) n.animate([{ opacity: 0, transform: "translateY(-8px) scale(0.98)" }, { opacity: 1, transform: "none" }], { duration: 260, easing: "cubic-bezier(0.22, 1, 0.36, 1)" });
      }));
    }).observe(box, { childList: true });
  }
})();
