/* Util thuần cho trang /delivery_plan: vào gì ra nấy, không đụng DOM, không gọi mạng,
   không đọc state. Mọi thứ có side effect nằm ở dispatch_ui.js. */
window.HlvDispatch = window.HlvDispatch || {};

(function (HD) {
  "use strict";

  /* Nhãn hiển thị — giữ trùng khớp với selection khai trong model Python. */
  HD.LABEL = {
    SESSION: {
      morning: "Sáng", afternoon: "Chiều", flexible: "Linh hoạt", technical: "Kỹ thuật",
    },
    STOCK: {
      ready: "Đủ hàng", partial_ready: "Đủ một phần", out_of_stock: "Chưa có hàng",
      delivered: "Đã giao", unknown: "Chưa rõ",
    },
    /* state -> [nhãn, class badge] */
    REG_STATE: {
      draft: ["Nháp", ""], submitted: ["Chờ duyệt", "dp-badge-blue"],
      accepted: ["Đã nhận", "dp-badge-green"], rejected: ["Từ chối", "dp-badge-red"],
      deferred: ["Dời lại", "dp-badge-amber"], cancelled: ["Đã huỷ", ""],
    },
    PROCEDURE: {
      customs: "Cần khai hải quan trước", register: "Cần đăng ký trước",
    },
  };

  /**
   * Escape HTML. Nhận mọi kiểu; null/undefined ra chuỗi rỗng.
   * Mọi dữ liệu từ server đều phải đi qua đây trước khi nhét vào innerHTML.
   */
  HD.esc = function (value) {
    var div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  };

  /** Ngày hôm nay theo giờ máy người dùng, dạng "YYYY-MM-DD" (khớp input type=date). */
  HD.todayStr = function () {
    return HD.formatDate(new Date());
  };

  /** Date -> "YYYY-MM-DD". */
  HD.formatDate = function (date) {
    return date.getFullYear() +
      "-" + ("0" + (date.getMonth() + 1)).slice(-2) +
      "-" + ("0" + date.getDate()).slice(-2);
  };

  /**
   * Dịch chuỗi ngày "YYYY-MM-DD" đi `days` ngày. Chuỗi rỗng/sai thì tính từ hôm nay.
   * Trả về chuỗi cùng định dạng.
   */
  HD.shiftDate = function (dateStr, days) {
    var parts = (dateStr || HD.todayStr()).split("-");
    var date = new Date(+parts[0], +parts[1] - 1, +parts[2]);
    date.setDate(date.getDate() + days);
    return HD.formatDate(date);
  };

  /**
   * Datetime UTC của Odoo ("YYYY-MM-DD HH:MM:SS") -> "HH:MM DD/MM" giờ địa phương.
   * Chuỗi không parse được thì trả lại nguyên văn để không nuốt mất thông tin.
   */
  HD.fmtDateTime = function (value) {
    if (!value) return "";
    var date = new Date(value.replace(" ", "T") + "Z");
    if (isNaN(date)) return value;
    return ("0" + date.getHours()).slice(-2) + ":" + ("0" + date.getMinutes()).slice(-2) +
      " " + ("0" + date.getDate()).slice(-2) + "/" + ("0" + (date.getMonth() + 1)).slice(-2);
  };

  /** Số phút -> "45 phút" hoặc "2h15". */
  HD.fmtMinutes = function (total) {
    total = total || 0;
    if (total < 60) return total + " phút";
    return Math.floor(total / 60) + "h" + ("0" + (total % 60)).slice(-2);
  };

  /** Trả về HTML của một badge đã escape. */
  HD.badge = function (text, cls) {
    return '<span class="dp-badge ' + (cls || "") + '">' + HD.esc(text) + "</span>";
  };

  /**
   * Dựng HTML <select>.
   * `items` nhận cả [id, nhãn] lẫn {id, name}. `blankLabel` có thì thêm option rỗng.
   */
  HD.selectHtml = function (name, value, items, blankLabel) {
    var options = (blankLabel ? '<option value="">' + HD.esc(blankLabel) + "</option>" : "") +
      (items || []).map(function (item) {
        var id = String(item[0] !== undefined ? item[0] : item.id);
        var label = item[1] !== undefined ? item[1] : item.name;
        return '<option value="' + HD.esc(id) + '"' +
          (String(value) === id ? " selected" : "") + ">" + HD.esc(label) + "</option>";
      }).join("");
    return '<select data-field="' + name + '">' + options + "</select>";
  };
})(window.HlvDispatch);
