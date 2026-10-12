/* Bảng so giá — đổi ý hỏi NCC món nào, từng ô (sale_compare.js gọi khi vẽ ô):
   - ô NCC không được hỏi món đó / đã thu hồi: gạch chéo, "+ Hỏi món này" / "+ Hỏi lại" (add_quote_lines);
   - ô đang hỏi mà chưa được chọn / chưa lên YCMH: "Thu hồi" (withdraw_quote_lines) — không xoá dòng, NCC không thấy
     món đó nữa, chatter báo giá ghi ai thu hồi. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;

  /** Báo giá NCC còn mở để hỏi thêm / thu hồi món (phiếu còn hỏi được, dòng chưa lên đơn mua đủ). */
  function canEditAsk(line, vendor, d) {
    return d.can_add_vendor && !line.locked && (vendor.state === "sent" || vendor.state === "quoted");
  }

  /** NCC không được hỏi món này (lúc lập phiếu không tick) hoặc đã thu hồi: ô gạch chéo — khác hẳn "Chờ báo giá".
      Đổi ý thì "+ Hỏi món này" / "+ Hỏi lại": thêm vào chính báo giá đã gửi NCC đó (dòng đã thu hồi được bật lại —
      vendor_quote.action_add_inquiry_lines). offer: dòng đã thu hồi (withdrawn), hoặc không có. */
  HQ.notAskedCell = function (line, vendor, d, offer) {
    var withdrawn = offer && offer.withdrawn;
    return '<td class="hq-offer hq-offer-skip"><span class="hq-muted">' + (withdrawn ? "Đã thu hồi" : "Không hỏi") +
      "</span>" + (canEditAsk(line, vendor, d)
      ? '<button type="button" class="hq-btn hq-btn-mini" data-ask-line="' + vendor.quote_id + ":" + line.id +
        '" title="Hỏi món này với ' + esc(vendor.name) + ' — NCC thấy ngay trên trang báo giá của họ">' +
        (withdrawn ? "+ Hỏi lại" : "+ Hỏi món này") + "</button>"
      : "") + "</td>";
  };

  /** Nút "Thu hồi" dưới ô: chỉ món NCC CHƯA trả lời (chưa báo giá / chưa báo hết hàng), chưa được chọn, chưa lên
      YCMH. Không xoá dòng (giữ để tra lại). */
  HQ.withdrawLink = function (line, vendor, d, offer) {
    var answered = offer.price_unit || offer.unavailable;
    if (!canEditAsk(line, vendor, d) || answered || offer.selected || (offer.request_names || []).length) {
      return "";
    }
    return '<button type="button" class="hq-link hq-withdraw" data-withdraw-line="' + vendor.quote_id + ":" + line.id +
      '" title="Thu hồi yêu cầu báo giá món này với ' + esc(vendor.name) + ' — NCC không thấy món này nữa">Thu hồi</button>';
  };

  /** Gắn thêm HTML vào cuối ô offerCell trả về (mọi nhánh của offerCell đều kết thúc bằng "</td>"). */
  HQ.appendToCell = function (cell, html) {
    return html ? cell.slice(0, -"</td>".length) + html + "</td>" : cell;
  };

  function withdrawLine(button) {
    var parts = button.dataset.withdrawLine.split(":");
    var line = HQ.addVendorDetail.lines.find(function (l) { return l.id === +parts[1]; });
    var vendor = HQ.addVendorDetail.vendors.find(function (v) { return v.quote_id === +parts[0]; });
    if (!window.confirm("Thu hồi yêu cầu báo giá \"" + (line ? line.name : "") + "\" với " + (vendor ? vendor.name : "NCC") +
        "?\nNCC sẽ không thấy món này nữa; lịch sử vẫn giữ, bấm \"Hỏi lại\" để hỏi lại.")) {
      return;
    }
    button.disabled = true;
    HQ.api("withdraw_quote_lines", { inquiry_id: HQ.addVendorDetail.id, quote_id: +parts[0], line_ids: [+parts[1]] }).then(function (detail) {
      done(detail, "Đã thu hồi — NCC không thấy món này nữa");
    }).catch(function (err) {
      button.disabled = false;
      HQ.toast(err.message);
    });
  }

  function askLine(button) {
    var parts = button.dataset.askLine.split(":");
    button.disabled = true;
    HQ.api("add_quote_lines", { inquiry_id: HQ.addVendorDetail.id, quote_id: +parts[0], line_ids: [+parts[1]] }).then(function (detail) {
      done(detail, "Đã hỏi thêm món này — NCC thấy ngay trên trang báo giá của họ");
    }).catch(function (err) {
      button.disabled = false;
      HQ.toast(err.message);
    });
  }

  function done(detail, message) {
    HQ.renderInquiry(detail);
    HQ.toast(message);
    HQ.reloadAll();
  }

  HQ.bindCompareAskEvents = function () {
    var panel = HQ.$("hq-drawer-panel");
    HQ.on(panel, "click", "[data-ask-line]", askLine);
    HQ.on(panel, "click", "[data-withdraw-line]", withdrawLine);
  };
})(window.HlvQuote);
