/* Ngăn soạn một hợp đồng: ô nhập dựng theo bộ biến của mẫu đang chọn, bảng hàng (chọn từ
   sản phẩm / đơn bán hoặc gõ tay), chuyển trạng thái, và hộp Xem nhanh. */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var S = HD.S;
  var esc = HD.esc;
  var SECTION_ORDER = ["general", "buyer", "terms", "other"];

  function template() {
    var id = S.form.template_id;
    return (S.config.templates || []).filter(function (t) { return t.id === id; })[0] ||
      { id: id, variables: [], has_lines: false, name: "" };
  }

  function editable() {
    return !S.contract || S.contract.editable;
  }

  /* ---------------------------------------------------------- ô nhập theo biến */

  function fieldHtml(v) {
    var value = S.form.values[v.name];
    if (value == null || value === "") {
      value = v.default_value || "";
    }
    var id = "hd-v-" + v.name;
    var suggest = HD.PARTNER_SUGGEST_FIELDS.indexOf(v.name) >= 0;
    var attrs = ' class="hd-input w-100" data-var="' + esc(v.name) + '" data-var-type="' + v.var_type + '" id="' + id + '"' +
      (suggest ? ' data-partner-suggest="1" autocomplete="off" placeholder="Gõ tên / MST để chọn khách, hoặc nhập tay"' : "");
    var input;
    if (v.var_type === "textarea") {
      input = "<textarea" + attrs + ' rows="2">' + esc(value) + "</textarea>";
    } else if (v.var_type === "date") {
      input = '<input type="date"' + attrs + ' value="' + esc(value) + '"/>';
    } else {
      var shown = v.var_type === "money" && value !== "" && !isNaN(+value) ? HD.money(value) : value;
      input = '<input type="text"' + attrs + ' value="' + esc(shown) + '"/>';
    }
    var linked = suggest && S.form.partner_id
      ? ' <span class="hd-linked-tag" title="Đang gắn với khách trong danh bạ: ' + esc(S.form.partner_label) + '">● ' +
        esc(S.form.partner_label) + "</span>" : "";
    return '<div class="hd-field' + (v.var_type === "textarea" ? " hd-field-wide" : "") + '">' +
      '<label class="hd-label" for="' + id + '" title="' + esc(v.name) + '">' + esc(v.label) + linked + "</label>" + input + "</div>";
  }

  function sectionsHtml() {
    var vars = template().variables;
    var labels = {};
    (S.config.library.sections || []).forEach(function (s) { labels[s[0]] = s[1]; });
    return SECTION_ORDER.map(function (section) {
      var items = vars.filter(function (v) { return v.section === section; });
      if (!items.length) {
        return "";
      }
      var hasSuggestField = vars.some(function (v) { return HD.PARTNER_SUGGEST_FIELDS.indexOf(v.name) >= 0; });
      var picker = section === "buyer" && !hasSuggestField
        ? '<div class="hd-picker"><label class="hd-label" for="hd-partner-search">Chọn khách hàng có sẵn để điền nhanh (hoặc gõ tay bên dưới)</label>' +
          '<input type="search" id="hd-partner-search" class="hd-input w-100" autocomplete="off" ' +
          'placeholder="Tên công ty, mã số thuế…" value="' + esc(S.form.partner_label) + '"/>' +
          '<div id="hd-partner-results" class="hd-dropdown hd-hidden"></div></div>'
        : "";
      return '<section class="hd-step"><h3 class="hd-h3">' + esc(labels[section]) + "</h3>" + picker +
        '<div class="hd-grid">' + items.map(fieldHtml).join("") + "</div></section>";
    }).join("");
  }

  /* ---------------------------------------------------------- bảng hàng */

  function lineRowHtml(line, index) {
    var input = function (field, value, cls) {
      return '<input type="text" class="hd-input hd-line-input ' + (cls || "") + '" data-line="' + index +
        '" data-line-field="' + field + '" value="' + esc(value) + '" autocomplete="off"/>';
    };
    return "<tr>" +
      '<td class="hd-center hd-muted">' + (index + 1) + "</td>" +
      '<td class="hd-line-name">' + input("product_name", line.product_name, "") +
      (line.product_id ? '<span class="hd-linked" title="Đã gắn sản phẩm trong danh mục">●</span>' : "") + "</td>" +
      "<td>" + input("uom", line.uom, "hd-center") + "</td>" +
      "<td>" + input("quantity", HD.qty(line.quantity), "hd-right") + "</td>" +
      "<td>" + input("price_incl", HD.money(line.price_incl), "hd-right") +
      '<div class="hd-sub-price" data-excl="' + index + '">chưa VAT ' + HD.money(line.price_excl) + "</div></td>" +
      '<td class="hd-right hd-num"><b data-total-incl="' + index + '">' + HD.money(line.subtotal_incl) + "</b>" +
      '<div class="hd-sub-price" data-total-excl="' + index + '">chưa VAT ' + HD.money(line.subtotal) + "</div></td>" +
      '<td class="hd-center"><button type="button" class="hd-icon-btn" data-remove-line="' + index +
      '" title="Xoá dòng" aria-label="Xoá dòng ' + (index + 1) + '">✕</button></td></tr>';
  }

  function linesHtml() {
    if (!template().has_lines) {
      return "";
    }
    var c = S.contract || {};
    return '<section class="hd-step"><div class="hd-step-head"><h3 class="hd-h3">Hàng hoá</h3>' +
      '<span class="hd-muted hd-small">Gõ mã/tên để chọn sản phẩm, hoặc gõ tự do · giá nhập là giá SAU VAT</span>' +
      '<div class="hd-push d-flex gap-2"><button type="button" class="hd-btn hd-btn-mini" id="hd-paste-toggle">Dán từ Excel</button>' +
      '<button type="button" class="hd-btn hd-btn-mini" id="hd-add-line">+ Thêm dòng</button></div></div>' +
      '<div class="hd-picker hd-order-picker"><input type="search" id="hd-order-search" class="hd-input w-100" autocomplete="off" ' +
      'placeholder="Lấy hàng từ đơn bán: gõ số đơn (S…, DH…) hoặc tên khách"/>' +
      '<div id="hd-order-results" class="hd-dropdown hd-hidden"></div></div>' +
      '<div id="hd-paste-box" class="hd-paste hd-hidden">' +
      '<textarea id="hd-paste-text" rows="4" class="hd-input hd-textarea w-100" ' +
      'placeholder="Copy các cột Tên hàng | ĐVT | Số lượng | Đơn giá sau VAT từ Excel rồi dán vào đây"></textarea>' +
      '<div class="d-flex gap-2 mt-2"><button type="button" class="hd-btn hd-btn-primary hd-btn-mini" id="hd-paste-run">Thêm vào bảng</button>' +
      '<button type="button" class="hd-btn hd-btn-mini" id="hd-paste-cancel">Đóng</button></div></div>' +
      '<div class="hd-table-wrap hd-lines-wrap"><table class="hd-lines"><thead><tr>' +
      '<th class="hd-col-stt">STT</th><th>Tên hàng</th><th class="hd-col-uom">ĐVT</th>' +
      '<th class="hd-col-qty hd-right">Số lượng</th><th class="hd-col-price hd-right">Đơn giá sau VAT</th>' +
      '<th class="hd-col-price hd-right">Thành tiền sau VAT</th><th class="hd-col-del"></th></tr></thead>' +
      '<tbody id="hd-lines-body">' + S.lines.map(lineRowHtml).join("") + "</tbody></table></div>" +
      '<div class="hd-totals">' +
      '<div class="hd-total-grand"><span>Tổng giá trị (sau VAT)</span><b class="hd-num" id="hd-t-total">' + HD.money(c.amount_total) + "</b></div>" +
      '<div class="hd-total-words" id="hd-t-words">' + esc(c.amount_words || "") + "</div>" +
      '<div class="hd-total-sub"><span>Tiền hàng chưa VAT</span><span class="hd-num" id="hd-t-untaxed">' + HD.money(c.amount_untaxed) + "</span></div>" +
      '<div class="hd-total-sub"><span>Thuế VAT <input type="text" class="hd-input hd-vat-input" id="hd-vat" value="' +
      esc(HD.qty(S.form.vat_rate)) + '" aria-label="Thuế suất VAT"/> %</span><span class="hd-num" id="hd-t-vat">' + HD.money(c.amount_vat) + "</span></div>" +
      "</div></section>";
  }

  /* ---------------------------------------------------------- khung ngăn */

  function templateOptions() {
    var current = S.form.template_id;
    return (S.config.templates || []).filter(function (t) { return t.active || t.id === current; }).map(function (t) {
      return '<option value="' + t.id + '"' + (t.id === current ? " selected" : "") + ">" + esc(t.name) + "</option>";
    }).join("");
  }

  function headerHtml() {
    var c = S.contract;
    var tag = c ? HD.stateTag(c) : "";
    var files = c
      ? '<button type="button" class="hd-btn" data-act="preview">Xem nhanh</button>' +
        '<button type="button" class="hd-btn" data-act="docx">Word</button>' +
        '<button type="button" class="hd-btn" data-act="pdf">PDF</button>'
      : "";
    return '<header class="hd-drawer-head"><div><h2 class="hd-h2">' + (c ? esc(c.name) : "Hợp đồng mới") + " " + tag + "</h2>" +
      (c ? '<div class="hd-muted hd-small">Phụ trách: ' + esc(c.user) + "</div>" : "") + "</div>" +
      '<div class="hd-push d-flex flex-wrap gap-2">' + files + "</div>" +
      '<button type="button" class="btn-close ms-2" data-close="drawer" aria-label="Đóng"></button></header>';
  }

  function footerHtml() {
    var actions = (S.contract ? S.contract.actions : []).map(function (key) {
      var def = HD.ACTIONS[key];
      return '<button type="button" class="hd-btn ' + def[1] + '" data-action="' + key + '">' + def[0] + "</button>";
    }).join("");
    var save = editable() ? '<button type="button" class="hd-btn hd-btn-primary" id="hd-save">Lưu</button>' : "";
    var locked = editable() ? "" : '<span class="hd-muted">Hợp đồng đã khoá — chỉ Quản lý sửa được.</span>';
    return '<footer class="hd-drawer-foot">' + actions + '<span class="hd-push hd-muted" id="hd-dirty"></span>' + locked + save + "</footer>";
  }

  function render() {
    var body =
      '<fieldset id="hd-form"' + (editable() ? "" : " disabled") + ">" +
      '<section class="hd-step"><h3 class="hd-h3">Hợp đồng</h3><div class="hd-grid">' +
      '<div class="hd-field"><label class="hd-label" for="hd-f-template">Mẫu</label>' +
      '<select class="hd-input w-100" id="hd-f-template">' + templateOptions() + "</select></div>" +
      '<div class="hd-field"><label class="hd-label" for="hd-f-date">Ngày ký</label>' +
      '<input type="date" class="hd-input w-100" id="hd-f-date" value="' + esc(S.form.contract_date) + '"/></div>' +
      "</div></section>" +
      sectionsHtml() + linesHtml() +
      '<section class="hd-step"><label class="hd-label" for="hd-f-note">Ghi chú nội bộ (không in ra hợp đồng)</label>' +
      '<textarea class="hd-input hd-textarea w-100" id="hd-f-note" rows="2">' + esc(S.form.note) + "</textarea></section>" +
      "</fieldset>";
    HD.$("hd-drawer-panel").innerHTML = headerHtml() + '<div class="hd-drawer-body">' + body + "</div>" + footerHtml();
    if (HD.$("hd-partner-search")) {
      bindPartnerPicker();
    }
    if (HD.$("hd-order-search")) {
      bindOrderPicker();
    }
    markDirty(S.dirty);
  }

  function markDirty(on) {
    S.dirty = on;
    var label = HD.$("hd-dirty");
    if (label) {
      label.textContent = on ? "Có thay đổi chưa lưu" : "";
    }
  }

  /* ---------------------------------------------------------- chọn khách / đơn bán */

  /** Điền giá trị bên mua vào các biến mẫu có; ô đã gõ tay thì chỉ ghi đè khi overwrite. */
  function fillVariables(values, overwrite) {
    template().variables.forEach(function (v) {
      if (values[v.name] == null || (!overwrite && S.form.values[v.name])) {
        return;
      }
      S.form.values[v.name] = values[v.name];
      var input = document.querySelector('#hd-form [data-var="' + v.name + '"]');
      if (input) {
        input.value = values[v.name];
      }
    });
  }

  function applyPartner(p) {
    collectForm();
    S.form.partner_id = p.id;
    S.form.partner_label = p.label;
    fillVariables(p.values, true);
    markDirty(true);
    render();
  }

  /** Mẫu không có ô tên/MST bên mua: vẫn có ô chọn khách riêng để điền các biến bên mua khác. */
  function bindPartnerPicker() {
    HD.bindPicker(HD.$("hd-partner-search"), HD.$("hd-partner-results"), function (term) {
      return HD.api("partners", { search: term });
    }, HD.partnerItemHtml, applyPartner);
  }

  /** Gõ vào ô tên / MST bên mua: gợi ý khách; gõ tay tên khác thì bỏ gắn khách cũ. */
  var suggestPartners = HD.debounce(function (input) {
    var term = input.value.trim();
    if (term.length < 2) {
      HD.suggest.close();
      return;
    }
    HD.api("partners", { search: term }).then(function (items) {
      HD.suggest.open(input, items, HD.partnerItemHtml, applyPartner, HD.PARTNER_HINT);
    }).catch(HD.fail);
  }, 250);

  function bindOrderPicker() {
    var input = HD.$("hd-order-search");
    HD.bindPicker(input, HD.$("hd-order-results"), function (term) {
      return HD.api("sale_orders", { search: term });
    }, function (o) {
      return '<span class="hd-strong">' + esc(o.label) + "</span> " + esc(o.partner) +
        ' <span class="hd-muted">' + HD.money(o.amount_total) + "</span>";
    }, function (o) {
      HD.api("sale_order_lines", { order_id: o.id, vat_rate: S.form.vat_rate }).then(function (result) {
        if (S.lines.length && window.confirm("Thay các dòng hàng đang có bằng hàng của đơn " + o.label + "?\n(Huỷ = thêm vào cuối)")) {
          S.lines = [];
        }
        addLines(result.lines);
        input.value = "";
        // Chưa có khách thì lấy khách của đơn; ô bên mua đã gõ tay thì giữ nguyên
        if (!S.form.partner_id) {
          collectForm();
          S.form.partner_id = result.partner_id;
          S.form.partner_label = result.partner_label;
          fillVariables(result.partner_values, false);
          render();
        }
        HD.toast("Đã lấy " + result.lines.length + " dòng từ " + o.label);
      }).catch(HD.fail);
    });
  }

  /* ---------------------------------------------------------- chọn sản phẩm trên dòng hàng */

  var searchProducts = HD.debounce(function (input, index) {
    var term = input.value.trim();
    if (term.length < 2) {
      HD.suggest.close();
      return;
    }
    HD.api("products", { search: term, vat_rate: S.form.vat_rate }).then(function (items) {
      HD.suggest.open(input, items, function (p) {
        return "<span>" + esc(p.label) + '</span> <span class="hd-muted">' + esc(p.uom) + " · " + HD.money(p.price_incl) + "</span>";
      }, function (item) { pickProduct(index, item); }, "Chọn sản phẩm, hoặc cứ gõ tiếp để dùng tên tự do");
    }).catch(HD.fail);
  }, 250);

  function pickProduct(index, item) {
    Object.assign(S.lines[index], { product_id: item.id, product_name: item.name, uom: item.uom, price_incl: item.price_incl });
    redrawLines();
    markDirty(true);
    var qty = document.querySelector('[data-line="' + index + '"][data-line-field="quantity"]');
    if (qty) {
      qty.focus();
      qty.select();
    }
  }

  /* ---------------------------------------------------------- tổng tiền */

  var refreshTotals = HD.debounce(function () {
    HD.api("totals", { lines: S.lines, vat_rate: S.form.vat_rate }).then(function (t) {
      t.subtotals.forEach(function (value, index) {
        var line = S.lines[index];
        if (!line) {
          return;
        }
        line.subtotal = value;
        line.subtotal_incl = t.subtotals_incl[index];
        line.price_excl = t.prices_excl[index];
        var set = function (selector, text) {
          var el = document.querySelector(selector);
          if (el) {
            el.textContent = text;
          }
        };
        set('[data-total-incl="' + index + '"]', HD.money(line.subtotal_incl));
        set('[data-total-excl="' + index + '"]', "chưa VAT " + HD.money(value));
        set('[data-excl="' + index + '"]', "chưa VAT " + HD.money(line.price_excl));
      });
      HD.$("hd-t-untaxed").textContent = HD.money(t.untaxed);
      HD.$("hd-t-vat").textContent = HD.money(t.vat);
      HD.$("hd-t-total").textContent = HD.money(t.total);
      HD.$("hd-t-words").textContent = t.words;
    }).catch(HD.fail);
  }, 300);

  function redrawLines() {
    var body = HD.$("hd-lines-body");
    if (body) {
      body.innerHTML = S.lines.map(lineRowHtml).join("");
      refreshTotals();
    }
  }

  function addLines(lines) {
    S.lines = S.lines.concat(lines.map(function (l) {
      return Object.assign({ product_id: false, uom: "", quantity: 1, price_incl: 0, subtotal: 0, subtotal_incl: 0, price_excl: 0 }, l);
    }));
    redrawLines();
    markDirty(true);
  }

  /* ---------------------------------------------------------- lưu & thao tác */

  function collectForm() {
    var form = S.form;
    form.contract_date = HD.$("hd-f-date").value;
    form.note = HD.$("hd-f-note").value;
    document.querySelectorAll("#hd-form [data-var]").forEach(function (el) {
      var type = el.dataset.varType;
      form.values[el.dataset.var] = (type === "money" || type === "number") && el.value.trim() !== ""
        ? String(HD.parseNumber(el.value)) : el.value;
    });
  }

  function loadDetail(detail) {
    S.contract = detail;
    S.form = {
      template_id: detail.template_id,
      contract_date: detail.contract_date,
      partner_id: detail.partner_id,
      partner_label: detail.partner_label,
      vat_rate: detail.vat_rate,
      note: detail.note,
      values: Object.assign({}, detail.values),
    };
    S.lines = detail.lines.map(function (l) { return Object.assign({ price_excl: l.price_unit }, l); });
  }

  function save() {
    collectForm();
    var payload = {
      contract_id: S.contract ? S.contract.id : null,
      template_id: S.form.template_id,
      contract_date: S.form.contract_date,
      partner_id: S.form.partner_id || false,
      vat_rate: S.form.vat_rate,
      note: S.form.note,
      values: S.form.values,
    };
    if (template().has_lines) {
      payload.lines = S.lines;
    }
    return HD.api("save", payload).then(function (detail) {
      loadDetail(detail);
      markDirty(false);
      render();
      HD.toast("Đã lưu " + detail.name);
      HD.loadList();
      return detail;
    });
  }

  /** Lưu trước nếu đang có thay đổi, để Xem nhanh / Word / PDF ra đúng nội dung đang thấy. */
  function saveIfDirty() {
    return S.dirty && editable() ? save() : Promise.resolve(S.contract);
  }

  function runAction(key) {
    var def = HD.ACTIONS[key];
    if (def[2] && !window.confirm(def[2])) {
      return;
    }
    var id = S.contract.id;
    saveIfDirty().then(function () {
      return HD.api("action", { contract_id: id, action: key });
    }).then(function (result) {
      if (result.deleted) {
        closeDrawer(true);
        HD.toast("Đã xoá hợp đồng");
      } else {
        loadDetail(result);
        render();
        HD.toast(result.state_label);
      }
      HD.loadList();
    }).catch(HD.fail);
  }

  function closeDrawer(force) {
    if (!force && S.dirty && !window.confirm("Hợp đồng có thay đổi chưa lưu. Đóng và bỏ thay đổi?")) {
      return;
    }
    markDirty(false);
    HD.show("hd-drawer", false);
  }

  HD.closeDrawer = closeDrawer;

  /** Mở hợp đồng id; id = null là hợp đồng mới, templateId (tuỳ chọn) chọn sẵn mẫu. */
  HD.openContract = function (id, templateId) {
    S.dirty = false;
    var load = id ? HD.api("get", { contract_id: id }) : Promise.resolve(null);
    load.then(function (detail) {
      if (detail) {
        loadDetail(detail);
      } else {
        var first = (S.config.templates || []).filter(function (t) { return t.active; })[0];
        S.contract = null;
        S.form = {
          template_id: templateId || (first ? first.id : false),
          contract_date: S.config.today,
          partner_id: false,
          partner_label: "",
          vat_rate: S.config.default_vat,
          note: "",
          values: {},
        };
        S.lines = [];
      }
      render();
      HD.show("hd-drawer", true);
    }).catch(HD.fail);
  };

  /* ---------------------------------------------------------- xem nhanh */

  HD.openPreview = function (id) {
    HD.api("preview", { contract_id: id }).then(function (result) {
      HD.$("hd-preview-title").textContent = "Xem nhanh · " + result.name;
      HD.$("hd-preview-paper").innerHTML = result.html;
      HD.$("hd-preview-actions").innerHTML =
        '<button type="button" class="hd-btn" data-download="docx" data-id="' + id + '">Tải Word</button>' +
        '<button type="button" class="hd-btn hd-btn-primary" data-download="pdf" data-id="' + id + '">Tải PDF</button>';
      HD.openModal("hd-preview");
    }).catch(HD.fail);
  };

  /* ---------------------------------------------------------- gắn sự kiện */

  HD.initForm = function () {
    var panel = HD.$("hd-drawer-panel");

    HD.on(panel, "input", "[data-var], #hd-f-date, #hd-f-note", function () { markDirty(true); });
    HD.on(panel, "input", "[data-partner-suggest]", function (el) {
      if (el.dataset.var === "Ten_Ben_Mua" && S.form.partner_id) {
        S.form.partner_id = false;   // gõ tay tên khác: không còn là khách trong danh bạ
        S.form.partner_label = "";
      }
      suggestPartners(el);
    });
    HD.on(panel, "focusout", '[data-var-type="money"]', function (el) {
      if (el.value.trim() !== "") {
        el.value = HD.money(HD.parseNumber(el.value));
      }
    });
    // Đổi mẫu: giữ giá trị đã gõ (biến cùng tên dùng lại), vẽ lại ô theo bộ biến của mẫu mới
    HD.on(panel, "change", "#hd-f-template", function (el) {
      collectForm();
      S.form.template_id = +el.value;
      render();
      markDirty(true);
    });
    HD.on(panel, "input", "#hd-vat", function (el) {
      S.form.vat_rate = HD.parseNumber(el.value);
      markDirty(true);
      refreshTotals();
    });
    HD.on(panel, "input", "[data-line-field]", function (el) {
      var index = +el.dataset.line;
      var line = S.lines[index];
      var field = el.dataset.lineField;
      markDirty(true);
      if (field === "product_name") {
        line.product_name = el.value;
        line.product_id = false;   // gõ tay thì bỏ gắn sản phẩm cũ
        searchProducts(el, index);
        return;
      }
      line[field] = field === "uom" ? el.value : HD.parseNumber(el.value);
      if (field !== "uom") {
        refreshTotals();
      }
    });
    // Gõ xong định dạng lại "4382640" -> "4.382.640" cho dễ soát
    HD.on(panel, "focusout", '[data-line-field="price_incl"], [data-line-field="quantity"]', function (el) {
      var value = S.lines[+el.dataset.line][el.dataset.lineField];
      el.value = el.dataset.lineField === "price_incl" ? HD.money(value) : HD.qty(value);
    });
    HD.on(panel, "click", "[data-remove-line]", function (el) {
      S.lines.splice(+el.dataset.removeLine, 1);
      redrawLines();
      markDirty(true);
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
    HD.on(panel, "click", "#hd-save", function () { save().catch(HD.fail); });
    HD.on(panel, "click", "[data-action]", function (el) { runAction(el.dataset.action); });
    HD.on(panel, "click", "[data-act]", function (el) {
      var act = el.dataset.act;
      saveIfDirty().then(function (detail) {
        if (act === "preview") {
          HD.openPreview(detail.id);
        } else {
          HD.download(HD.exportUrl([detail.id], act));
        }
      }).catch(HD.fail);
    });
    HD.on(HD.$("hd-drawer"), "click", '[data-close="drawer"]', function () { closeDrawer(false); });
    HD.on(HD.$("hd-preview"), "click", "[data-download]", function (el) {
      HD.download(HD.exportUrl([+el.dataset.id], el.dataset.download));
    });
  };
})(window.HlvContract);
