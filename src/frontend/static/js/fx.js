// Motion layer (Motion One, vendored as window.Motion). Purely decorative:
// the store works the same without it, and nothing runs under reduced motion.
(function () {
  "use strict";
  const root = document.documentElement;
  const M = window.Motion;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.__fxReady = true;
  if (!M || reduce) {
    root.classList.add("fx-off");
    return;
  }
  const { animate, inView, stagger } = M;
  const rtl = root.dir === "rtl";
  const springy = { type: "spring", stiffness: 260, damping: 22 };

  // ------------------------------------------------------------ hero load sequence
  // One orchestrated moment: headline lines rise out of their masks, the photo
  // drops in crooked, the sticker slaps on last.
  const hero = document.querySelector("[data-hero]");
  if (hero) {
    const part = (name) => [...hero.querySelectorAll(`[data-hero-part="${name}"]`)];
    const lines = part("line");
    lines.forEach((el) => (el.style.opacity = "1"));
    animate(lines.map((el) => el.firstElementChild), { y: ["105%", "0%"] }, { duration: 0.8, delay: stagger(0.12), ease: [0.22, 1, 0.36, 1] });
    animate(part("photo"), { opacity: [0, 1], y: [60, 0], rotate: [rtl ? 9 : -9, rtl ? 3 : -3], scale: [0.92, 1] }, { ...springy, delay: 0.25 });
    animate(part("copy"), { opacity: [0, 1], y: [16, 0] }, { duration: 0.6, delay: 0.5, ease: "easeOut" });
    animate(part("sticker"), { opacity: [0, 1], scale: [0.2, 1], rotate: [-90, 0] }, { type: "spring", stiffness: 320, damping: 14, delay: 0.75 });
  }

  // ------------------------------------------------------------ scroll reveals
  function reveal(scope) {
    scope.querySelectorAll("[data-reveal]:not([data-revealed])").forEach((el) => {
      el.setAttribute("data-revealed", "");
      inView(
        el,
        () => {
          const kids = el.hasAttribute("data-reveal-stagger") ? [...el.children] : null;
          if (kids) {
            el.style.opacity = "1";
            animate(kids, { opacity: [0, 1], y: [28, 0], rotate: [rtl ? -1.5 : 1.5, 0] }, { duration: 0.55, delay: stagger(0.06), ease: [0.22, 1, 0.36, 1] });
          } else {
            animate(el, { opacity: [0, 1], y: [24, 0] }, { duration: 0.6, ease: [0.22, 1, 0.36, 1] });
          }
        },
        { amount: 0.15 },
      );
    });
  }
  reveal(document);
  document.addEventListener("htmx:afterSettle", (e) => reveal(e.target));

  // ------------------------------------------------------------ header: hide on scroll down
  const header = document.querySelector("[data-header]");
  if (header) {
    let last = window.scrollY;
    let ticking = false;
    window.addEventListener(
      "scroll",
      () => {
        if (ticking) return;
        ticking = true;
        requestAnimationFrame(() => {
          const y = window.scrollY;
          const hide = y > last && y > 160 && !document.querySelector(".hs-overlay.open");
          header.toggleAttribute("data-hidden", hide);
          header.toggleAttribute("data-scrolled", y > 8);
          last = y;
          ticking = false;
        });
      },
      { passive: true },
    );
  }

  // ------------------------------------------------------------ cart feedback
  // The badge is swapped out-of-band after add/update: pop it and nudge the bag.
  let lastCount = (document.getElementById("cart-badge") || {}).textContent;
  document.addEventListener("htmx:oobAfterSwap", (e) => {
    const badge = e.detail && e.detail.target;
    if (!badge || badge.id !== "cart-badge") return;
    if (badge.textContent === lastCount) return;
    lastCount = badge.textContent;
    animate(badge, { scale: [0.4, 1.35, 1] }, { duration: 0.5, ease: "easeOut" });
    const bag = document.querySelector("[data-cart-trigger] svg");
    if (bag) animate(bag, { rotate: [0, -14, 10, -6, 0] }, { duration: 0.6 });
  });

  // Drawer contents cascade in whenever the body is replaced.
  document.addEventListener("htmx:afterSwap", (e) => {
    if (!e.target || e.target.id !== "cart-drawer-body") return;
    const items = e.target.querySelectorAll("li");
    if (items.length) animate(items, { opacity: [0, 1], x: [rtl ? -24 : 24, 0] }, { duration: 0.4, delay: stagger(0.05), ease: "easeOut" });
  });

  // Add-to-bag button: brief squash on success.
  document.addEventListener("htmx:afterRequest", (e) => {
    const form = e.target && e.target.closest && e.target.closest("[data-add-form]");
    if (!form || !e.detail.successful) return;
    const btn = form.querySelector("[data-add-button]");
    if (btn) animate(btn, { scale: [1, 0.94, 1.03, 1] }, { duration: 0.45 });
  });

  // ------------------------------------------------------------ toasts slide in
  const box = document.getElementById("toasts");
  if (box) {
    new MutationObserver((list) => {
      list.forEach((m) => m.addedNodes.forEach((n) => {
        if (n.nodeType === 1) animate(n, { opacity: [0, 1], y: [-16, 0], scale: [0.96, 1] }, springy);
      }));
    }).observe(box, { childList: true });
  }
})();
