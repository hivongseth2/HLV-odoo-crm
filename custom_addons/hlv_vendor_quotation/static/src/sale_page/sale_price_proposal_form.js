/* Form "Hỏi lại NCC" của đề xuất thu mua trả về (sale_price_proposal.js): một hàng mở ra ngay dưới dòng sản phẩm trên
   bảng so giá. Sale chốt mã / SL / giá mong muốn (điền sẵn theo đề xuất của thu mua), chọn có cần NCC báo giá lại không
   rồi gửi (models/po_proposal_change.py). Đổi mã luôn phải hỏi NCC (mã mới chưa có giá); chỉ giảm SL thì mặc định gửi
   thẳng thu mua — sale bật lại được. Dòng chữ "Duyệt xong: …" nói trước đơn mua sẽ đổi thế nào. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var EPS = 1e-9;
  // Theo id đề xuất: mã đang chọn {id, name}; sale đã tự bấm ô "Cần NCC báo giá lại" (thôi tự đặt mặc định).
  var picked = {};
  var touched = {};

  /** Hàng form (ẩn) dưới dòng sản phẩm, cho đề xuất còn hỏi lại được có ô của món trên đơn ở dòng đó. */
  HQ.proposalFormRows = function (d, line, colspan) {
    return d.vendors.map(function (v) {
      var offer = line.offers[v.quote_id];
      var p = offer && HQ.openProposal(d, offer.line_id);
      return p && p.can_requote && offer.line_id === p.quote_line_id ? row(p, colspan) : "";
    }).join("");
  };

  function row(p, colspan) {
    var id = p.id;
    var product = p.form_product || {};
    return '<tr class="hq-pp-form-row hq-hidden" data-pp-row="' + id + '"><td colspan="' + colspan + '">' +
      '<div class="hq-pp-form"><div class="hq-pp-fields">' +
      '<div class="hq-pp-field hq-pp-field-wide"><label class="hq-label" for="hq-pp-prod-' + id + '">Mã hàng</label>' +
      '<div class="hq-picker"><input type="text" class="hq-input" id="hq-pp-prod-' + id + '" autocomplete="off" value="' +
      esc(product.name || "") + '" placeholder="Gõ mã / tên để đổi sang mã khác"/>' +
      '<div class="hq-dropdown hq-hidden" id="hq-pp-prod-list-' + id + '"></div></div></div>' +
      '<div class="hq-pp-field"><label class="hq-label" for="hq-pp-qty-' + id + '">SL (' + esc(p.uom) + ") · trên đơn " +
      HQ.qty(p.old_qty) + '</label><input type="number" class="hq-input" id="hq-pp-qty-' + id + '" min="0" step="any" ' +
      'inputmode="decimal" data-pp-qty="' + id + '" value="' + p.form_qty + '"/></div>' +
      '<div class="hq-pp-field"><label class="hq-label" for="hq-pp-price-' + id + '">Giá mong muốn (sau VAT)</label>' +
      '<input type="number" class="hq-input" id="hq-pp-price-' + id + '" min="0" step="any" inputmode="decimal" ' +
      'data-pp-price="' + id + '" value="' + (p.suggested_price || "") + '" placeholder="Không bắt buộc"/></div></div>' +
      '<label class="hq-pp-check"><input type="checkbox" data-pp-vendor="' + id + '"/> Cần NCC báo giá lại</label>' +
      '<div class="hq-pp-outcome" data-pp-outcome="' + id + '"></div>' +
      '<label class="hq-sr-only" for="hq-pp-note-' + id + '">Ghi thêm</label>' +
      '<textarea class="hq-input hq-textarea" rows="2" maxlength="1000" id="hq-pp-note-' + id + '" data-pp-note="' + id +
      '"></textarea>' +
      '<div class="hq-pp-actions"><button type="button" class="hq-btn hq-btn-primary" data-pp-send="' + id + '"></button>' +
      '<button type="button" class="hq-btn" data-pp-form="' + id + '">Thôi</button></div></div></td></tr>';
  }

  function field(panel, attr, id) {
    return panel.querySelector("[" + attr + '="' + id + '"]');
  }

  /** Đơn mua sẽ đổi thế nào khi thu mua duyệt — nói trước để sale không bất ngờ. "" = chưa hợp lệ (đã báo lỗi). */
  function outcome(p, product, qty, swapped) {
    var uom = " " + p.uom;
    if (!(qty > EPS)) {
      return "Nhập SL lớn hơn 0.";
    }
    if (swapped) {
      return p.qty_received > EPS ? "Kho đã nhận mã cũ — không đổi mã được nữa."
        : "Duyệt xong: dòng " + p.product + " về SL 0, thêm dòng " + product.name + " " + HQ.qty(qty) + uom + ".";
    }
    if (qty < p.qty_received - EPS) {
      return "Kho đã nhận " + HQ.qty(p.qty_received) + uom + " — không giảm dưới số đó.";
    }
    if (qty > p.old_qty + EPS) {
      return "Duyệt xong: dòng cũ giữ " + HQ.qty(p.old_qty) + ", thêm dòng mới " + HQ.qty(qty - p.old_qty) + uom +
        " trên " + p.order + ".";
    }
    if (qty < p.old_qty - EPS) {
      return "Duyệt xong: dòng giảm " + HQ.qty(p.old_qty) + " → " + HQ.qty(qty) + uom + ", NCC được báo trên đơn.";
    }
    return "Giữ SL " + HQ.qty(p.old_qty) + uom + " — chỉ hỏi lại giá.";
  }

  function refresh(panel, id) {
    var p = HQ.proposalById(id);
    var product = picked[id] || p.form_product || {};
    var qty = Number(field(panel, "data-pp-qty", id).value) || 0;
    var swapped = !!product.id && product.id !== p.product_id;
    var vendor = field(panel, "data-pp-vendor", id);
    vendor.disabled = swapped;
    if (swapped) {
      vendor.checked = true;
    } else if (!touched[id]) {
      // Chỉ giảm SL, không đòi giá mới: không cần NCC báo giá — gửi thẳng thu mua (NCC vẫn được báo khi duyệt).
      vendor.checked = !(qty < p.old_qty - EPS && !Number(field(panel, "data-pp-price", id).value));
    }
    field(panel, "data-pp-outcome", id).textContent = outcome(p, product, qty, swapped);
    field(panel, "data-pp-send", id).textContent = vendor.checked ? "Gửi NCC báo giá" : "Gửi thu mua duyệt";
    field(panel, "data-pp-note", id).placeholder = vendor.checked
      ? "Ghi thêm cho NCC (không bắt buộc) — lời nhắn đã soạn sẵn theo mã / SL / giá"
      : "Ghi chú cho thu mua (không bắt buộc)";
  }

  function searchProducts(term) {
    return HQ.rpc("/api/hoi-gia-ncc/products", { search: term }).then(function (r) { return r.products; });
  }

  function open(panel, id) {
    var formRow = field(panel, "data-pp-row", id);
    if (!formRow) {
      return;
    }
    var opening = formRow.classList.contains("hq-hidden");
    formRow.classList.toggle("hq-hidden");
    if (!opening) {
      return;
    }
    var p = HQ.proposalById(id);
    picked[id] = p.form_product;
    touched[id] = false;
    var input = HQ.$("hq-pp-prod-" + id);
    if (!input.dataset.bound) {
      input.dataset.bound = "1";
      HQ.bindPicker(input.id, "hq-pp-prod-list-" + id, searchProducts, function (item) {
        return esc(item.product);
      }, function (item) {
        picked[id] = { id: item.product_id, name: item.product };
        refresh(panel, id);
        return item.product;  // ô giữ tên mã vừa chọn
      });
    }
    refresh(panel, id);
    formRow.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  HQ.bindProposalFormEvents = function (panel) {
    HQ.on(panel, "click", "[data-pp-form]", function (el) { open(panel, +el.dataset.ppForm); });
    HQ.on(panel, "input", "[data-pp-qty], [data-pp-price]", function (el) {
      refresh(panel, +(el.dataset.ppQty || el.dataset.ppPrice));
    });
    HQ.on(panel, "change", "[data-pp-vendor]", function (el) {
      touched[+el.dataset.ppVendor] = true;
      refresh(panel, +el.dataset.ppVendor);
    });
    HQ.on(panel, "click", "[data-pp-send]", function (el) {
      var id = +el.dataset.ppSend;
      var product = picked[id] || {};
      var vendor = field(panel, "data-pp-vendor", id).checked;
      HQ.proposalSend("price_requote", {
        proposal_id: id, product_id: product.id || null, qty: Number(field(panel, "data-pp-qty", id).value) || 0,
        price: Number(field(panel, "data-pp-price", id).value) || 0, needs_vendor: vendor,
        note: field(panel, "data-pp-note", id).value,
      }, el, vendor ? "Đã gửi NCC — chờ NCC báo giá" : "Đã gửi thu mua duyệt");
    });
  };
})(window.HlvQuote);
