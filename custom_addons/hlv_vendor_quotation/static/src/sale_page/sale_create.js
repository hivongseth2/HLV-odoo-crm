/* Hộp "Hỏi giá NCC": sale hỏi giá theo SẢN PHẨM — thêm sản phẩm (hoặc lấy hàng từ một đơn
   bán), chọn NCC (gợi ý theo lịch sử mua + tự thêm), hạn & lời nhắn, gửi — rồi hiện tin
   nhắn copy gửi Zalo cho từng NCC. Chọn giá và lên YCMH làm sau, ở ngăn chi tiết phiếu. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var S = HQ.S;
  var C = S.create;
  var esc = HQ.esc;
  var DEFAULT_DEADLINE_DAYS = 2;
  // Gợi ý chỉ để tham khảo: hiện vài NCC đầu, phần còn lại mở khi cần.
  var SUGGEST_VISIBLE = 5;

  /** Mở hộp lập phiếu điền sẵn sản phẩm + NCC (nút "Dùng giá này" ở khung giá đã hỏi). */
  HQ.openCreateWith = function (lines, vendors) {
    HQ.openCreate();
    lines.forEach(function (line) { C.lines = HQ.mergeLine(C.lines, line); });
    vendors.forEach(function (v) {
      if (!isChosen(v.id)) {
        C.chosen.push(v);
      }
    });
    renderAll();
    refreshSuggestions();
  };

  HQ.openCreate = function () {
    C.saleOrder = null;
    C.lines = [];
    var vendor = S.vendors.find(function (v) { return v.id === S.vendorId; });
    C.chosen = vendor ? [{ id: vendor.id, name: vendor.name }] : [];
    C.suggestions = [];
    C.priceHints = {};
    C.showAllSuggestions = false;
    HQ.$("hq-deadline").value = HQ.addDays(S.config.today, DEFAULT_DEADLINE_DAYS);
    HQ.$("hq-note").value = "";
    renderCodePicker();
    HQ.$("hq-modal-title").textContent = "Hỏi giá nhà cung cấp";
    HQ.show("hq-modal-foot", true);
    HQ.$("hq-modal-body").classList.remove("hq-hidden");
    removeResults();
    HQ.showAlert("hq-modal-alert", "");
    renderAll();
    HQ.show("hq-modal", true);
  };

  /** Đang xem "Tất cả" thì phiếu phải chọn một mã sale cụ thể (hoặc để trống nếu là thu mua). */
  function renderCodePicker() {
    var all = S.code === S.config.all_code;
    HQ.show("hq-create-code-wrap", all);
    if (all) {
      HQ.$("hq-create-code").innerHTML = '<option value="' + esc(S.config.all_code) + '">— Không gắn mã sale —</option>' +
        S.config.codes.map(function (c) {
          return '<option value="' + esc(c.code) + '">' + esc(c.code) + "</option>";
        }).join("");
    }
  }

  function createCode() {
    return S.code === S.config.all_code ? HQ.$("hq-create-code").value : S.code;
  }

  function renderAll() {
    renderSourceChip();
    renderLines();
    renderChosen();
    renderSuggestions();
    renderSummary();
  }

  /* ---------------- Sản phẩm ---------------- */

  function pickSaleOrder(order) {
    HQ.rpc("/api/hoi-gia-ncc/sale_order_lines", { order_id: order.id }).then(function (res) {
      C.saleOrder = res.order;
      res.lines.forEach(function (line) { C.lines = HQ.mergeLine(C.lines, line); });
      if (!res.lines.length) {
        HQ.toast("Đơn này không có mặt hàng mua được");
      }
      renderAll();
      refreshSuggestions();
    }).catch(function (err) { HQ.toast(err.message); });
  }

  function renderSourceChip() {
    HQ.$("hq-req-chip").innerHTML = C.saleOrder
      ? '<span class="hq-chip hq-chip-blue">Đơn bán ' + esc(C.saleOrder.name) +
        (C.saleOrder.partner ? " · " + esc(C.saleOrder.partner) : "") +
        '<button type="button" class="hq-chip-x" data-unlink-order="1" title="Bỏ gắn đơn bán">×</button></span>' +
        '<span class="hq-muted">Phiếu gắn đơn này; khi lên YCMH vẫn đổi được.</span>'
      : "";
  }

  function renderLines() {
    HQ.$("hq-lines").innerHTML = C.lines.length
      ? '<table class="hq-table hq-table-edit"><thead><tr><th></th><th>Sản phẩm</th>' +
        '<th class="hq-num">Số lượng</th><th>ĐVT</th><th></th></tr></thead><tbody>' +
        C.lines.map(function (l, index) {
          return "<tr>" +
            '<td><img class="hq-thumb" loading="lazy" src="/web/image/product.product/' + l.product_id +
            '/image_128" alt=""/></td>' +
            '<td><div class="hq-strong">' + esc(l.name || l.product) + "</div>" +
            HQ.priceHintHtml((C.priceHints || {})[l.product_id]) + "</td>" +
            '<td class="hq-num"><input type="number" min="0" step="any" class="hq-qty" data-line="' +
            index + '" value="' + l.qty + '"/></td>' +
            "<td>" + esc(l.uom) + "</td>" +
            '<td><button type="button" class="hq-icon-btn" data-remove-line="' + index +
            '" title="Bỏ dòng">×</button></td></tr>';
        }).join("") + "</tbody></table>"
      : '<div class="hq-muted">Chưa có sản phẩm. Tìm sản phẩm để thêm, hoặc lấy hàng từ một đơn bán.</div>';
  }

  /* ---------------- Nhà cung cấp ---------------- */

  var refreshSuggestions = HQ.debounce(function () {
    var productIds = C.lines.map(function (l) { return l.product_id; });
    // Giá đã hỏi (mọi mã sale) hiện dưới từng sản phẩm — để khỏi hỏi trùng.
    HQ.fetchPriceHints(productIds).then(function (hints) {
      C.priceHints = hints;
      renderLines();
    }).catch(function () { /* gợi ý phụ, lỗi thì thôi */ });
    if (!productIds.length) {
      C.suggestions = [];
      renderSuggestions();
      return;
    }
    HQ.$("hq-suggestions").innerHTML = '<div class="hq-loading">Đang tìm NCC phù hợp…</div>';
    HQ.rpc("/api/hoi-gia-ncc/suggest", { product_ids: productIds }).then(function (res) {
      C.suggestions = res.suggestions || [];
      renderSuggestions();
    }).catch(function (err) { HQ.toast(err.message); });
  }, 300);

  function isChosen(partnerId) {
    return C.chosen.some(function (v) { return v.id === partnerId; });
  }

  function toggleVendor(vendor) {
    C.chosen = isChosen(vendor.id)
      ? C.chosen.filter(function (v) { return v.id !== vendor.id; })
      : C.chosen.concat([{ id: vendor.id, name: vendor.name }]);
    renderChosen();
    renderSuggestions();
    renderSummary();
  }

  function renderChosen() {
    HQ.$("hq-chosen").innerHTML = C.chosen.map(function (v) {
      return '<span class="hq-chip hq-chip-green">' + esc(v.name) +
        '<button type="button" class="hq-chip-x" data-unchoose-vendor="' + v.id + '">×</button></span>';
    }).join("");
  }

  function renderSuggestions() {
    var box = HQ.$("hq-suggestions");
    if (!C.lines.length) {
      box.innerHTML = "";
      return;
    }
    if (!C.suggestions.length) {
      box.innerHTML = '<div class="hq-muted">Chưa có lịch sử mua các sản phẩm này — tìm NCC ở ô phía trên.</div>';
      return;
    }
    var visible = C.showAllSuggestions ? C.suggestions : C.suggestions.slice(0, SUGGEST_VISIBLE);
    var hidden = C.suggestions.length - visible.length;
    box.innerHTML = visible.map(function (s) {
      var on = isChosen(s.partner_id);
      var stats = s.matched + "/" + s.total + " sản phẩm · " + s.order_count + " đơn" +
        (s.last_date ? " · " + s.last_date : "") + (s.from_pricelist ? " · có bảng giá" : "");
      // Tên các sản phẩm NCC từng bán để trong tooltip, cho mỗi gợi ý gọn một dòng.
      return '<button type="button" class="hq-suggest' + (on ? " hq-suggest-on" : "") +
        '" data-suggest="' + s.partner_id + '" title="Từng bán: ' + esc(s.matched_products) + '">' +
        '<span class="hq-check-box">' + (on ? "✓" : "") + "</span>" +
        '<span class="hq-suggest-name">' + esc(s.name) + "</span>" +
        '<span class="hq-suggest-stats">' + esc(stats) + "</span></button>";
    }).join("") + (hidden > 0
      ? '<button type="button" class="hq-link" data-more-suggest="1">Xem thêm ' + hidden + " gợi ý</button>"
      : "");
  }

  function renderSummary() {
    HQ.$("hq-summary").textContent = C.lines.length + " sản phẩm · " + C.chosen.length + " nhà cung cấp";
    HQ.$("hq-submit").disabled = !C.lines.length || !C.chosen.length;
  }

  /* ---------------- Gửi ---------------- */

  function submit() {
    HQ.showAlert("hq-modal-alert", "");
    HQ.$("hq-submit").disabled = true;
    HQ.rpc("/api/hoi-gia-ncc/create", {
      code: createCode(),
      lines: C.lines,
      vendor_ids: C.chosen.map(function (v) { return v.id; }),
      sale_order_id: C.saleOrder ? C.saleOrder.id : null,
      deadline: HQ.$("hq-deadline").value,
      note: HQ.$("hq-note").value,
    }).then(function (res) {
      showResults(res);
      HQ.reloadAll();
    }).catch(function (err) {
      HQ.showAlert("hq-modal-alert", err.message);
      renderSummary();
    });
  }

  function removeResults() {
    var old = HQ.$("hq-results");
    if (old) {
      old.remove();
    }
  }

  function showResults(res) {
    var results = res.results || [];
    HQ.$("hq-modal-title").textContent = "Đã tạo phiếu " + res.inquiry.name + " — gửi cho " + results.length + " NCC";
    HQ.$("hq-modal-body").classList.add("hq-hidden");
    HQ.show("hq-modal-foot", false);
    removeResults();
    var box = document.createElement("div");
    box.id = "hq-results";
    box.className = "hq-modal-body";
    box.innerHTML = '<p class="hq-muted">Copy tin nhắn dưới đây gửi Zalo cho từng NCC. ' +
      "NCC báo giá xong, mở phiếu để so giá và chọn NCC cho từng sản phẩm.</p>" +
      results.map(function (r, index) {
        return '<div class="hq-result"><div class="hq-share-head"><b>' + esc(r.vendor_name) + "</b>" +
          '<span class="hq-muted">' + esc(r.name) + "</span>" +
          (r.reused ? '<span class="hq-tag hq-tag-mine" title="NCC đã báo giá các sản phẩm này, giá còn hiệu lực — ' +
            'không cần gửi link">Đã có giá — không cần gửi</span>' : "") + "<span class=\"hq-spacer\"></span>" +
          '<button type="button" class="hq-btn hq-btn-mini hq-btn-primary" data-copy-result="' + index +
          '">Copy tin nhắn</button></div>' +
          '<pre class="hq-share-text" id="hq-result-' + index + '">' + esc(r.share_message) + "</pre></div>";
      }).join("") +
      '<div class="hq-modal-foot"><span class="hq-spacer"></span>' +
      '<button type="button" class="hq-btn hq-btn-primary" data-close="modal">Xong</button></div>';
    HQ.$("hq-modal-body").after(box);
  }

  /* ---------------- Nối sự kiện ---------------- */

  HQ.bindCreateEvents = function () {
    HQ.bindPicker("hq-so-search", "hq-so-results", function (term) {
      return HQ.rpc("/api/hoi-gia-ncc/sale_orders", { search: term }).then(function (r) { return r.orders; });
    }, function (o) {
      return '<span class="hq-strong">' + esc(o.name) + "</span> " +
        '<span class="hq-muted">' + esc([o.partner, o.sale_code, o.date].filter(Boolean).join(" · ")) + "</span>";
    }, pickSaleOrder);

    HQ.bindPicker("hq-prod-search", "hq-prod-results", function (term) {
      return HQ.rpc("/api/hoi-gia-ncc/products", { search: term }).then(function (r) { return r.products; });
    }, function (p) {
      return esc(p.product) + ' <span class="hq-muted">' + esc(p.uom) + "</span>";
    }, function (product) {
      C.lines = HQ.mergeLine(C.lines, product);
      renderLines();
      renderSummary();
      refreshSuggestions();
    });

    HQ.bindPicker("hq-partner-search", "hq-partner-results", function (term) {
      return HQ.rpc("/api/hoi-gia-ncc/partners", { search: term }).then(function (r) { return r.partners; });
    }, function (p) {
      return esc(p.name) + (p.vat ? ' <span class="hq-muted">· MST ' + esc(p.vat) + "</span>" : "");
    }, function (partner) {
      if (!isChosen(partner.id)) {
        toggleVendor(partner);
      }
    });

    var modal = HQ.$("hq-modal");
    HQ.on(modal, "click", "[data-remove-line]", function (el) {
      C.lines.splice(+el.dataset.removeLine, 1);
      renderLines();
      renderSummary();
      refreshSuggestions();
    });
    HQ.on(modal, "change", ".hq-qty", function (el) {
      C.lines[+el.dataset.line].qty = parseFloat(el.value) || 0;
    });
    HQ.on(modal, "click", "[data-unlink-order]", function () {
      C.saleOrder = null;
      renderSourceChip();
    });
    HQ.on(modal, "click", "[data-suggest]", function (el) {
      var id = +el.dataset.suggest;
      var item = C.suggestions.find(function (s) { return s.partner_id === id; });
      toggleVendor({ id: id, name: item ? item.name : "" });
    });
    HQ.on(modal, "click", "[data-more-suggest]", function () {
      C.showAllSuggestions = true;
      renderSuggestions();
    });
    HQ.on(modal, "click", "[data-unchoose-vendor]", function (el) {
      toggleVendor({ id: +el.dataset.unchooseVendor });
    });
    HQ.on(modal, "click", "[data-copy-result]", function (el) {
      HQ.copy(HQ.$("hq-result-" + el.dataset.copyResult).textContent);
    });
    HQ.$("hq-submit").addEventListener("click", submit);
  };
})(window.HlvQuote);
