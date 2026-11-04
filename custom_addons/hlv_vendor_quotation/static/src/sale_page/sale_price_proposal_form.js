/* Popup "Hỏi lại NCC" của đề xuất thu mua trả về (sale_price_proposal.js): sale chốt mã / SL / giá mong muốn (điền
   sẵn theo đề xuất của thu mua), chọn có cần NCC báo giá lại không rồi gửi (models/po_proposal_change.py). Đổi mã luôn
   phải hỏi NCC (mã mới chưa có giá); chỉ giảm SL thì mặc định gửi thẳng thu mua — sale bật lại được. Dòng "Duyệt xong:
   …" nói trước đơn mua sẽ đổi thế nào. Khung popup nằm sẵn trong trang (#hq-pp-modal, sale_page_templates.xml). */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var EPS = 1e-9;
  // Đề xuất đang mở trong popup; mã đang chọn {id, name}; sale đã tự bấm ô "Cần NCC báo giá lại" (thôi tự đặt mặc định).
  var F = { p: null, product: null, touched: false };

  function el(id) {
    return HQ.$("hq-pp-" + id);
  }

  function body(p) {
    var product = p.form_product || {};
    return '<div class="hq-pp-fields">' +
      '<div class="hq-pp-field hq-pp-field-wide"><label class="hq-label" for="hq-pp-prod">Mã hàng</label>' +
      '<div class="hq-picker"><input type="text" class="hq-input" id="hq-pp-prod" autocomplete="off" value="' +
      esc(product.name || "") + '" placeholder="Gõ mã / tên để đổi sang mã khác"/>' +
      '<div class="hq-dropdown hq-hidden" id="hq-pp-prod-list"></div></div></div>' +
      '<div class="hq-pp-field"><label class="hq-label" for="hq-pp-qty">SL (' + esc(p.uom) + ") · trên đơn " +
      HQ.qty(p.old_qty) + '</label><input type="number" class="hq-input" id="hq-pp-qty" min="0" step="any" ' +
      'inputmode="decimal" value="' + p.form_qty + '"/></div>' +
      '<div class="hq-pp-field"><label class="hq-label" for="hq-pp-price">Giá mong muốn (sau VAT)</label>' +
      '<input type="number" class="hq-input" id="hq-pp-price" min="0" step="any" inputmode="decimal" value="' +
      (p.suggested_price || "") + '" placeholder="Không bắt buộc"/></div></div>' +
      (p.buyer_note ? '<div class="hq-muted">Thu mua: ' + esc(p.buyer_note) + "</div>" : "") +
      '<label class="hq-pp-check"><input type="checkbox" id="hq-pp-vendor"/> Cần NCC báo giá lại</label>' +
      '<div class="hq-pp-outcome" id="hq-pp-outcome"></div>' +
      '<label class="hq-sr-only" for="hq-pp-note">Ghi thêm</label>' +
      '<textarea class="hq-input hq-textarea" rows="3" maxlength="1000" id="hq-pp-note"></textarea>';
  }

  /** Đơn mua sẽ đổi thế nào khi thu mua duyệt — nói trước để sale không bất ngờ. */
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
      // Kho chưa nhận gì: cộng thẳng vào dòng cũ; đã nhận một phần: tách dòng mới (po_proposal_change._apply_to_order).
      return p.qty_received > EPS
        ? "Duyệt xong: dòng cũ giữ " + HQ.qty(p.old_qty) + " (kho đã nhận một phần), thêm dòng mới " +
          HQ.qty(qty - p.old_qty) + uom + " trên " + p.order + "."
        : "Duyệt xong: dòng trên " + p.order + " tăng " + HQ.qty(p.old_qty) + " → " + HQ.qty(qty) + uom + ".";
    }
    if (qty < p.old_qty - EPS) {
      return "Duyệt xong: dòng giảm " + HQ.qty(p.old_qty) + " → " + HQ.qty(qty) + uom + ", NCC được báo trên đơn.";
    }
    return "Giữ SL " + HQ.qty(p.old_qty) + uom + " — chỉ hỏi lại giá.";
  }

  function refresh() {
    var p = F.p;
    var product = F.product || {};
    var qty = Number(el("qty").value) || 0;
    var swapped = !!product.id && product.id !== p.product_id;
    var vendor = el("vendor");
    vendor.disabled = swapped;
    if (swapped) {
      vendor.checked = true;
    } else if (!F.touched) {
      // Chỉ giảm SL, không đòi giá mới: không cần NCC báo giá — gửi thẳng thu mua (NCC vẫn được báo khi duyệt).
      vendor.checked = !(qty < p.old_qty - EPS && !Number(el("price").value));
    }
    el("outcome").textContent = outcome(p, product, qty, swapped);
    el("send").textContent = vendor.checked ? "Gửi NCC báo giá" : "Gửi thu mua duyệt";
    el("note").placeholder = vendor.checked
      ? "Ghi thêm cho NCC (không bắt buộc) — lời nhắn đã soạn sẵn theo mã / SL / giá"
      : "Ghi chú cho thu mua (không bắt buộc)";
  }

  function searchProducts(term) {
    return HQ.rpc("/api/hoi-gia-ncc/products", { search: term }).then(function (r) { return r.products; });
  }

  function open(id) {
    var p = HQ.proposalById(id);
    F.p = p;
    F.product = p.form_product;
    F.touched = false;
    el("title").textContent = "Hỏi lại NCC — " + p.product + " (" + p.order + ")";
    el("body").innerHTML = body(p);
    HQ.bindPicker("hq-pp-prod", "hq-pp-prod-list", searchProducts, function (item) {
      return esc(item.product);
    }, function (item) {
      F.product = { id: item.product_id, name: item.product };
      refresh();
      return item.product;  // ô giữ tên mã vừa chọn
    });
    refresh();
    HQ.show("hq-pp-modal", true);
    el("qty").focus();
  }

  function close() {
    HQ.show("hq-pp-modal", false);
    F.p = null;
  }

  HQ.bindProposalFormEvents = function (panel) {
    var modal = HQ.$("hq-pp-modal");
    HQ.on(panel, "click", "[data-pp-form]", function (button) { open(+button.dataset.ppForm); });
    HQ.on(modal, "click", "[data-pp-close]", close);
    HQ.on(modal, "input", "#hq-pp-qty, #hq-pp-price", refresh);
    HQ.on(modal, "change", "#hq-pp-vendor", function () {
      F.touched = true;
      refresh();
    });
    HQ.on(modal, "click", "#hq-pp-send", function (button) {
      var vendor = el("vendor").checked;
      HQ.proposalSend("price_requote", {
        proposal_id: F.p.id, product_id: (F.product || {}).id || null, qty: Number(el("qty").value) || 0,
        price: Number(el("price").value) || 0, needs_vendor: vendor, note: el("note").value,
      }, button, vendor ? "Đã gửi NCC — chờ NCC báo giá" : "Đã gửi thu mua duyệt").then(function (ok) {
        if (ok) {
          close();
        }
      });
    });
  };
})(window.HlvQuote);
