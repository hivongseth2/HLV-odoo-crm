/* "Dán danh sách" trong hộp lập phiếu: sale dán nguyên tin Zalo / cột Excel ("Vòng bi 6212-ZZCM
   NSK: 2 cái", "2608595053:  6"…), server tách dòng + dò sản phẩm theo mã
   (services/product_paste.py), sale xem lại: xanh = khớp, vàng = nhiều khả năng (chọn đúng
   mã), xám = không thấy (bỏ qua, tìm tay, hoặc tìm trên MISA CRM — chọn hàng CRM thì khi thêm vào
   phiếu sản phẩm được tạo trong Odoo, sale_crm_product.js). Dán nhiều dòng vào ô "Thêm sản phẩm"
   cũng mở khung này. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var rows = [];

  /** Dòng thêm được vào phiếu: có sản phẩm Odoo, hoặc đã chọn hàng trên MISA CRM. */
  function ready(row) {
    return !!(row.product || row.crmCode);
  }

  function statusTag(row) {
    if (row.crm) {
      return '<span class="hq-tag hq-tag-warn">MISA CRM</span>';
    }
    return row.status === "matched" ? '<span class="hq-tag hq-tag-ok">khớp</span>'
      : row.status === "ambiguous" ? '<span class="hq-tag hq-tag-warn">chọn mã</span>'
      : '<span class="hq-tag hq-tag-soft">không thấy</span>';
  }

  function productCell(row, index) {
    if (row.crm) {
      if (!row.crm.candidates.length) {
        return '<span class="hq-muted">MISA CRM cũng không có — tìm tay ở ô "Thêm sản phẩm"</span>';
      }
      return '<select class="hq-input w-100" data-paste-crm="' + index + '">' +
        '<option value="">— Chọn hàng trên MISA CRM —</option>' + row.crm.candidates.map(function (p) {
          return '<option value="' + esc(p.code) + '"' + (p.code === row.crmCode ? " selected" : "") +
            (p.is_combo ? " disabled" : "") + ">" + esc(HQ.crmLabel(p)) + (p.is_combo ? " (combo)" : "") + "</option>";
        }).join("") + "</select>" +
        '<div class="hq-muted hq-small">Chưa có trong Odoo — thêm vào phiếu là tạo sản phẩm theo CRM.</div>';
    }
    if (!row.candidates.length) {
      return '<span class="hq-muted">Không có trong Odoo</span>';
    }
    if (row.status === "matched" && row.candidates.length === 1) {
      return '<span class="hq-strong">' + esc(row.product.product) + "</span>";
    }
    var selected = row.product ? row.product.product_id : null;
    return '<select class="hq-input w-100" data-paste-product="' + index + '">' +
      (selected ? "" : '<option value="">— Chọn đúng mã —</option>') +
      row.candidates.map(function (p) {
        return '<option value="' + p.product_id + '"' + (p.product_id === selected ? " selected" : "") + ">" +
          esc(p.product) + "</option>";
      }).join("") + "</select>";
  }

  function render() {
    var box = HQ.$("hq-paste-result");
    if (!rows.length) {
      box.innerHTML = '<div class="hq-muted">Không đọc được mặt hàng nào. Mỗi dòng một mặt hàng, có mã hàng — ' +
        'VD "Vòng bi 6212-ZZCM NSK: 2 cái".</div>';
      return;
    }
    var count = rows.filter(function (r) { return r.use && ready(r); }).length;
    var missing = rows.filter(function (r) { return r.status === "missing" && !r.crm; }).length;
    box.innerHTML = '<div class="hq-table-wrap"><table class="hq-table hq-paste-table"><thead><tr><th></th>' +
      "<th>Dòng đã dán</th><th>Sản phẩm</th><th class=\"hq-num\">SL</th></tr></thead><tbody>" +
      rows.map(function (row, index) {
        return '<tr class="hq-paste-' + row.status + '"><td><input type="checkbox" data-paste-use="' + index + '"' +
          (row.use ? " checked" : "") + (ready(row) ? "" : " disabled") + ' aria-label="Thêm dòng này"/></td>' +
          '<td><div class="hq-paste-raw">' + esc(row.raw) + "</div>" + statusTag(row) + "</td>" +
          "<td>" + productCell(row, index) + "</td>" +
          '<td class="hq-num"><input type="number" min="0" step="any" class="hq-qty" data-paste-qty="' + index +
          '" value="' + row.qty + '"/>' + (row.qty_found ? "" : '<div class="hq-muted hq-small">chưa ghi SL</div>') + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<div class="hq-paste-actions"><button type="button" class="hq-btn hq-btn-primary" id="hq-paste-add"' +
      (count ? "" : " disabled") + ">Thêm " + count + " sản phẩm vào phiếu</button>" +
      (missing ? '<button type="button" class="hq-btn" id="hq-paste-crm">Tìm ' + missing + " dòng không thấy trên MISA CRM</button>" : "") +
      '<span class="hq-muted hq-small">Dòng vàng: chọn đúng mã rồi tick. Dòng xám: tìm trên MISA CRM hoặc tìm tay ở ô "Thêm sản phẩm".</span></div>';
  }

  function run(text) {
    var box = HQ.$("hq-paste-result");
    box.innerHTML = '<div class="hq-loading">Đang nhận diện…</div>';
    HQ.rpc("/api/hoi-gia-ncc/parse_products", { text: text }).then(function (res) {
      rows = (res.rows || []).map(function (row) {
        // Chỉ tick sẵn dòng chắc chắn; dòng vàng chờ sale chọn mã.
        return Object.assign({}, row, { use: row.status === "matched" });
      });
      render();
    }).catch(function (err) {
      box.innerHTML = '<div class="hq-alert">' + esc(err.message) + "</div>";
    });
  }

  function open(text) {
    HQ.show("hq-paste-box", true);
    var area = HQ.$("hq-paste-text");
    if (text) {
      area.value = text;
      run(text);
    } else {
      area.focus();
    }
  }

  function close() {
    HQ.show("hq-paste-box", false);
    HQ.$("hq-paste-text").value = "";
    HQ.$("hq-paste-result").innerHTML = "";
    rows = [];
  }

  /** Dòng "không thấy" → tìm trên MISA CRM; chọn sẵn hàng CRM khi chấm điểm chắc chắn. */
  function searchCrm(button) {
    var targets = rows.filter(function (r) { return r.status === "missing" && !r.crm; });
    button.disabled = true;
    button.textContent = "Đang tìm trên MISA CRM…";
    HQ.crmMatchRows(targets.map(function (r) { return r.raw; })).then(function (found) {
      targets.forEach(function (row, i) {
        row.crm = found[i] || { best: "", candidates: [] };
        row.crmCode = row.crm.best;
        row.use = !!row.crmCode;
      });
      render();
    }).catch(function (err) {
      HQ.toast(err.message);
      render();
    });
  }

  /** Thêm vào phiếu; dòng chọn hàng CRM thì tạo sản phẩm Odoo trước. Mã tạo lỗi: giữ dòng lại. */
  function addToInquiry(button) {
    var picked = rows.filter(function (r) { return r.use && ready(r) && r.qty > 0; });
    var fromCrm = picked.filter(function (r) { return !r.product; });
    button.disabled = true;
    var created = fromCrm.length ? HQ.crmImport(fromCrm.map(function (r) { return r.crmCode; })) : Promise.resolve([]);
    created.then(function (results) {
      var errors = [];
      fromCrm.forEach(function (row, i) {
        var result = results[i] || { error: "Không tạo được " + row.crmCode };
        if (result.product) {
          row.product = result.product;
        } else {
          errors.push(result.error);
        }
      });
      var done = picked.filter(function (r) { return r.product; });
      HQ.addCreateLines(done.map(function (r) { return Object.assign({}, r.product, { qty: r.qty }); }));
      if (errors.length) {
        rows = rows.filter(function (r) { return done.indexOf(r) < 0; });
        render();
        HQ.toast("Đã thêm " + done.length + " sản phẩm. Lỗi: " + errors.join("; "));
        return;
      }
      HQ.toast("Đã thêm " + done.length + " sản phẩm" + (fromCrm.length ? " (" + fromCrm.length + " tạo từ MISA CRM)" : ""));
      close();
    }).catch(function (err) {
      button.disabled = false;
      HQ.toast(err.message);
    });
  }

  HQ.bindPasteEvents = function () {
    var modal = HQ.$("hq-modal");
    HQ.$("hq-paste-open").addEventListener("click", function () { open(""); });
    HQ.$("hq-paste-cancel").addEventListener("click", close);
    HQ.$("hq-paste-run").addEventListener("click", function () { run(HQ.$("hq-paste-text").value); });
    // Dán nhiều dòng vào ô "Thêm sản phẩm" → chuyển sang khung dán danh sách.
    HQ.$("hq-prod-search").addEventListener("paste", function (event) {
      var text = event.clipboardData && event.clipboardData.getData("text");
      if (text && text.trim().indexOf("\n") >= 0) {
        event.preventDefault();
        open(text);
      }
    });
    HQ.on(modal, "change", "[data-paste-product]", function (el) {
      var row = rows[+el.dataset.pasteProduct];
      row.product = row.candidates.find(function (p) { return p.product_id === +el.value; }) || null;
      row.use = !!row.product;
      render();
    });
    HQ.on(modal, "change", "[data-paste-crm]", function (el) {
      var row = rows[+el.dataset.pasteCrm];
      row.crmCode = el.value;
      row.use = !!row.crmCode;
      render();
    });
    HQ.on(modal, "click", "#hq-paste-crm", searchCrm);
    HQ.on(modal, "change", "[data-paste-use]", function (el) {
      rows[+el.dataset.pasteUse].use = el.checked;
      render();
    });
    HQ.on(modal, "change", "[data-paste-qty]", function (el) {
      rows[+el.dataset.pasteQty].qty = parseFloat(el.value) || 0;
    });
    HQ.on(modal, "click", "#hq-paste-add", addToInquiry);
  };
})(window.HlvQuote);
