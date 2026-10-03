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
    const tone =
      kind === "error"
        ? "bg-danger text-paper"
        : kind === "info"
          ? "bg-paper text-ink"
          : "bg-mango text-ink";
    el.className =
      "pointer-events-auto max-w-sm rounded-full border-2 border-ink px-5 py-3 text-sm font-semibold shadow-[4px_4px_0_0_var(--color-ink)] transition-opacity duration-200 " +
      tone;
    el.setAttribute("role", kind === "error" ? "alert" : "status");
    el.textContent = message;
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
    const button = form.querySelector("[data-add-button]");
    const label = form.querySelector("[data-add-label]");
    const priceEl = root.querySelector("[data-price]");
    const colorName = form.querySelector("[data-color-name]");
    const gallery = root.querySelector("[data-gallery]");
    const fmt = (p) => priceEl && priceEl.textContent.replace(/[\d,.]+/, (p / 100).toLocaleString("en-US", { maximumFractionDigits: 2 }));
    const basePrice = priceEl ? priceEl.textContent : "";

    const selected = (list) => (list.find((i) => i.checked) || {}).value || null;

    function findVariant(color, size) {
      return data.variants.find(
        (v) => (colors.length ? v.color === color : true) && (sizes.length ? v.size === size : true),
      );
    }

    function setMessage(kind, n) {
      if (!stockEl) return;
      const map = { in: ["text-olive", stockEl.dataset.msgIn], low: ["text-hibiscus", (stockEl.dataset.msgLow || "").replace("{n}", n)], out: ["text-danger", stockEl.dataset.msgOut] };
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
      if (colorName && color) {
        const c = colors.find((i) => i.checked);
        colorName.textContent = c ? c.dataset.name : "";
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
        if (priceEl) priceEl.textContent = basePrice;
        button.disabled = false;
        label.textContent = stockEl.dataset.msgAdd;
        return;
      }
      const v = findVariant(color, size);
      if (!v || v.stock <= 0) {
        setMessage("out");
        button.disabled = true;
        label.textContent = stockEl.dataset.msgSoldout;
      } else {
        setMessage(v.stock <= data.lowStock ? "low" : "in", v.stock);
        button.disabled = false;
        label.textContent = stockEl.dataset.msgAdd;
      }
      if (priceEl && v) priceEl.textContent = fmt(v.price);
    }

    form.addEventListener("change", update);
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
