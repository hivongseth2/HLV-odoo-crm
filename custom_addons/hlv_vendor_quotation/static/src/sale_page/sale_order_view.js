/* Xem đơn mua sinh ra từ phiếu hỏi giá: sale biết đang mua gì, của NCC nào, đã nhận tới đâu.
   Sale chỉ sửa được mã đơn hàng của khách (Tài liệu gốc — sale_po_origin.js); còn lại là việc
   của thu mua trong backend. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;

  function fact(label, value) {
    return value ? '<div class="hq-fact"><span class="hq-label">' + esc(label) + "</span>" + esc(value) + "</div>" : "";
  }

  function render(o) {
    HQ.$("hq-po-title").textContent = "Đơn mua " + o.name;
    HQ.$("hq-po-body").innerHTML =
      '<div class="hq-facts">' +
      fact("Nhà cung cấp", o.vendor) + fact("Trạng thái", o.state) + fact("Ngày đặt", o.date) +
      fact("Ngày nhận dự kiến", o.date_planned) + fact("NCC báo", o.vendor_status) +
      "</div>" +
      (o.can_set_origin ? HQ.originEditor("po", o.origin, [o.id], "Lưu", function () {
        HQ.openOrderView(o.id, true);
        if (HQ.S.openInquiryId && !HQ.$("hq-drawer").classList.contains("hq-hidden")) {
          HQ.openInquiry(HQ.S.openInquiryId, true);
        }
      }) : fact("Mã đơn hàng", o.origin)) +
      '<div class="hq-table-wrap"><table class="hq-table"><thead><tr><th>Mặt hàng</th>' +
      '<th class="hq-num">SL</th><th class="hq-num">Đã nhận</th><th class="hq-num">Đơn giá</th>' +
      '<th class="hq-num">Thành tiền</th></tr></thead><tbody>' +
      o.lines.map(function (l) {
        return "<tr><td>" + esc(l.name) +
          (l.invoice_name ? '<div class="hq-muted">Tên xuất HĐ: ' + esc(l.invoice_name) + "</div>" : "") +
          '</td><td class="hq-num">' + HQ.qty(l.qty) + " " + esc(l.uom) +
          '</td><td class="hq-num">' + HQ.qty(l.qty_received) + '</td><td class="hq-num">' + HQ.money(l.price_unit) +
          '</td><td class="hq-num">' + HQ.money(l.subtotal) + "</td></tr>";
      }).join("") +
      '</tbody><tfoot><tr><td colspan="4" class="hq-num">Tổng chưa VAT</td><td class="hq-num">' +
      HQ.money(o.amount_untaxed) + '</td></tr><tr><td colspan="4" class="hq-num">Thuế</td><td class="hq-num">' +
      HQ.money(o.amount_tax) + '</td></tr><tr><td colspan="4" class="hq-num hq-strong">Tổng cộng</td>' +
      '<td class="hq-num hq-strong">' + HQ.money(o.amount_total) + "</td></tr></tfoot></table></div>";
    HQ.bindOriginPicker("po");
  }

  /** quiet: tải lại ngầm đơn đang mở (vừa lưu mã đơn hàng) — không nháy "Đang tải…". */
  HQ.openOrderView = function (orderId, quiet) {
    if (!quiet) {
      HQ.$("hq-po-title").textContent = "Đơn mua";
      HQ.$("hq-po-body").innerHTML = '<div class="hq-loading">Đang tải…</div>';
    }
    HQ.show("hq-po", true);
    HQ.api("purchase_order", { order_id: orderId }).then(render).catch(function (err) {
      HQ.$("hq-po-body").innerHTML = '<div class="hq-alert">' + esc(err.message) + "</div>";
    });
  };

  HQ.bindOrderViewEvents = function () {
    HQ.on(HQ.$("hq-app"), "click", "[data-po]", function (el) {
      HQ.openOrderView(+el.dataset.po);
    });
    HQ.on(HQ.$("hq-po"), "click", "[data-close-po]", function () {
      HQ.show("hq-po", false);
    });
  };
})(window.HlvQuote);
