/* Khởi động trang /hoi-gia-ncc. Phải nạp SAU các file feature vì gọi HQ.loadVendors,
   HQ.loadQuotes, HQ.openQuote, HQ.openCreate, HQ.bindCreateEvents. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var S = HQ.S;

  function bindEvents(app) {
    HQ.on(app, "click", "[data-vendor]", function (el) {
      HQ.selectVendor(+el.dataset.vendor || null);
    });
    HQ.on(app, "click", "[data-status]", function (el) {
      S.status = el.dataset.status;
      S.page = 1;
      HQ.loadQuotes();
    });
    HQ.on(app, "click", "[data-page]", function (el) {
      S.page = +el.dataset.page;
      HQ.loadQuotes();
    });
    HQ.on(app, "click", "[data-quote]", function (el) {
      HQ.openQuote(+el.dataset.quote);
    });
    HQ.on(app, "click", "[data-action]", function (el) {
      HQ.quoteAction(el.dataset.action);
    });
    HQ.on(app, "click", "[data-copy]", function (el) {
      HQ.copy(el.dataset.copy);
    });
    HQ.on(app, "click", "[data-copy-share]", function () {
      HQ.copy(HQ.$("hq-share-text").textContent);
    });
    HQ.on(app, "click", "[data-close]", function (el) {
      HQ.show(el.dataset.close === "drawer" ? "hq-drawer" : "hq-modal", false);
    });
    HQ.on(app, "click", "#hq-new-for-vendor", function () {
      HQ.openCreate(S.vendors.find(function (v) { return v.id === S.vendorId; }));
    });

    HQ.$("hq-new").addEventListener("click", function () { HQ.openCreate(null); });
    HQ.$("hq-toggle-side").addEventListener("click", function () {
      document.body.classList.toggle("hq-side-open");
    });
    HQ.$("hq-mine").addEventListener("change", function (event) {
      S.mine = event.target.checked;
      S.page = 1;
      HQ.loadVendors();
      HQ.loadQuotes();
    });
    HQ.$("hq-vendor-search").addEventListener("input", HQ.debounce(HQ.loadVendors, 250));
    HQ.$("hq-search").addEventListener("input", HQ.debounce(function (event) {
      S.search = event.target.value.trim();
      S.page = 1;
      HQ.loadQuotes();
    }, 300));
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        HQ.show("hq-drawer", false);
      }
    });
  }

  function start() {
    var app = HQ.$("hq-app");
    if (!app || !HQ.$("hq-quote-list")) {
      return;  // chưa có quyền: trang chỉ hiện thông báo
    }
    S.vendorId = +app.dataset.initialVendor || null;
    bindEvents(app);
    HQ.bindCreateEvents();
    HQ.rpc("/api/hoi-gia-ncc/config", {}).then(function (config) {
      S.config = config;
      HQ.$("hq-user").textContent = config.user_name || "";
      return Promise.all([HQ.loadVendors(), HQ.loadQuotes()]);
    }).catch(function (err) {
      HQ.showAlert("hq-alert", err.message);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})(window.HlvQuote);
