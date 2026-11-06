/* Popup "Hỏi lại NCC" của đề xuất thu mua trả về (sale_price_proposal.js): sale chốt mã / SL / giá mong muốn (điền
   sẵn theo đề xuất của thu mua), VAT, chọn có cần NCC báo giá lại không rồi gửi (models/po_proposal_change.py). Đổi mã
   luôn phải hỏi NCC (mã mới chưa có giá); chỉ giảm SL / đổi VAT thì mặc định gửi thẳng thu mua (giữ giá chưa VAT) —
   sale bật lại được; SL 0 = không mua nữa, luôn gửi thẳng thu mua. Dòng "Duyệt xong: …" nói trước đơn mua sẽ đổi thế
   nào. Khung popup nằm sẵn trong trang (#hq-pp-modal, sale_page_templates.xml).
   Bộ ô SL / giá trước VAT / VAT / giá sau VAT (lineFields) dùng chung với popup "Xử lý tất cả" (sale_price_proposal_bulk.js):
   gõ giá ô nào thì ô kia tự tính theo VAT; nhãn mỗi ô ghi giá trị cũ trên đơn, ô khác với đơn thì tô màu. */
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

  function pct(rate) {
    return HQ.qty(rate || 0) + "%";
  }

  /** % của mã VAT: "kct" → 0, "" → null (giữ VAT trên đơn). */
  function vatRate(code) {
    return code ? (code === "kct" ? 0 : Number(code)) : null;
  }

  /** Giá chưa VAT (2 số lẻ) từ giá sau VAT, và giá sau VAT (tới đồng) từ giá chưa VAT. */
  function netOf(gross, rate) {
    return Math.round(gross / (1 + rate / 100) * 100) / 100;
  }

  function grossOf(net, rate) {
    return Math.round(net * (1 + rate / 100));
  }

  /** Ô VAT điền sẵn mức đang chốt / trên đơn (form_vat). Chỉ khi mức trên đơn không có trong danh sách (công ty không
      còn khai) mới có dòng "Giữ VAT trên đơn". */
  function vatSelect(p) {
    var known = (p.vat_options || []).some(function (o) { return o.code === p.form_vat; });
    return '<select class="hq-input" data-pp-vat>' +
      (known ? "" : '<option value="">Giữ VAT trên đơn (' + pct(p.tax_rate) + ")</option>") +
      (p.vat_options || []).map(function (o) {
        return '<option value="' + esc(o.code) + '"' + (o.code === p.form_vat ? " selected" : "") + ">" + esc(o.label) +
          "</option>";
      }).join("") + "</select>";
  }

  /** Bộ ô SL · giá trước VAT · VAT · giá sau VAT của một đề xuất (giá mong muốn điền sẵn theo gợi ý của thu mua).
      Nhãn vẽ ở refreshLine. data-tax: % VAT trên đơn — dùng khi ô VAT là "giữ VAT trên đơn". */
  function lineFields(p) {
    var rate = vatRate(p.form_vat);
    var gross = p.suggested_price || "";
    var net = gross ? HQ.qty(netOf(gross, rate === null ? p.tax_rate : rate)) : "";
    gross = gross ? HQ.qty(gross) : "";
    function field(name, input) {
      return '<label class="hq-pp-field"><span class="hq-label" data-pp-label="' + name + '"></span>' + input + "</label>";
    }
    // Ô tiền là ô chữ (không phải type=number) để hiện dấu chấm ngăn cách nghìn: "1.250.000".
    function money(attr, value) {
      return '<input type="text" class="hq-input" ' + attr + ' inputmode="decimal" value="' + value +
        '" placeholder="Không bắt buộc"/>';
    }
    return '<div class="hq-pp-line" data-pp-line data-basis="gross" data-tax="' + p.tax_rate + '">' +
      field("qty", '<input type="number" class="hq-input" data-pp-qty min="0" step="any" inputmode="decimal" ' +
        'title="0 = không mua nữa" value="' + p.form_qty + '"/>') +
      field("net", money("data-pp-net", net)) + field("vat", vatSelect(p)) + field("gross", money("data-pp-gross", gross)) +
      "</div>";
  }

  /** {qty (NaN khi trống — ô trống không phải "0 = không mua"), vat (mã), rate (null = giữ), price (sau VAT, 0 = không
      ghi)} đang nhập trong bộ ô. */
  function readLine(box) {
    var raw = box.querySelector("[data-pp-qty]").value.trim();
    var code = box.querySelector("[data-pp-vat]").value;
    return { qty: raw === "" ? NaN : Number(raw), vat: code, rate: vatRate(code),
             price: HQ.parseVnNumber(box.querySelector("[data-pp-gross]").value) || 0 };
  }

  /** Gõ giá một ô (source) hoặc đổi VAT (source null): tính lại ô giá còn lại theo ô sale gõ sau cùng. */
  function syncPrice(box, source) {
    if (source) {
      box.dataset.basis = source.hasAttribute("data-pp-net") ? "net" : "gross";
    }
    var rate = vatRate(box.querySelector("[data-pp-vat]").value);
    rate = rate === null ? Number(box.dataset.tax) : rate;
    var net = box.querySelector("[data-pp-net]");
    var gross = box.querySelector("[data-pp-gross]");
    if (box.dataset.basis === "net") {
      var netValue = HQ.parseVnNumber(net.value);
      gross.value = netValue === null ? "" : HQ.qty(grossOf(netValue, rate));
    } else {
      var grossValue = HQ.parseVnNumber(gross.value);
      net.value = grossValue === null ? "" : HQ.qty(netOf(grossValue, rate));
    }
  }

  function setField(box, name, changed, labelHtml) {
    var label = box.querySelector('[data-pp-label="' + name + '"]');
    label.innerHTML = labelHtml;
    label.parentNode.classList.toggle("is-changed", changed);
  }

  /** Nhãn + màu của bộ ô theo cái đang nhập: nhãn luôn kèm giá trị cũ trên đơn ("cũ 8%"), ô khác với đơn thì tô
      màu (CSS .is-changed). Trả readLine. */
  function refreshLine(box, p) {
    var v = readLine(box);
    var rate = v.rate === null ? p.tax_rate : v.rate;
    var priceChanged = v.price > 0 && Math.abs(v.price - p.old_price) >= 1;
    var old = function (text) {
      return ' <span class="hq-pp-old">cũ ' + text + "</span>";
    };
    setField(box, "qty", v.qty >= 0 && Math.abs(v.qty - p.old_qty) > EPS,
      "SL (" + esc(p.uom) + ")" + old(HQ.qty(p.old_qty)));
    setField(box, "net", priceChanged, "Giá trước VAT" + old(HQ.money(p.old_price / (1 + p.tax_rate / 100))));
    setField(box, "vat", Math.abs(rate - p.tax_rate) > EPS, "VAT" + old(pct(p.tax_rate)));
    setField(box, "gross", priceChanged, "Giá sau VAT" + old(HQ.money(p.old_price)));
    return v;
  }

  /** Gắn sự kiện cho mọi bộ ô trong root; onChange chạy sau mỗi lần sửa (sau khi đã tính lại ô giá kia). */
  function bindLine(root, onChange) {
    HQ.on(root, "input", "[data-pp-net], [data-pp-gross]", function (input) {
      syncPrice(input.closest("[data-pp-line]"), input);
      onChange();
    });
    HQ.on(root, "change", "[data-pp-vat]", function (select) {
      syncPrice(select.closest("[data-pp-line]"), null);
      onChange();
    });
    HQ.on(root, "input", "[data-pp-qty]", onChange);
    // Rời ô tiền: viết lại cho có dấu chấm ngăn cách (không làm khi đang gõ — con trỏ sẽ nhảy).
    HQ.on(root, "change", "[data-pp-net], [data-pp-gross]", function (input) {
      var value = HQ.parseVnNumber(input.value);
      if (value !== null) {
        input.value = HQ.qty(value);
      }
    });
  }

  /** Giá khác giá trên đơn (≥ 1 đồng) — 0 / trống là không ghi giá. */
  function priceChanged(p, price) {
    return price > 0 && Math.abs(price - p.old_price) >= 1;
  }

  /** Giá / VAT đổi thế nào khi duyệt. Hỏi NCC: theo giá + VAT NCC báo. Gửi thẳng: đổi giá thì áp giá sale nhập (cài
      đặt "apply" — po_price_proposal._send_direct), không thì giữ giá chưa VAT, giá sau VAT đổi theo VAT. */
  function vatOutcome(p, rate, vendor, price) {
    var vatChanged = rate !== null && Math.abs(rate - p.tax_rate) > EPS;
    var vatText = vatChanged ? " VAT " + pct(p.tax_rate) + " → " + pct(rate) : "";
    if (vendor) {
      return vatChanged ? vatText + " (điền sẵn cho NCC, dòng đơn lấy VAT NCC báo)." : "";
    }
    if (priceChanged(p, price)) {
      return " Giá sau VAT " + HQ.money(p.old_price) + " → " + HQ.money(price) + (vatChanged ? "," + vatText : "") + ".";
    }
    if (!vatChanged) {
      return "";
    }
    var unit = p.old_price / (1 + p.tax_rate / 100);
    return vatText + ": giữ giá chưa VAT, giá sau VAT " + HQ.money(p.old_price) + " → " +
      HQ.money(Math.round(unit * (1 + rate / 100))) + ".";
  }

  /** Đơn mua sẽ đổi thế nào khi thu mua duyệt — nói trước để sale không bất ngờ. */
  function outcome(p, product, qty, swapped) {
    var uom = " " + p.uom;
    if (!(qty >= 0)) {
      return "Nhập SL (0 = không mua nữa).";
    }
    if (qty < EPS) {
      if (swapped) {
        return "Đổi mã thì nhập SL mua mã mới.";
      }
      return p.qty_received > EPS ? "Kho đã nhận " + HQ.qty(p.qty_received) + uom + " — không bỏ dòng được."
        : "Duyệt xong: dòng " + p.product + " về SL 0 — không mua nữa, NCC được báo trên đơn.";
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
    return "Giữ SL " + HQ.qty(p.old_qty) + uom + ".";
  }

  /** Ô "Cần NCC báo giá lại" mặc định: {checked, disabled, priceLocked}. Đổi mã luôn hỏi NCC (mã mới chưa có giá); SL
      0 (không mua nữa) không có gì cho NCC báo; giá trong ô (mặc định là giá thu mua đề xuất) khác giá cũ mà cài đặt
      là "Đổi giá thì phải hỏi NCC" ("block") → bắt hỏi NCC, giữ nguyên giá đề xuất làm giá đề nghị NCC (priceLocked —
      muốn gửi thẳng thì xoá ô giá); chỉ giảm SL / đổi VAT mà không đổi giá thì gửi thẳng thu mua (NCC vẫn được báo khi
      duyệt); còn lại hỏi NCC. rate: % VAT chọn (null = giữ); price: giá sau VAT trong ô (0 = không ghi). */
  function vendorDefault(p, qty, rate, price, swapped) {
    if (swapped) {
      return { checked: true, disabled: true };
    }
    if (qty === 0) {
      return { checked: false, disabled: true };
    }
    var changed = priceChanged(p, price);
    if (changed && p.direct_price_mode === "block") {
      return { checked: true, disabled: true, priceLocked: true };
    }
    var vatChanged = rate !== null && Math.abs(rate - p.tax_rate) > EPS;
    var directOnly = (qty < p.old_qty - EPS || vatChanged) && qty <= p.old_qty + EPS;
    return { checked: !(directOnly && !changed), disabled: false };
  }

  // Cài đặt "Đổi giá thì phải hỏi NCC": nói vì sao không gửi thẳng được.
  var BLOCK_NOTE = " Đổi giá thì phải hỏi NCC (cài đặt) — muốn gửi thẳng thu mua thì xoá ô giá.";

  // Popup xử lý nhiều món (sale_price_proposal_bulk.js) dùng đúng các quy tắc này.
  HQ.ppRules = {
    outcome: outcome, vatOutcome: vatOutcome, vendorDefault: vendorDefault, lineFields: lineFields,
    refreshLine: refreshLine, bindLine: bindLine, BLOCK_NOTE: BLOCK_NOTE,
  };

  function body(p) {
    var product = p.form_product || {};
    return '<div class="hq-pp-field"><label class="hq-label" for="hq-pp-prod">Mã hàng</label>' +
      '<div class="hq-picker"><input type="text" class="hq-input" id="hq-pp-prod" autocomplete="off" value="' +
      esc(product.name || "") + '" placeholder="Gõ mã / tên để đổi sang mã khác"/>' +
      '<div class="hq-dropdown hq-hidden" id="hq-pp-prod-list"></div></div></div>' + lineFields(p) +
      (p.buyer_note ? '<div class="hq-muted">Thu mua: ' + esc(p.buyer_note) + "</div>" : "") +
      '<label class="hq-pp-check"><input type="checkbox" id="hq-pp-vendor"/> Cần NCC báo giá lại</label>' +
      '<div class="hq-pp-outcome" id="hq-pp-outcome"></div>' +
      '<label class="hq-sr-only" for="hq-pp-note">Ghi thêm</label>' +
      '<textarea class="hq-input hq-textarea" rows="3" maxlength="1000" id="hq-pp-note"></textarea>';
  }

  function line() {
    return el("body").querySelector("[data-pp-line]");
  }

  function refresh() {
    var p = F.p;
    var product = F.product || {};
    var v = refreshLine(line(), p);
    var swapped = !!product.id && product.id !== p.product_id;
    var vendor = el("vendor");
    var def = vendorDefault(p, v.qty, v.rate, v.price, swapped);
    vendor.disabled = def.disabled;
    if (def.disabled || !F.touched) {
      vendor.checked = def.checked;
    }
    el("outcome").textContent = outcome(p, product, v.qty, swapped) + vatOutcome(p, v.rate, vendor.checked, v.price) +
      (def.priceLocked ? BLOCK_NOTE : "");
    el("send").textContent = vendor.checked ? "Gửi NCC báo giá" : "Gửi thu mua duyệt";
    el("send").disabled = !(v.qty >= 0) || (v.qty < EPS && swapped);
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
    refresh();  // cũng mở khoá nút gửi — nút có sẵn trong trang, lần gửi trước đã khoá nó
    HQ.show("hq-pp-modal", true);
    line().querySelector("[data-pp-qty]").focus();
  }

  function close() {
    HQ.show("hq-pp-modal", false);
    F.p = null;
  }

  HQ.bindProposalFormEvents = function (panel) {
    var modal = HQ.$("hq-pp-modal");
    HQ.on(panel, "click", "[data-pp-form]", function (button) { open(+button.dataset.ppForm); });
    HQ.on(modal, "click", "[data-pp-close]", close);
    bindLine(modal, refresh);
    HQ.on(modal, "change", "#hq-pp-vendor", function () {
      F.touched = true;
      refresh();
    });
    HQ.on(modal, "click", "#hq-pp-send", function (button) {
      var vendor = el("vendor").checked;
      var v = readLine(line());
      HQ.proposalSend("price_requote", {
        proposal_id: F.p.id, product_id: (F.product || {}).id || null, qty: v.qty || 0, price: v.price,
        needs_vendor: vendor, note: el("note").value, vat: v.vat,
      }, button, vendor ? "Đã gửi NCC — chờ NCC báo giá" : "Đã gửi thu mua duyệt").then(function (ok) {
        if (ok) {
          close();
        }
      });
    });
  };
})(window.HlvQuote);
