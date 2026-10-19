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
  // Tìm khi Enter hoặc ngừng gõ 3 giây: không thấy trong Odoo thì server hỏi tiếp MISA CRM (chậm).
  var SEARCH_DELAY = 3000;

  // Một ô cho cả "đơn bán" và "mã đơn hàng": trùng số đơn bán thì server gắn luôn đơn bán (action_set_order_ref_crm).
  HQ.ORIGIN_LABEL = "Mã đơn hàng của khách (Tài liệu gốc đơn mua) — số đơn DH… / S…, gõ xong bấm Enter để tìm";
  var ORIGIN_LABEL = HQ.ORIGIN_LABEL;

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
   * onSaved: gọi sau khi lưu xong (vẽ lại phần đang mở) với kết quả server;
   * inquiryId: ghi cho cả phiếu (YCMH + đơn mua — set_order_ref) thay vì từng đơn mua.
   */
  HQ.originEditor = function (key, value, orderIds, buttonLabel, onSaved, inquiryId) {
    after[key] = onSaved;
    return '<div class="hq-origin">' +
      '<label class="hq-label" for="' + inputId(key) + '">' + ORIGIN_LABEL + "</label>" +
      '<div class="hq-origin-row">' + HQ.originInput(key, value) +
      '<button type="button" class="hq-btn hq-btn-primary" data-save-origin="' + key + '" data-order-ids="' +
      orderIds.join(",") + '"' + (inquiryId ? ' data-inquiry-id="' + inquiryId + '"' : "") + ">" +
      esc(buttonLabel) + "</button></div></div>";
  };

  /** Chỉ ô nhập + gợi ý, không nút lưu — ô ở bước lên YCMH gửi kèm create_request (origin). */
  HQ.originInput = function (key, value) {
    return '<div class="hq-picker hq-origin-picker">' +
      '<input type="text" id="' + inputId(key) + '" class="hq-input" autocomplete="off" maxlength="250" ' +
      'value="' + esc(value) + '" placeholder="VD DH125524949237215 — nhiều mã cách nhau dấu phẩy"/>' +
      '<div id="' + inputId(key) + '-results" class="hq-dropdown hq-hidden"></div></div>';
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
        // link: gợi ý theo nguồn trong Cài đặt — Odoo hoặc MISA CRM.
        ? HQ.rpc("/api/hoi-gia-ncc/sale_orders", { search: term, link: true }).then(function (r) { return r.orders; })
        : Promise.resolve([]);
    }, function (o) {
      return '<span class="hq-strong">' + esc(o.name) + "</span> " +
        '<span class="hq-muted">' + esc([o.partner, o.owner || HQ.saleName(o.sale_code), o.date,
          o.crm_id && !o.id ? HQ.CRM_ORDER_WAITING : ""].filter(Boolean).join(" · ")) + "</span>";
    }, function (order) {
      return replaceLastCode(input.value, order.name);
    }, { enter: true, delay: SEARCH_DELAY });
  };

  function save(button) {
    var key = button.dataset.saveOrigin;
    var origin = HQ.$(inputId(key)).value;
    var inquiryId = +button.dataset.inquiryId;
    button.disabled = true;
    var call = inquiryId
      ? HQ.api("set_order_ref", { inquiry_id: inquiryId, origin: origin })
      : HQ.api("po_origin", { order_ids: button.dataset.orderIds.split(",").map(Number), origin: origin });
    call.then(function (res) {
      HQ.toast(inquiryId
        ? "Đã cập nhật mã đơn hàng cho YCMH" + (res.order_ref_result.orders ? " và " + res.order_ref_result.orders + " đơn mua" : "")
        : "Đã cập nhật mã đơn hàng cho " + res.orders.length + " đơn mua");
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
