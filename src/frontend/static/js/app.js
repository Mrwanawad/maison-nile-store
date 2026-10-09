// Small progressive-enhancement layer. Everything works without it; this adds
// toasts, the cart drawer, the variant picker and checkout conveniences.
(function () {
  "use strict";

  // ---------------------------------------------------------------- toasts
  const toastBox = () => document.getElementById("toasts");

  function toast(message, kind) {
    const box = toastBox();
    if (!box || !message) return;
    const el = document.createElement("div");
    // Toasts float on the functional layer: glass, monochrome text, an icon for the kind.
    const mark = kind === "error" ? "!" : kind === "info" ? "i" : "\u2713";
    const tone = kind === "error" ? "bg-danger text-canvas" : "bg-tint text-on-tint";
    el.className =
      "glass pointer-events-auto flex max-w-sm items-center gap-3 rounded-full py-2.5 ps-2.5 pe-5 text-[0.9375rem] font-medium text-label shadow-[var(--shadow-float)] ring-1 ring-separator transition-[opacity,transform] duration-300 ease-out";
    const icon = document.createElement("span");
    icon.className = "flex size-6 shrink-0 items-center justify-center rounded-full text-[0.8125rem] font-bold " + tone;
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = mark;
    el.appendChild(icon);
    el.setAttribute("role", kind === "error" ? "alert" : "status");
    el.appendChild(document.createTextNode(message));
    box.appendChild(el);
    setTimeout(() => {
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 250);
    }, 3200);
  }
  window.storeToast = toast;

  document.body.addEventListener("toast", (e) => toast(e.detail.message, e.detail.kind));

  // Server-side flash messages (after redirects)
  const flash = document.getElementById("flash");
  if (flash) toast((flash.content || flash).textContent.trim(), flash.dataset.kind);

  // Generic network / server errors for HTMX requests without a message
  document.body.addEventListener("htmx:sendError", () =>
    toast(document.documentElement.lang === "ar" ? "تعذّر الاتصال. حاول مرة أخرى." : "Connection problem. Please try again.", "error"),
  );
  document.body.addEventListener("htmx:responseError", (e) => {
    const xhr = e.detail.xhr;
    if (xhr && !xhr.getResponseHeader("HX-Trigger")) {
      toast(document.documentElement.lang === "ar" ? "حدث خطأ. حاول مرة أخرى." : "Something went wrong. Please try again.", "error");
    }
  });

  // ---------------------------------------------------------------- Preline
  function reinitPreline() {
    ["HSOverlay", "HSAccordion", "HSCollapse"].forEach((name) => {
      const plugin = window[name];
      if (plugin && typeof plugin.autoInit === "function") plugin.autoInit();
    });
  }
  document.addEventListener("htmx:afterSwap", reinitPreline);

  function openDrawer() {
    if (window.HSOverlay) window.HSOverlay.open("#cart-drawer");
  }
  document.body.addEventListener("cart:open", openDrawer);
  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("[data-cart-trigger]");
    if (trigger && window.HSOverlay) {
      e.preventDefault();
      openDrawer();
    }
  });

  // Size guide: open the modal right away; HTMX fills it from the size-guide page.
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-size-guide]") && window.HSOverlay && window.htmx) window.HSOverlay.open("#size-guide");
  });

  // ---------------------------------------------------------------- variant picker
  function initPicker(root) {
    const dataEl = root.querySelector("[data-picker-json]");
    if (!dataEl) return;
    const data = JSON.parse(dataEl.textContent);
    const form = root.querySelector("[data-add-form]");
    if (!form) return;
    const colors = [...form.querySelectorAll("[data-color]")];
    const sizes = [...form.querySelectorAll("[data-size]")];
    const stockEl = form.querySelector("[data-stock]");
    // The add button lives in the form and, on small screens, in the buy bar too.
    const buttons = [...document.querySelectorAll("[data-add-button]")];
    const labels = [...document.querySelectorAll("[data-add-label]")];
    const priceEl = root.querySelector("[data-price]");
    const barPrice = document.querySelector("[data-buybar-price]");
    const colorName = form.querySelector("[data-color-name]");
    const gallery = root.querySelector("[data-gallery]");
    const fmt = (p) => priceEl && priceEl.textContent.replace(/[\d,.]+/, (p / 100).toLocaleString("en-US", { maximumFractionDigits: 2 }));
    const basePrice = priceEl ? priceEl.textContent : "";
    const setButtons = (disabled, text) => {
      buttons.forEach((b) => (b.disabled = disabled));
      labels.forEach((l) => (l.textContent = text));
    };
    const setPrice = (text) => {
      if (priceEl) priceEl.textContent = text;
      if (barPrice) barPrice.textContent = text;
    };

    const selected = (list) => (list.find((i) => i.checked) || {}).value || null;

    function findVariant(color, size) {
      return data.variants.find(
        (v) => (colors.length ? v.color === color : true) && (sizes.length ? v.size === size : true),
      );
    }

    function setMessage(kind, n) {
      if (!stockEl) return;
      const map = { in: ["text-success", stockEl.dataset.msgIn], low: ["text-caution", (stockEl.dataset.msgLow || "").replace("{n}", n)], out: ["text-danger", stockEl.dataset.msgOut] };
      if (!kind) { stockEl.innerHTML = ""; return; }
      const [cls, text] = map[kind];
      stockEl.innerHTML = "";
      const span = document.createElement("span");
      span.className = cls;
      span.textContent = text;
      stockEl.appendChild(span);
    }

    function update() {
      const color = selected(colors);
      const size = selected(sizes);
      if (color) {
        const c = colors.find((i) => i.checked);
        if (colorName) colorName.textContent = c ? c.dataset.name : "";
        // Signature: the page washes into the chosen colour (CSS cross-fades --ambient).
        if (c && c.dataset.hex) root.style.setProperty("--ambient", c.dataset.hex);
      }
      // Mark sizes sold out for the chosen color
      sizes.forEach((input) => {
        const v = findVariant(color, input.value);
        const soldOut = !v || v.stock <= 0;
        input.toggleAttribute("data-soldout", colors.length ? (color ? soldOut : !data.variants.some((x) => x.size === input.value && x.stock > 0)) : soldOut);
      });
      // Gallery: show this color's photos first
      if (gallery && color) {
        const figures = [...gallery.querySelectorAll("[data-image-color]")];
        const match = figures.filter((f) => f.dataset.imageColor === color);
        if (match.length) {
          figures.forEach((f) => {
            const keep = f.dataset.imageColor === color || f.dataset.imageColor === "";
            f.classList.toggle("hidden", !keep);
          });
          figures.forEach((f) => f.classList.remove("md:col-span-2"));
          const first = figures.find((f) => !f.classList.contains("hidden"));
          if (first) first.classList.add("md:col-span-2");
        }
      }
      const ready = (!colors.length || color) && (!sizes.length || size);
      if (!ready) {
        setMessage(null);
        setPrice(basePrice);
        setButtons(false, stockEl.dataset.msgAdd);
        return;
      }
      const v = findVariant(color, size);
      if (!v || v.stock <= 0) {
        setMessage("out");
        setButtons(true, stockEl.dataset.msgSoldout);
      } else {
        setMessage(v.stock <= data.lowStock ? "low" : "in", v.stock);
        setButtons(false, stockEl.dataset.msgAdd);
      }
      if (v) setPrice(fmt(v.price));
    }

    form.addEventListener("change", update);
    // Buy bar (small screens): appears once the main button has scrolled out of view.
    const bar = document.querySelector("[data-buybar]");
    const main = root.querySelector("[data-buy-main]");
    if (bar && main && "IntersectionObserver" in window) {
      new IntersectionObserver(([entry]) => {
        const show = !entry.isIntersecting && entry.boundingClientRect.top < 0;
        bar.toggleAttribute("data-shown", show);
        bar.setAttribute("aria-hidden", show ? "false" : "true");
        bar.querySelectorAll("button").forEach((b) => (show ? b.removeAttribute("tabindex") : b.setAttribute("tabindex", "-1")));
      }).observe(main);
    }

    form.addEventListener("submit", (e) => {
      // Native "required" handles the no-selection case; just make it visible.
      if (!form.checkValidity()) {
        e.preventDefault();
        form.reportValidity();
      }
    });
    form.addEventListener("htmx:configRequest", (e) => {
      // Only guard the add-to-bag post, not requests from links inside the form (size guide).
      if (e.detail.elt === form && !form.checkValidity()) {
        e.preventDefault();
        form.reportValidity();
      }
    });
    update();
  }
  document.querySelectorAll("[data-picker]").forEach(initPicker);

  // ---------------------------------------------------------------- checkout
  const checkout = document.querySelector("[data-checkout-form]");
  if (checkout) {
    const KEY = "checkout-details-v1";
    const fields = [...checkout.querySelectorAll("[data-remember]")];
    // Restore saved details (this device only) unless the server re-rendered values
    try {
      const saved = JSON.parse(localStorage.getItem(KEY) || "{}");
      const gov = checkout.querySelector("#governorate");
      const govWasEmpty = gov && !gov.value;
      fields.forEach((f) => {
        if (!f.value && saved[f.name]) f.value = saved[f.name];
      });
      // Refresh the delivery fee for a restored governorate once HTMX has initialised.
      if (govWasEmpty && gov.value) {
        document.addEventListener("DOMContentLoaded", () => window.htmx && window.htmx.trigger(gov, "change"));
      }
    } catch (_) { /* storage unavailable */ }

    const submit = checkout.querySelector("[data-submit]");
    const submitLabel = checkout.querySelector("[data-submit-label]");
    function syncLabel() {
      const method = (checkout.querySelector("[data-payment]:checked") || {}).value;
      if (submitLabel && method) submitLabel.textContent = method === "paymob" ? submit.dataset.labelPaymob : submit.dataset.labelCod;
    }
    checkout.addEventListener("change", syncLabel);
    syncLabel();

    checkout.addEventListener("submit", () => {
      try {
        const data = {};
        fields.forEach((f) => (data[f.name] = f.value));
        localStorage.setItem(KEY, JSON.stringify(data));
      } catch (_) { /* ignore */ }
      // Prevent double orders from double clicks
      if (submit) {
        setTimeout(() => (submit.disabled = true), 0);
      }
    });
  }

  // ---------------------------------------------------------------- misc
  document.querySelectorAll("[data-back]").forEach((a) =>
    a.addEventListener("click", (e) => {
      if (history.length > 1) {
        e.preventDefault();
        history.back();
      }
    }),
  );

  // Admin: confirm destructive actions
  document.addEventListener("submit", (e) => {
    const msg = e.target.getAttribute && e.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) e.preventDefault();
  });
})();
