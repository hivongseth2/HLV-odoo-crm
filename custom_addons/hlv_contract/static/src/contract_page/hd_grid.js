/* Bảng dữ liệu một mẫu — như một sheet trong file Excel cũ: mỗi hợp đồng một dòng, mỗi biến
   của mẫu một cột, bấm ô để sửa tại chỗ. Dòng hàng hoá sửa trong ngăn soạn (bấm ô Hàng hoá). */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var S = HD.S;
  var esc = HD.esc;
  var editing = null;   // {td, input, id, name, original}
  var preview = null;   // khung xem trước của dòng đang chọn
  var previewId = null;

  function columns() {
    var template = S.gridTemplate;
    var cols = [{ name: "contract_date", label: "Ngày ký", var_type: "date", fixed: true }];
    return cols.concat(template.variables);
  }

  function rawValue(row, col) {
    return col.name === "contract_date" ? row.contract_date : (row.values[col.name] == null ? "" : row.values[col.name]);
  }

  /** Giá trị lưu -> chữ hiện trong ô: ngày dd/mm/yyyy, tiền 1.250.000, số 2,5. */
  function displayValue(value, varType) {
    if (value === "" || value == null) {
      return "";
    }
    if (varType === "date") {
      return HD.date(value) || esc(value);
    }
    if (varType === "money" && !isNaN(+value)) {
      return HD.money(value);
    }
    if (varType === "number" && !isNaN(+value)) {
      return HD.qty(value);
    }
    return esc(value).replace(/\n/g, "<br>");
  }

  function linesSummary(row) {
    if (!row.lines.length) {
      return '<span class="hd-muted">+ Thêm hàng</span>';
    }
    var first = row.lines.slice(0, 2).map(function (l) {
      return esc(l.name) + ' <span class="hd-muted">× ' + HD.qty(l.quantity) + "</span>";
    }).join("<br>");
    return first + (row.lines.length > 2 ? '<br><span class="hd-muted">… và ' + (row.lines.length - 2) + " mặt hàng</span>" : "");
  }

  function rowHtml(row) {
    var cells = columns().map(function (col) {
      // Hợp đồng lập từ mẫu cũ không có biến mẫu mới thêm: ô đó để trống, không sửa
      var own = col.fixed || row.var_names.indexOf(col.name) >= 0;
      var cls = "hd-cell hd-cell-" + col.var_type + (row.editable && own ? " is-editable" : "") + (own ? "" : " is-na");
      return '<td class="' + cls + '" data-cell="' + esc(col.name) + '" data-type="' + col.var_type + '">' +
        displayValue(rawValue(row, col), col.var_type) + "</td>";
    }).join("");
    var lines = S.gridTemplate.has_lines
      ? '<td class="hd-cell-lines" data-lines="' + row.id + '">' + linesSummary(row) + "</td>" +
        '<td class="hd-right hd-num hd-strong">' + HD.money(row.amount_total) + "</td>"
      : "";
    return '<tr data-id="' + row.id + '" class="hd-row hd-grid-row' + (S.selected[row.id] ? " is-selected" : "") +
      (row.id === previewId ? " is-previewing" : "") +
      (row.editable ? "" : " is-locked") + '">' + HD.checkCell(row) +
      '<td class="hd-strong hd-nowrap hd-sticky-col">' + esc(row.name) + "</td>" + cells + lines +
      "<td>" + HD.stateTag(row) + "</td>" + HD.rowActions(row) + "</tr>";
  }

  function headHtml() {
    var head = columns().map(function (col) {
      return '<th class="hd-col-' + col.var_type + '" title="' + esc(col.name) + '">' + esc(col.label) +
        (col.fixed ? "" : '<div class="hd-th-code">' + esc(col.name) + "</div>") + "</th>";
    }).join("");
    var lines = S.gridTemplate.has_lines ? '<th>Hàng hoá</th><th class="hd-right">Tổng (sau VAT)</th>' : "";
    return '<tr><th class="hd-col-check"><input type="checkbox" id="hd-check-all" aria-label="Chọn tất cả"/></th>' +
      '<th class="hd-sticky-col">Số hợp đồng</th>' + head + lines + "<th>Trạng thái</th><th></th></tr>";
  }

  HD.loadGrid = function () {
    cancelEdit();
    return HD.api("grid", { template_id: S.sheet, search: S.search, state: S.state, page: S.page }).then(function (result) {
      S.gridTemplate = result.template;
      S.rows = result.rows;
      HD.$("hd-thead").innerHTML = headHtml();
      HD.$("hd-list").innerHTML = S.rows.length
        ? S.rows.map(rowHtml).join("")
        : '<tr><td colspan="' + (columns().length + 6) + '" class="hd-empty">Chưa có hợp đồng nào theo mẫu này. ' +
          "Bấm “+ Thêm dòng” để tạo.</td></tr>";
      HD.$("hd-sheet-hint").innerHTML = '<span>Bấm vào ô để sửa — <b>Enter</b> lưu, <b>Tab</b> sang ô kế, <b>Esc</b> huỷ. ' +
        (S.gridTemplate.has_lines ? "Hàng hoá: bấm ô “Hàng hoá” để mở ngăn soạn. " : "") +
        "Hợp đồng đã xác nhận / đã ký bị khoá (chỉ Quản lý sửa).</span>" +
        '<button type="button" class="hd-btn hd-btn-mini hd-push' + (S.gridPreviewOn ? " is-on" : "") +
        '" data-grid-preview-toggle="1">' + (S.gridPreviewOn ? "Ẩn xem trước" : "Xem trước hợp đồng") + "</button>";
      HD.show("hd-sheet-hint", true);
      if (previewId && !findRow(previewId)) {
        previewId = null;
      }
      showPreview(previewId || (S.rows[0] && S.rows[0].id));
      HD.show("hd-grid-add", true);
      HD.afterLoad(result);
    }).catch(HD.fail);
  };

  /* ---------------------------------------------------------- sửa tại ô */

  function findRow(id) {
    return S.rows.filter(function (r) { return r.id === id; })[0];
  }

  function startEdit(td) {
    if (editing && editing.td === td) {
      return;
    }
    commitEdit();
    var tr = td.closest("tr");
    var row = findRow(+tr.dataset.id);
    var name = td.dataset.cell;
    var type = td.dataset.type;
    var col = columns().filter(function (c) { return c.name === name; })[0];
    var original = String(rawValue(row, col));
    var input = document.createElement(type === "textarea" ? "textarea" : "input");
    input.className = "hd-cell-input";
    if (type === "date") {
      input.type = "date";
    } else if (type !== "textarea") {
      input.type = "text";
    }
    if (type === "textarea") {
      input.rows = 3;
    }
    input.value = type === "money" && original !== "" && !isNaN(+original) ? HD.money(original) : original;
    td.classList.add("is-editing");
    td.innerHTML = "";
    td.appendChild(input);
    if (row.id !== previewId) {
      showPreview(row.id);
    }
    if (preview) {
      preview.highlight(name);
    }
    input.focus();
    if (input.select && type !== "date") {
      input.select();
    }
    editing = { td: td, input: input, id: row.id, name: name, type: type, original: original };
    if (HD.PARTNER_SUGGEST_FIELDS.indexOf(name) >= 0) {
      input.setAttribute("autocomplete", "off");
      input.addEventListener("input", function () { suggestPartners(input, row.id); });
    }
  }

  /* Ô tên / MST bên mua: gõ thì gợi ý khách; chọn thì điền mọi cột bên mua của dòng, không
     chọn thì lưu đúng chữ đã gõ như ô thường. */
  var suggestPartners = HD.debounce(function (input, contractId) {
    var term = input.value.trim();
    if (term.length < 2) {
      HD.suggest.close();
      return;
    }
    HD.api("partners", { search: term }).then(function (items) {
      HD.suggest.open(input, items, HD.partnerItemHtml, function (partner) {
        editing = null;   // bỏ chữ đang gõ dở, server điền theo khách đã chọn
        HD.api("set_partner", { contract_id: contractId, partner_id: partner.id }).then(function (row) {
          replaceRow(row);
          HD.toast("Đã điền thông tin " + partner.label);
        }).catch(HD.fail);
      }, HD.PARTNER_HINT);
    }).catch(HD.fail);
  }, 250);

  function replaceRow(row) {
    S.rows = S.rows.map(function (r) { return r.id === row.id ? row : r; });
    var tr = HD.$("hd-list").querySelector('tr[data-id="' + row.id + '"]');
    if (tr) {
      tr.outerHTML = rowHtml(row);
    }
    if (row.id === previewId) {
      showPreview(row.id);
    }
  }

  /* ---------------------------------------------------------- xem trước dòng đang chọn */

  /** Hiện hợp đồng của dòng id ở khung bên phải (dữ liệu đã lưu, có đánh dấu chỗ từng biến). */
  function showPreview(id) {
    var aside = HD.$("hd-grid-preview");
    HD.show("hd-grid-preview", !!S.gridPreviewOn && !!id);
    HD.$("hd-sheet-body").classList.toggle("with-preview", !!S.gridPreviewOn && !!id);
    if (!S.gridPreviewOn || !id) {
      preview = null;
      return;
    }
    if (previewId !== id || !preview) {
      HD.$("hd-list").querySelectorAll("tr.is-previewing").forEach(function (tr) { tr.classList.remove("is-previewing"); });
      var tr = HD.$("hd-list").querySelector('tr[data-id="' + id + '"]');
      if (tr) {
        tr.classList.add("is-previewing");
      }
    }
    if (!preview) {
      preview = HD.mountLivePreview(aside, { title: "bấm vào để sửa ô đó trong bảng", onPick: editFromPreview });
    }
    previewId = id;
    preview.setStatus("đang tải…");
    HD.api("preview", { contract_id: id, marks: true }).then(function (result) {
      if (preview && previewId === id) {
        preview.setHtml(result.html);
        preview.setStatus(result.name);
      }
    }).catch(function (err) {
      if (preview) {
        preview.setStatus(err.message);
      }
    });
  }

  /** Bấm chỗ biến trên tờ hợp đồng: mở ô tương ứng của dòng đang xem để sửa. */
  function editFromPreview(name) {
    var tr = HD.$("hd-list").querySelector('tr[data-id="' + previewId + '"]');
    var td = tr ? tr.querySelector('td.is-editable[data-cell="' + name + '"]') : null;
    if (td) {
      td.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
      startEdit(td);
    } else {
      HD.toast(name === "So_Hop_Dong" ? "Số hợp đồng tự cấp khi lưu" : "Ô này không sửa được ở đây");
    }
  }

  /** Giá trị ô -> giá trị lưu: số/tiền đọc kiểu Việt ("4.058.000" -> "4058000"), còn lại nguyên văn. */
  function storedValue(type, text) {
    if ((type === "money" || type === "number") && text.trim() !== "") {
      return String(HD.parseNumber(text));
    }
    return text;
  }

  function cancelEdit() {
    if (!editing) {
      return;
    }
    var current = editing;
    editing = null;
    var row = findRow(current.id);
    if (row && current.td.isConnected) {
      current.td.classList.remove("is-editing");
      var col = columns().filter(function (c) { return c.name === current.name; })[0];
      current.td.innerHTML = displayValue(rawValue(row, col), current.type);
    }
  }

  function commitEdit() {
    if (!editing) {
      return Promise.resolve();
    }
    var current = editing;
    var value = storedValue(current.type, current.input.value);
    if (value === current.original) {
      cancelEdit();
      return Promise.resolve();
    }
    editing = null;
    current.td.classList.add("is-saving");
    return HD.api("set_value", { contract_id: current.id, name: current.name, value: value }).then(replaceRow).catch(function (err) {
      editing = current;
      cancelEdit();
      HD.fail(err);
    });
  }

  function editableCells(tr) {
    return Array.prototype.slice.call(tr.querySelectorAll("td.is-editable"));
  }

  function moveEdit(step) {
    var current = editing;
    var tr = current.td.closest("tr");
    var cells = editableCells(tr);
    var index = cells.indexOf(current.td) + step;
    var id = +tr.dataset.id;
    var name = index >= 0 && index < cells.length ? cells[index].dataset.cell : null;
    commitEdit().then(function () {
      var row = HD.$("hd-list").querySelector('tr[data-id="' + id + '"]');
      var next = name && row ? row.querySelector('td[data-cell="' + name + '"]') : null;
      if (next) {
        startEdit(next);
      }
    });
  }

  function addRow() {
    HD.api("save", { template_id: S.sheet }).then(function (detail) {
      S.page = 1;
      return HD.loadGrid().then(function () {
        var tr = HD.$("hd-list").querySelector('tr[data-id="' + detail.id + '"]');
        var first = tr ? tr.querySelector("td.is-editable:not([data-cell=\"contract_date\"])") : null;
        if (first) {
          startEdit(first);
        }
        HD.toast("Đã tạo " + detail.name);
      });
    }).catch(HD.fail);
  }

  HD.initGrid = function () {
    var list = HD.$("hd-list");
    S.gridPreviewOn = HD.previewEnabled();
    HD.on(HD.$("hd-sheet-hint"), "click", "[data-grid-preview-toggle]", function () {
      S.gridPreviewOn = HD.previewEnabled(!S.gridPreviewOn);
      preview = null;
      HD.loadGrid();
    });
    // Bấm vào dòng (chỗ không phải ô sửa / nút) thì xem trước hợp đồng của dòng đó
    HD.on(list, "click", "tr.hd-grid-row", function (tr, event) {
      if (!event.target.closest("input, button, textarea, td.is-editable, [data-lines]")) {
        showPreview(+tr.dataset.id);
      }
    });
    HD.on(list, "click", "td.is-editable", function (td, event) {
      if (!event.target.closest("input, textarea")) {
        startEdit(td);
      }
    });
    HD.on(list, "click", "[data-lines]", function (el) { HD.openContract(+el.dataset.lines); });
    list.addEventListener("keydown", function (event) {
      if (!editing || event.target !== editing.input) {
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        cancelEdit();
      } else if (event.key === "Tab") {
        event.preventDefault();
        moveEdit(event.shiftKey ? -1 : 1);
      } else if (event.key === "Enter" && !(editing.type === "textarea" && event.shiftKey)) {
        event.preventDefault();
        commitEdit();
      }
    });
    list.addEventListener("focusout", function (event) {
      if (editing && event.target === editing.input) {
        // Đợi một nhịp: bấm sang ô khác thì startEdit đã tự lưu ô cũ
        setTimeout(function () {
          if (editing && document.activeElement !== editing.input) {
            commitEdit();
          }
        }, 120);
      }
    });
    HD.$("hd-grid-add").addEventListener("click", addRow);
  };
})(window.HlvContract);
