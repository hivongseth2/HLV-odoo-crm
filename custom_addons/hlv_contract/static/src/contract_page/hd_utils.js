/* Util thuần cho trang /hop-dong: vào gì ra nấy, không đụng DOM, không gọi mạng, không đọc
   state. Mọi thứ có side effect nằm ở hd_ui.js. */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  /* Trạng thái hợp đồng -> class nhãn. Cam = đang chờ ký, xanh = xong, xám = huỷ. */
  HD.STATE_CLASS = {
    draft: "hd-tag-soft",
    confirmed: "hd-tag-warn",
    signed: "hd-tag-ok",
    cancel: "hd-tag-muted",
  };

  /* Nút chuyển trạng thái: [nhãn, class nút, câu hỏi xác nhận hoặc ""]. Server quyết nút nào hiện. */
  HD.ACTIONS = {
    confirm: ["Xác nhận", "hd-btn-primary", ""],
    sign: ["Đã ký", "hd-btn-ok", "Đánh dấu hợp đồng đã ký? Sau bước này chỉ Quản lý sửa được."],
    draft: ["Về nháp để sửa", "", ""],
    cancel: ["Huỷ hợp đồng", "hd-btn-danger-soft", "Huỷ hợp đồng này?"],
    delete: ["Xoá", "hd-btn-danger-soft", "Xoá hẳn hợp đồng này? Không khôi phục được."],
  };

  var ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

  /** Escape HTML; null/undefined -> "". Mọi dữ liệu từ server phải qua đây trước khi vào innerHTML. */
  HD.esc = function (value) {
    return (value == null ? "" : String(value)).replace(/[&<>"']/g, function (ch) {
      return ESCAPES[ch];
    });
  };

  /** Số tiền -> "39.476.160" (làm tròn đồng). null/NaN -> "0". */
  HD.money = function (value) {
    return new Intl.NumberFormat("vi-VN").format(Math.round(+value || 0));
  };

  /** Số lượng -> "4" / "2,5" (tối đa 3 chữ số lẻ). */
  HD.qty = function (value) {
    return new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 3 }).format(+value || 0);
  };

  /** "2026-10-11" -> "11/10/2026"; rỗng/sai -> "". */
  HD.date = function (iso) {
    var parts = String(iso || "").split("-");
    return parts.length === 3 ? parts[2] + "/" + parts[1] + "/" + parts[0] : "";
  };

  /**
   * Đọc số người dùng gõ theo kiểu Việt hoặc Excel: "4.058.000" -> 4058000, "2,5" -> 2.5,
   * "1,250,000" -> 1250000, "1.5" -> 1.5. Rỗng/không phải số -> 0.
   */
  HD.parseNumber = function (text) {
    var s = String(text == null ? "" : text).replace(/[\s₫đ]/gi, "");
    if (!s) {
      return 0;
    }
    var hasDot = s.indexOf(".") >= 0;
    var hasComma = s.indexOf(",") >= 0;
    if (hasDot && hasComma) {
      // Dấu đứng sau cùng là dấu thập phân
      s = s.lastIndexOf(",") > s.lastIndexOf(".") ? s.replace(/\./g, "").replace(",", ".") : s.replace(/,/g, "");
    } else if (hasDot && /^-?\d{1,3}(\.\d{3})+$/.test(s)) {
      s = s.replace(/\./g, "");
    } else if (hasComma) {
      s = /^-?\d{1,3}(,\d{3})+$/.test(s) ? s.replace(/,/g, "") : s.replace(",", ".");
    }
    var value = parseFloat(s);
    return isNaN(value) ? 0 : value;
  };

  /**
   * Dòng hàng dán từ Excel / Zalo: mỗi dòng "Tên<TAB>ĐVT<TAB>Số lượng<TAB>Đơn giá sau VAT" (tab
   * hoặc ";"). Thiếu cột thì để trống; dòng trống bỏ qua. Dòng chỉ có 3 cột mà cột 2 là số thì
   * hiểu là "Tên, Số lượng, Đơn giá". Trả [{product_name, uom, quantity, price_incl}].
   */
  HD.parsePastedLines = function (text) {
    return String(text || "").split(/\r?\n/).map(function (row) {
      return row.split(/\t|;/).map(function (cell) { return cell.trim(); });
    }).filter(function (cells) {
      return cells[0];
    }).map(function (cells) {
      if (cells.length === 3 && HD.parseNumber(cells[1])) {
        cells = [cells[0], "", cells[1], cells[2]];
      }
      return {
        product_name: cells[0],
        uom: cells[1] || "",
        quantity: cells[2] ? HD.parseNumber(cells[2]) : 1,
        price_incl: HD.parseNumber(cells[3]),
      };
    });
  };

  /**
   * Nhãn tiếng Việt -> tên biến: "Thời hạn bảo hành" -> "Thoi_Han_Bao_Hanh". Bỏ dấu, đ -> d,
   * chỉ giữ chữ/số; rỗng -> "Bien"; bắt đầu bằng số thì thêm "Bien_". Tên này là thứ nằm trong
   * mẫu — server lấy tên trong mẫu làm chuẩn nên không cần trùng khớp với cách đặt ở Python.
   */
  HD.variableCode = function (label) {
    var text = String(label || "").replace(/đ/g, "d").replace(/Đ/g, "D")
      .normalize("NFD").replace(/[̀-ͯ]/g, "");
    var words = text.match(/[A-Za-z0-9]+/g) || [];
    var code = words.map(function (w) { return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase(); }).join("_") || "Bien";
    return /^\d/.test(code) ? "Bien_" + code : code;
  };

  /** Chip biến trong trình soạn — không cho sửa chữ bên trong để biến không bị gõ hỏng. */
  HD.varChip = function (name) {
    return '<span class="hlv-var" contenteditable="false">{{' + HD.esc(name) + "}}</span>";
  };

  /**
   * Bảng hàng hoá dựng sẵn cho trình soạn: tiêu đề + MỘT dòng hàng (biến _1) + 3 dòng tổng.
   * Một dòng là đủ: hợp đồng nhiều mặt hàng thì dòng này tự nhân bản khi xuất.
   */
  HD.goodsTableHtml = function () {
    var cell = function (content, extra) {
      return "<td" + (extra || "") + ' style="padding:2px 5px;vertical-align:top">' + content + "</td>";
    };
    var center = '<p style="text-align:center">';
    var right = '<p style="text-align:right">';
    var head = ["STT", "Tên hàng", "ĐVT", "Số lượng", "Đơn giá (VND)", "Thành tiền (VND)"].map(function (title) {
      return cell(center + "<strong>" + title + "</strong></p>");
    }).join("");
    var line = [
      cell(center + "1</p>"),
      cell("<p>" + HD.varChip("Ten_Hang_1") + "</p>"),
      cell(center + HD.varChip("DVT_1") + "</p>"),
      cell(center + HD.varChip("So_Luong_1") + "</p>"),
      cell(right + HD.varChip("Don_Gia_1") + "</p>"),
      cell(right + HD.varChip("Thanh_Tien_1") + "</p>"),
    ].join("");
    var total = function (label, html) {
      return "<tr>" + cell(right + "<strong>" + label + "</strong></p>", ' colspan="5"') +
        cell(right + html + "</p>") + "</tr>";
    };
    var widths = [6, 38, 9, 11, 17, 19].map(function (w) {
      return '<col style="width:' + w + '%">';
    }).join("");
    return '<table class="hlv-grid" style="border-collapse:collapse;width:100%;table-layout:fixed">' +
      "<colgroup>" + widths + "</colgroup>" +
      "<tr>" + head + "</tr><tr>" + line + "</tr>" +
      total("Tổng tiền hàng", HD.varChip("Tong_Tien_Hang")) +
      total("Thuế VAT " + HD.varChip("Thue_Suat_VAT") + "%", HD.varChip("Tien_Thue_VAT")) +
      total("Tổng cộng", "<strong>" + HD.varChip("Tong_Gia_Tri_HD") + "</strong>") +
      "</table><p><br></p>";
  };

  /** Bảng trống rows x cols có viền, cột chia đều. rows/cols < 1 -> 1. */
  HD.tableHtml = function (rows, cols) {
    rows = Math.max(1, rows | 0);
    cols = Math.max(1, cols | 0);
    var tr = "<tr>" + new Array(cols + 1).join('<td style="padding:2px 5px;vertical-align:top"><p><br></p></td>') + "</tr>";
    return '<table class="hlv-grid" style="border-collapse:collapse;width:100%;table-layout:fixed">' +
      new Array(rows + 1).join(tr) + "</table><p><br></p>";
  };
})(window.HlvContract);
