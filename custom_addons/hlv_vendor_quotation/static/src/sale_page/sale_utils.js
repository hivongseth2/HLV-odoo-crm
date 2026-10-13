/* Util thuần cho trang /hoi-gia-ncc: vào gì ra nấy, không đụng DOM, không gọi mạng,
   không đọc state. Mọi thứ có side effect nằm ở sale_ui.js. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  /* Tình trạng phiếu hỏi giá -> class nhãn (mã do services/sale_page_payload.py trả).
     Màu như /giao-hang: cam = đang chờ, màu nhấn = tới lượt sale làm, xanh lá = xong. */
  HQ.SALE_STATUS_CLASS = {
    waiting: "hq-tag-warn",
    quoted: "hq-tag-mine",
    requested: "hq-tag-ok",
    partial: "hq-tag-warn",
    closed: "hq-tag-soft",
    cancel: "hq-tag-soft",
  };

  /* Trạng thái YCMH (purchase_request) — từ chối tô đỏ để sale thấy ngay. */
  HQ.REQUEST_STATE_CLASS = {
    draft: "hq-tag-soft",
    to_approve: "hq-tag-warn",
    approved: "hq-tag-mine",
    in_progress: "hq-tag-mine",
    done: "hq-tag-ok",
    rejected: "hq-tag-danger",
  };

  /* Tiến độ đơn mua (purchase.order._hlv_vendor_progress) → màu chip ở bảng phiếu. */
  HQ.ORDER_PROGRESS_CLASS = {
    rfq: "hq-tag-soft",
    waiting: "hq-tag-warn",
    acknowledged: "hq-tag-ack",
    packed: "hq-tag-mine",
    shipped: "hq-tag-info",
    partial: "hq-tag-part",
    delivered: "hq-tag-ok",
    cancel: "hq-tag-void",
  };

  /* Chú thích màu dưới bảng phiếu: [lớp màu, nghĩa] — cùng màu với REQUEST_STATE_CLASS / ORDER_PROGRESS_CLASS. */
  HQ.REQUEST_LEGEND = [
    ["hq-tag-soft", "Nháp"],
    ["hq-tag-warn", "Chờ duyệt"],
    ["hq-tag-mine", "Đã duyệt / đang mua"],
    ["hq-tag-ok", "Hoàn thành"],
    ["hq-tag-danger", "Từ chối"],
  ];
  HQ.ORDER_LEGEND = [
    ["hq-tag-soft", "Chờ xác nhận"],
    ["hq-tag-warn", "Đơn mới"],
    ["hq-tag-ack", "Nhận thông tin"],
    ["hq-tag-mine", "Đã đóng gói"],
    ["hq-tag-info", "Đã gửi hàng"],
    ["hq-tag-part", "Giao một phần"],
    ["hq-tag-ok", "Đã giao"],
    ["hq-tag-void", "Đã hủy"],
  ];

  /**
   * Chip số chứng từ chỉ có màu (bảng phiếu — chỗ hẹp): trạng thái nằm ở màu + tooltip, không ghi chữ.
   * name: số; cls: lớp hq-tag-* (trống → xám); label: trạng thái hiện khi rê chuột ("" = không tooltip);
   * note: ghi chú đi kèm chính chứng từ này, hiện TRONG chip sau số ("" = không có) — để không bị đọc nhầm sang
   * chứng từ bên cạnh.
   */
  HQ.colorChip = function (name, cls, label, note) {
    return '<span class="hq-doc ' + (cls || "hq-tag-soft") + '"' + (label ? ' title="' + HQ.esc(label) + '"' : "") + ">" +
      HQ.esc(name) + (note ? '<span class="hq-doc-state hq-doc-note">' + HQ.esc(note) + "</span>" : "") + "</span>";
  };

  /**
   * Chip một số chứng từ (YCMH / đơn mua / báo giá / đơn bán) — mọi số chứng từ trên trang hiện bằng chip này.
   * name: số; state: chữ trạng thái kèm trong chip ("" = không có); cls: màu (lớp hq-tag-*, mặc định xám).
   */
  HQ.docChip = function (name, state, cls) {
    return '<span class="hq-doc ' + (cls || "hq-tag-soft") + '">' + HQ.esc(name) +
      (state ? '<span class="hq-doc-state">' + HQ.esc(state) + "</span>" : "") + "</span>";
  };

  /** Chip YCMH, màu theo trạng thái. r: {name, state, label}. */
  HQ.requestTag = function (r) {
    return HQ.docChip(r.name, r.label, HQ.REQUEST_STATE_CLASS[r.state]);
  };

  /** Chip đơn mua kèm tiến độ NCC báo. o: {name, vendor_status}. */
  HQ.orderTag = function (o) {
    return HQ.docChip(o.name, o.vendor_status, o.vendor_status ? "hq-tag-ok" : "");
  };

  /** Icon tin nhắn + số ở góc: unread > 0 → nền cam (NCC nhắn chưa xem), không thì số tin đã có. "" khi chưa có tin. */
  HQ.chatIcon = function (count, unread) {
    if (!unread && !count) {
      return "";
    }
    var title = unread ? unread + " tin NCC bạn chưa xem" : "Đã có " + count + " tin trao đổi với NCC";
    return '<span class="hq-chat-icon' + (unread ? " is-new" : "") + '" title="' + title + '" aria-label="' + title + '">' +
      HQ.ICON_CHAT + '<span class="hq-chat-count">' + (unread || count) + "</span></span>";
  };

  /* Trạng thái báo giá của từng NCC trong phiếu. */
  HQ.QUOTE_STATE_CLASS = {
    draft: "hq-tag-soft",
    sent: "hq-tag-warn",
    quoted: "hq-tag-ok",
    done: "hq-tag-soft",
    cancel: "hq-tag-soft",
  };

  /* Ô số đầu trang: [tình trạng phiếu, nhãn]. */
  HQ.KPIS = [
    ["waiting", "phiếu đang chờ NCC báo giá"],
    ["quoted", "phiếu NCC đã báo giá — chờ bạn chọn"],
    ["requested", "phiếu đã lên YCMH"],
    ["partial", "phiếu còn thiếu hàng — hỏi thêm NCC"],
  ];

  /* Icon tin nhắn (đen, vẽ bằng nét) cho badge số tin trao đổi. */
  HQ.ICON_CHAT = '<svg class="hq-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" ' +
    'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 21l1.9-5.4A8 8 0 1 1 21 12z"/></svg>';

  var ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

  /**
   * Escape HTML. Nhận mọi kiểu; null/undefined ra chuỗi rỗng.
   * Mọi dữ liệu từ server phải qua đây trước khi nhét vào innerHTML.
   */
  /**
   * Ô lấy hàng ở bước 1 nhận hai loại mã: "CH…" = số cơ hội trên MISA CRM, "DH…" / "S…" = số đơn bán
   * trong Odoo (không phân biệt hoa thường, bỏ khoảng trắng đầu). Trả "crm" | "order" | "" (chưa biết).
   */
  HQ.sourceKind = function (term) {
    var text = String(term || "").trim().toUpperCase();
    if (text.indexOf("CH") === 0) {
      return "crm";
    }
    return text.indexOf("DH") === 0 || text.indexOf("S") === 0 ? "order" : "";
  };

  /**
   * Chữ gõ có phải mã số thuế Việt Nam không: 10 số, mã chi nhánh 10 số-3 số, hoặc 12 số (từ 07/2025 cá
   * nhân / hộ kinh doanh dùng số CCCD làm MST); bỏ khoảng trắng và tiền tố "VN". Trả MST đã chuẩn hoá
   * ("0312345678" / "0312345678-001" / "077185006104"), không phải MST → "".
   * Cùng quy tắc với hlv_contact_refine (VIETNAM_TAX_CODE_PATTERN) — server vẫn kiểm lại.
   * hỗ trợ 12 số
   */
  HQ.taxCode = function (term) {
    var text = String(term || "").replace(/\s+/g, "").toUpperCase().replace(/^VN/, "");
    return /^(\d{10}(-\d{3})?|\d{12})$/.test(text) ? text : "";
  };

  HQ.esc = function (value) {
    return (value == null ? "" : String(value)).replace(/[&<>"']/g, function (ch) {
      return ESCAPES[ch];
    });
  };

  /* Danh bạ sale {MÃ VIẾT HOA: tên} — trang chính nạp từ config, trang tra giá từ data-sale-names. */
  HQ.saleNames = {};

  /** Tên sale của một mã (không phân biệt hoa thường). Mã chưa có trong danh bạ → chính mã; rỗng → "". */
  HQ.saleName = function (code) {
    var value = String(code == null ? "" : code).trim();
    return HQ.saleNames[value.toUpperCase()] || value;
  };

  /** "Tên (mã)" cho ô chọn mã sale — để còn nhận ra mã; chưa có tên → chỉ mã. */
  HQ.saleLabel = function (code) {
    var value = String(code == null ? "" : code).trim();
    var name = HQ.saleName(value);
    return name && name !== value ? name + " (" + value + ")" : value;
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

  /**
   * Gộp dòng mới vào danh sách dòng đang có: cùng sản phẩm và cùng dòng YCMH thì cộng
   * số lượng thay vì thêm dòng trùng. Trả mảng mới, không sửa mảng vào.
   * Dòng tách từ combo mang "combo" (tên combo): gộp thì nối tên các combo, không trùng ("A, B").
   */
  HQ.mergeLine = function (lines, line) {
    var found = false;
    var merged = lines.map(function (item) {
      if (!found && item.product_id === line.product_id &&
          (item.request_line_id || 0) === (line.request_line_id || 0)) {
        found = true;
        var combos = [item.combo, line.combo].filter(Boolean).join(", ").split(", ").filter(function (c, i, all) {
          return c && all.indexOf(c) === i;
        });
        return Object.assign({}, item, { qty: (item.qty || 0) + (line.qty || 0), combo: combos.join(", ") });
      }
      return item;
    });
    return found ? merged : merged.concat([Object.assign({}, line)]);
  };
})(window.HlvQuote);
