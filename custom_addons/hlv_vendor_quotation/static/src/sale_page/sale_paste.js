/* "Dán danh sách" trong hộp lập phiếu: sale dán nguyên tin Zalo / cột Excel ("Vòng bi 6212-ZZCM
   NSK: 2 cái", "2608595053:  6"…), server tách dòng + dò sản phẩm theo mã
   (services/product_paste.py), sale xem lại: xanh = khớp, vàng = nhiều khả năng (chọn đúng
   mã), xám = không thấy (bỏ qua hoặc tìm tay). Dán nhiều dòng vào ô "Thêm sản phẩm" cũng mở
   khung này. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var rows = [];

  function statusTag(row) {
    return row.status === "matched" ? '<span class="hq-tag hq-tag-ok">khớp</span>'
      : row.status === "ambiguous" ? '<span class="hq-tag hq-tag-warn">chọn mã</span>'
      : '<span class="hq-tag hq-tag-soft">không thấy</span>';
  }

  function productCell(row, index) {
    if (!row.candidates.length) {
      return '<span class="hq-muted">Không tìm thấy sản phẩm — tìm tay ở ô "Thêm sản phẩm"</span>';
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
    var ready = rows.filter(function (r) { return r.use && r.product; }).length;
    box.innerHTML = '<div class="hq-table-wrap"><table class="hq-table hq-paste-table"><thead><tr><th></th>' +
      "<th>Dòng đã dán</th><th>Sản phẩm</th><th class=\"hq-num\">SL</th></tr></thead><tbody>" +
      rows.map(function (row, index) {
        return '<tr class="hq-paste-' + row.status + '"><td><input type="checkbox" data-paste-use="' + index + '"' +
          (row.use ? " checked" : "") + (row.product ? "" : " disabled") + ' aria-label="Thêm dòng này"/></td>' +
          '<td><div class="hq-paste-raw">' + esc(row.raw) + "</div>" + statusTag(row) + "</td>" +
          "<td>" + productCell(row, index) + "</td>" +
          '<td class="hq-num"><input type="number" min="0" step="any" class="hq-qty" data-paste-qty="' + index +
          '" value="' + row.qty + '"/>' + (row.qty_found ? "" : '<div class="hq-muted hq-small">chưa ghi SL</div>') + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<div class="hq-paste-actions"><button type="button" class="hq-btn hq-btn-primary" id="hq-paste-add"' +
      (ready ? "" : " disabled") + ">Thêm " + ready + " sản phẩm vào phiếu</button>" +
      '<span class="hq-muted hq-small">Dòng vàng: chọn đúng mã rồi tick. Dòng xám: tìm tay ở ô "Thêm sản phẩm".</span></div>';
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

  function addToInquiry() {
    var lines = rows.filter(function (r) { return r.use && r.product && r.qty > 0; }).map(function (r) {
      return Object.assign({}, r.product, { qty: r.qty });
    });
    HQ.addCreateLines(lines);
    HQ.toast("Đã thêm " + lines.length + " sản phẩm");
    close();
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
