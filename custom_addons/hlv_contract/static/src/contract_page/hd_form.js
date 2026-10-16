/* Ngăn soạn một hợp đồng: ô nhập dựng theo bộ biến của mẫu đang chọn, số hợp đồng và phần sửa
   đè biến tự điền, xem trước, chuyển trạng thái, hộp Xem nhanh. Bảng hàng hoá ở hd_lines.js; căn cứ
   văn bản gốc và thanh toán theo đợt ở hd_links.js. */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var S = HD.S;
  var esc = HD.esc;
  var SECTION_ORDER = ["general", "buyer", "goods", "terms", "other"];
  var preview = null;
  var previewToken = 0;

  /**
   * Bộ ô nhập đang dùng. Hợp đồng đã lập giữ bản chụp riêng (mẫu sửa sau không đổi theo) nên
   * lấy theo hợp đồng; hợp đồng mới hoặc vừa đổi sang mẫu khác thì lấy theo mẫu.
   */
  function template() {
    var id = S.form.template_id;
    if (S.contract && S.contract.template_id === id) {
      return { id: id, variables: S.contract.variables, has_lines: S.contract.has_lines, contract_type: S.contract.contract_type };
    }
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
      // Mẫu có bảng hàng: biến nhóm Hàng hoá vẽ chung trong khung bảng hàng (linesHtml)
      if (!items.length || (section === "goods" && template().has_lines)) {
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
    var toggle = '<button type="button" class="hd-btn' + (S.previewOn ? " is-on" : "") + '" data-toggle-preview="1">' +
      (S.previewOn ? "Ẩn xem trước" : "Xem trước khi soạn") + "</button>";
    var bodyEdit = c && editable()
      ? '<button type="button" class="hd-btn" data-edit-body="1" title="Sửa chữ trên riêng hợp đồng này, mẫu gốc không đổi">Sửa nội dung</button>'
      : "";
    if (c && c.doc_custom) {
      tag += ' <span class="hd-tag hd-tag-mine" title="Hợp đồng này đã sửa chữ riêng, khác mẫu gốc">Nội dung sửa riêng</span>';
    }
    files = bodyEdit + files + HD.childButtonsHtml(c);
    return '<header class="hd-drawer-head"><div><h2 class="hd-h2">' + (c ? esc(c.name) : "Hợp đồng mới") + " " + tag + "</h2>" +
      (c ? '<div class="hd-muted hd-small">Phụ trách: ' + esc(c.user) + "</div>" : "") + "</div>" +
      '<div class="hd-push d-flex flex-wrap gap-2">' + toggle + files + "</div>" +
      '<button type="button" class="btn-close ms-2" data-close="drawer" aria-label="Đóng"></button></header>';
  }

  function footerHtml() {
    var actions = (S.contract ? S.contract.actions : []).map(function (key) {
      var def = HD.ACTIONS[key];
      return '<button type="button" class="hd-btn ' + def[1] + '" data-action="' + key + '">' + def[0] + "</button>";
    }).join("");
    var save = editable() ? '<button type="button" class="hd-btn hd-btn-primary" id="hd-save">Lưu</button>' : "";
    var locked = editable() ? "" : '<span class="hd-muted">Hợp đồng đã chốt nên bị khoá — bấm "Về nháp để sửa" nếu cần sửa.</span>';
    return '<footer class="hd-drawer-foot">' + actions + '<span class="hd-push hd-muted" id="hd-dirty"></span>' + locked + save + "</footer>";
  }

  /** Ô số hợp đồng: số theo khuôn của mẫu hiện sẵn (chữ mờ) trước khi lưu, người soạn gõ đè được. */
  function numberFieldHtml() {
    return '<div class="hd-field"><label class="hd-label" for="hd-f-name">Số hợp đồng</label>' +
      '<input type="text" class="hd-input w-100" id="hd-f-name" value="' + esc(S.form.name) + '" placeholder="' +
      esc(numberState.number || "") + '"/>' +
      '<div class="hd-muted hd-small" id="hd-f-name-hint">' + esc(numberHint()) + "</div></div>";
  }

  // Số dự kiến theo mẫu + khách đang chọn; chỉ hỏi lại server khi một trong hai đổi
  var numberState = { key: null, number: null };

  function numberHint() {
    var c = S.contract;
    if (!c) {
      return numberState.number ? "Số dự kiến theo khuôn của mẫu, cấp khi lưu — gõ vào để đặt số khác"
        : "Cấp theo khuôn của mẫu khi lưu — gõ vào để đặt số khác";
    }
    if (numberState.number && S.form.name === c.name) {
      return "Lưu xong số đổi thành " + numberState.number + " theo khuôn — gõ vào để giữ số khác";
    }
    return c.number_auto ? "Theo khuôn của mẫu — đổi khách thì tự cấp lại; sửa tay được" : "Đã sửa tay";
  }

  function showNumber() {
    var input = HD.$("hd-f-name");
    if (input) {
      input.placeholder = numberState.number || "";
      HD.$("hd-f-name-hint").textContent = numberHint();
    }
  }

  function refreshNumber() {
    var key = [S.contract ? S.contract.id : 0, S.form.template_id, S.form.partner_id || 0, S.form.quote_code].join("|");
    if (key === numberState.key || !S.form.template_id) {
      showNumber();
      return;
    }
    numberState = { key: key, number: null };
    HD.api("number_preview", {
      contract_id: S.contract ? S.contract.id : null,
      template_id: S.form.template_id,
      partner_id: S.form.partner_id || false,
      quote_code: S.form.quote_code,
    }).then(function (result) {
      if (numberState.key === key) {
        numberState.number = result.number;
        showNumber();
      }
    }).catch(HD.fail);
  }

  /** Biến tự điền (ngày ký, bên bán, tổng tiền bằng chữ…): để trống là dùng giá trị tự tính,
      gõ vào là sửa đè cho riêng hợp đồng này. */
  function overridesHtml() {
    var fields = (S.contract && S.contract.template_id === S.form.template_id) ? S.contract.system_fields : [];
    if (!fields || !fields.length) {
      return "";
    }
    var used = fields.filter(function (f) { return S.form.overrides[f.name]; }).length;
    return '<details class="hd-step"' + (used ? " open" : "") + '><summary class="hd-h3">Thông tin tự điền — sửa đè nếu cần' +
      (used ? ' <span class="hd-tag hd-tag-warn">' + used + " ô đang sửa đè</span>" : "") + "</summary>" +
      '<p class="hd-muted hd-small mt-2">Để trống là dùng giá trị tự tính (chữ mờ trong ô). Gõ vào là thay cho riêng hợp đồng này.</p>' +
      '<div class="hd-grid">' + fields.map(function (f) {
        return '<div class="hd-field"><label class="hd-label" for="hd-o-' + f.name + '">' + esc(f.label) + "</label>" +
          '<input type="text" class="hd-input w-100" id="hd-o-' + f.name + '" data-override="' + esc(f.name) + '" value="' +
          esc(S.form.overrides[f.name] || "") + '" placeholder="' + esc(f.auto) + '"/></div>';
      }).join("") + "</div></details>";
  }

  /** Thông báo đầu ngăn: mẫu đã được sửa sau khi lập hợp đồng (nháp thì cho áp dụng mẫu mới). */
  function noticesHtml() {
    var c = S.contract;
    if (!c || !c.template_outdated || c.template_id !== S.form.template_id) {
      return "";
    }
    return '<div class="hd-notice">Mẫu <b>' + esc(c.template_name) + "</b> đã được sửa sau khi lập hợp đồng này. " +
      "Hợp đồng vẫn giữ nội dung lúc lập." +
      (editable() ? ' <button type="button" class="hd-btn hd-btn-mini" data-apply-template="1">Áp dụng mẫu mới</button>' : "") +
      "</div>";
  }

  /** Hiện lại hợp đồng sau khi thao tác ở nơi khác (hộp sửa nội dung) đã lưu. */
  HD.showContractDetail = function (detail) {
    loadDetail(detail);
    S.dirty = false;
    render();
    HD.loadList();
  };

  function render() {
    var body = noticesHtml() +
      '<fieldset id="hd-form"' + (editable() ? "" : " disabled") + ">" +
      '<section class="hd-step"><h3 class="hd-h3">Hợp đồng</h3><div class="hd-grid">' + numberFieldHtml() +
      '<div class="hd-field"><label class="hd-label" for="hd-f-template">Mẫu</label>' +
      '<select class="hd-input w-100" id="hd-f-template">' + templateOptions() + "</select></div>" +
      '<div class="hd-field"><label class="hd-label" for="hd-f-date">Ngày ký</label>' +
      '<input type="date" class="hd-input w-100" id="hd-f-date" value="' + esc(S.form.contract_date) + '"/></div>' +
      "</div></section>" + HD.linksHtml() +
      sectionsHtml() + HD.linesHtml() + overridesHtml() +
      '<section class="hd-step"><label class="hd-label" for="hd-f-note">Ghi chú nội bộ (không in ra hợp đồng)</label>' +
      '<textarea class="hd-input hd-textarea w-100" id="hd-f-note" rows="2">' + esc(S.form.note) + "</textarea></section>" +
      "</fieldset>" + HD.signedHtml() +
      (S.contract ? '<details class="hd-step hd-log-box" id="hd-log-box"><summary class="hd-h3">Nhật ký — ai tạo, sửa, đổi trạng thái, xuất file</summary>' +
        '<div class="hd-log-list"></div></details>' : "");
    var panel = HD.$("hd-drawer-panel");
    panel.classList.toggle("with-preview", !!S.previewOn);
    panel.innerHTML = headerHtml() +
      '<div class="hd-drawer-body hd-compose"><div class="hd-compose-form">' + body + "</div>" +
      (S.previewOn ? '<aside class="hd-compose-preview" id="hd-compose-preview"></aside>' : "") + "</div>" + footerHtml();
    preview = S.previewOn ? HD.mountLivePreview(HD.$("hd-compose-preview"), {
      title: "bấm vào để tới ô nhập",
      onPick: focusVariable,
    }) : null;
    refreshPreview();
    refreshNumber();
    if (S.contract) {
      HD.bindContractLogs(HD.$("hd-log-box"), S.contract.id);
    }
    if (HD.$("hd-partner-search")) {
      bindPartnerPicker();
    }
    HD.bindLines();
    HD.bindLinks();
    markDirty(S.dirty);
  }

  function markDirty(on) {
    S.dirty = on;
    var label = HD.$("hd-dirty");
    if (label) {
      label.textContent = on ? "Có thay đổi chưa lưu" : "";
    }
    if (on) {
      refreshPreview();
      refreshNumber();
    }
  }

  /* ---------------------------------------------------------- xem trước khi soạn */

  /** Dựng lại bản xem trước từ nội dung đang gõ (chưa lưu). Chỉ lấy kết quả của lần gọi mới nhất. */
  var refreshPreview = HD.debounce(function () {
    if (!preview || !S.form.template_id || !HD.$("hd-f-date")) {
      return;
    }
    collectForm();
    var payload = formPayload();
    var token = ++previewToken;
    var target = preview;
    target.setStatus("đang cập nhật…");
    HD.api("preview_draft", payload).then(function (result) {
      if (token === previewToken && target === preview) {
        target.setHtml(result.html);
        target.setStatus("");
      }
    }).catch(function (err) {
      if (target === preview) {
        target.setStatus(err.message);
      }
    });
  }, 500);

  /** Bấm chỗ biến trên bản xem trước: nhảy tới ô nhập của biến đó. */
  function focusVariable(name) {
    var input = name === "So_Hop_Dong" ? HD.$("hd-f-name")
      : document.querySelector('#hd-form [data-var="' + name + '"]') || document.querySelector('#hd-form [data-override="' + name + '"]');
    if (!input) {
      HD.toast("Chỗ này tự điền theo bảng hàng");
      return;
    }
    var box = input.closest("details");
    if (box) {
      box.open = true;
    }
    input.scrollIntoView({ block: "center", behavior: "smooth" });
    input.focus({ preventScroll: true });
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

  /* ---------------------------------------------------------- lưu & thao tác */

  function collectForm() {
    var form = S.form;
    form.contract_date = HD.$("hd-f-date").value;
    form.note = HD.$("hd-f-note").value;
    form.name = HD.$("hd-f-name").value.trim();
    document.querySelectorAll("#hd-form [data-override]").forEach(function (el) {
      form.overrides[el.dataset.override] = el.value.trim();
    });
    document.querySelectorAll("#hd-form [data-var]").forEach(function (el) {
      var type = el.dataset.varType;
      form.values[el.dataset.var] = (type === "money" || type === "number") && el.value.trim() !== ""
        ? String(HD.parseNumber(el.value)) : el.value;
    });
    HD.collectLinks(form);
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
      name: detail.name,
      values: Object.assign({}, detail.values),
      overrides: Object.fromEntries(detail.system_fields.map(function (f) { return [f.name, f.override]; })),
    };
    Object.assign(S.form, HD.linkFormDefaults(detail));
    S.lines = detail.lines.map(function (l) { return Object.assign({ price_basis: "incl" }, l); });
  }

  /** Dữ liệu ngăn soạn gửi server (Lưu và Xem trước dùng chung). */
  function formPayload() {
    var payload = Object.assign({
      contract_id: S.contract ? S.contract.id : null,
      template_id: S.form.template_id,
      contract_date: S.form.contract_date,
      partner_id: S.form.partner_id || false,
      vat_rate: S.form.vat_rate,
      note: S.form.note,
      name: S.form.name,
      overrides: S.form.overrides,
      values: S.form.values,
    }, HD.linkPayload());
    if (template().has_lines) {
      payload.lines = S.lines;
    }
    return payload;
  }

  function save() {
    collectForm();
    return HD.api("save", formPayload()).then(function (detail) {
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

  /** Mở hợp đồng id; id = null là hợp đồng mới, templateId (tuỳ chọn) chọn sẵn mẫu, prepare (tuỳ
      chọn) điền sẵn S.form của văn bản mới trước khi vẽ (lập phụ lục / đề nghị thanh toán từ văn bản gốc). */
  HD.openContract = function (id, templateId, prepare) {
    S.dirty = false;
    S.previewOn = HD.previewEnabled();
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
          name: "",
          values: {},
          overrides: {},
        };
        Object.assign(S.form, HD.linkFormDefaults(null));
        S.lines = [];
        if (prepare) {
          prepare();
          S.dirty = true;
        }
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

  HD.form = {
    template: template,
    fieldHtml: fieldHtml,
    markDirty: markDirty,
    collectForm: collectForm,
    fillVariables: fillVariables,
    saveIfDirty: saveIfDirty,
    render: function () { render(); },
  };

  /* ---------------------------------------------------------- gắn sự kiện */

  HD.initForm = function () {
    var panel = HD.$("hd-drawer-panel");

    HD.on(panel, "input", "[data-var], [data-override], #hd-f-date, #hd-f-note, #hd-f-name", function () { markDirty(true); });
    HD.on(panel, "focusin", "[data-var]", function (el) {
      if (preview) {
        preview.highlight(el.dataset.var);
      }
    });
    HD.on(panel, "click", "[data-edit-body]", function () {
      saveIfDirty().then(function (detail) { HD.openBodyEditor(detail.id); }).catch(HD.fail);
    });
    HD.on(panel, "click", "[data-apply-template]", function () {
      var warn = S.contract.doc_custom ? "\nPhần chữ đã sửa riêng trên hợp đồng này sẽ bị bỏ." : "";
      if (!window.confirm("Lấy lại nội dung theo mẫu hiện tại? Giá trị đã điền được giữ." + warn)) {
        return;
      }
      saveIfDirty().then(function (detail) {
        return HD.api("apply_template", { contract_id: detail.id });
      }).then(function (detail) {
        HD.showContractDetail(detail);
        HD.toast("Đã áp dụng mẫu mới");
      }).catch(HD.fail);
    });
    HD.on(panel, "click", "[data-toggle-preview]", function () {
      collectForm();
      S.previewOn = HD.previewEnabled(!S.previewOn);
      render();
    });
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
      HD.checkParentType();
      render();
      markDirty(true);
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
