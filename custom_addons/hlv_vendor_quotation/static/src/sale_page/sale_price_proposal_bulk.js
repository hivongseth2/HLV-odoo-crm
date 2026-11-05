/* Popup "Xử lý tất cả" các món thu mua trả về của phiếu (sale_price_proposal.js): mỗi món một hàng, điền sẵn như popup
   một món (sale_price_proposal_form.js — dùng chung quy tắc HQ.ppRules): NCC đã báo mới → gửi thu mua duyệt; chưa báo
   → hỏi lại NCC / gửi thẳng thu mua (SL, giá mong muốn, VAT, có cần NCC báo giá lại); NCC giữ nguyên giá → giữ giá.
   Sale sửa hàng nào cần rồi bấm gửi MỘT lần (API price_bulk — một món lỗi thì không món nào được ghi). Đổi sang mã khác
   mã thu mua đề xuất thì dùng nút "Hỏi lại NCC" trên ô (popup một món có ô tìm mã). Khung popup: #hq-ppb-modal. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var EPS = 1e-9;
  var SKIP = "skip";
  // Đề xuất trong popup, theo id.
  var B = { byId: {} };

  function el(id) {
    return HQ.$("hq-ppb-" + id);
  }

  /** Việc mặc định của một món: NCC đã báo giá mới → gửi duyệt; NCC giữ nguyên giá → giữ giá; còn lại hỏi lại NCC. */
  function defaultAction(p) {
    if (p.can_submit) {
      return "submit";
    }
    if (p.vendor_kept_price && p.can_keep) {
      return "keep";
    }
    return p.can_requote ? "requote" : p.can_keep ? "keep" : SKIP;
  }

  function actionSelect(p) {
    var options = [];
    if (p.can_submit) {
      options.push(["submit", "Gửi thu mua duyệt — NCC báo " + HQ.money(p.vendor_price)]);
    }
    if (p.can_requote) {
      options.push(["requote", p.can_submit ? "Hỏi lại NCC lần nữa" : "Hỏi lại NCC / gửi thẳng thu mua"]);
    }
    if (p.can_keep) {
      options.push(["keep", "NCC giữ giá — đơn giữ nguyên"]);
    }
    options.push([SKIP, "Để sau"]);
    var chosen = defaultAction(p);
    return '<select class="hq-input" data-ppb-action>' + options.map(function (o) {
      return '<option value="' + o[0] + '"' + (o[0] === chosen ? " selected" : "") + ">" + esc(o[1]) + "</option>";
    }).join("") + "</select>";
  }

  /** Ô nhập phần "hỏi lại NCC" của một món (ẩn khi chọn việc khác). */
  function requoteFields(p) {
    var product = p.form_product || {};
    var swapped = !!product.id && product.id !== p.product_id;
    return '<div class="hq-ppb-requote" data-ppb-requote>' +
      (swapped ? '<div class="hq-muted">Đổi sang mã ' + esc(product.name) + "</div>" : "") +
      '<label class="hq-pp-field"><span class="hq-label">SL (' + esc(p.uom) + ", 0 = không mua) · trên đơn " +
      HQ.qty(p.old_qty) + '</span><input type="number" class="hq-input" data-ppb-qty min="0" step="any" ' +
      'inputmode="decimal" value="' + p.form_qty + '"/></label>' +
      '<label class="hq-pp-field"><span class="hq-label">Giá mong muốn (sau VAT)</span><input type="number" ' +
      'class="hq-input" data-ppb-price min="0" step="any" inputmode="decimal" value="' + (p.suggested_price || "") +
      '" placeholder="Không bắt buộc"/></label>' +
      '<label class="hq-pp-field"><span class="hq-label">VAT</span>' +
      HQ.ppRules.vatSelect(p, "hq-ppb-vat-" + p.id).replace("<select ", "<select data-ppb-vat ") + "</label>" +
      '<label class="hq-pp-check hq-ppb-wide"><input type="checkbox" data-ppb-vendor/> Cần NCC báo giá lại</label>' +
      '<div class="hq-pp-outcome hq-ppb-wide" data-ppb-outcome></div></div>';
  }

  /** Một món = một thẻ: số thứ tự + ảnh + tên đậm ở đầu để nhìn là biết thẻ nào của món nào. */
  function row(p, index) {
    var wish = [p.buyer_note ? "Lý do: " + esc(p.buyer_note) : "",
      p.vendor_price && !p.vendor_kept_price ? "NCC báo lại <b>" + HQ.money(p.vendor_price) + "</b>" : "",
      p.vendor_kept_price ? "NCC giữ nguyên giá" : ""].filter(Boolean).join(" · ");
    return '<div class="hq-ppb-row" data-ppb-id="' + p.id + '">' +
      '<img class="hq-ppb-img" src="' + esc(p.image) + '" alt="" loading="lazy"/>' +
      '<div class="hq-ppb-main"><div class="hq-ppb-head"><span class="hq-ppb-no">' + (index + 1) + "</span><b>" +
      esc(p.product) + "</b>" + HQ.docChip(p.order) + "</div>" +
      '<div class="hq-muted">Trên đơn ' + HQ.money(p.old_price) + " sau VAT · " + HQ.qty(p.old_qty) + " " + esc(p.uom) +
      (wish ? " · " + wish : "") + "</div>" +
      actionSelect(p) + (p.can_requote ? requoteFields(p) : "") +
      '<input type="text" class="hq-input" data-ppb-note maxlength="1000" placeholder="Ghi chú (không bắt buộc)"/>' +
      "</div></div>";
  }

  /** {qty, rate, price, swapped} đang nhập ở phần hỏi lại của một hàng. */
  function readRequote(box, p) {
    var raw = box.querySelector("[data-ppb-qty]").value.trim();
    var product = p.form_product || {};
    return {
      qty: raw === "" ? NaN : Number(raw),  // ô trống không phải "0 = không mua"
      rate: HQ.ppRules.vatRate(box.querySelector("[data-ppb-vat]").value),
      price: Number(box.querySelector("[data-ppb-price]").value) || 0,
      swapped: !!product.id && product.id !== p.product_id,
    };
  }

  /** Vẽ lại một hàng sau khi sửa: ẩn / hiện phần hỏi lại, ô "Cần NCC báo giá lại" (giữ lựa chọn sale đã bấm), câu
      "Duyệt xong: …". Trả false khi hàng chưa gửi được (SL trống / đổi mã mà SL 0). */
  function refreshRow(rowEl) {
    var p = B.byId[rowEl.dataset.ppbId];
    var action = rowEl.querySelector("[data-ppb-action]").value;
    var box = rowEl.querySelector("[data-ppb-requote]");
    rowEl.classList.toggle("is-skip", action === SKIP);
    if (!box) {
      return true;
    }
    box.classList.toggle("hq-hidden", action !== "requote");
    if (action !== "requote") {
      return true;
    }
    var v = readRequote(box, p);
    var vendor = box.querySelector("[data-ppb-vendor]");
    var def = HQ.ppRules.vendorDefault(p, v.qty, v.rate, v.price, v.swapped);
    vendor.disabled = def.disabled;
    if (def.disabled || !vendor.dataset.touched) {
      vendor.checked = def.checked;
    }
    box.querySelector("[data-ppb-outcome]").textContent = HQ.ppRules.outcome(p, p.form_product || {}, v.qty, v.swapped) +
      HQ.ppRules.vatOutcome(p, v.rate, vendor.checked) + (vendor.checked ? " Hỏi NCC." : " Gửi thẳng thu mua.");
    return v.qty >= 0 && !(v.qty < EPS && v.swapped);
  }

  function refreshAll() {
    var rows = Array.prototype.slice.call(el("body").querySelectorAll("[data-ppb-id]"));
    var ok = rows.map(refreshRow).every(Boolean);
    var count = rows.filter(function (r) { return r.querySelector("[data-ppb-action]").value !== SKIP; }).length;
    el("send").disabled = !ok || !count;
    el("send").textContent = "Gửi " + count + " món";
  }

  function item(rowEl) {
    var p = B.byId[rowEl.dataset.ppbId];
    var action = rowEl.querySelector("[data-ppb-action]").value;
    var data = { proposal_id: p.id, action: action, note: rowEl.querySelector("[data-ppb-note]").value };
    if (action === "requote") {
      var box = rowEl.querySelector("[data-ppb-requote]");
      var v = readRequote(box, p);
      data.qty = v.qty;
      data.price = v.price;
      data.vat = box.querySelector("[data-ppb-vat]").value;
      data.product_id = (p.form_product || {}).id || null;
      data.needs_vendor = box.querySelector("[data-ppb-vendor]").checked;
    }
    return data;
  }

  function open(list) {
    B.byId = {};
    list.forEach(function (p) { B.byId[p.id] = p; });
    el("title").textContent = "Thu mua trả về " + list.length + " món";
    el("body").innerHTML = list.map(row).join("");
    refreshAll();
    HQ.show("hq-ppb-modal", true);
  }

  function close() {
    HQ.show("hq-ppb-modal", false);
    B.byId = {};
  }

  HQ.bindProposalBulkEvents = function (panel) {
    var modal = HQ.$("hq-ppb-modal");
    HQ.on(panel, "click", "[data-ppb-open]", function () {
      open(HQ.proposalTodo(HQ.addVendorDetail || {}));
    });
    HQ.on(modal, "click", "[data-ppb-close]", close);
    HQ.on(modal, "input", "[data-ppb-qty], [data-ppb-price]", refreshAll);
    HQ.on(modal, "change", "[data-ppb-action], [data-ppb-vat]", refreshAll);
    HQ.on(modal, "change", "[data-ppb-vendor]", function (input) {
      input.dataset.touched = "1";
      refreshAll();
    });
    HQ.on(modal, "click", "#hq-ppb-send", function (button) {
      var items = Array.prototype.slice.call(el("body").querySelectorAll("[data-ppb-id]")).filter(function (r) {
        return r.querySelector("[data-ppb-action]").value !== SKIP;
      }).map(item);
      HQ.proposalSend("price_bulk", { items: items }, button, "Đã gửi " + items.length + " món").then(function (ok) {
        if (ok) {
          close();
        }
      });
    });
  };
})(window.HlvQuote);
