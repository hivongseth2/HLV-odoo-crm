/* State dùng chung + những thứ có side effect: DOM, gọi API, clipboard.
   Tách khỏi sale_utils.js để phần util giữ được tính thuần. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  HQ.S = {
    config: {},
    vendors: [],
    vendorId: null,     // id res.partner (công ty NCC) đang lọc; null = tất cả
    vendorsLimited: false,
    status: "all",
    search: "",
    mine: true,
    page: 1,
    counts: {},
    pager: {},
    openQuoteId: null,

    create: {
      request: null,    // YCMH đã chọn (nếu có)
      lines: [],        // [{product_id, product, name, qty, uom_id, uom, request_line_id}]
      chosen: [],       // [{id, name}] NCC sẽ gửi
      suggestions: [],
      quotedVendorIds: [],
    },
  };

  HQ.$ = function (id) { return document.getElementById(id); };

  HQ.show = function (id, on) {
    HQ.$(id).classList.toggle("hq-hidden", !on);
  };

  /**
   * Gọi endpoint JSON-RPC của Odoo. Trả Promise của `result`; lỗi phía server (UserError,
   * AccessError) ném thành Error có message đọc được.
   */
  HQ.rpc = function (url, params) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: params || {} }),
    }).then(function (response) {
      return response.json();
    }).then(function (payload) {
      if (payload.error) {
        var data = payload.error.data || {};
        throw new Error(data.message || payload.error.message || "Lỗi máy chủ");
      }
      return payload.result || {};
    });
  };

  HQ.showAlert = function (id, message) {
    var box = HQ.$(id);
    box.textContent = message || "";
    box.classList.toggle("hq-hidden", !message);
  };

  var toastTimer = null;
  HQ.toast = function (message) {
    var box = HQ.$("hq-toast");
    box.textContent = message;
    box.classList.remove("hq-hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { box.classList.add("hq-hidden"); }, 2500);
  };

  /** Copy chữ vào clipboard; trình duyệt chặn Clipboard API (http) thì dùng textarea tạm. */
  HQ.copy = function (text) {
    var done = function () { HQ.toast("Đã copy"); };
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(done);
    }
    var area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    done();
    return Promise.resolve();
  };

  HQ.debounce = function (fn, ms) {
    var timer = null;
    return function () {
      var args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(null, args); }, ms);
    };
  };

  /** Uỷ quyền sự kiện: handler(el, event) chạy khi `event` xảy ra trên phần tử khớp selector. */
  HQ.on = function (root, eventName, selector, handler) {
    root.addEventListener(eventName, function (event) {
      var el = event.target.closest(selector);
      if (el && root.contains(el)) {
        handler(el, event);
      }
    });
  };

  /** Nối ô tìm + danh sách thả xuống: gõ → gọi fetchItems(term) → vẽ bằng renderItem. */
  HQ.bindPicker = function (inputId, listId, fetchItems, renderItem, onPick) {
    var input = HQ.$(inputId);
    var list = HQ.$(listId);
    var items = [];
    var run = HQ.debounce(function () {
      var term = input.value.trim();
      if (!term) {
        list.classList.add("hq-hidden");
        return;
      }
      fetchItems(term).then(function (result) {
        items = result;
        list.innerHTML = items.length
          ? items.map(function (item, index) {
            return '<button type="button" class="hq-dropdown-item" data-index="' + index + '">' +
              renderItem(item) + "</button>";
          }).join("")
          : '<div class="hq-dropdown-empty">Không tìm thấy</div>';
        list.classList.remove("hq-hidden");
      }).catch(function (err) { HQ.toast(err.message); });
    }, 250);
    input.addEventListener("input", run);
    input.addEventListener("blur", function () {
      setTimeout(function () { list.classList.add("hq-hidden"); }, 150);
    });
    HQ.on(list, "mousedown", ".hq-dropdown-item", function (el, event) {
      event.preventDefault();
      onPick(items[+el.dataset.index]);
      input.value = "";
      list.classList.add("hq-hidden");
    });
  };
})(window.HlvQuote);
