/* Util thuần cho trang /hoi-gia-ncc: vào gì ra nấy, không đụng DOM, không gọi mạng,
   không đọc state. Mọi thứ có side effect nằm ở sale_ui.js. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  /* trạng thái báo giá -> class badge. Mã trạng thái do services/sale_page_payload.py trả. */
  HQ.STATE_CLASS = {
    draft: "hq-badge-gray",
    sent: "hq-badge-amber",
    quoted: "hq-badge-green",
    expired: "hq-badge-red",
    done: "hq-badge-slate",
    cancel: "hq-badge-gray",
  };

  var ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

  /**
   * Escape HTML. Nhận mọi kiểu; null/undefined ra chuỗi rỗng.
   * Mọi dữ liệu từ server phải qua đây trước khi nhét vào innerHTML.
   */
  HQ.esc = function (value) {
    return (value == null ? "" : String(value)).replace(/[&<>"']/g, function (ch) {
      return ESCAPES[ch];
    });
  };

  /** Số tiền -> "1.250.000 ₫" (làm tròn đồng). null/NaN -> "—". */
  HQ.money = function (value) {
    if (value == null || isNaN(value)) {
      return "—";
    }
    return new Intl.NumberFormat("vi-VN").format(Math.round(value)) + " ₫";
  };

  /** Số lượng -> "1.250" / "2,5" (tối đa 2 chữ số lẻ). */
  HQ.qty = function (value) {
    return new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 2 }).format(value || 0);
  };

  /** "YYYY-MM-DD" + n ngày -> "YYYY-MM-DD". Chuỗi rỗng/sai -> "". */
  HQ.addDays = function (dateStr, days) {
    var parts = String(dateStr || "").split("-");
    if (parts.length !== 3) {
      return "";
    }
    var date = new Date(+parts[0], +parts[1] - 1, +parts[2] + days);
    return date.getFullYear() + "-" + ("0" + (date.getMonth() + 1)).slice(-2) +
      "-" + ("0" + date.getDate()).slice(-2);
  };

  /** "Tên A" -> "TA" để làm avatar chữ. Rỗng -> "?". */
  HQ.initials = function (name) {
    var words = String(name || "").trim().split(/\s+/).filter(Boolean);
    if (!words.length) {
      return "?";
    }
    var picked = words.length === 1 ? [words[0]] : [words[0], words[words.length - 1]];
    return picked.map(function (w) { return w.charAt(0); }).join("").toUpperCase();
  };

  /**
   * Gộp dòng mới vào danh sách dòng đang có: cùng sản phẩm và cùng dòng YCMH thì cộng
   * số lượng thay vì thêm dòng trùng. Trả mảng mới, không sửa mảng vào.
   */
  HQ.mergeLine = function (lines, line) {
    var found = false;
    var merged = lines.map(function (item) {
      if (!found && item.product_id === line.product_id &&
          (item.request_line_id || 0) === (line.request_line_id || 0)) {
        found = true;
        return Object.assign({}, item, { qty: (item.qty || 0) + (line.qty || 0) });
      }
      return item;
    });
    return found ? merged : merged.concat([Object.assign({}, line)]);
  };
})(window.HlvQuote);
