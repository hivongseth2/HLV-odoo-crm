/* Hộp "Hỏi giá NCC": chọn mặt hàng (từ đơn bán, từ YCMH hoặc tự thêm), chọn NCC (gợi ý +
   tự thêm), hạn & lời nhắn, gửi — rồi hiện tin nhắn copy gửi Zalo cho từng NCC.
   Từ đơn bán mà chưa có YCMH: server tạo YCMH cho đơn đó ngay lúc gửi. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var S = HQ.S;
  var C = S.create;
  var esc = HQ.esc;
  var DEFAULT_DEADLINE_DAYS = 2;
  // Gợi ý chỉ để tham khảo: hiện vài NCC đầu, phần còn lại mở khi cần.
  var SUGGEST_VISIBLE = 5;

  HQ.openCreate = function (vendor) {
    C.request = null;
    C.saleOrder = null;
    C.lines = [];
    C.chosen = vendor ? [{ id: vendor.id, name: vendor.name }] : [];
    C.suggestions = [];
    C.quotedVendorIds = [];
    C.showAllSuggestions = false;
    HQ.$("hq-deadline").value = HQ.addDays(S.config.today, DEFAULT_DEADLINE_DAYS);
    HQ.$("hq-note").value = "";
    HQ.$("hq-modal-title").textContent = "Hỏi giá nhà cung cấp";
    HQ.show("hq-modal-foot", true);
    HQ.$("hq-modal-body").classList.remove("hq-hidden");
    removeResults();
    HQ.showAlert("hq-modal-alert", "");
    renderAll();
    HQ.show("hq-modal", true);
  };

  function renderAll() {
    renderSourceChips();
    renderLines();
    renderChosen();
    renderSuggestions();
    renderSummary();
  }

  /* ---------------- Mặt hàng ---------------- */

  /** Dòng sale tự thêm — giữ lại khi đổi nguồn (đơn bán / YCMH). */
  function manualLines() {
    return C.lines.filter(function (l) { return !l.request_line_id && !l.sale_line_id; });
  }

  function pickSaleOrder(order) {
    HQ.rpc("/api/hoi-gia-ncc/sale_order_lines", { order_id: order.id }).then(function (res) {
      C.saleOrder = res.order;
      C.request = null;
      C.quotedVendorIds = [];
      C.lines = manualLines().concat(res.lines);
      if (!res.lines.length) {
        HQ.toast("Đơn này không có mặt hàng mua được");
      }
      renderAll();
      refreshSuggestions();
    }).catch(function (err) { HQ.toast(err.message); });
  }

  function pickRequest(req) {
    HQ.rpc("/api/hoi-gia-ncc/request_lines", { request_id: req.id }).then(function (res) {
      C.request = res.request;
      // YCMH đã mang theo đơn bán; dòng của nguồn cũ bỏ, dòng tự thêm giữ.
      C.saleOrder = null;
      C.lines = manualLines();
      res.lines.forEach(function (line) { C.lines = HQ.mergeLine(C.lines, line); });
      if (!res.lines.length) {
        HQ.toast("YCMH này không còn mặt hàng nào cần mua");
      }
      renderAll();
      refreshSuggestions();
    }).catch(function (err) { HQ.toast(err.message); });
  }

  function renderSourceChips() {
    var chip = "";
    if (C.request) {
      chip = '<span class="hq-chip hq-chip-blue">YCMH ' + esc(C.request.name) +
        (C.request.sale_order ? " · " + esc(C.request.sale_order) : "") +
        '<button type="button" class="hq-chip-x" data-unlink-request="1" title="Bỏ YCMH">×</button></span>';
    } else if (C.saleOrder) {
      chip = '<span class="hq-chip hq-chip-blue">Đơn bán ' + esc(C.saleOrder.name) +
        (C.saleOrder.partner ? " · " + esc(C.saleOrder.partner) : "") +
        (C.saleOrder.sale_code ? " · " + esc(C.saleOrder.sale_code) : "") +
        '<button type="button" class="hq-chip-x" data-unlink-order="1" title="Bỏ đơn bán">×</button></span>';
    }
    HQ.$("hq-req-chip").innerHTML = chip;

    // Server quyết định gộp hay tạo mới (purchase.request._add_sale_order_lines); ở đây chỉ
    // báo trước cho sale thấy điều sẽ xảy ra.
    var note = HQ.$("hq-source-note");
    if (C.saleOrder && !C.request) {
      var merge = C.saleOrder.merge_request;
      var others = C.saleOrder.requests.filter(function (r) { return !merge || r.id !== merge.id; });
      note.innerHTML = (merge
        ? "Khi gửi sẽ <b>gộp vào " + esc(merge.name) + "</b> (chưa duyệt): cùng sản phẩm thì cộng số lượng, " +
          "NCC đã hỏi cho YCMH đó được bổ sung hàng vào báo giá cũ."
        : "Khi gửi sẽ tạo YCMH mới (chờ phê duyệt) gồm các mặt hàng bên dưới.") +
        (others.length ? " YCMH khác của đơn: " + others.map(function (r) {
          return '<button type="button" class="hq-link" data-use-request="' + r.id + '">' + esc(r.name) + "</button>";
        }).join(", ") + " — bấm để hỏi giá cho YCMH đó." : "");
    }
    note.classList.toggle("hq-hidden", !(C.saleOrder && !C.request));
  }

  function renderLines() {
    HQ.$("hq-lines").innerHTML = C.lines.length
      ? '<table class="hq-table hq-table-edit"><thead><tr><th></th><th>Mặt hàng</th>' +
        '<th class="hq-num">Số lượng</th><th>ĐVT</th><th></th></tr></thead><tbody>' +
        C.lines.map(function (l, index) {
          return "<tr>" +
            '<td><img class="hq-thumb" loading="lazy" src="/web/image/product.product/' + l.product_id +
            '/image_128" alt=""/></td>' +
            '<td><div class="hq-strong">' + esc(l.name || l.product) + "</div>" +
            (l.request_line_id ? '<span class="hq-tag hq-tag-mine">Từ YCMH</span>' : "") + "</td>" +
            '<td class="hq-num"><input type="number" min="0" step="any" class="hq-qty" data-line="' +
            index + '" value="' + l.qty + '"/></td>' +
            "<td>" + esc(l.uom) + "</td>" +
            '<td><button type="button" class="hq-icon-btn" data-remove-line="' + index +
            '" title="Bỏ dòng">×</button></td></tr>';
        }).join("") + "</tbody></table>"
      : '<div class="hq-muted">Chưa có mặt hàng. Chọn một YCMH hoặc tìm sản phẩm để thêm.</div>';
  }

  /* ---------------- Nhà cung cấp ---------------- */

  var refreshSuggestions = HQ.debounce(function () {
    var productIds = C.lines.map(function (l) { return l.product_id; });
    if (!productIds.length) {
      C.suggestions = [];
      renderSuggestions();
      return;
    }
    HQ.$("hq-suggestions").innerHTML = '<div class="hq-loading">Đang tìm NCC phù hợp…</div>';
    HQ.rpc("/api/hoi-gia-ncc/suggest", {
      product_ids: productIds,
      // Sắp gộp vào YCMH chưa duyệt thì đánh dấu NCC đã hỏi cho YCMH đó.
      request_id: C.request ? C.request.id
        : (C.saleOrder && C.saleOrder.merge_request ? C.saleOrder.merge_request.id : null),
    }).then(function (res) {
      C.suggestions = res.suggestions || [];
      C.quotedVendorIds = res.quoted_vendor_ids || [];
      renderSuggestions();
      renderChosen();
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
      var quoted = C.quotedVendorIds.indexOf(v.id) !== -1;
      return '<span class="hq-chip hq-chip-green"' +
        (quoted ? ' title="Đã có báo giá cho YCMH này — hàng mới được bổ sung vào báo giá đó"' : "") + ">" +
        esc(v.name) + (quoted ? " (bổ sung báo giá cũ)" : "") +
        '<button type="button" class="hq-chip-x" data-unchoose="' + v.id + '">×</button></span>';
    }).join("");
  }

  function renderSuggestions() {
    var box = HQ.$("hq-suggestions");
    if (!C.lines.length) {
      box.innerHTML = "";
      return;
    }
    if (!C.suggestions.length) {
      box.innerHTML = '<div class="hq-muted">Chưa có lịch sử mua các mặt hàng này — tìm NCC ở ô phía trên.</div>';
      return;
    }
    var visible = C.showAllSuggestions ? C.suggestions : C.suggestions.slice(0, SUGGEST_VISIBLE);
    var hidden = C.suggestions.length - visible.length;
    box.innerHTML = visible.map(function (s) {
      var on = isChosen(s.partner_id);
      var stats = s.matched + "/" + s.total + " mặt hàng · " + s.order_count + " đơn" +
        (s.last_date ? " · " + s.last_date : "") + (s.from_pricelist ? " · có bảng giá" : "") +
        (C.quotedVendorIds.indexOf(s.partner_id) !== -1 ? " · đã hỏi" : "");
      // Tên các mặt hàng NCC từng bán để trong tooltip, cho mỗi gợi ý gọn một dòng.
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
    var vendors = C.chosen;
    var merge = C.saleOrder && !C.request && C.saleOrder.merge_request;
    HQ.$("hq-summary").textContent = C.lines.length + " mặt hàng · " + vendors.length + " nhà cung cấp" +
      (C.saleOrder && !C.request ? (merge ? " · gộp vào " + merge.name : " · tạo YCMH mới") : "");
    HQ.$("hq-submit").disabled = !C.lines.length || !vendors.length;
  }

  /* ---------------- Gửi ---------------- */

  function submit() {
    HQ.showAlert("hq-modal-alert", "");
    HQ.$("hq-submit").disabled = true;
    HQ.rpc("/api/hoi-gia-ncc/create", {
      request_id: C.request ? C.request.id : null,
      sale_order_id: C.saleOrder && !C.request ? C.saleOrder.id : null,
      lines: C.lines,
      vendor_ids: C.chosen.map(function (v) { return v.id; }),
      deadline: HQ.$("hq-deadline").value,
      note: HQ.$("hq-note").value,
    }).then(function (res) {
      showResults(res.results || [], res.request_result);
      HQ.loadVendors();
      HQ.loadQuotes();
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

  function showResults(results, requestResult) {
    HQ.$("hq-modal-title").textContent = "Đã tạo " + results.length + " yêu cầu báo giá — gửi cho NCC";
    HQ.$("hq-modal-body").classList.add("hq-hidden");
    HQ.show("hq-modal-foot", false);
    removeResults();
    var box = document.createElement("div");
    box.id = "hq-results";
    box.className = "hq-modal-body";
    box.innerHTML = (requestResult ? '<div class="hq-source-note">' +
      (requestResult.merged ? "Đã gộp hàng vào yêu cầu mua hàng <b>" : "Đã tạo yêu cầu mua hàng <b>") +
      esc(requestResult.name) + "</b> cho đơn " + esc(requestResult.sale_order) +
      " — đang chờ phê duyệt.</div>" : "") +
      '<p class="hq-muted">Copy tin nhắn dưới đây gửi Zalo cho từng NCC. ' +
      "Tin nhắn có sẵn link và mật khẩu; NCC báo giá xong sẽ hiện trong danh sách.</p>" +
      results.map(function (r, index) {
        return '<div class="hq-result"><div class="hq-share-head"><b>' + esc(r.vendor_name) + "</b>" +
          '<span class="hq-muted">' + esc(r.name) + "</span><span class=\"hq-spacer\"></span>" +
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

    HQ.bindPicker("hq-req-search", "hq-req-results", function (term) {
      return HQ.rpc("/api/hoi-gia-ncc/requests", { search: term }).then(function (r) { return r.requests; });
    }, function (r) {
      return '<span class="hq-strong">' + esc(r.name) + "</span> " +
        '<span class="hq-muted hq-small">' + esc([r.sale_order || r.origin, r.requested_by, r.date]
          .filter(Boolean).join(" · ")) + "</span>";
    }, pickRequest);

    HQ.bindPicker("hq-prod-search", "hq-prod-results", function (term) {
      return HQ.rpc("/api/hoi-gia-ncc/products", { search: term }).then(function (r) { return r.products; });
    }, function (p) {
      return esc(p.product) + ' <span class="hq-muted hq-small">' + esc(p.uom) + "</span>";
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
    HQ.on(modal, "click", "[data-unlink-request]", function () {
      C.request = null;
      C.lines = manualLines();
      C.quotedVendorIds = [];
      renderAll();
      refreshSuggestions();
    });
    HQ.on(modal, "click", "[data-unlink-order]", function () {
      C.saleOrder = null;
      C.lines = manualLines();
      renderAll();
      refreshSuggestions();
    });
    HQ.on(modal, "click", "[data-use-request]", function (el) {
      pickRequest({ id: +el.dataset.useRequest });
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
    HQ.on(modal, "click", "[data-unchoose]", function (el) {
      toggleVendor({ id: +el.dataset.unchoose });
    });
    HQ.on(modal, "click", "[data-copy-result]", function (el) {
      HQ.copy(HQ.$("hq-result-" + el.dataset.copyResult).textContent);
    });
    HQ.$("hq-submit").addEventListener("click", submit);
  };
})(window.HlvQuote);
