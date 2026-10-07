/* Khởi động trang /hoi-gia-ncc. Phải nạp SAU các file feature vì gọi HQ.loadVendors,
   HQ.loadInquiries, HQ.openInquiry, HQ.openCreate, HQ.bindCreateEvents, HQ.bindCompareEvents,
   HQ.bindChatEvents, HQ.bindOrderViewEvents.

   Mã sale lấy từ link riêng ?t=<token> như /misa_sale_status: mỗi sale chỉ có mã của mình
   (khai ở tài khoản), thu mua / quản lý thêm "Tất cả". Trang chỉ chọn mã để hiển thị — server
   kiểm lại mã ở mọi API. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var S = HQ.S;
  var CODE_KEY = "hq_sale_code";

  function tokenOf(code) {
    var match = (S.config.codes || []).find(function (c) { return c.code === code; });
    return match ? match.token : "";
  }

  /** Mã sale ban đầu: theo ?t=, rồi mã đã chọn lần trước, rồi mặc định. null = không được xem. */
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
    return codes.length ? codes[0].code : null;
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
      .concat((S.config.codes || []).map(function (c) { return [c.code, c.code]; }));
    HQ.$("hq-code").innerHTML = options.map(function (o) {
      return '<option value="' + HQ.esc(o[0]) + '"' + (o[0] === S.code ? " selected" : "") + ">" +
        HQ.esc(o[1]) + "</option>";
    }).join("");
  }

  function deny(message) {
    var box = HQ.$("hq-denied");
    box.textContent = message;
    box.classList.remove("hq-hidden");
    Array.prototype.forEach.call(document.querySelectorAll(".hq-toolbar, .hq-kpis, #hq-app > .row"), function (el) {
      el.classList.add("hq-hidden");
    });
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

    HQ.$("hq-code").addEventListener("change", function (event) {
      S.code = event.target.value;
      S.page = 1;
      HQ.syncUrl();
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
    HQ.rpc("/api/hoi-gia-ncc/config", {}).then(function (config) {
      S.config = config;
      var code = resolveCode(config);
      if (code === null) {
        deny((config.codes || []).length
          ? "Link này thuộc mã sale khác — bạn chỉ xem được phiếu hỏi giá của mã sale của mình."
          : "Tài khoản chưa được khai mã sale MISA (Thiết lập → Người dùng → Mã sale MISA), " +
            "nên chưa xem được phiếu hỏi giá. Liên hệ quản trị để bổ sung.");
        return null;
      }
      S.code = code;
      renderCodeSelect();
      HQ.syncUrl();
      return HQ.reloadAll();
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
