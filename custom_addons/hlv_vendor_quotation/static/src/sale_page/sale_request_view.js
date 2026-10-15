/* Xem YCMH đã lên từ phiếu hỏi giá ngay trên trang (chỉ đọc): hàng gì, NCC nào, giá nào, đã ra đơn mua chưa.
   Sửa YCMH là việc của thu mua trong backend — sale đổi SL / NCC ở bảng so giá, YCMH tự cập nhật. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;

  function fact(label, value) {
    return value ? '<div class="hq-fact"><span class="hq-label">' + esc(label) + "</span>" + esc(value) + "</div>" : "";
  }

  function orderChips(orders) {
    if (!orders.length) {
      return '<span class="hq-muted">Chưa có</span>';
    }
    return orders.map(function (o) {
      return '<button type="button" class="hq-doc-btn" data-po="' + o.id + '" title="Xem đơn mua">' +
        HQ.docChip(o.name) + "</button>";
    }).join(" ");
  }

  function lineRow(l) {
    var sub = [
      l.backorder ? "Phần NCC hẹn giao" : "",
      l.note ? "Ghi chú: " + l.note : "",
    ].filter(Boolean).map(function (text) { return '<div class="hq-muted">' + esc(text) + "</div>"; }).join("");
    return '<tr' + (l.cancelled ? ' class="hq-line-cancelled" title="Dòng đã huỷ"' : "") + "><td>" + esc(l.name) + sub +
      "</td><td>" + (esc(l.vendor) || "—") +
      '</td><td class="hq-num">' + HQ.qty(l.qty) + " " + esc(l.uom) +
      '</td><td class="hq-num">' + HQ.money(l.price) + '<div class="hq-muted">chưa VAT ' + HQ.money(l.price_net) + "</div>" +
      '</td><td class="hq-num">' + HQ.money(l.price * l.qty) +
      "</td><td>" + (esc(l.date_required) || "—") +
      "</td><td>" + orderChips(l.orders) + "</td></tr>";
  }

  function render(r) {
    var live = r.lines.filter(function (l) { return !l.cancelled; });
    var total = live.reduce(function (sum, l) { return sum + l.price * l.qty; }, 0);
    HQ.$("hq-pr-title").innerHTML = "Yêu cầu mua hàng " + HQ.docChip(r.name, r.state_label, HQ.REQUEST_STATE_CLASS[r.state]);
    HQ.$("hq-pr-body").innerHTML =
      '<div class="hq-facts">' +
      fact("Người yêu cầu", r.requester) + fact("Ngày yêu cầu", r.date_start) +
      fact("Ngày muốn nhận hàng", r.date_wanted) + fact("Kho nhận hàng", r.picking_type) +
      fact("Địa điểm giao", r.delivery_address) + fact("Mã đơn hàng", r.origin) +
      "</div>" +
      '<div class="hq-table-wrap"><table class="hq-table"><thead><tr><th>Mặt hàng</th><th>NCC</th>' +
      '<th class="hq-num">SL</th><th class="hq-num">Đơn giá sau VAT</th><th class="hq-num">Thành tiền sau VAT</th>' +
      "<th>NCC giao dự kiến</th><th>Đơn mua</th></tr></thead><tbody>" +
      r.lines.map(lineRow).join("") +
      '</tbody><tfoot><tr><td colspan="4" class="hq-num hq-strong">Tổng sau VAT</td>' +
      '<td class="hq-num hq-strong">' + HQ.money(total) + '</td><td colspan="2"></td></tr></tfoot></table></div>';
  }

  HQ.openRequestView = function (requestId) {
    HQ.$("hq-pr-title").textContent = "Yêu cầu mua hàng";
    HQ.$("hq-pr-body").innerHTML = '<div class="hq-loading">Đang tải…</div>';
    HQ.show("hq-pr", true);
    HQ.api("purchase_request", { request_id: requestId }).then(render).catch(function (err) {
      HQ.$("hq-pr-body").innerHTML = '<div class="hq-alert">' + esc(err.message) + "</div>";
    });
  };

  HQ.bindRequestViewEvents = function () {
    HQ.on(HQ.$("hq-app"), "click", "[data-pr]", function (el) {
      HQ.openRequestView(+el.dataset.pr);
    });
    HQ.on(HQ.$("hq-pr"), "click", "[data-close-pr]", function () {
      HQ.show("hq-pr", false);
    });
  };
})(window.HlvQuote);
