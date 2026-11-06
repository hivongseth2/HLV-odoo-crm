/* Popup "Xử lý tất cả" các món thu mua trả về của phiếu (sale_price_proposal.js): mỗi món một hàng, điền sẵn như popup
   một món (sale_price_proposal_form.js — dùng chung quy tắc HQ.ppRules): NCC đã báo mới → gửi thu mua duyệt; chưa báo
   → "Hỏi lại NCC" hoặc "Gửi thẳng thu mua duyệt" (không hỏi NCC) với SL, giá trước / sau VAT, VAT — chọn sẵn theo
   ppRules.vendorDefault và tự đổi theo cái sale sửa cho tới khi sale tự chọn (từng món, hoặc ô "Tất cả các món" ở
   đầu popup); NCC giữ nguyên giá → giữ giá.
   Sale sửa hàng nào cần rồi bấm gửi MỘT lần (API price_bulk — một món lỗi thì không món nào được ghi). Đổi sang mã khác
   mã thu mua đề xuất thì dùng nút "Hỏi lại NCC" trên ô (popup một món có ô tìm mã). Khung popup: #hq-ppb-modal. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var EPS = 1e-9;
  var SKIP = "skip";
  // Hai việc của món chưa có giá NCC: hỏi lại NCC / gửi thẳng thu mua — cùng API "requote", khác needs_vendor.
  var REQUOTE = { vendor: true, direct: true };
  // Đề xuất trong popup, theo id.
  var B = { byId: {} };

  function el(id) {
    return HQ.$("hq-ppb-" + id);
  }

  /** Việc mặc định của một món: NCC đã báo giá mới → gửi duyệt; NCC giữ nguyên giá → giữ giá; còn lại hỏi lại NCC
      (refreshRow đổi sang gửi thẳng thu mua theo ppRules.vendorDefault). */
  function defaultAction(p) {
    if (p.can_submit) {
      return "submit";
    }
    if (p.vendor_kept_price && p.can_keep) {
      return "keep";
    }
    return p.can_requote ? "vendor" : p.can_keep ? "keep" : SKIP;
  }

  function actionSelect(p) {
    var options = [];
    if (p.can_submit) {
      options.push(["submit", "Gửi thu mua duyệt — NCC báo " + HQ.money(p.vendor_price)]);
    }
    if (p.can_requote) {
      options.push(["vendor", p.can_submit ? "Hỏi lại NCC lần nữa" : "Hỏi lại NCC"]);
      options.push(["direct", "Gửi thẳng thu mua duyệt (không hỏi NCC)"]);
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
      (swapped ? '<div class="hq-pp-diff">Đổi sang mã ' + esc(product.name) + "</div>" : "") +
      HQ.ppRules.lineFields(p) + '<div class="hq-pp-outcome" data-ppb-outcome></div></div>';
  }

  /** Một món = một thẻ: số thứ tự + ảnh + tên đậm ở đầu để nhìn là biết thẻ nào của món nào. */
  function row(p, index) {
    // Giá / VAT / SL cũ đã nằm ở nhãn các ô bên dưới — dòng đầu chỉ còn lý do của thu mua (+ NCC đã báo gì).
    var wish = [p.buyer_note ? "Lý do: " + esc(p.buyer_note) : "",
      p.vendor_price && !p.vendor_kept_price ? "NCC báo lại <b>" + HQ.money(p.vendor_price) + "</b>" : "",
      p.vendor_kept_price ? "NCC giữ nguyên giá" : ""].filter(Boolean).join(" · ");
    return '<div class="hq-ppb-row" data-ppb-id="' + p.id + '">' +
      '<img class="hq-ppb-img" src="' + esc(p.image) + '" alt="" loading="lazy"/>' +
      '<div class="hq-ppb-main"><div class="hq-ppb-head"><span class="hq-ppb-no">' + (index + 1) + "</span><b>" +
      esc(p.product) + "</b>" + HQ.docChip(p.order) + "</div>" +
      (wish ? '<div class="hq-muted">' + wish + "</div>" : "") +
      actionSelect(p) + (p.can_requote ? requoteFields(p) : "") +
      '<input type="text" class="hq-input" data-ppb-note maxlength="1000" placeholder="Ghi chú (không bắt buộc)"/>' +
      "</div></div>";
  }

  /** Món đổi sang mã thu mua đề xuất. */
  function swapped(p) {
    var product = p.form_product || {};
    return !!product.id && product.id !== p.product_id;
  }

  /** Vẽ lại một hàng sau khi sửa: ẩn / hiện phần hỏi lại, chọn "Hỏi lại NCC" / "Gửi thẳng thu mua" theo
      ppRules.vendorDefault (đổi mã luôn hỏi NCC, SL 0 luôn gửi thẳng; còn lại chỉ tự đổi khi sale chưa tự chọn việc),
      câu "Duyệt xong: …". Trả false khi hàng chưa gửi được (SL trống / đổi mã mà SL 0). */
  function refreshRow(rowEl) {
    var p = B.byId[rowEl.dataset.ppbId];
    var select = rowEl.querySelector("[data-ppb-action]");
    var box = rowEl.querySelector("[data-ppb-requote]");
    rowEl.classList.toggle("is-skip", select.value === SKIP);
    if (!box) {
      return true;
    }
    box.classList.toggle("hq-hidden", !REQUOTE[select.value]);
    if (!REQUOTE[select.value]) {
      return true;
    }
    var v = HQ.ppRules.refreshLine(box.querySelector("[data-pp-line]"), p);
    var swap = swapped(p);
    var def = HQ.ppRules.vendorDefault(p, v.qty, v.rate, v.price, swap);
    if (def.disabled || !select.dataset.touched) {
      select.value = def.checked ? "vendor" : "direct";
    }
    rowEl.dataset.priceLocked = def.priceLocked ? "1" : "";
    // Bắt buộc hỏi NCC (đổi mã / đổi giá mà cài đặt cấm gửi thẳng) hoặc bắt buộc gửi thẳng (SL 0): khoá lựa chọn kia.
    select.querySelector('option[value="direct"]').disabled = def.disabled && def.checked;
    select.querySelector('option[value="vendor"]').disabled = def.disabled && !def.checked;
    box.querySelector("[data-ppb-outcome]").textContent = HQ.ppRules.outcome(p, p.form_product || {}, v.qty, swap) +
      HQ.ppRules.vatOutcome(p, v.rate, select.value === "vendor", v.price) +
      (def.priceLocked ? HQ.ppRules.BLOCK_NOTE : "");
    return v.qty >= 0 && !(v.qty < EPS && swap);
  }

  function refreshAll() {
    var rows = Array.prototype.slice.call(el("body").querySelectorAll("[data-ppb-id]"));
    var ok = rows.map(refreshRow).every(Boolean);
    var count = rows.filter(function (r) { return r.querySelector("[data-ppb-action]").value !== SKIP; }).length;
    el("send").disabled = !ok || !count;
    // Chọn chung "Gửi thẳng" mà có món đổi giá bị cài đặt bắt hỏi NCC: nói rõ để khỏi tưởng đã gửi thẳng hết.
    var all = el("body").querySelector("[data-ppb-all]");
    var locked = rows.filter(function (r) { return r.dataset.priceLocked; }).length;
    var note = el("body").querySelector("[data-ppb-all-note]");
    if (note) {
      note.textContent = all.value === "direct" && locked
        ? locked + " món có giá khác giá cũ nên vẫn hỏi lại NCC (cài đặt: đổi giá thì phải hỏi NCC)." : "";
    }
    el("send").textContent = "Gửi " + count + " món";
  }

  function item(rowEl) {
    var p = B.byId[rowEl.dataset.ppbId];
    var action = rowEl.querySelector("[data-ppb-action]").value;
    var data = { proposal_id: p.id, action: action, note: rowEl.querySelector("[data-ppb-note]").value };
    if (REQUOTE[action]) {
      data.action = "requote";
      var box = rowEl.querySelector("[data-ppb-requote]");
      var v = HQ.ppRules.refreshLine(box.querySelector("[data-pp-line]"), p);
      data.qty = v.qty;
      data.price = v.price;
      data.vat = v.vat;
      data.product_id = (p.form_product || {}).id || null;
      data.needs_vendor = action === "vendor";
    }
    return data;
  }

  /** Ô chọn chung đầu popup — chỉ khi có món hỏi lại / gửi thẳng được. */
  function allSelect(list) {
    if (!list.some(function (p) { return p.can_requote; })) {
      return "";
    }
    return '<label class="hq-ppb-all"><span>Tất cả các món</span><select class="hq-input" data-ppb-all>' +
      '<option value="">Chọn từng món</option><option value="vendor">Hỏi lại NCC</option>' +
      '<option value="direct">Gửi thẳng thu mua duyệt (không hỏi NCC)</option></select>' +
      '<span class="hq-pp-diff" data-ppb-all-note></span></label>';
  }

  /** Áp việc chung cho mọi món có việc đó; món bắt buộc khác (đổi mã → hỏi NCC, SL 0 → gửi thẳng) refreshRow sửa lại. */
  function applyAll(value) {
    if (!value) {
      return;
    }
    el("body").querySelectorAll("[data-ppb-action]").forEach(function (select) {
      if (select.querySelector('option[value="' + value + '"]')) {
        select.value = value;
        select.dataset.touched = "1";
      }
    });
    refreshAll();
  }

  function open(list) {
    B.byId = {};
    list.forEach(function (p) { B.byId[p.id] = p; });
    el("title").textContent = "Thu mua trả về " + list.length + " món";
    el("body").innerHTML = allSelect(list) + list.map(row).join("");
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
    HQ.ppRules.bindLine(modal, refreshAll);
    HQ.on(modal, "change", "[data-ppb-all]", function (select) { applyAll(select.value); });
    HQ.on(modal, "change", "[data-ppb-action]", function (select) {
      select.dataset.touched = "1";  // sale tự chọn việc — thôi tự đổi hỏi NCC / gửi thẳng
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
