/* Màn Mẫu hợp đồng (chỉ Quản lý): danh sách mẫu, trình soạn, bộ biến riêng của từng mẫu,
   import .doc/.docx, thay file Word; và hộp Thông tin bên bán. */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var S = HD.S;
  var esc = HD.esc;
  var editorApi = null;

  var SELLER_FIELDS = [
    ["contract_seller_name", "Tên bên bán", "Để trống sẽ dùng tên công ty"],
    ["contract_seller_vat", "Mã số thuế", ""],
    ["contract_seller_address", "Địa chỉ", ""],
    ["contract_seller_phone", "Điện thoại", ""],
    ["contract_seller_representative", "Người đại diện", "VD: Ông VŨ ĐỨC TẬP"],
    ["contract_seller_position", "Chức vụ", ""],
    ["contract_seller_bank_account", "Số tài khoản", ""],
    ["contract_seller_bank_name", "Ngân hàng – chi nhánh", ""],
    ["contract_court", "Toà án giải quyết tranh chấp (mặc định)", ""],
    ["contract_vat_rate", "Thuế suất VAT mặc định (%)", ""],
  ];

  /* Khung mở đầu cho mẫu mới: quốc hiệu, tên hợp đồng, số, ngày ký. */
  var STARTER_HTML =
    '<p style="text-align:center"><strong>CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM</strong></p>' +
    '<p style="text-align:center"><strong>Độc lập - Tự do - Hạnh phúc</strong></p><p><br></p>' +
    '<p style="text-align:center"><span style="font-size:16pt"><strong>HỢP ĐỒNG</strong></span></p>' +
    '<p style="text-align:center">Số: ' + HD.varChip("So_Hop_Dong") + "</p>" +
    "<p>Hôm nay, ngày " + HD.varChip("Ngay_Ky") + " tháng " + HD.varChip("Thang_Ky") + " năm " +
    HD.varChip("Nam_Ky") + ", chúng tôi gồm có:</p><p><br></p>";

  function refreshConfig() {
    return HD.api("config").then(function (config) { S.config = config; });
  }

  function sourceBadge(t) {
    return t.source === "builder"
      ? '<span class="hd-tag hd-tag-mine">Soạn trên trang</span>'
      : '<span class="hd-tag hd-tag-soft">File Word</span>';
  }

  function renderList() {
    var currentId = S.template ? S.template.id : null;
    HD.$("hd-tpl-list").innerHTML = S.templates.length ? S.templates.map(function (t) {
      return '<button type="button" class="hd-tpl-item' + (t.id === currentId ? " is-active" : "") +
        (t.active ? "" : " is-archived") + '" data-tpl="' + t.id + '">' +
        '<span class="hd-strong">' + esc(t.name) + "</span>" +
        '<span class="hd-tpl-meta">' + esc(t.type_label) + " · " + sourceBadge(t) + " · " + t.variables.length + " biến" +
        (t.active ? "" : ' <span class="hd-tag hd-tag-muted">Ngừng dùng</span>') + "</span></button>";
    }).join("") : '<div class="hd-pad hd-muted">Chưa có mẫu nào.</div>';
  }

  HD.loadTemplates = function () {
    return HD.api("templates").then(function (list) {
      S.templates = list;
      renderList();
    }).catch(HD.fail);
  };

  /* ---------------------------------------------------------- tab Biến của mẫu */

  function options(list, selected) {
    return list.map(function (item) {
      return '<option value="' + item[0] + '"' + (item[0] === selected ? " selected" : "") + ">" + esc(item[1]) + "</option>";
    }).join("");
  }

  function variablesHtml() {
    var lib = S.config.library;
    var rows = S.varDefs.map(function (v, i) {
      return "<tr>" +
        '<td class="hd-nowrap"><button type="button" class="hd-icon-btn" data-move="' + i + '" data-dir="-1" title="Lên">▲</button>' +
        '<button type="button" class="hd-icon-btn" data-move="' + i + '" data-dir="1" title="Xuống">▼</button></td>' +
        '<td><input type="text" class="hd-input w-100" data-var-index="' + i + '" data-var-field="label" value="' + esc(v.label) + '"/></td>' +
        "<td><code>" + esc(v.name) + "</code></td>" +
        '<td><select class="hd-input" data-var-index="' + i + '" data-var-field="var_type">' + options(lib.types, v.var_type) + "</select></td>" +
        '<td><select class="hd-input" data-var-index="' + i + '" data-var-field="section">' + options(lib.sections, v.section) + "</select></td>" +
        '<td><input type="text" class="hd-input w-100" data-var-index="' + i + '" data-var-field="default_value" value="' +
        esc(v.default_value) + '" placeholder="(trống)"/></td></tr>';
    }).join("");
    var system = (S.template.system_fields || []).map(function (f) {
      return '<span class="hlv-var is-system" title="' + esc(f.name) + '">' + esc(f.label) + "</span>";
    }).join(" ");
    return '<div class="hd-pad">' +
      '<p class="hd-muted">Mỗi biến là một ô người dùng điền trên hợp đồng (và một cột trong bảng dữ liệu). ' +
      "Thêm/bớt biến bằng cách chèn/xoá biến trong nội dung mẫu" +
      (S.template.source === "docx" ? " (với mẫu file Word: sửa trường trộn trong Word rồi thay file)" : "") +
      ". Ở đây chỉnh nhãn, kiểu ô, nhóm và thứ tự hiện.</p>" +
      (rows ? '<div class="hd-table-wrap"><table class="hd-table hd-vars-table"><thead><tr><th></th><th>Nhãn hiện cho người điền</th>' +
        "<th>Tên trong mẫu</th><th>Kiểu ô</th><th>Nhóm</th><th>Giá trị mặc định</th></tr></thead><tbody>" + rows + "</tbody></table></div>"
        : '<div class="hd-info">Mẫu chưa có biến nào người dùng phải điền.</div>') +
      (system ? '<h3 class="hd-h3 mt-3 mb-2">Biến tự điền có trong mẫu</h3><div class="hd-chip-row">' + system + "</div>" +
        (S.template.has_lines ? '<p class="hd-muted mt-2">Mẫu có bảng hàng hoá — hợp đồng sẽ có phần nhập hàng và tổng tiền.</p>' : "") : "") +
      "</div>";
  }

  /* ---------------------------------------------------------- vẽ mẫu đang mở */

  function headerHtml(t) {
    var isNew = !t.id;
    return '<div class="hd-tpl-head">' +
      '<input type="text" class="hd-input hd-tpl-name" id="hd-tpl-name" placeholder="Tên mẫu" value="' + esc(t.name) + '"/>' +
      '<select class="hd-input" id="hd-tpl-type" title="Loại — quyết định dãy số HĐMB-/HĐNT-">' + HD.typeOptions(t.contract_type) + "</select>" +
      '<label class="hd-check-label"><input type="checkbox" id="hd-tpl-active"' + (t.active ? " checked" : "") + "/> Đang dùng</label>" +
      '<div class="hd-push d-flex flex-wrap gap-2">' +
      (isNew ? "" : '<button type="button" class="hd-btn" id="hd-tpl-download">Tải file Word</button>') +
      (isNew ? "" : '<button type="button" class="hd-btn" id="hd-tpl-replace">Thay bằng file Word…</button>') +
      (t.source === "docx" && !isNew ? '<button type="button" class="hd-btn" id="hd-tpl-convert">Chuyển sang soạn trên trang</button>' : "") +
      '<button type="button" class="hd-btn hd-btn-primary" id="hd-tpl-save">Lưu mẫu</button>' +
      '<input type="file" id="hd-tpl-replace-file" class="hd-hidden" accept=".doc,.docx"/>' +
      "</div></div>" +
      '<div class="hd-subtabs">' +
      '<button type="button" class="hd-subtab' + (S.tplTab === "content" ? " is-active" : "") + '" data-tpl-tab="content">Nội dung mẫu</button>' +
      '<button type="button" class="hd-subtab' + (S.tplTab === "vars" ? " is-active" : "") + '" data-tpl-tab="vars">Biến của mẫu (' +
      S.varDefs.length + ")</button></div>";
  }

  function contentHtml(t) {
    if (t.source === "builder") {
      return '<div id="hd-editor-host"></div>';
    }
    return '<div class="hd-pad"><div class="hd-info">Mẫu dùng nguyên file Word <b>' + esc(t.filename) +
      "</b> — giữ đúng định dạng gốc, hợp đồng được điền vào các trường trộn (MERGEFIELD) trong file. " +
      "Muốn sửa chữ: tải file về sửa bằng Word rồi bấm “Thay bằng file Word…”, hoặc chuyển sang soạn trên trang.</div></div>";
  }

  function renderTemplate() {
    var t = S.template;
    var panel = HD.$("hd-tpl-editor");
    // Vẽ lại (đổi tab, đổi thứ tự biến) thì giữ nội dung đang soạn dở
    if (editorApi) {
      t.body_html = editorApi.getHtml();
    }
    panel.innerHTML = headerHtml(t) +
      '<div class="' + (S.tplTab === "content" ? "" : "hd-hidden") + '">' + contentHtml(t) + "</div>" +
      '<div class="' + (S.tplTab === "vars" ? "" : "hd-hidden") + '">' + variablesHtml() + "</div>" +
      '<div class="hd-pad hd-tpl-note"><label class="hd-label" for="hd-tpl-note">Ghi chú</label>' +
      '<textarea id="hd-tpl-note" class="hd-input hd-textarea w-100" rows="2">' + esc(t.note) + "</textarea></div>";
    editorApi = t.source === "builder" ? HD.mountEditor(HD.$("hd-editor-host"), t.body_html, {
      variables: function () { return S.varDefs; },
      onAddVariable: function (def) {
        S.varDefs.push(def);
        var tab = document.querySelector('[data-tpl-tab="vars"]');
        if (tab) {
          tab.textContent = "Biến của mẫu (" + S.varDefs.length + ")";
        }
      },
    }) : null;
    renderList();
  }

  function setTemplate(detail) {
    editorApi = null;
    S.template = detail;
    S.varDefs = detail.variables.map(function (v) { return Object.assign({}, v); });
    renderTemplate();
  }

  function openTemplate(id) {
    HD.api("template", { template_id: id }).then(function (detail) {
      S.tplTab = "content";
      setTemplate(detail);
    }).catch(HD.fail);
  }

  function newTemplate() {
    S.tplTab = "content";
    setTemplate({
      id: null, name: "", contract_type: "sale", source: "builder", active: true, has_lines: false,
      body_html: STARTER_HTML, note: "", variables: [], system_fields: [], filename: "",
    });
    HD.$("hd-tpl-name").focus();
  }

  function afterTemplateChange(detail, message) {
    setTemplate(detail);
    HD.toast(message);
    return Promise.all([HD.loadTemplates(), refreshConfig()]).then(HD.refreshSheets);
  }

  function saveTemplate() {
    var t = S.template;
    var params = {
      template_id: t.id,
      name: HD.$("hd-tpl-name").value,
      contract_type: HD.$("hd-tpl-type").value,
      active: HD.$("hd-tpl-active").checked,
      note: HD.$("hd-tpl-note").value,
      variables: S.varDefs,
    };
    if (t.source === "builder") {
      params.body_html = editorApi ? editorApi.getHtml() : t.body_html;
    }
    HD.api("template/save", params).then(function (detail) {
      return afterTemplateChange(detail, "Đã lưu mẫu");
    }).catch(HD.fail);
  }

  function uploadFile(file, extra) {
    return HD.readFileBase64(file).then(function (data) {
      return HD.api("template/upload", Object.assign({ filename: file.name, data: data }, extra));
    });
  }

  /* ---------------------------------------------------------- import / bên bán */

  function openImport() {
    HD.$("hd-import-file").value = "";
    HD.$("hd-import-name").value = "";
    HD.$("hd-import-type").innerHTML = HD.typeOptions("sale");
    HD.openModal("hd-import");
  }

  function runImport() {
    var file = HD.$("hd-import-file").files[0];
    if (!file) {
      HD.toast("Chọn file .doc hoặc .docx", "error");
      return;
    }
    var mode = (document.querySelector('input[name="hd-import-mode"]:checked') || {}).value;
    uploadFile(file, {
      name: HD.$("hd-import-name").value || file.name.replace(/\.docx?$/i, ""),
      contract_type: HD.$("hd-import-type").value,
      keep_word_file: mode === "keep",
    }).then(function (detail) {
      HD.closeModal("hd-import");
      S.tplTab = "vars";
      return afterTemplateChange(detail, "Đã import " + file.name + " — kiểm tra lại nhãn các biến");
    }).catch(HD.fail);
  }

  function openSeller() {
    HD.api("seller").then(function (values) {
      HD.$("hd-seller-body").innerHTML = '<div class="hd-grid">' + SELLER_FIELDS.map(function (f) {
        return '<div class="hd-field"><label class="hd-label" for="hd-s-' + f[0] + '">' + f[1] + "</label>" +
          '<input type="text" class="hd-input w-100" id="hd-s-' + f[0] + '" data-seller="' + f[0] + '" value="' +
          esc(values[f[0]]) + '" placeholder="' + esc(f[2]) + '"/></div>';
      }).join("") + '</div><p class="hd-muted hd-small mt-2">Dùng cho các biến "Bên bán" tự điền trong mẫu. ' +
        "Hai mẫu Word gốc ghi cứng bên bán trong file nên không đổi theo chỗ này.</p>";
      HD.openModal("hd-seller");
    }).catch(HD.fail);
  }

  function saveSeller() {
    var values = {};
    document.querySelectorAll("[data-seller]").forEach(function (el) {
      values[el.dataset.seller] = el.dataset.seller === "contract_vat_rate" ? HD.parseNumber(el.value) : el.value;
    });
    HD.api("seller", { values: values }).then(function () {
      HD.closeModal("hd-seller");
      HD.toast("Đã lưu thông tin bên bán");
      return refreshConfig();
    }).catch(HD.fail);
  }

  HD.openSeller = openSeller;

  HD.initTemplates = function () {
    S.tplTab = "content";
    S.varDefs = [];
    HD.on(HD.$("hd-tpl-list"), "click", "[data-tpl]", function (el) { openTemplate(+el.dataset.tpl); });
    HD.$("hd-tpl-new").addEventListener("click", newTemplate);
    HD.$("hd-tpl-import-open").addEventListener("click", openImport);
    HD.$("hd-import-run").addEventListener("click", runImport);
    HD.$("hd-import-file").addEventListener("change", function (event) {
      var file = event.target.files[0];
      var isDoc = file && /\.doc$/i.test(file.name);
      // File .doc không giữ nguyên được: buộc mở trong trình soạn
      document.querySelector('input[name="hd-import-mode"][value="keep"]').disabled = !!isDoc;
      if (isDoc) {
        document.querySelector('input[name="hd-import-mode"][value="builder"]').checked = true;
      }
      if (file && !HD.$("hd-import-name").value) {
        HD.$("hd-import-name").value = file.name.replace(/\.docx?$/i, "");
      }
    });
    HD.$("hd-seller-save").addEventListener("click", saveSeller);

    var panel = HD.$("hd-tpl-editor");
    HD.on(panel, "click", "[data-tpl-tab]", function (el) {
      S.tplTab = el.dataset.tplTab;
      renderTemplate();
    });
    HD.on(panel, "input", "[data-var-field]", function (el) {
      S.varDefs[+el.dataset.varIndex][el.dataset.varField] = el.value;
    });
    HD.on(panel, "change", "select[data-var-field]", function (el) {
      S.varDefs[+el.dataset.varIndex][el.dataset.varField] = el.value;
    });
    HD.on(panel, "click", "[data-move]", function (el) {
      var from = +el.dataset.move;
      var to = from + (+el.dataset.dir);
      if (to < 0 || to >= S.varDefs.length) {
        return;
      }
      var item = S.varDefs.splice(from, 1)[0];
      S.varDefs.splice(to, 0, item);
      renderTemplate();
    });
    HD.on(panel, "click", "#hd-tpl-save", saveTemplate);
    HD.on(panel, "click", "#hd-tpl-download", function () {
      HD.download("/hop-dong/mau/" + S.template.id + "/file");
    });
    HD.on(panel, "click", "#hd-tpl-convert", function () {
      if (!window.confirm("Chuyển mẫu sang soạn trên trang? Đầu/chân trang và khổ giấy riêng của file Word sẽ không giữ lại.")) {
        return;
      }
      HD.api("template/convert", { template_id: S.template.id }).then(function (detail) {
        return afterTemplateChange(detail, "Đã chuyển sang soạn trên trang");
      }).catch(HD.fail);
    });
    HD.on(panel, "click", "#hd-tpl-replace", function () { HD.$("hd-tpl-replace-file").click(); });
    HD.on(panel, "change", "#hd-tpl-replace-file", function (el) {
      var file = el.files[0];
      if (!file) {
        return;
      }
      // Thay file giữ nguyên dạng file Word, trừ .doc buộc đi qua trình soạn
      uploadFile(file, { template_id: S.template.id, keep_word_file: !/\.doc$/i.test(file.name) }).then(function (detail) {
        return afterTemplateChange(detail, "Đã thay file " + file.name);
      }).catch(HD.fail);
    });
  };
})(window.HlvContract);
