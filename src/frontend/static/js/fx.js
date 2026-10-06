// Motion layer (Motion One, vendored as window.Motion). Purely decorative:
// the store works the same without it, and nothing runs under reduced motion.
//
//   intro curtain (first home visit per session) → hero sequence + scroll parallax
//   [data-split]        words rise out of masks when they enter the viewport
//   [data-reveal]       fade/rise ("clip" = wipe up); [data-reveal-stagger] staggers children
//   [data-scrub-words]  words light up with scroll progress
//   [data-hscroll]      desktop: pinned section, row slides sideways with scroll
//   [data-velocity-marquee]  CSS marquee sped up / reversed by scroll velocity
//   [data-magnetic]     pulls toward the pointer; [data-cursor-label] shows the "View" cursor
//   [data-footer-mark]  wordmark rises letter by letter
//   cart: fly-to-bag, badge pop, drawer cascade; toasts; ticker; header states.
(function () {
  "use strict";
  const root = document.documentElement;
  const M = window.Motion;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.__fxReady = true;

  // The announcement ticker and header state are useful even without Motion.
  ticker();
  headerState();

  if (!M || reduce) {
    root.classList.add("fx-off");
    root.classList.remove("intro-on");
    return;
  }
  const { animate, inView, stagger, scroll } = M;
  const rtl = root.dir === "rtl";
  const fine = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  const expo = [0.16, 1, 0.3, 1];
  const springy = { type: "spring", stiffness: 260, damping: 24 };
  const isLatin = (s) => /^[\u0000-ɏ\s -⁯]+$/.test(s);

  // ------------------------------------------------------------ text splitting
  // Wraps each word (or each letter, Latin only: Arabic letters must stay joined)
  // in a mask span. Elements inside (e.g. <em class="serif">) move as one word.
  function split(el, letters) {
    const parts = [];
    const wrap = (node) => {
      const outer = document.createElement("span");
      outer.className = "sw";
      const inner = document.createElement("span");
      outer.appendChild(inner);
      inner.appendChild(node);
      parts.push(inner);
      return outer;
    };
    [...el.childNodes].forEach((node) => {
      if (node.nodeType === 3) {
        const frag = document.createDocumentFragment();
        node.textContent.split(/(\s+)/).forEach((chunk) => {
          if (!chunk) return;
          if (/^\s+$/.test(chunk)) frag.appendChild(document.createTextNode(" "));
          else if (letters && isLatin(chunk)) [...chunk].forEach((ch) => frag.appendChild(wrap(document.createTextNode(ch))));
          else frag.appendChild(wrap(document.createTextNode(chunk)));
        });
        node.replaceWith(frag);
      } else if (node.nodeType === 1) {
        node.replaceWith(wrap(node.cloneNode(true)));
      }
    });
    el.setAttribute("data-split-done", "");
    return parts;
  }

  // ------------------------------------------------------------ intro curtain
  let heroDelay = 0;
  const intro = document.querySelector("[data-intro]");
  if (intro && root.classList.contains("intro-on")) {
    try { sessionStorage.setItem("introSeen", "1"); } catch (e) { /* private mode */ }
    const word = intro.querySelector("[data-intro-word]");
    const letters = split(word, true);
    animate(letters, { y: ["110%", "0%"] }, { duration: 0.8, delay: stagger(0.035), ease: expo });
    animate(intro.querySelector("[data-intro-bar]"), { scaleX: [0, 1] }, { duration: 1.0, ease: [0.65, 0, 0.35, 1] });
    animate(letters, { y: ["0%", "-110%"] }, { duration: 0.6, delay: stagger(0.02, { startDelay: 1.05 }), ease: [0.7, 0, 0.84, 0] });
    animate(intro, { clipPath: ["inset(0% 0% 0% 0%)", "inset(0% 0% 100% 0%)"] }, { duration: 0.9, delay: 1.35, ease: [0.76, 0, 0.24, 1] })
      .then(() => root.classList.remove("intro-on"));
    heroDelay = 1.55;
  } else {
    root.classList.remove("intro-on");
  }

  // ------------------------------------------------------------ hero
  const hero = document.querySelector("[data-hero]");
  if (hero) {
    const part = (name) => [...hero.querySelectorAll(`[data-hero-part="${name}"]`)];
    const lines = part("line");
    lines.forEach((el) => (el.style.opacity = "1"));
    const img = hero.querySelector("[data-hero-img]");
    if (img) animate(img, { scale: [1.18, 1], filter: ["brightness(0.6)", "brightness(1)"] }, { duration: 2.2, delay: heroDelay, ease: expo });
    animate(lines.map((el) => el.firstElementChild), { y: ["108%", "0%"] }, { duration: 1.1, delay: stagger(0.11, { startDelay: heroDelay + 0.15 }), ease: expo });
    animate(part("copy"), { opacity: [0, 1], y: [18, 0] }, { duration: 0.9, delay: stagger(0.1, { startDelay: heroDelay + 0.55 }), ease: expo });

    // Scroll: photo drifts slower than the page, type lifts and fades.
    const media = hero.querySelector("[data-hero-media]");
    const content = hero.querySelector("[data-hero-content]");
    const opts = { target: hero, offset: ["start start", "end start"] };
    if (media) scroll(animate(media, { y: ["0%", "28%"], scale: [1, 1.08] }, { ease: "linear" }), opts);
    if (content) scroll(animate(content, { y: [0, -120], opacity: [1, 0] }, { ease: "linear" }), opts);
  }

  // ------------------------------------------------------------ split headings
  function splits(scope) {
    scope.querySelectorAll("[data-split]:not([data-split-done])").forEach((el) => {
      const words = split(el, false);
      inView(el, () => {
        animate(words, { y: ["110%", "0%"] }, { duration: 1, delay: stagger(0.06), ease: expo });
      }, { amount: 0.4 });
    });
  }

  // ------------------------------------------------------------ scroll reveals
  function reveal(scope) {
    scope.querySelectorAll("[data-reveal]:not([data-revealed])").forEach((el) => {
      el.setAttribute("data-revealed", "");
      inView(el, () => {
        if (el.getAttribute("data-reveal") === "clip") {
          animate(el, { clipPath: ["inset(100% 0% 0% 0%)", "inset(0% 0% 0% 0%)"] }, { duration: 1.2, ease: expo });
          return;
        }
        const kids = el.hasAttribute("data-reveal-stagger") ? [...el.children] : null;
        if (kids) {
          el.style.opacity = "1";
          animate(kids, { opacity: [0, 1], y: [48, 0] }, { duration: 1.1, delay: stagger(0.07), ease: expo });
          kids.forEach((k) => {
            const media = k.querySelector(".card-media");
            if (media) animate(media, { clipPath: ["inset(18% 0% 0% 0%)", "inset(0% 0% 0% 0%)"] }, { duration: 1.3, ease: expo });
          });
        } else {
          animate(el, { opacity: [0, 1], y: [32, 0] }, { duration: 1, ease: expo });
        }
      }, { amount: 0.12 });
    });
  }

  splits(document);
  reveal(document);
  document.addEventListener("htmx:afterSettle", (e) => { splits(e.target); reveal(e.target); magnets(e.target); });

  // ------------------------------------------------------------ manifesto word scrub
  document.querySelectorAll("[data-scrub-words]").forEach((el) => {
    const words = split(el, false);
    words.forEach((w) => (w.style.opacity = "0.14"));
    scroll((p) => {
      const lit = p * (words.length + 4) - 2;
      words.forEach((w, i) => (w.style.opacity = String(Math.min(1, Math.max(0.14, lit - i + 0.14)))));
    }, { target: el, offset: ["start 85%", "end 50%"] });
  });

  // ------------------------------------------------------------ scroll progress
  const bar = document.querySelector("[data-progress]");
  if (bar && document.body.scrollHeight > window.innerHeight * 2) {
    scroll(animate(bar, { scaleX: [0, 1] }, { ease: "linear" }));
  }

  // ------------------------------------------------------------ pinned horizontal row
  const hs = document.querySelector("[data-hscroll]");
  if (hs) {
    const desk = window.matchMedia("(min-width: 1024px)");
    const track = hs.querySelector("[data-hscroll-track]");
    const count = hs.querySelector("[data-hscroll-count]");
    let stop = [];
    const setup = () => {
      stop.forEach((fn) => fn());
      stop = [];
      hs.style.height = "";
      track.style.transform = "";
      hs.toggleAttribute("data-hscroll-on", desk.matches);
      if (!desk.matches) return;
      const distance = Math.max(0, track.scrollWidth - track.clientWidth);
      if (!distance) { hs.removeAttribute("data-hscroll-on"); return; }
      hs.style.height = `${window.innerHeight + distance}px`;
      const opts = { target: hs, offset: ["start start", "end end"] };
      stop.push(scroll(animate(track, { x: [0, rtl ? distance : -distance] }, { ease: "linear" }), opts));
      const n = track.children.length;
      if (count) stop.push(scroll((p) => { count.textContent = String(Math.min(n, 1 + Math.floor(p * n))).padStart(2, "0"); }, opts));
    };
    setup();
    let t;
    window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(setup, 200); });
    desk.addEventListener("change", setup);
  }

  // ------------------------------------------------------------ velocity marquee
  const marquees = [...document.querySelectorAll("[data-velocity-marquee] .marquee-track")];
  if (marquees.length && marquees[0].getAnimations) {
    let lastY = window.scrollY;
    let v = 0;
    let dir = 1;
    const tick = () => {
      const y = window.scrollY;
      const dy = y - lastY;
      lastY = y;
      if (dy) dir = dy > 0 ? 1 : -1;
      v += (Math.min(Math.abs(dy), 120) / 12 - v) * 0.08;
      const rate = dir * (1 + v);
      marquees.forEach((m) => m.getAnimations().forEach((a) => (a.playbackRate = rate)));
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  // ------------------------------------------------------------ footer wordmark
  const mark = document.querySelector("[data-footer-mark]");
  if (mark) {
    mark.style.overflow = "hidden";
    const letters = split(mark, true);
    letters.forEach((l) => (l.style.transform = "translateY(100%)"));
    inView(mark, () => {
      animate(letters, { y: ["100%", "0%"] }, { duration: 1.2, delay: stagger(0.045), ease: expo });
    }, { amount: 0.5 });
  }

  // ------------------------------------------------------------ pointer niceties
  function magnets(scope) {
    if (!fine) return;
    scope.querySelectorAll("[data-magnetic]:not([data-magnet-on])").forEach((el) => {
      el.setAttribute("data-magnet-on", "");
      el.addEventListener("pointermove", (e) => {
        const r = el.getBoundingClientRect();
        const x = (e.clientX - r.left - r.width / 2) * 0.28;
        const y = (e.clientY - r.top - r.height / 2) * 0.35;
        animate(el, { x, y }, { duration: 0.35, ease: "easeOut" });
      });
      el.addEventListener("pointerleave", () => animate(el, { x: 0, y: 0 }, { type: "spring", stiffness: 300, damping: 14 }));
    });
  }
  magnets(document);

  const cursor = document.querySelector("[data-cursor]");
  if (cursor && fine) {
    root.classList.add("has-cursor");
    let tx = -100, ty = -100, cx = -100, cy = -100, s = 0.2, ts = 0.2, label = "";
    document.addEventListener("pointermove", (e) => {
      tx = e.clientX; ty = e.clientY;
      const zone = e.target.closest && e.target.closest("[data-cursor-label]");
      const next = zone ? zone.getAttribute("data-cursor-label") : "";
      if (next !== label) {
        label = next;
        if (label) cursor.textContent = label;
        cursor.toggleAttribute("data-on", !!label);
        ts = label ? 1 : 0.2;
      }
    }, { passive: true });
    document.addEventListener("pointerleave", () => { cursor.removeAttribute("data-on"); label = ""; ts = 0.2; });
    const loop = () => {
      cx += (tx - cx) * 0.18; cy += (ty - cy) * 0.18; s += (ts - s) * 0.16;
      cursor.style.transform = `translate3d(${cx}px, ${cy}px, 0) translate(-50%, -50%) scale(${s})`;
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  // ------------------------------------------------------------ cart feedback
  // Fly the product photo into the bag, then pop the badge.
  let lastCount = (document.getElementById("cart-badge") || {}).textContent;
  function popBadge(badge) {
    animate(badge, { scale: [0.3, 1.4, 1] }, { duration: 0.55, ease: "easeOut" });
    const bag = document.querySelector("[data-cart-trigger] svg");
    if (bag) animate(bag, { rotate: [0, -14, 10, -6, 0] }, { duration: 0.6 });
  }
  document.addEventListener("htmx:oobAfterSwap", (e) => {
    const badge = e.detail && e.detail.target;
    if (!badge || badge.id !== "cart-badge") return;
    if (badge.textContent === lastCount) return;
    lastCount = badge.textContent;
    setTimeout(() => popBadge(badge), flying ? 650 : 0);
  });

  let flying = false;
  document.addEventListener("htmx:beforeRequest", (e) => {
    const form = e.target && e.target.closest && e.target.closest("[data-add-form]");
    if (!form || e.detail.elt !== form) return;
    const src = [...document.querySelectorAll("[data-gallery] figure:not(.hidden) img")][0];
    const bag = document.querySelector("[data-cart-trigger]");
    if (!src || !bag) return;
    const a = src.getBoundingClientRect();
    const b = bag.getBoundingClientRect();
    if (a.bottom < 0 || a.top > window.innerHeight) return;
    const ghost = src.cloneNode();
    ghost.removeAttribute("srcset");
    ghost.src = src.currentSrc || src.src;
    Object.assign(ghost.style, {
      position: "fixed", left: `${a.left}px`, top: `${a.top}px`, width: `${a.width}px`, height: `${a.height}px`,
      objectFit: "cover", borderRadius: "4px", zIndex: 97, pointerEvents: "none", margin: 0,
    });
    ghost.setAttribute("aria-hidden", "true");
    ghost.alt = "";
    document.body.appendChild(ghost);
    flying = true;
    const dx = b.left + b.width / 2 - (a.left + a.width / 2);
    const dy = b.top + b.height / 2 - (a.top + a.height / 2);
    animate(ghost, { x: [0, dx], y: [0, dy], scale: [1, 0.06], borderRadius: ["4px", "999px"], opacity: [1, 1, 0.6] }, { duration: 0.75, ease: [0.65, 0, 0.35, 1] })
      .then(() => { ghost.remove(); flying = false; });
  });

  // Drawer contents cascade in whenever the body is replaced.
  document.addEventListener("htmx:afterSwap", (e) => {
    if (!e.target || e.target.id !== "cart-drawer-body") return;
    const items = e.target.querySelectorAll("li");
    if (items.length) animate(items, { opacity: [0, 1], x: [rtl ? -32 : 32, 0] }, { duration: 0.7, delay: stagger(0.06, { startDelay: 0.1 }), ease: expo });
  });

  // Add-to-bag button: brief squash on success.
  document.addEventListener("htmx:afterRequest", (e) => {
    const form = e.target && e.target.closest && e.target.closest("[data-add-form]");
    if (!form || !e.detail.successful) return;
    const btn = form.querySelector("[data-add-button]");
    if (btn) animate(btn, { scale: [1, 0.95, 1.02, 1] }, { duration: 0.45 });
  });

  // ------------------------------------------------------------ toasts rise in
  const box = document.getElementById("toasts");
  if (box) {
    new MutationObserver((list) => {
      list.forEach((m) => m.addedNodes.forEach((n) => {
        if (n.nodeType === 1) animate(n, { opacity: [0, 1], y: [-20, 0], scale: [0.96, 1] }, springy);
      }));
    }).observe(box, { childList: true });
  }

  // ============================================================ helpers that work without Motion
  function ticker() {
    const items = [...document.querySelectorAll("[data-ticker-item]")];
    if (items.length < 2 || reduce) return;
    let i = 0;
    const show = (el, on) => {
      el.classList.remove("translate-y-full", "-translate-y-full", "opacity-0");
      if (!on) el.classList.add("-translate-y-full", "opacity-0");
      el.toggleAttribute("aria-hidden", !on);
    };
    setInterval(() => {
      if (document.hidden) return;
      const cur = items[i];
      i = (i + 1) % items.length;
      const next = items[i];
      // Park the next item below without a transition, then roll both.
      next.style.transition = "none";
      next.classList.remove("-translate-y-full");
      next.classList.add("translate-y-full", "opacity-0");
      void next.offsetHeight;
      next.style.transition = "";
      show(cur, false);
      show(next, true);
    }, 3800);
  }

  function headerState() {
    const header = document.querySelector("[data-header]");
    if (!header) return;
    const heroEl = document.querySelector("[data-hero]");
    let last = window.scrollY;
    let ticking = false;
    const update = () => {
      const y = window.scrollY;
      const threshold = heroEl && header.hasAttribute("data-over") ? heroEl.offsetHeight - header.offsetHeight - 40 : 8;
      const hide = y > last && y > 200 && !document.querySelector(".hs-overlay.open");
      header.toggleAttribute("data-hidden", hide);
      header.toggleAttribute("data-scrolled", y > threshold);
      last = y;
      ticking = false;
    };
    window.addEventListener("scroll", () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(update);
    }, { passive: true });
    update();
  }
})();
