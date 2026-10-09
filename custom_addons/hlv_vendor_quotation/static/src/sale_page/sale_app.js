/* Khởi động trang /hoi-gia-ncc. Phải nạp SAU các file feature vì gọi HQ.loadVendors,
   HQ.loadInquiries, HQ.openInquiry, HQ.openCreate, HQ.bindCreateEvents, HQ.bindCompareEvents,
   HQ.bindChatEvents, HQ.bindOrderViewEvents, HQ.bindOriginEvents, HQ.bindVendorInfoEvents,
   HQ.bindCloseEvents, HQ.bindBellEvents, HQ.loadBell, HQ.bindAddVendorEvents, HQ.bindPriceHistoryEvents, HQ.bindPasteEvents, HQ.bindCrmEvents,
   HQ.listenBus.

   Mã sale lấy từ link riêng ?t=<token> như /misa_sale_status: mỗi sale chỉ có mã của mình
   (khai ở tài khoản); nhóm Quản lý Hỏi giá NCC thêm "Tất cả" và đổi mã tự do, nhóm Người dùng
   bị khoá ô mã. Tài khoản dùng chung nhiều mã mà vào không kèm ?t= (VD từ menu /sale_plan) thì
   hỏi "Bạn là sale nào?" một lần, máy nhớ cho lần sau. Trang chỉ chọn mã để hiển thị — server
   kiểm lại mã ở mọi API. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var S = HQ.S;
  var CODE_KEY = "hq_sale_code";
  var CHOOSE = "";  // resolveCode: tài khoản nhiều mã, chưa biết người đang xem là sale nào
  var GATED = ".hq-toolbar, .hq-kpis, #hq-app > .row";

  function tokenOf(code) {
    var match = (S.config.codes || []).find(function (c) { return c.code === code; });
    return match ? match.token : "";
  }

  /** Mã sale ban đầu: theo ?t=, rồi mã đã chọn lần trước trên máy này, rồi mặc định.
      null = không được xem; CHOOSE = phải hỏi sale chọn mã. */
  function resolveCode(config) {
    var token = new URLSearchParams(window.location.search).get("t");
    var codes = config.codes || [];
    var byToken = token && codes.find(function (c) { return c.token === token; });
    if (byToken) {
      return byToken.code;
    }
    if (token && !config.can_see_all) {
      return null;  // link của sale khác
    }
    var stored = "";
    try { stored = window.localStorage.getItem(CODE_KEY) || ""; } catch (e) { stored = ""; }
    if (stored === config.all_code && config.can_see_all) {
      return stored;
    }
    if (codes.some(function (c) { return c.code === stored; })) {
      return stored;
    }
    if (config.can_see_all) {
      return config.all_code;
    }
    if (codes.length === 1) {
      return codes[0].code;
    }
    return codes.length ? CHOOSE : null;
  }

  /** Giữ URL khớp với mã sale + NCC đang xem, để copy link là ra đúng màn hình này. */
  HQ.syncUrl = function () {
    var url = new URL(window.location.href);
    var token = S.code !== S.config.all_code ? tokenOf(S.code) : "";
    if (token) { url.searchParams.set("t", token); } else { url.searchParams.delete("t"); }
    if (S.vendorId) { url.searchParams.set("ncc", S.vendorId); } else { url.searchParams.delete("ncc"); }
    window.history.replaceState(null, "", url);
    try { window.localStorage.setItem(CODE_KEY, S.code); } catch (e) { /* trình duyệt chặn lưu */ }
    // Nút copy link mã: cho thu mua / quản lý gửi link riêng cho từng sale.
    HQ.show("hq-copy-code-link", S.config.can_see_all && !!token);
  };

  function renderCodeSelect() {
    var options = (S.config.can_see_all ? [[S.config.all_code, "Tất cả mã sale"]] : [])
      .concat((S.config.codes || []).map(function (c) { return [c.code, HQ.saleLabel(c.code)]; }));
    var select = HQ.$("hq-code");
    select.innerHTML = options.map(function (o) {
      return '<option value="' + HQ.esc(o[0]) + '"' + (o[0] === S.code ? " selected" : "") + ">" +
        HQ.esc(o[1]) + "</option>";
    }).join("");
    // Nhóm Người dùng: khoá ô mã. Tài khoản dùng chung nhiều mã đổi qua nút "Đổi mã" (hỏi lại).
    select.disabled = !S.config.can_see_all;
    select.title = select.disabled ? "Mã sale của bạn — chỉ nhóm Quản lý Hỏi giá NCC đổi được" : "";
    HQ.show("hq-switch-code", !S.config.can_see_all && (S.config.codes || []).length > 1);
  }

  /** Che trang, chỉ hiện một ô thông báo (không có quyền / chọn mã). html đã escape. */
  function showGate(html) {
    var box = HQ.$("hq-denied");
    box.innerHTML = html;
    box.classList.remove("hq-hidden");
    Array.prototype.forEach.call(document.querySelectorAll(GATED), function (el) { el.classList.add("hq-hidden"); });
  }

  function hideGate() {
    HQ.$("hq-denied").classList.add("hq-hidden");
    Array.prototype.forEach.call(document.querySelectorAll(GATED), function (el) { el.classList.remove("hq-hidden"); });
  }

  function deny(message) {
    showGate(HQ.esc(message));
  }

  function chooseCode() {
    showGate('<h2 class="hq-h2">Bạn là sale nào?</h2>' +
      '<p class="hq-muted">Tài khoản này dùng chung cho nhiều mã sale. Chọn mã của bạn — máy này sẽ nhớ cho ' +
      "lần sau. Mở link riêng của mình (có ?t=…) thì vào thẳng, khỏi chọn.</p>" +
      '<div class="hq-code-choices">' + (S.config.codes || []).map(function (c) {
        return '<button type="button" class="hq-btn" data-pick-code="' + HQ.esc(c.code) + '">' + HQ.esc(HQ.saleLabel(c.code)) + "</button>";
      }).join("") + "</div>");
  }

  function enterCode(code) {
    hideGate();
    S.code = code;
    S.page = 1;
    renderCodeSelect();
    HQ.syncUrl();
    HQ.listenBus();
    HQ.loadBell();
    return HQ.reloadAll();
  }

  function bindEvents(app) {
    HQ.on(app, "click", "[data-vendor]", function (el) {
      HQ.selectVendor(+el.dataset.vendor || null);
    });
    HQ.on(app, "click", "[data-status]", function (el) {
      // Bấm lại ô số đang chọn thì bỏ lọc.
      var again = el.classList.contains("hq-kpi") && S.status === el.dataset.status;
      S.status = again ? "all" : el.dataset.status;
      S.page = 1;
      HQ.loadInquiries();
    });
    HQ.on(app, "click", "[data-page]", function (el) {
      S.page = +el.dataset.page;
      HQ.loadInquiries();
    });
    HQ.on(app, "click", "[data-inquiry]", function (el) {
      HQ.openInquiry(+el.dataset.inquiry);
    });
    HQ.on(app, "click", "[data-copy]", function (el) {
      HQ.copy(el.dataset.copy);
    });
    HQ.on(app, "click", "[data-close]", function (el) {
      HQ.show(el.dataset.close === "drawer" ? "hq-drawer" : "hq-modal", false);
    });

    HQ.on(app, "click", "[data-pick-code]", function (el) {
      enterCode(el.dataset.pickCode);
    });
    HQ.$("hq-switch-code").addEventListener("click", chooseCode);
    HQ.$("hq-code").addEventListener("change", function (event) {
      S.code = event.target.value;
      S.page = 1;
      HQ.syncUrl();
      HQ.listenBus();
      HQ.loadBell();
      HQ.reloadAll();
    });
    HQ.$("hq-copy-code-link").addEventListener("click", function () {
      HQ.copy(window.location.origin + window.location.pathname + "?t=" + tokenOf(S.code));
    });
    HQ.$("hq-new").addEventListener("click", function () { HQ.openCreate(); });
    HQ.$("hq-vendor-search").addEventListener("input", HQ.debounce(HQ.loadVendors, 250));
    HQ.$("hq-search").addEventListener("input", HQ.debounce(function (event) {
      S.search = event.target.value.trim();
      S.page = 1;
      HQ.loadInquiries();
      HQ.loadPriceHistory(S.search);
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
    HQ.bindCompareEvents();
    HQ.bindChatEvents();
    HQ.bindOrderViewEvents();
    HQ.bindOriginEvents();
    HQ.bindVendorInfoEvents();
    HQ.bindCloseEvents();
    HQ.bindBellEvents();
    HQ.bindAddVendorEvents();
    HQ.bindPriceHistoryEvents();
    HQ.bindPasteEvents();
    HQ.bindCrmEvents();
    HQ.rpc("/api/hoi-gia-ncc/config", {}).then(function (config) {
      S.config = config;
      HQ.saleNames = config.sale_names || {};
      var code = resolveCode(config);
      if (code === null) {
        deny((config.codes || []).length
          ? "Link này thuộc mã sale khác — bạn chỉ xem được phiếu hỏi giá của mã sale của mình."
          : "Tài khoản chưa được khai mã sale MISA (Thiết lập → Người dùng → Mã sale MISA), " +
            "nên chưa xem được phiếu hỏi giá. Liên hệ quản trị để bổ sung.");
        return null;
      }
      if (code === CHOOSE) {
        chooseCode();
        return null;
      }
      return enterCode(code);
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
