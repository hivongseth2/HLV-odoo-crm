/* Sale ghi mã đơn hàng của khách vào Tài liệu gốc (purchase.order.origin) của đơn mua.

   Lúc hỏi giá khách chưa chắc mua nên chưa có đơn hàng; khách chốt thì sale điền ở ngăn
   phiếu (cho mọi đơn mua của phiếu) hoặc trong hộp xem một đơn mua. Gợi ý từ đơn bán (theo
   mã đang gõ sau dấu phẩy cuối); gõ tay vẫn được, nhiều mã cách nhau dấu phẩy. Server chuẩn
   hoá lại (vendor_quote_utils.normalize_origin). */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var after = {};  // key → việc làm sau khi lưu (tải lại ngăn phiếu / hộp đơn mua)

  function inputId(key) {
    return "hq-origin-" + key;
  }

  /** Mã đang gõ: phần sau dấu phẩy cuối. */
  function lastCode(text) {
    return text.split(",").pop().trim();
  }

  /** Thay mã đang gõ bằng số đơn bán vừa chọn, giữ các mã trước đó. */
  function replaceLastCode(text, name) {
    var parts = text.split(",");
    parts[parts.length - 1] = name;
    return parts.map(function (p) { return p.trim(); }).filter(Boolean).join(", ");
  }

  /**
   * HTML ô nhập mã đơn hàng. key: hậu tố id duy nhất trên trang; orderIds: các đơn sẽ ghi;
   * onSaved: gọi sau khi lưu xong (vẽ lại phần đang mở).
   */
  HQ.originEditor = function (key, value, orderIds, buttonLabel, onSaved) {
    after[key] = onSaved;
    return '<div class="hq-origin">' +
      '<label class="hq-label" for="' + inputId(key) + '">Mã đơn hàng của khách (Tài liệu gốc đơn mua)</label>' +
      '<div class="hq-origin-row"><div class="hq-picker hq-origin-picker">' +
      '<input type="text" id="' + inputId(key) + '" class="hq-input" autocomplete="off" maxlength="250" ' +
      'value="' + esc(value) + '" placeholder="VD DH125524949237215 — nhiều mã cách nhau dấu phẩy"/>' +
      '<div id="' + inputId(key) + '-results" class="hq-dropdown hq-hidden"></div></div>' +
      '<button type="button" class="hq-btn hq-btn-primary" data-save-origin="' + key + '" data-order-ids="' +
      orderIds.join(",") + '">' + esc(buttonLabel) + "</button></div>" +
      '<p class="hq-muted hq-small">Khách chốt mua thì điền mã đơn hàng để thu mua và MISA khớp đơn mua với đơn bán.</p>' +
      "</div>";
  };

  /** Gắn gợi ý đơn bán cho ô vừa vẽ (gọi sau mỗi lần vẽ lại). */
  HQ.bindOriginPicker = function (key) {
    var input = HQ.$(inputId(key));
    if (!input) {
      return;
    }
    HQ.bindPicker(inputId(key), inputId(key) + "-results", function () {
      var term = lastCode(input.value);
      return term
        ? HQ.rpc("/api/hoi-gia-ncc/sale_orders", { search: term }).then(function (r) { return r.orders; })
        : Promise.resolve([]);
    }, function (o) {
      return '<span class="hq-strong">' + esc(o.name) + "</span> " +
        '<span class="hq-muted">' + esc([o.partner, o.sale_code, o.date].filter(Boolean).join(" · ")) + "</span>";
    }, function (order) {
      return replaceLastCode(input.value, order.name);
    });
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        save(document.querySelector('[data-save-origin="' + key + '"]'));
      }
    });
  };

  function save(button) {
    var key = button.dataset.saveOrigin;
    var ids = button.dataset.orderIds.split(",").map(Number);
    button.disabled = true;
    HQ.api("po_origin", { order_ids: ids, origin: HQ.$(inputId(key)).value }).then(function (res) {
      HQ.toast("Đã cập nhật mã đơn hàng cho " + res.orders.length + " đơn mua");
      if (after[key]) {
        after[key](res);
      }
    }).catch(function (err) {
      HQ.toast(err.message);
    }).finally(function () {
      button.disabled = false;
    });
  }

  HQ.bindOriginEvents = function () {
    HQ.on(HQ.$("hq-app"), "click", "[data-save-origin]", save);
  };
})(window.HlvQuote);
