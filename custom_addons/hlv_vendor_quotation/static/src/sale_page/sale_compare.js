/* Ngăn chi tiết một phiếu hỏi giá: bảng so giá sản phẩm × NCC, sale bấm chọn giá, rồi lên
   yêu cầu mua hàng (đơn bán tuỳ chọn). Sau khi lên YCMH: hiện YCMH và đơn mua sinh ra. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var S = HQ.S;
  var esc = HQ.esc;
  // Phiếu đang mở + đơn bán sẽ gắn khi lên YCMH; confirming: đang xem bảng tóm tắt trước khi tạo YCMH.
  var D = { detail: null, saleOrder: null, confirming: false };

  /** quiet: tải lại ngầm phiếu đang mở (có tin mới) — không nháy "Đang tải…". */
  HQ.openInquiry = function (inquiryId, quiet) {
    S.openInquiryId = inquiryId;
    HQ.show("hq-drawer", true);
    if (!quiet) {
      D.confirming = false;
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

  /** Bước 1: hiện bảng tóm tắt (sản phẩm, NCC, giá sẽ lên YCMH) để sale soát trước khi tạo. */
  function reviewRequest(on) {
    D.confirming = on;
    render(D.detail);
  }

  /** Bước 2: sale bấm xác nhận trên bảng tóm tắt. */
  function createRequest(button) {
    var d = D.detail;
    button.disabled = true;
    HQ.api("create_request", {
      inquiry_id: d.id,
      sale_order_id: D.saleOrder ? D.saleOrder.id : null,
    }).then(function (detail) {
      var r = detail.request_result;
      D.confirming = false;
      afterChange(detail, (r.merged ? "Đã gộp vào yêu cầu mua hàng " : "Đã tạo yêu cầu mua hàng ") + r.name);
    }).catch(function (err) {
      button.disabled = false;
      HQ.toast(err.message);
    });
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
    HQ.addVendorDetail = d;
    HQ.$("hq-drawer-panel").innerHTML =
      '<div class="hq-drawer-head"><div><div class="hq-muted">Phiếu hỏi giá' +
      (d.sale_code ? " · " + esc(HQ.saleName(d.sale_code)) : "") + "</div>" +
      '<h2 class="hq-h2">' + esc(d.name) + ' <span class="hq-tag ' + (HQ.SALE_STATUS_CLASS[d.sale_status] || "") +
      '">' + esc(d.sale_status_label) + "</span></h2></div>" +
      '<button type="button" class="btn-close" data-close="drawer" aria-label="Đóng"></button></div>' +
      renderFacts(d) +
      renderRejected(d) +
      HQ.closedBanner(d) +
      renderCompare(d) +
      HQ.addVendorBox(d) +
      renderRequestBox(d) +
      renderOrders(d) +
      renderVendors(d) +
      (d.note ? '<div class="hq-note"><span class="hq-label">Lời nhắn gửi NCC</span>' + esc(d.note) + "</div>" : "") +
      HQ.closeBox(d) +
      (d.can_cancel || d.can_close ? '<div class="hq-drawer-actions">' +
        (d.can_close ? '<button type="button" class="hq-btn" data-close-toggle="1" title="Khách không lấy… — giá NCC ' +
          'vẫn giữ để lần sau dùng lại">Không mua</button>' : "") +
        (d.can_cancel ? '<button type="button" class="hq-btn hq-btn-danger" data-cancel-inquiry="1" title="Hỏi nhầm / ' +
          'lập sai — bỏ luôn giá">Huỷ phiếu</button>' : "") + "</div>" : "");
    bindSaleOrderPicker();
    HQ.bindOriginPicker("inquiry");
    HQ.bindAddVendorPicker();
  }
  HQ.renderInquiry = render;

  function fact(label, value) {
    return value ? '<div class="hq-fact"><span class="hq-label">' + esc(label) + "</span>" + value + "</div>" : "";
  }

  function renderFacts(d) {
    var orders = d.orders.map(HQ.orderTag).join("");
    return '<div class="hq-facts">' +
      fact("Sale", esc(HQ.saleLabel(d.sale_code))) +
      opportunityFact(d) +
      fact("Đơn bán", esc(d.sale_order)) +
      fact("Hạn báo giá", esc(d.deadline)) +
      fact("Yêu cầu mua hàng", d.requests.map(HQ.requestTag).join("")) +
      fact("Đơn mua", orders) +
      "</div>";
  }

  /** Số cơ hội: sửa tại chỗ (thường có số cơ hội sau khi đã hỏi giá). */
  function opportunityFact(d) {
    if (!d.can_set_opportunity) {
      return fact("Số cơ hội", esc(d.opportunity_ref));
    }
    return '<div class="hq-fact"><label class="hq-label" for="hq-opp-input">Số cơ hội</label>' +
      '<span class="hq-opp-edit"><input type="text" id="hq-opp-input" class="hq-input" maxlength="64" autocomplete="off" ' +
      'value="' + esc(d.opportunity_ref) + '" placeholder="Chưa có"/>' +
      '<button type="button" class="hq-btn hq-btn-mini" data-save-opp="1">Lưu</button></span></div>';
  }

  function saveOpportunity(button) {
    var value = HQ.$("hq-opp-input").value;
    button.disabled = true;
    HQ.api("set_opportunity", { inquiry_id: D.detail.id, opportunity_ref: value }).then(function (detail) {
      afterChange(detail, detail.opportunity_ref ? "Đã lưu số cơ hội " + detail.opportunity_ref : "Đã bỏ số cơ hội");
    }).catch(function (err) {
      button.disabled = false;
      HQ.toast(err.message);
    });
  }

  /** YCMH bị thu mua từ chối: báo đỏ ngay đầu ngăn — trước đây chỉ là chữ nhỏ trong ngoặc. */
  function renderRejected(d) {
    var rejected = d.requests.filter(function (r) { return r.state === "rejected"; });
    if (!rejected.length) {
      return "";
    }
    return '<div class="hq-alert hq-alert-strong">' + rejected.map(function (r) { return esc(r.name); }).join(", ") +
      " bị thu mua <b>từ chối</b>. Hỏi thu mua lý do (nút Trao đổi trên đơn mua, hoặc chatter YCMH), chọn lại NCC " +
      "nếu cần rồi lên YCMH mới.</div>";
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
      var tag = line.locked ? '<span class="hq-muted" title="NCC giao thiếu / hết hàng: nhờ thu mua sửa số lượng dòng ' +
        'này trên đơn mua xuống đúng số NCC giao được — phần còn thiếu mở ra để chọn NCC khác">đã lên đơn mua — khoá</span>'
        : line.ordered_qty > 0 ? '<span class="hq-partial">đã đặt ' + HQ.qty(line.ordered_qty) + "/" +
          HQ.qty(line.requested_qty) + " — chọn NCC cho " + HQ.qty(line.requested_qty - line.ordered_qty) + " còn thiếu</span>"
        : line.request_rejected ? '<span class="hq-expired">' + esc(line.request_name) + " bị từ chối — chọn lại NCC rồi lên YCMH mới</span>"
        : line.request_name ? '<span class="hq-muted">trong ' + esc(line.request_name) + "</span>" : "";
      return "<tr><td>" + esc(line.name) + (tag ? "<div>" + tag + "</div>" : "") +
        '</td><td class="hq-num hq-nowrap">' + HQ.qty(line.qty) + " " +
        esc(line.uom) + "</td>" + d.vendors.map(function (v) {
          return offerCell(line.offers[v.quote_id], v, d.can_choose && !line.locked);
        }).join("") + "</tr>";
    }).join("");
    return '<div class="hq-compare-head"><h3 class="hq-h3 hq-section-title">So giá — bấm vào giá để chọn NCC</h3>' +
      (d.can_add_vendor ? '<button type="button" class="hq-btn hq-btn-mini" data-add-toggle="1" title="NCC báo hết hàng / ' +
        'cần thêm giá để so — gửi sản phẩm cho NCC khác">+ Hỏi thêm NCC</button>' : "") + "</div>" +
      '<div class="hq-table-wrap hq-compare-wrap"><table class="hq-table hq-compare"><thead>' + head +
      "</thead><tbody>" + rows + "</tbody><tfoot><tr><td colspan=\"" + (2 + d.vendors.length) +
      '" class="hq-num">Tổng các giá đã chọn: <b>' + HQ.money(d.chosen_total_incl) + "</b> sau VAT · " +
      HQ.money(d.chosen_total) + " chưa VAT</td></tr></tfoot>" +
      "</table></div>" +
      '<div class="hq-muted hq-legend">Chữ xanh đậm = giá sau VAT thấp nhất · nền xanh = giá đã chọn.</div>';
  }

  function offerCell(offer, vendor, canChoose) {
    if (!offer || (!offer.price_unit && !offer.unavailable)) {
      if (offer && offer.reference_price) {
        return '<td class="hq-offer hq-muted">Chờ NCC xác nhận<span class="hq-offer-meta">lần trước ' +
          HQ.money(offer.reference_price) + " sau VAT — đã điền sẵn cho NCC</span></td>";
      }
      return '<td class="hq-offer hq-muted">' + (vendor.state === "sent" ? "Chờ báo giá" : "—") + "</td>";
    }
    if (offer.unavailable) {
      // NCC đang được chọn mà báo hết hàng (thường là sửa sau khi đã lên YCMH): báo đỏ để
      // sale chọn NCC khác.
      return offer.selected
        ? '<td class="hq-offer hq-offer-alert">Đang được chọn — NCC báo hết hàng, chọn NCC khác hoặc hỏi thêm NCC</td>'
        : '<td class="hq-offer hq-muted">Không có hàng</td>';
    }
    var meta = [offer.vat ? "VAT " + offer.vat : "", offer.delivery_days ? offer.delivery_days + " ngày" : ""]
      .filter(Boolean).join(" · ");
    // Giá sau VAT là số chính (bên mình đọc và so theo giá sau VAT); giá chưa VAT ghi phụ.
    var body = '<span class="hq-offer-price' + (offer.is_best ? " is-best" : "") + '">' + HQ.money(offer.price_incl) +
      ' <span class="hq-offer-unit">sau VAT</span></span>' +
      '<span class="hq-offer-incl">' + HQ.money(offer.price_unit) + " chưa VAT</span>" +
      (meta ? '<span class="hq-offer-meta">' + esc(meta) + "</span>" : "") +
      (offer.list_price ? '<span class="hq-offer-meta">Trước CK ' + HQ.money(offer.list_price_incl) + " · CK " +
        HQ.qty(offer.discount) + "%</span>" : "") +
      (offer.invoice_name ? '<span class="hq-offer-meta" title="Tên xuất hóa đơn: ' + esc(offer.invoice_name) + '">HĐ: ' +
        esc(offer.invoice_name) + "</span>" : "") +
      (offer.vendor_note ? '<span class="hq-offer-meta" title="' + esc(offer.vendor_note) + '">' +
        esc(offer.vendor_note) + "</span>" : "") +
      (offer.inherited_from ? '<span class="hq-offer-reuse" title="Giá còn hiệu lực lấy lại từ ' +
        esc(offer.inherited_from) + ' — không hỏi lại NCC">giá cũ · ' + esc(offer.inherited_from) + "</span>" : "");
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
    // YCMH bị từ chối không tính là "đã lên": sản phẩm trong đó chờ lên YCMH mới.
    var live = d.requests.filter(function (r) { return r.state !== "rejected"; });
    var redo = d.lines.some(function (l) { return l.to_request && l.request_rejected; });
    var done = live.length
      ? '<div class="hq-muted">Đã lên ' + live.map(function (r) { return esc(r.name); }).join(", ") +
        ". Thu mua duyệt YCMH rồi tạo đơn mua theo NCC và giá đã chọn. Đổi NCC cho sản phẩm chưa lên " +
        "đơn mua: bấm giá NCC khác — YCMH tự cập nhật.</div>"
      : "";
    if (live.length && !d.pending_count) {
      return '<div class="hq-share"><b>Đã lên yêu cầu mua hàng</b>' + done + "</div>";
    }
    var title = redo ? "Lên lại yêu cầu mua hàng" : live.length ? "Bổ sung vào yêu cầu mua hàng" : "Lên yêu cầu mua hàng";
    var head = '<div class="hq-share"><div class="hq-share-head"><b>' + title + "</b>" +
      '<span class="hq-muted">' + (live.length || redo ? d.pending_count + " sản phẩm đã chọn NCC chưa lên YCMH"
        : d.chosen_count + "/" + d.line_count + " sản phẩm đã chọn NCC") + "</span></div>" + done;
    if (D.confirming && d.can_request) {
      return head + requestSummary(d) + '<div class="hq-request-row"><span class="hq-push"></span>' +
        '<button type="button" class="hq-btn" data-review-request="0">Quay lại</button>' +
        '<button type="button" class="hq-btn hq-btn-primary" data-create-request="1">Xác nhận tạo YCMH</button></div></div>';
    }
    return head +
      '<div class="hq-request-row"><div class="hq-picker hq-request-so">' +
      '<label class="hq-sr-only" for="hq-req-so-search">Đơn bán</label>' +
      '<input type="search" id="hq-req-so-search" class="hq-input w-100" autocomplete="off" ' +
      'placeholder="Gắn đơn bán (không bắt buộc)…"/>' +
      '<div id="hq-req-so-results" class="hq-dropdown hq-hidden"></div></div>' +
      '<div id="hq-req-so-chip" class="hq-chip-row">' + saleOrderChip() + "</div>" +
      '<button type="button" class="hq-btn hq-btn-primary hq-push" data-review-request="1"' +
      (d.can_request ? "" : " disabled") + ">" +
      (redo ? "Tạo YCMH mới" : live.length ? "Bổ sung vào YCMH" : "Tạo yêu cầu mua hàng") + "</button></div>" +
      '<div class="hq-muted hq-small">Có đơn bán và đơn đó có YCMH chưa duyệt thì hàng được gộp vào YCMH đó.</div></div>';
  }

  /** Bảng tóm tắt những gì sẽ lên YCMH: sản phẩm, NCC đã chọn, giá sau VAT; kèm sản phẩm bị bỏ lại. */
  function requestSummary(d) {
    var vendorNames = {};
    d.vendors.forEach(function (v) { vendorNames[v.quote_id] = v.name; });
    var total = 0;
    var rows = d.lines.filter(function (l) { return l.to_request; }).map(function (line) {
      var quoteId = Object.keys(line.offers).find(function (key) { return line.offers[key].selected; });
      var offer = line.offers[quoteId];
      total += offer.total_incl;
      return "<tr><td>" + esc(line.name) + '</td><td class="hq-num hq-nowrap">' + HQ.qty(line.qty) + " " + esc(line.uom) +
        "</td><td>" + esc(vendorNames[quoteId] || "") + '</td><td class="hq-num">' + HQ.money(offer.price_incl) +
        '</td><td class="hq-num">' + HQ.money(offer.total_incl) + "</td></tr>";
    }).join("");
    var unchosen = d.lines.filter(function (l) {
      return !l.locked && !Object.keys(l.offers).some(function (key) { return l.offers[key].selected; });
    });
    return '<div class="hq-table-wrap hq-request-summary"><table class="hq-table"><thead><tr><th>Sản phẩm</th>' +
      '<th class="hq-num">SL</th><th>Nhà cung cấp</th><th class="hq-num">Đơn giá sau VAT</th>' +
      '<th class="hq-num">Thành tiền</th></tr></thead><tbody>' + rows + "</tbody>" +
      '<tfoot><tr><td colspan="4" class="hq-num">Tổng sau VAT</td><td class="hq-num"><b>' + HQ.money(total) +
      "</b></td></tr></tfoot></table></div>" +
      '<div class="hq-muted hq-small">' + (D.saleOrder ? "Gắn đơn bán <b>" + esc(D.saleOrder.name) +
        "</b> — đơn đã có YCMH chưa duyệt thì hàng được gộp vào đó." : "Không gắn đơn bán.") + "</div>" +
      (unchosen.length ? '<div class="hq-alert hq-alert-strong">' + unchosen.length + " sản phẩm chưa chọn NCC sẽ " +
        "không lên YCMH: " + unchosen.map(function (l) { return esc(l.name); }).join(", ") + "</div>" : "");
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
          (v.submit_date ? '<div class="hq-muted">gửi ' + esc(v.submit_date) + "</div>" : "") +
          (v.price_valid_until ? '<div class="' + (v.price_valid ? "hq-muted" : "hq-expired") + '">giá hiệu lực đến ' +
            esc(v.price_valid_until) + (v.price_valid ? "" : " — đã hết") + "</div>" : "") +
          (v.reused ? '<div><span class="hq-tag hq-tag-mine">Dùng lại giá cũ</span></div>' : "") + "</td>" +
          '<td class="hq-num">' + (v.amount_total ? HQ.money(v.amount_total) : "") + "</td>" +
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
          "<td>" + (o.vendor_ship ? '<div class="hq-muted hq-small" title="NCC đã gửi">' + esc(o.vendor_ship) + "</div>" : "") +
          (o.vendor_status ? '<span class="hq-tag hq-tag-ok">' + esc(o.vendor_status) + "</span>"
            : '<span class="hq-muted">NCC chưa báo tiến độ</span>') + "</td>" +
          '<td class="hq-num">' + HQ.money(o.amount_total) + "</td>" +
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
        '<span class="hq-muted">' + esc([o.partner, HQ.saleName(o.sale_code), o.date].filter(Boolean).join(" · ")) + "</span>";
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
    HQ.on(panel, "click", "[data-review-request]", function (el) { reviewRequest(el.dataset.reviewRequest === "1"); });
    HQ.on(panel, "click", "[data-create-request]", createRequest);
    HQ.on(panel, "click", "[data-cancel-inquiry]", cancelInquiry);
    HQ.on(panel, "click", "[data-save-opp]", saveOpportunity);
    HQ.on(panel, "keydown", "#hq-opp-input", function (el, event) {
      if (event.key === "Enter") {
        event.preventDefault();
        saveOpportunity(panel.querySelector("[data-save-opp]"));
      }
    });
    HQ.on(panel, "click", "[data-clear-so]", function () {
      D.saleOrder = null;
      HQ.$("hq-req-so-chip").innerHTML = "";
    });
    HQ.on(panel, "click", "[data-copy-msg]", function (el) {
      HQ.copy(D.detail.vendors[+el.dataset.copyMsg].share_message);
    });
  };
})(window.HlvQuote);
