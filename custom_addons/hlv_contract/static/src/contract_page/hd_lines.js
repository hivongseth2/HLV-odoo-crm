/* Bảng hàng hoá trên ngăn soạn: chọn sản phẩm hoặc gõ tự do, giá nhập được cả chưa VAT lẫn sau
   VAT (ô còn lại server tự tính), lấy hàng từ đơn bán hoặc báo giá MISA CRM (BG…), dán từ Excel.
   Dùng các hàm của ngăn soạn qua HD.form (hd_form.js). */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var S = HD.S;
  var esc = HD.esc;

  function rowHtml(line, index) {
    var input = function (field, value, cls) {
      return '<input type="text" class="hd-input hd-line-input ' + (cls || "") + '" data-line="' + index +
        '" data-line-field="' + field + '" value="' + esc(value) + '" autocomplete="off"/>';
    };
    var basis = line.price_basis === "excl" ? "excl" : "incl";
    return "<tr>" +
      '<td class="hd-center hd-muted">' + (index + 1) + "</td>" +
      '<td class="hd-line-name">' + input("product_name", line.product_name, "") +
      (line.product_id ? '<span class="hd-linked" title="Đã gắn sản phẩm trong danh mục">●</span>' : "") + "</td>" +
      "<td>" + input("uom", line.uom, "hd-center") + "</td>" +
      "<td>" + input("quantity", HD.qty(line.quantity), "hd-right") + "</td>" +
      "<td>" + input("price_excl", HD.money(line.price_excl), "hd-right" + (basis === "excl" ? " is-basis" : "")) + "</td>" +
      "<td>" + input("price_incl", HD.money(line.price_incl), "hd-right" + (basis === "incl" ? " is-basis" : "")) + "</td>" +
      '<td class="hd-right hd-num"><b data-total-incl="' + index + '">' + HD.money(line.subtotal_incl) + "</b>" +
      '<div class="hd-sub-price" data-total-excl="' + index + '">chưa VAT ' + HD.money(line.subtotal) + "</div></td>" +
      '<td class="hd-center"><button type="button" class="hd-icon-btn" data-remove-line="' + index +
      '" title="Xoá dòng" aria-label="Xoá dòng ' + (index + 1) + '">✕</button></td></tr>';
  }

  /** HTML phần Hàng hoá của ngăn soạn ("" nếu mẫu không có bảng hàng). */
  HD.linesHtml = function () {
    var tpl = HD.form.template();
    if (!tpl.has_lines) {
      return "";
    }
    var c = S.contract || {};
    var goodsVars = tpl.variables.filter(function (v) { return v.section === "goods"; });
    return '<section class="hd-step"><div class="hd-step-head"><h3 class="hd-h3">Hàng hoá</h3>' +
      '<span class="hd-muted hd-small">Gõ mã/tên để chọn sản phẩm, hoặc gõ tự do · nhập giá chưa VAT hoặc sau VAT, ô kia tự tính</span>' +
      '<div class="hd-push d-flex gap-2"><button type="button" class="hd-btn hd-btn-mini" id="hd-paste-toggle">Dán từ Excel</button>' +
      '<button type="button" class="hd-btn hd-btn-mini" id="hd-add-line">+ Thêm dòng</button></div></div>' +
      (goodsVars.length ? '<div class="hd-grid">' + goodsVars.map(HD.form.fieldHtml).join("") + "</div>" : "") +
      '<div class="hd-picker hd-order-picker"><input type="search" id="hd-order-search" class="hd-input w-100" autocomplete="off" ' +
      'placeholder="Lấy hàng từ báo giá CRM (BG…) hoặc đơn bán (S…, DH…, tên khách)"/>' +
      '<div id="hd-order-results" class="hd-dropdown hd-hidden"></div></div>' +
      '<div id="hd-paste-box" class="hd-paste hd-hidden">' +
      '<textarea id="hd-paste-text" rows="4" class="hd-input hd-textarea w-100" ' +
      'placeholder="Copy các cột Tên hàng | ĐVT | Số lượng | Đơn giá sau VAT từ Excel rồi dán vào đây"></textarea>' +
      '<div class="d-flex gap-2 mt-2"><button type="button" class="hd-btn hd-btn-primary hd-btn-mini" id="hd-paste-run">Thêm vào bảng</button>' +
      '<button type="button" class="hd-btn hd-btn-mini" id="hd-paste-cancel">Đóng</button></div></div>' +
      '<div class="hd-table-wrap hd-lines-wrap"><table class="hd-lines"><thead><tr>' +
      '<th class="hd-col-stt">STT</th><th>Tên hàng</th><th class="hd-col-uom">ĐVT</th>' +
      '<th class="hd-col-qty hd-right">Số lượng</th><th class="hd-col-price hd-right">Đơn giá chưa VAT</th>' +
      '<th class="hd-col-price hd-right">Đơn giá sau VAT</th>' +
      '<th class="hd-col-price hd-right">Thành tiền sau VAT</th><th class="hd-col-del"></th></tr></thead>' +
      '<tbody id="hd-lines-body">' + S.lines.map(rowHtml).join("") + "</tbody></table></div>" +
      '<div class="hd-totals">' +
      '<div class="hd-total-grand"><span>Tổng giá trị (sau VAT)</span><b class="hd-num" id="hd-t-total">' + HD.money(c.amount_total) + "</b></div>" +
      '<div class="hd-total-words" id="hd-t-words">' + esc(c.amount_words || "") + "</div>" +
      '<div class="hd-total-sub"><span>Tiền hàng chưa VAT</span><span class="hd-num" id="hd-t-untaxed">' + HD.money(c.amount_untaxed) + "</span></div>" +
      '<div class="hd-total-sub"><span>Thuế VAT <input type="text" class="hd-input hd-vat-input" id="hd-vat" value="' +
      esc(HD.qty(S.form.vat_rate)) + '" aria-label="Thuế suất VAT"/> %</span><span class="hd-num" id="hd-t-vat">' + HD.money(c.amount_vat) + "</span></div>" +
      "</div></section>";
  };

  /* ---------------------------------------------------------- tổng tiền (tính ở server) */

  function setText(selector, text) {
    var el = document.querySelector(selector);
    if (el) {
      el.textContent = text;
    }
  }

  /** Cập nhật ô giá không đang gõ (ô đang gõ giữ nguyên chữ người dùng). */
  function setPriceInput(index, field, value) {
    var input = document.querySelector('[data-line="' + index + '"][data-line-field="' + field + '"]');
    if (input && document.activeElement !== input) {
      input.value = HD.money(value);
    }
  }

  var refreshTotals = HD.debounce(function () {
    HD.api("totals", { lines: S.lines, vat_rate: S.form.vat_rate }).then(function (t) {
      t.subtotals.forEach(function (value, index) {
        var line = S.lines[index];
        if (!line) {
          return;
        }
        Object.assign(line, {
          subtotal: value,
          subtotal_incl: t.subtotals_incl[index],
          price_excl: t.prices_excl[index],
          price_incl: t.prices_incl[index],
        });
        setPriceInput(index, "price_excl", line.price_excl);
        setPriceInput(index, "price_incl", line.price_incl);
        setText('[data-total-incl="' + index + '"]', HD.money(line.subtotal_incl));
        setText('[data-total-excl="' + index + '"]', "chưa VAT " + HD.money(value));
      });
      setText("#hd-t-untaxed", HD.money(t.untaxed));
      setText("#hd-t-vat", HD.money(t.vat));
      setText("#hd-t-total", HD.money(t.total));
      setText("#hd-t-words", t.words);
    }).catch(HD.fail);
  }, 300);

  HD.refreshTotals = refreshTotals;

  function redraw() {
    var body = HD.$("hd-lines-body");
    if (body) {
      body.innerHTML = S.lines.map(rowHtml).join("");
      refreshTotals();
    }
  }

  function addLines(lines) {
    S.lines = S.lines.concat(lines.map(function (l) {
      return Object.assign({
        product_id: false, uom: "", quantity: 1, price_basis: "incl", price_incl: 0, price_excl: 0, subtotal: 0, subtotal_incl: 0,
      }, l);
    }));
    redraw();
    HD.form.markDirty(true);
  }

  /* ---------------------------------------------------------- chọn sản phẩm */

  var searchProducts = HD.debounce(function (input, index) {
    var term = input.value.trim();
    if (term.length < 2) {
      HD.suggest.close();
      return;
    }
    HD.api("products", { search: term, vat_rate: S.form.vat_rate }).then(function (items) {
      HD.suggest.open(input, items, function (p) {
        return "<span>" + esc(p.label) + '</span> <span class="hd-muted">' + esc(p.uom) + " · " + HD.money(p.price_incl) + "</span>";
      }, function (item) {
        Object.assign(S.lines[index], {
          product_id: item.id, product_name: item.name, uom: item.uom,
          price_basis: "excl", price_excl: item.price_excl, price_incl: item.price_incl,
        });
        redraw();
        HD.form.markDirty(true);
        var qty = document.querySelector('[data-line="' + index + '"][data-line-field="quantity"]');
        if (qty) {
          qty.focus();
          qty.select();
        }
      }, "Chọn sản phẩm, hoặc cứ gõ tiếp để dùng tên tự do");
    }).catch(HD.fail);
  }, 250);

  /* ---------------------------------------------------------- lấy hàng: báo giá CRM / đơn bán */

  function isQuoteCode(term) {
    return /^BG/i.test((term || "").trim());
  }

  function fetchSources(term) {
    if (!term) {
      return Promise.resolve([]);
    }
    if (isQuoteCode(term)) {
      return HD.api("crm_quotes", { search: term }).then(function (rows) {
        return rows.map(function (q) { return Object.assign({ kind: "quote" }, q); });
      });
    }
    return HD.api("sale_orders", { search: term }).then(function (rows) {
      return rows.map(function (o) { return Object.assign({ kind: "order" }, o); });
    });
  }

  function sourceHtml(item) {
    if (item.kind === "quote") {
      return '<span class="hd-tag hd-tag-mine">Báo giá CRM</span> <span class="hd-strong">' + esc(item.code) + "</span> " +
        esc(item.account) + ' <span class="hd-muted">' + HD.money(item.total) + " · " + esc(item.stage) + "</span>";
    }
    return '<span class="hd-tag hd-tag-soft">Đơn bán</span> <span class="hd-strong">' + esc(item.label) + "</span> " +
      esc(item.partner) + ' <span class="hd-muted">' + HD.money(item.amount_total) + "</span>";
  }

  function applySource(item, result) {
    var label = item.kind === "quote" ? item.code : item.label;
    if (S.lines.length && window.confirm("Thay các dòng hàng đang có bằng hàng của " + label + "?\n(Huỷ = thêm vào cuối)")) {
      S.lines = [];
    }
    HD.form.collectForm();
    // Báo giá CRM có thuế suất riêng: dùng luôn để giá chưa VAT giữ đúng như trên báo giá
    if (result.vat_rate != null && result.vat_rate !== S.form.vat_rate) {
      S.form.vat_rate = result.vat_rate;
      HD.toast("Thuế VAT theo " + label + ": " + HD.qty(result.vat_rate) + "%");
    }
    S.lines = S.lines.concat(result.lines.map(function (l) {
      return Object.assign({ price_basis: "excl", subtotal: 0, subtotal_incl: 0 }, l);
    }));
    if (item.kind === "quote") {
      S.form.quote_code = item.code;   // số báo giá: in ra (So_Bao_Gia) và dùng được trong khuôn số
    }
    // Chưa có khách thì lấy khách của báo giá / đơn; ô bên mua đã gõ tay thì giữ nguyên
    if (!S.form.partner_id) {
      S.form.partner_id = result.partner_id || false;
      S.form.partner_label = result.partner_label || "";
      HD.form.fillVariables(result.partner_values || {}, false);
    }
    HD.form.markDirty(true);
    HD.form.render();
    HD.toast("Đã lấy " + result.lines.length + " dòng từ " + label);
  }

  function bindSourcePicker() {
    var input = HD.$("hd-order-search");
    if (!input) {
      return;
    }
    HD.bindPicker(input, HD.$("hd-order-results"), fetchSources, sourceHtml, function (item) {
      var request = item.kind === "quote"
        ? HD.api("crm_quote_lines", { quote_id: item.id, account_id: item.account_id, account_name: item.account, vat_rate: S.form.vat_rate })
        : HD.api("sale_order_lines", { order_id: item.id, vat_rate: S.form.vat_rate });
      request.then(function (result) { applySource(item, result); }).catch(HD.fail);
      input.value = "";
    });
  }

  HD.bindLines = bindSourcePicker;

  /* ---------------------------------------------------------- sự kiện */

  HD.initLines = function () {
    var panel = HD.$("hd-drawer-panel");
    HD.on(panel, "input", "#hd-vat", function (el) {
      S.form.vat_rate = HD.parseNumber(el.value);
      HD.form.markDirty(true);
      refreshTotals();
    });
    HD.on(panel, "input", "[data-line-field]", function (el) {
      var index = +el.dataset.line;
      var line = S.lines[index];
      var field = el.dataset.lineField;
      HD.form.markDirty(true);
      if (field === "product_name") {
        line.product_name = el.value;
        line.product_id = false;   // gõ tay thì bỏ gắn sản phẩm cũ
        searchProducts(el, index);
        return;
      }
      if (field === "uom") {
        line.uom = el.value;
        return;
      }
      line[field] = HD.parseNumber(el.value);
      if (field === "price_excl" || field === "price_incl") {
        // Ô vừa gõ là giá gốc; ô còn lại server tính theo thuế suất
        line.price_basis = field === "price_excl" ? "excl" : "incl";
        el.closest("tr").querySelectorAll('[data-line-field^="price_"]').forEach(function (other) {
          other.classList.toggle("is-basis", other === el);
        });
      }
      refreshTotals();
    });
    // Gõ xong định dạng lại "4382640" -> "4.382.640" cho dễ soát
    HD.on(panel, "focusout", '[data-line-field^="price_"], [data-line-field="quantity"]', function (el) {
      var value = S.lines[+el.dataset.line][el.dataset.lineField];
      el.value = el.dataset.lineField === "quantity" ? HD.qty(value) : HD.money(value);
    });
    HD.on(panel, "click", "[data-remove-line]", function (el) {
      S.lines.splice(+el.dataset.removeLine, 1);
      redraw();
      HD.form.markDirty(true);
    });
    HD.on(panel, "click", "#hd-add-line", function () {
      addLines([{ product_name: "" }]);
      var inputs = panel.querySelectorAll('[data-line-field="product_name"]');
      inputs[inputs.length - 1].focus();
    });
    HD.on(panel, "click", "#hd-paste-toggle", function () { HD.show("hd-paste-box", true); HD.$("hd-paste-text").focus(); });
    HD.on(panel, "click", "#hd-paste-cancel", function () { HD.show("hd-paste-box", false); });
    HD.on(panel, "click", "#hd-paste-run", function () {
      var lines = HD.parsePastedLines(HD.$("hd-paste-text").value);
      if (!lines.length) {
        HD.toast("Không nhận ra dòng hàng nào", "error");
        return;
      }
      addLines(lines);
      HD.$("hd-paste-text").value = "";
      HD.show("hd-paste-box", false);
      HD.toast("Đã thêm " + lines.length + " dòng");
    });
  };
})(window.HlvContract);
