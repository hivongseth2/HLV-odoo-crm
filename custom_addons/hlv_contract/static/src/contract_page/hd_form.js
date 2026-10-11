/* Ngăn soạn một hợp đồng (tạo / sửa / chuyển trạng thái) và hộp Xem nhanh. */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var S = HD.S;
  var esc = HD.esc;

  /* [field, nhãn, kiểu ô, chỉ hiện cho loại hợp đồng ("" = mọi loại)] */
  var BUYER_FIELDS = [
    ["buyer_name", "Tên bên mua", "text", ""],
    ["buyer_vat", "Mã số thuế", "text", ""],
    ["buyer_address", "Địa chỉ", "text", ""],
    ["buyer_phone", "Điện thoại", "text", ""],
    ["buyer_fax", "Fax", "text", "principle"],
    ["buyer_representative", "Người đại diện", "text", ""],
    ["buyer_position", "Chức vụ", "text", ""],
  ];
  var TERM_FIELDS = [
    ["main_product", "Mặt hàng chính", "text", "principle"],
    ["delivery_time", "Thời gian giao hàng", "text", "sale"],
    ["delivery_place", "Địa điểm giao hàng", "text", "sale"],
    ["payment_terms", "Điều kiện thanh toán", "textarea", "sale"],
    ["court", "Toà án giải quyết tranh chấp", "text", ""],
    ["note", "Ghi chú nội bộ (không in ra hợp đồng)", "textarea", ""],
  ];

  function values() {
    return S.contract ? S.contract.values : S.draftValues;
  }

  function editable() {
    return !S.contract || S.contract.editable;
  }

  function newValues() {
    var cfg = S.config;
    var template = (cfg.templates || []).filter(function (t) { return t.active && t.contract_type === "sale"; })[0];
    return {
      contract_type: "sale",
      template_id: template ? template.id : false,
      contract_date: cfg.today,
      expiry_date: "",
      partner_id: false,
      vat_rate: cfg.defaults.vat_rate,
      court: cfg.defaults.court,
    };
  }

  function fieldHtml(def, vals) {
    var name = def[0];
    var value = vals[name] == null ? "" : vals[name];
    var input = def[2] === "textarea"
      ? '<textarea class="hd-input hd-textarea w-100" rows="2" data-field="' + name + '" id="hd-f-' + name + '">' +
        esc(value) + "</textarea>"
      : '<input type="' + def[2] + '" class="hd-input w-100" data-field="' + name + '" id="hd-f-' + name +
        '" value="' + esc(value) + '"/>';
    var hidden = def[3] && def[3] !== vals.contract_type ? " hd-hidden" : "";
    return '<div class="hd-field' + (def[2] === "textarea" ? " hd-field-wide" : "") + hidden +
      '" data-for-type="' + def[3] + '"><label class="hd-label" for="hd-f-' + name + '">' + def[1] + "</label>" +
      input + "</div>";
  }

  function templateOptions(vals) {
    var current = vals.template_id;
    var list = (S.config.templates || []).filter(function (t) {
      return t.contract_type === vals.contract_type && (t.active || t.id === current);
    });
    if (!list.length) {
      return '<option value="">— Chưa có mẫu cho loại này —</option>';
    }
    return list.map(function (t) {
      return '<option value="' + t.id + '"' + (t.id === current ? " selected" : "") + ">" + esc(t.name) + "</option>";
    }).join("");
  }

  function lineRowHtml(line, index) {
    var cell = function (field, value, cls, type) {
      return '<td><input type="' + (type || "text") + '" class="hd-input hd-line-input ' + (cls || "") +
        '" data-line="' + index + '" data-line-field="' + field + '" value="' + esc(value) + '"/></td>';
    };
    return "<tr>" +
      '<td class="hd-center hd-muted">' + (index + 1) + "</td>" +
      cell("product_name", line.product_name, "") +
      cell("uom", line.uom, "hd-center") +
      cell("quantity", line.quantity === "" ? "" : HD.qty(line.quantity), "hd-right") +
      cell("price_unit", line.price_unit === "" ? "" : HD.money(line.price_unit), "hd-right") +
      '<td class="hd-right hd-num" data-subtotal="' + index + '">' + HD.money(line.subtotal) + "</td>" +
      '<td class="hd-center"><button type="button" class="hd-icon-btn" data-remove-line="' + index +
      '" title="Xoá dòng" aria-label="Xoá dòng ' + (index + 1) + '">✕</button></td></tr>';
  }

  function linesSection(vals) {
    var c = S.contract || {};
    return '<section class="hd-step" id="hd-lines-section"' + (vals.contract_type === "principle" ? ' hidden' : "") + ">" +
      '<div class="hd-step-head"><h3 class="hd-h3">Hàng hoá</h3>' +
      '<span class="hd-muted hd-small">Số kiểu Việt: 4.058.000 · 2,5</span>' +
      '<div class="hd-push d-flex gap-2"><button type="button" class="hd-btn hd-btn-mini" id="hd-paste-toggle">Dán từ Excel</button>' +
      '<button type="button" class="hd-btn hd-btn-mini" id="hd-add-line">+ Thêm dòng</button></div></div>' +
      '<div id="hd-paste-box" class="hd-paste hd-hidden">' +
      '<textarea id="hd-paste-text" rows="4" class="hd-input hd-textarea w-100" ' +
      'placeholder="Copy các cột Tên hàng | ĐVT | Số lượng | Đơn giá từ Excel rồi dán vào đây"></textarea>' +
      '<div class="d-flex gap-2 mt-2"><button type="button" class="hd-btn hd-btn-primary hd-btn-mini" id="hd-paste-run">Thêm vào bảng</button>' +
      '<button type="button" class="hd-btn hd-btn-mini" id="hd-paste-cancel">Đóng</button></div></div>' +
      '<div class="hd-table-wrap"><table class="hd-lines"><thead><tr>' +
      '<th class="hd-col-stt">STT</th><th>Tên hàng</th><th class="hd-col-uom">ĐVT</th>' +
      '<th class="hd-col-qty hd-right">Số lượng</th><th class="hd-col-price hd-right">Đơn giá</th>' +
      '<th class="hd-col-price hd-right">Thành tiền</th><th class="hd-col-del"></th></tr></thead>' +
      '<tbody id="hd-lines-body">' + S.lines.map(lineRowHtml).join("") + "</tbody></table></div>" +
      '<div class="hd-totals">' +
      '<div><span>Tổng tiền hàng</span><b class="hd-num" id="hd-t-untaxed">' + HD.money(c.amount_untaxed) + "</b></div>" +
      '<div><span>Thuế VAT <input type="text" class="hd-input hd-vat-input" data-field="vat_rate" value="' +
      esc(vals.vat_rate) + '" aria-label="Thuế suất VAT"/> %</span><b class="hd-num" id="hd-t-vat">' + HD.money(c.amount_vat) + "</b></div>" +
      '<div class="hd-total-grand"><span>Tổng giá trị</span><b class="hd-num" id="hd-t-total">' + HD.money(c.amount_total) + "</b></div>" +
      '<div class="hd-total-words" id="hd-t-words">' + esc(c.amount_words || "") + "</div></div></section>";
  }

  function headerHtml() {
    var c = S.contract;
    var title = c ? esc(c.name) : "Hợp đồng mới";
    var tag = c ? '<span class="hd-tag ' + (HD.STATE_CLASS[c.state] || "") + '">' + esc(c.state_label) + "</span>" : "";
    var files = c
      ? '<button type="button" class="hd-btn" data-act="preview">Xem nhanh</button>' +
        '<button type="button" class="hd-btn" data-act="docx">Word</button>' +
        '<button type="button" class="hd-btn" data-act="pdf">PDF</button>'
      : "";
    return '<header class="hd-drawer-head"><div><h2 class="hd-h2">' + title + " " + tag + "</h2>" +
      (c ? '<div class="hd-muted hd-small">Phụ trách: ' + esc(c.user) + "</div>" : "") + "</div>" +
      '<div class="hd-push d-flex flex-wrap gap-2">' + files + "</div>" +
      '<button type="button" class="btn-close ms-2" data-close="drawer" aria-label="Đóng"></button></header>';
  }

  function footerHtml() {
    var c = S.contract;
    var actions = (c ? c.actions : []).map(function (key) {
      var def = HD.ACTIONS[key];
      return '<button type="button" class="hd-btn ' + def[1] + '" data-action="' + key + '">' + def[0] + "</button>";
    }).join("");
    var save = editable() ? '<button type="button" class="hd-btn hd-btn-primary" id="hd-save">Lưu</button>' : "";
    var locked = editable() ? "" : '<span class="hd-muted">Hợp đồng đã khoá — chỉ Quản lý sửa được.</span>';
    return '<footer class="hd-drawer-foot">' + actions + '<span class="hd-push hd-muted" id="hd-dirty"></span>' +
      locked + save + "</footer>";
  }

  function render() {
    var vals = values();
    var body =
      '<fieldset id="hd-form"' + (editable() ? "" : " disabled") + ">" +
      '<section class="hd-step"><h3 class="hd-h3">Thông tin hợp đồng</h3><div class="hd-grid">' +
      '<div class="hd-field"><label class="hd-label" for="hd-f-contract_type">Loại hợp đồng</label>' +
      '<select class="hd-input w-100" data-field="contract_type" id="hd-f-contract_type">' +
      HD.typeOptions(vals.contract_type) + "</select></div>" +
      '<div class="hd-field"><label class="hd-label" for="hd-f-template_id">Mẫu</label>' +
      '<select class="hd-input w-100" data-field="template_id" id="hd-f-template_id">' + templateOptions(vals) + "</select></div>" +
      '<div class="hd-field"><label class="hd-label" for="hd-f-contract_date">Ngày ký</label>' +
      '<input type="date" class="hd-input w-100" data-field="contract_date" id="hd-f-contract_date" value="' + esc(vals.contract_date) + '"/></div>' +
      '<div class="hd-field' + (vals.contract_type === "principle" ? "" : " hd-hidden") + '" data-for-type="principle">' +
      '<label class="hd-label" for="hd-f-expiry_date">Hiệu lực đến</label>' +
      '<input type="date" class="hd-input w-100" data-field="expiry_date" id="hd-f-expiry_date" value="' + esc(vals.expiry_date) + '"/></div>' +
      "</div></section>" +
      '<section class="hd-step"><div class="hd-step-head"><h3 class="hd-h3">Bên mua</h3></div>' +
      '<div class="hd-picker"><label class="hd-label" for="hd-partner-search">Chọn khách hàng có sẵn để điền nhanh</label>' +
      '<input type="search" id="hd-partner-search" class="hd-input w-100" autocomplete="off" ' +
      'placeholder="Tên công ty, mã số thuế…" value="' + esc(S.contract ? S.contract.partner_label : "") + '"/>' +
      '<div id="hd-partner-results" class="hd-dropdown hd-hidden"></div></div>' +
      '<div class="hd-grid">' + BUYER_FIELDS.map(function (d) { return fieldHtml(d, vals); }).join("") + "</div></section>" +
      linesSection(vals) +
      '<section class="hd-step"><h3 class="hd-h3">Điều khoản</h3><div class="hd-grid">' +
      TERM_FIELDS.map(function (d) { return fieldHtml(d, vals); }).join("") + "</div></section>" +
      "</fieldset>";
    HD.$("hd-drawer-panel").innerHTML = headerHtml() + '<div class="hd-drawer-body">' + body + "</div>" + footerHtml();
    bindPartnerPicker();
    markDirty(S.dirty);
  }

  function markDirty(on) {
    S.dirty = on;
    var label = HD.$("hd-dirty");
    if (label) {
      label.textContent = on ? "Có thay đổi chưa lưu" : "";
    }
  }

  function bindPartnerPicker() {
    var input = HD.$("hd-partner-search");
    HD.bindPicker(input, HD.$("hd-partner-results"), function (term) {
      return HD.api("partners", { search: term });
    }, function (p) {
      return '<span class="hd-strong">' + esc(p.label) + "</span>" + (p.vat ? ' <span class="hd-muted">MST ' + esc(p.vat) + "</span>" : "");
    }, function (p) {
      var vals = values();
      Object.keys(p.values).forEach(function (key) {
        vals[key] = p.values[key];
        var field = document.querySelector('#hd-form [data-field="' + key + '"]');
        if (field) {
          field.value = p.values[key];
        }
      });
      input.value = p.label;
      markDirty(true);
    });
  }

  /* -------------------------------------------------------------- dòng hàng & tổng */

  var refreshTotals = HD.debounce(function () {
    HD.api("totals", { lines: S.lines, vat_rate: HD.parseNumber(values().vat_rate) }).then(function (t) {
      t.subtotals.forEach(function (value, index) {
        S.lines[index].subtotal = value;
        var cell = document.querySelector('[data-subtotal="' + index + '"]');
        if (cell) {
          cell.textContent = HD.money(value);
        }
      });
      HD.$("hd-t-untaxed").textContent = HD.money(t.untaxed);
      HD.$("hd-t-vat").textContent = HD.money(t.vat);
      HD.$("hd-t-total").textContent = HD.money(t.total);
      HD.$("hd-t-words").textContent = t.words;
    }).catch(HD.fail);
  }, 300);

  function redrawLines() {
    HD.$("hd-lines-body").innerHTML = S.lines.map(lineRowHtml).join("");
    refreshTotals();
  }

  function addLines(lines) {
    S.lines = S.lines.concat(lines.map(function (l) { return Object.assign({ subtotal: 0 }, l); }));
    redrawLines();
    markDirty(true);
  }

  /* -------------------------------------------------------------- lưu & thao tác */

  function collectValues() {
    var vals = Object.assign({}, values());
    document.querySelectorAll("#hd-form [data-field]").forEach(function (el) {
      vals[el.dataset.field] = el.value;
    });
    vals.vat_rate = HD.parseNumber(vals.vat_rate);
    vals.template_id = +vals.template_id || false;
    return vals;
  }

  function save() {
    var vals = collectValues();
    var payload = { contract_id: S.contract ? S.contract.id : null, values: vals };
    if (vals.contract_type !== "principle") {
      payload.lines = S.lines;
    }
    return HD.api("save", payload).then(function (detail) {
      S.contract = detail;
      S.lines = detail.lines.slice();
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
        S.contract = result;
        S.lines = result.lines.slice();
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

  HD.openContract = function (id) {
    S.dirty = false;
    var load = id ? HD.api("get", { contract_id: id }) : Promise.resolve(null);
    load.then(function (detail) {
      S.contract = detail;
      S.draftValues = detail ? null : newValues();
      S.lines = detail ? detail.lines.slice() : [];
      render();
      HD.show("hd-drawer", true);
      if (!detail) {
        HD.$("hd-partner-search").focus();
      }
    }).catch(HD.fail);
  };

  /* -------------------------------------------------------------- xem nhanh */

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

  /* -------------------------------------------------------------- gắn sự kiện */

  HD.initForm = function () {
    var panel = HD.$("hd-drawer-panel");

    HD.on(panel, "input", "[data-field]", function (el) {
      values()[el.dataset.field] = el.value;
      markDirty(true);
      if (el.dataset.field === "vat_rate") {
        refreshTotals();
      }
    });
    // Đổi loại: giữ những gì đã gõ, chọn lại mẫu đầu tiên của loại mới, vẽ lại để ẩn/hiện ô theo loại
    HD.on(panel, "change", '[data-field="contract_type"]', function (el) {
      var vals = Object.assign(values(), collectValues());
      var match = (S.config.templates || []).filter(function (t) { return t.active && t.contract_type === el.value; })[0];
      vals.template_id = match ? match.id : false;
      render();
      markDirty(true);
    });
    HD.on(panel, "input", "[data-line-field]", function (el) {
      var line = S.lines[+el.dataset.line];
      var field = el.dataset.lineField;
      line[field] = field === "quantity" || field === "price_unit" ? HD.parseNumber(el.value) : el.value;
      markDirty(true);
      if (field === "quantity" || field === "price_unit") {
        refreshTotals();
      }
    });
    // Gõ xong đơn giá thì định dạng lại "4058000" -> "4.058.000" cho dễ soát
    HD.on(panel, "focusout", '[data-line-field="price_unit"], [data-line-field="quantity"]', function (el) {
      var value = S.lines[+el.dataset.line][el.dataset.lineField];
      el.value = el.dataset.lineField === "price_unit" ? HD.money(value) : HD.qty(value);
    });
    HD.on(panel, "click", "[data-remove-line]", function (el) {
      S.lines.splice(+el.dataset.removeLine, 1);
      redrawLines();
      markDirty(true);
    });
    HD.on(panel, "click", "#hd-add-line", function () {
      addLines([{ product_name: "", uom: "", quantity: 1, price_unit: 0 }]);
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
