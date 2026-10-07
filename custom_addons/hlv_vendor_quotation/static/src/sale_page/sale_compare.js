/* Ngăn chi tiết một phiếu hỏi giá: bảng so giá sản phẩm × NCC, sale bấm chọn giá, rồi lên
   yêu cầu mua hàng (đơn bán tuỳ chọn). Sau khi lên YCMH: hiện YCMH và đơn mua sinh ra. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var S = HQ.S;
  var esc = HQ.esc;
  var D = { detail: null, saleOrder: null };  // phiếu đang mở + đơn bán sẽ gắn khi lên YCMH

  /** quiet: tải lại ngầm phiếu đang mở (có tin mới) — không nháy "Đang tải…". */
  HQ.openInquiry = function (inquiryId, quiet) {
    S.openInquiryId = inquiryId;
    HQ.show("hq-drawer", true);
    if (!quiet) {
      HQ.$("hq-drawer-panel").innerHTML = '<div class="hq-loading">Đang tải…</div>';
    }
    return HQ.api("inquiry", { inquiry_id: inquiryId }).then(function (detail) {
      D.saleOrder = detail.sale_order_id ? { id: detail.sale_order_id, name: detail.sale_order } : null;
      render(detail);
    }).catch(function (err) {
      HQ.$("hq-drawer-panel").innerHTML = '<div class="hq-alert">' + esc(err.message) + "</div>";
    });
  };

  function afterChange(detail, message) {
    render(detail);
    if (message) {
      HQ.toast(message);
    }
    HQ.reloadAll();
  }

  function choose(lineId, on) {
    HQ.api("choose", { quote_line_id: lineId, choose: on }).then(function (detail) {
      afterChange(detail);
    }).catch(function (err) { HQ.toast(err.message); });
  }

  function createRequest() {
    var d = D.detail;
    var missing = d.line_count - d.chosen_count;
    if (!d.requests.length && missing &&
        !window.confirm(missing + " sản phẩm chưa chọn NCC sẽ không lên yêu cầu mua hàng. Tiếp tục?")) {
      return;
    }
    HQ.api("create_request", {
      inquiry_id: d.id,
      sale_order_id: D.saleOrder ? D.saleOrder.id : null,
    }).then(function (detail) {
      var r = detail.request_result;
      afterChange(detail, (r.merged ? "Đã gộp vào yêu cầu mua hàng " : "Đã tạo yêu cầu mua hàng ") + r.name);
    }).catch(function (err) { HQ.toast(err.message); });
  }

  function cancelInquiry() {
    if (!window.confirm("Huỷ phiếu hỏi giá này? Các NCC sẽ không báo giá được nữa.")) {
      return;
    }
    HQ.api("cancel", { inquiry_id: D.detail.id }).then(function (detail) {
      afterChange(detail, "Đã huỷ phiếu");
    }).catch(function (err) { HQ.toast(err.message); });
  }

  /* ---------------- vẽ ---------------- */

  function render(d) {
    D.detail = d;
    HQ.$("hq-drawer-panel").innerHTML =
      '<div class="hq-drawer-head"><div><div class="hq-muted">Phiếu hỏi giá' +
      (d.sale_code ? " · " + esc(d.sale_code) : "") + "</div>" +
      '<h2 class="hq-h2">' + esc(d.name) + ' <span class="hq-tag ' + (HQ.SALE_STATUS_CLASS[d.sale_status] || "") +
      '">' + esc(d.sale_status_label) + "</span></h2></div>" +
      '<button type="button" class="btn-close" data-close="drawer" aria-label="Đóng"></button></div>' +
      renderFacts(d) +
      renderCompare(d) +
      renderRequestBox(d) +
      renderOrders(d) +
      renderVendors(d) +
      (d.note ? '<div class="hq-note"><span class="hq-label">Lời nhắn gửi NCC</span>' + esc(d.note) + "</div>" : "") +
      (d.can_cancel ? '<div class="hq-drawer-actions"><button type="button" class="hq-btn hq-btn-danger" ' +
        'data-cancel-inquiry="1">Huỷ phiếu</button></div>' : "");
    bindSaleOrderPicker();
    HQ.bindOriginPicker("inquiry");
  }

  function fact(label, value) {
    return value ? '<div class="hq-fact"><span class="hq-label">' + esc(label) + "</span>" + value + "</div>" : "";
  }

  function renderFacts(d) {
    var orders = d.purchase_orders.map(function (o) {
      return esc(o.name) + (o.vendor_status ? ' <span class="hq-muted">(' + esc(o.vendor_status) + ")</span>" : "");
    }).join("<br/>");
    return '<div class="hq-facts">' +
      fact("Mã sale", esc(d.sale_code)) +
      fact("Đơn bán", esc(d.sale_order)) +
      fact("Hạn báo giá", esc(d.deadline)) +
      fact("Yêu cầu mua hàng", d.requests.map(function (r) {
        return esc(r.name) + ' <span class="hq-muted">(' + esc(r.state) + ")</span>";
      }).join("<br/>")) +
      fact("Đơn mua", orders) +
      fact("Người tạo", esc(d.user_name)) +
      "</div>";
  }

  /** Bảng sản phẩm (dòng) × NCC (cột). Ô có giá bấm được để chọn khi phiếu còn mở. */
  function renderCompare(d) {
    if (!d.vendors.length) {
      return "";
    }
    var head = '<tr><th>Sản phẩm</th><th class="hq-num">SL</th>' + d.vendors.map(function (v) {
      return '<th class="hq-vendor-col"><button type="button" class="hq-link-btn hq-ellipsis" data-vendor-info="' +
        v.quote_id + '" title="Xem thông tin, link và mật khẩu của ' + esc(v.name) + '">' + esc(v.name) +
        '</button><span class="hq-tag ' + (HQ.QUOTE_STATE_CLASS[v.state] || "") + '">' + esc(v.state_label) + "</span></th>";
    }).join("") + "</tr>";
    var rows = d.lines.map(function (line) {
      var tag = line.locked ? '<span class="hq-muted">đã lên đơn mua — khoá</span>'
        : line.request_name ? '<span class="hq-muted">trong ' + esc(line.request_name) + "</span>" : "";
      return "<tr><td>" + esc(line.name) + (tag ? "<div>" + tag + "</div>" : "") +
        '</td><td class="hq-num hq-nowrap">' + HQ.qty(line.qty) + " " +
        esc(line.uom) + "</td>" + d.vendors.map(function (v) {
          return offerCell(line.offers[v.quote_id], v, d.can_choose && !line.locked);
        }).join("") + "</tr>";
    }).join("");
    return '<h3 class="hq-h3 hq-section-title">So giá — bấm vào giá để chọn NCC</h3>' +
      '<div class="hq-table-wrap hq-compare-wrap"><table class="hq-table hq-compare"><thead>' + head +
      "</thead><tbody>" + rows + "</tbody><tfoot><tr><td colspan=\"" + (2 + d.vendors.length) +
      '" class="hq-num">Tổng các giá đã chọn: <b>' + HQ.money(d.chosen_total) + "</b> chưa VAT · <b>" +
      HQ.money(d.chosen_total_incl) + "</b> sau VAT</td></tr></tfoot>" +
      "</table></div>" +
      '<div class="hq-muted hq-legend">Chữ xanh đậm = giá thấp nhất · nền xanh = giá đã chọn.</div>';
  }

  function offerCell(offer, vendor, canChoose) {
    if (!offer || (!offer.price_unit && !offer.unavailable)) {
      return '<td class="hq-offer hq-muted">' + (vendor.state === "sent" ? "Chờ báo giá" : "—") + "</td>";
    }
    if (offer.unavailable) {
      // NCC đang được chọn mà báo hết hàng (thường là sửa sau khi đã lên YCMH): báo đỏ để
      // sale chọn NCC khác.
      return offer.selected
        ? '<td class="hq-offer hq-offer-alert">Đang được chọn — NCC báo hết hàng, chọn NCC khác</td>'
        : '<td class="hq-offer hq-muted">Không có hàng</td>';
    }
    var meta = [offer.vat ? "VAT " + offer.vat : "", offer.delivery_days ? offer.delivery_days + " ngày" : ""]
      .filter(Boolean).join(" · ");
    var body = '<span class="hq-offer-price' + (offer.is_best ? " is-best" : "") + '">' + HQ.money(offer.price_unit) +
      ' <span class="hq-offer-unit">chưa VAT</span></span>' +
      (offer.vat ? '<span class="hq-offer-incl">' + HQ.money(offer.price_incl) + " sau VAT</span>" : "") +
      (meta ? '<span class="hq-offer-meta">' + esc(meta) + "</span>" : "") +
      (offer.vendor_note ? '<span class="hq-offer-meta" title="' + esc(offer.vendor_note) + '">' +
        esc(offer.vendor_note) + "</span>" : "");
    var cls = "hq-offer" + (offer.selected ? " is-selected" : "");
    if (!canChoose) {
      return '<td class="' + cls + '"><div class="hq-offer-static">' + body + "</div></td>";
    }
    return '<td class="' + cls + '"><button type="button" class="hq-offer-btn" data-' +
      (offer.selected ? "unchoose" : "choose") + '="' + offer.line_id + '" title="' +
      (offer.selected ? "Bấm để bỏ chọn" : "Chọn NCC này") + '">' + body + "</button></td>";
  }

  function renderRequestBox(d) {
    if (d.sale_status === "cancel") {
      return "";
    }
    var done = d.requests.length
      ? '<div class="hq-muted">Đã lên ' + d.requests.map(function (r) { return esc(r.name); }).join(", ") +
        ". Thu mua duyệt YCMH rồi tạo đơn mua theo NCC và giá đã chọn. Đổi NCC cho sản phẩm chưa lên " +
        "đơn mua: bấm giá NCC khác — YCMH tự cập nhật.</div>"
      : "";
    if (d.requests.length && !d.pending_count) {
      return '<div class="hq-share"><b>Đã lên yêu cầu mua hàng</b>' + done + "</div>";
    }
    return '<div class="hq-share"><div class="hq-share-head"><b>' +
      (d.requests.length ? "Bổ sung vào yêu cầu mua hàng" : "Lên yêu cầu mua hàng") + "</b>" +
      '<span class="hq-muted">' + (d.requests.length ? d.pending_count + " sản phẩm mới chọn chưa lên YCMH"
        : d.chosen_count + "/" + d.line_count + " sản phẩm đã chọn NCC") + "</span></div>" + done +
      '<div class="hq-request-row"><div class="hq-picker hq-request-so">' +
      '<label class="hq-sr-only" for="hq-req-so-search">Đơn bán</label>' +
      '<input type="search" id="hq-req-so-search" class="hq-input w-100" autocomplete="off" ' +
      'placeholder="Gắn đơn bán (không bắt buộc)…"/>' +
      '<div id="hq-req-so-results" class="hq-dropdown hq-hidden"></div></div>' +
      '<div id="hq-req-so-chip" class="hq-chip-row">' + saleOrderChip() + "</div>" +
      '<button type="button" class="hq-btn hq-btn-primary hq-push" data-create-request="1"' +
      (d.can_request ? "" : " disabled") + ">" + (d.requests.length ? "Bổ sung vào YCMH" : "Tạo yêu cầu mua hàng") +
      "</button></div>" +
      '<div class="hq-muted hq-small">Có đơn bán và đơn đó có YCMH chưa duyệt thì hàng được gộp vào YCMH đó.</div></div>';
  }

  function saleOrderChip() {
    return D.saleOrder ? '<span class="hq-chip hq-chip-blue">Đơn bán ' + esc(D.saleOrder.name) +
      '<button type="button" class="hq-chip-x" data-clear-so="1" title="Bỏ đơn bán">×</button></span>' : "";
  }

  function renderVendors(d) {
    if (!d.vendors.length) {
      return "";
    }
    return '<h3 class="hq-h3 hq-section-title">Nhà cung cấp đã hỏi ' +
      '<span class="hq-muted hq-small">— bấm tên NCC để xem thông tin, link và mật khẩu</span></h3>' +
      '<div class="hq-table-wrap"><table class="hq-table"><tbody>' +
      d.vendors.map(function (v, index) {
        return '<tr><td><button type="button" class="hq-link-btn" data-vendor-info="' + v.quote_id +
          '" title="Xem thông tin, link và mật khẩu">' + esc(v.name) + "</button></td>" +
          '<td><span class="hq-tag ' + (HQ.QUOTE_STATE_CLASS[v.state] || "") + '">' + esc(v.state_label) + "</span>" +
          (v.submit_date ? '<div class="hq-muted">gửi ' + esc(v.submit_date) + "</div>" : "") + "</td>" +
          '<td class="hq-num">' + (v.amount_untaxed ? HQ.money(v.amount_untaxed) : "") + "</td>" +
          '<td class="hq-num hq-nowrap">' + chatButton("quote", v.quote_id, v.chat_count, v.chat_unread) + " " +
          (v.share_message ? '<button type="button" class="hq-btn hq-btn-mini" data-copy-msg="' + index +
            '">Copy tin nhắn</button> ' : "") +
          (v.portal_url ? '<a class="hq-btn hq-btn-mini" target="_blank" href="' + esc(v.portal_url) +
            '">Mở trang NCC</a>' : "") + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  /** Nút mở trao đổi với NCC; có tin NCC chưa xem thì làm nổi lên kèm số tin mới. */
  function chatButton(model, id, count, unread) {
    return '<button type="button" class="hq-btn hq-btn-mini' + (unread ? " hq-btn-soft" : "") +
      '" data-chat-model="' + model + '" data-chat-id="' + id + '">' +
      (unread ? unread + " tin mới" : "Trao đổi" + (count ? " (" + count + ")" : "")) + "</button>";
  }

  /** Ô mã đơn hàng cho mọi đơn mua của phiếu; điền sẵn khi các đơn đang cùng một mã. */
  function originBox(d) {
    var editable = d.purchase_orders.filter(function (o) { return o.can_set_origin; });
    if (!editable.length) {
      return "";
    }
    var origins = editable.map(function (o) { return o.origin; });
    var common = origins.every(function (v) { return v === origins[0]; }) ? origins[0] : "";
    return HQ.originEditor("inquiry", common, editable.map(function (o) { return o.id; }),
      editable.length > 1 ? "Cập nhật cho " + editable.length + " đơn mua" : "Cập nhật",
      function () { HQ.openInquiry(d.id, true); });
  }

  function renderOrders(d) {
    if (!d.purchase_orders.length) {
      return "";
    }
    return '<h3 class="hq-h3 hq-section-title">Đơn mua</h3>' + originBox(d) +
      '<div class="hq-table-wrap"><table class="hq-table"><tbody>' +
      d.purchase_orders.map(function (o) {
        return '<tr><td><button type="button" class="hq-link-btn" data-po="' + o.id + '" title="Xem đơn mua">' +
          esc(o.name) + "</button>" + (o.origin ? '<div class="hq-muted">Mã ĐH ' + esc(o.origin) + "</div>"
            : '<div class="hq-muted">Chưa có mã đơn hàng</div>') + "</td><td>" + esc(o.vendor) + "</td>" +
          "<td>" + (o.vendor_status ? '<span class="hq-tag hq-tag-ok">' + esc(o.vendor_status) + "</span>"
            : '<span class="hq-muted">NCC chưa báo tiến độ</span>') + "</td>" +
          '<td class="hq-num">' + HQ.money(o.amount_untaxed) + "</td>" +
          '<td class="hq-num">' + chatButton("order", o.id, o.chat_count, o.chat_unread) + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  function bindSaleOrderPicker() {
    if (!HQ.$("hq-req-so-search")) {
      return;
    }
    HQ.bindPicker("hq-req-so-search", "hq-req-so-results", function (term) {
      return HQ.rpc("/api/hoi-gia-ncc/sale_orders", { search: term }).then(function (r) { return r.orders; });
    }, function (o) {
      return '<span class="hq-strong">' + esc(o.name) + "</span> " +
        '<span class="hq-muted">' + esc([o.partner, o.sale_code, o.date].filter(Boolean).join(" · ")) + "</span>";
    }, function (order) {
      D.saleOrder = { id: order.id, name: order.name };
      HQ.$("hq-req-so-chip").innerHTML = saleOrderChip();
    });
  }

  /* ---------------- sự kiện ---------------- */

  HQ.bindCompareEvents = function () {
    var panel = HQ.$("hq-drawer-panel");
    HQ.on(panel, "click", "[data-choose]", function (el) { choose(+el.dataset.choose, true); });
    HQ.on(panel, "click", "[data-unchoose]", function (el) { choose(+el.dataset.unchoose, false); });
    HQ.on(panel, "click", "[data-create-request]", createRequest);
    HQ.on(panel, "click", "[data-cancel-inquiry]", cancelInquiry);
    HQ.on(panel, "click", "[data-clear-so]", function () {
      D.saleOrder = null;
      HQ.$("hq-req-so-chip").innerHTML = "";
    });
    HQ.on(panel, "click", "[data-copy-msg]", function (el) {
      HQ.copy(D.detail.vendors[+el.dataset.copyMsg].share_message);
    });
  };
})(window.HlvQuote);
