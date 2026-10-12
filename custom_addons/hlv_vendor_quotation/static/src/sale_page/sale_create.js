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

  /** Thêm nhiều dòng một lúc (ô tìm, dán danh sách, cơ hội CRM, đơn bán); trùng sản phẩm thì cộng SL.
      Combo (BoM kit) được tách thành mặt hàng con trước — NCC bán từng thành phần (services/combo_lines.py).
      Trả Promise các dòng đã thêm. */
  HQ.addCreateLines = function (lines) {
    var ready = lines.some(function (l) { return l.is_kit; })
      ? HQ.rpc("/api/hoi-gia-ncc/expand_lines", { lines: lines }).then(function (r) { return r.lines; })
      : Promise.resolve(lines);
    return ready.then(function (rows) {
      rows.forEach(function (line) { C.lines = HQ.mergeLine(C.lines, line); });
      renderLines();
      renderSummary();
      refreshSuggestions();
      if (rows.some(function (l) { return l.combo; })) {
        HQ.toast("Combo đã được tách thành các mặt hàng con để hỏi giá NCC");
      }
      return rows;
    }).catch(function (err) {
      HQ.toast(err.message);
      return [];
    });
  };

  /** Mở hộp lập phiếu điền sẵn sản phẩm + NCC (nút "Dùng giá này" ở khung giá đã hỏi).
      reuse: {product_id: vendor_id} — giá chọn dùng lại sẵn. */
  HQ.openCreateWith = function (lines, vendors, reuse) {
    HQ.openCreate();
    C.reuse = Object.assign({}, reuse || {});
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
    C.lines = [];
    var vendor = S.vendors.find(function (v) { return v.id === S.vendorId; });
    C.chosen = vendor ? [{ id: vendor.id, name: vendor.name }] : [];
    C.suggestions = [];
    C.priceHints = {};
    C.reuse = {};
    C.picks = {};  // gợi ý NCC theo từng mặt hàng (sale_create_ask.js)
    C.ask = {};    // ô tick NCC × mặt hàng sale đã bấm tay
    C.askInfo = {};  // mặt hàng đang mở dẫn chứng gợi ý (nút "i")
    C.showAllSuggestions = false;
    HQ.$("hq-deadline").value = HQ.addDays(S.config.today, DEFAULT_DEADLINE_DAYS);
    HQ.$("hq-note").value = "";
    HQ.$("hq-opportunity").value = "";
    HQ.resetSourcePick();
    HQ.show("hq-crm-results", false);
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
          return '<option value="' + esc(c.code) + '">' + esc(HQ.saleLabel(c.code)) + "</option>";
        }).join("");
    }
  }

  function createCode() {
    return S.code === S.config.all_code ? HQ.$("hq-create-code").value : S.code;
  }

  function renderAll() {
    renderLines();
    renderSuggestions();
    renderSummary();
  }

  /* ---------------- Sản phẩm ---------------- */

  /** Bảng sản phẩm — kiêm luôn chỗ chọn NCC hỏi từng mặt hàng: cột tick mỗi NCC đã chọn, gợi ý NCC + nút "i"
      dưới tên hàng (sale_create_ask.js). */
  function renderLines() {
    HQ.$("hq-lines").innerHTML = C.lines.length
      ? '<table class="hq-table hq-table-edit"><thead><tr><th></th><th>Sản phẩm</th>' +
        '<th class="hq-num">Số lượng</th><th>ĐVT</th>' + HQ.askHeadCells() + "<th></th></tr></thead><tbody>" +
        C.lines.map(function (l, index) {
          return "<tr>" +
            '<td><img class="hq-thumb" loading="lazy" src="/web/image/product.product/' + l.product_id +
            '/image_128" alt=""/></td>' +
            '<td><div class="hq-strong">' + esc(l.name || l.product) + "</div>" +
            (l.combo ? '<div class="hq-muted hq-small">Thành phần của combo ' + esc(l.combo) + "</div>" : "") +
            HQ.priceReuseHtml((C.priceHints || {})[l.product_id], l, C.reuse[l.product_id]) +
            HQ.askLineExtras(l) + "</td>" +
            '<td class="hq-num"><input type="number" min="0" step="any" class="hq-qty" data-line="' +
            index + '" value="' + l.qty + '"/></td>' +
            "<td>" + esc(l.uom) + "</td>" + HQ.askCells(l) +
            '<td><button type="button" class="hq-icon-btn" data-remove-line="' + index +
            '" title="Bỏ dòng">×</button></td></tr>';
        }).join("") + "</tbody>" + HQ.askFootRow(4, 1) + "</table>" +
        (C.chosen.length ? '<div class="hq-muted hq-small">Cột NCC: tick mặt hàng hỏi NCC đó — tick sẵn mặt hàng NCC ' +
          "từng bán; NCC chưa từng bán thì hỏi hết.</div>" : "")
      : '<div class="hq-muted">Chưa có sản phẩm. Tìm sản phẩm để thêm, hoặc lấy hàng từ một đơn bán.</div>';
  }

  /* ---------------- Nhà cung cấp ---------------- */

  var refreshSuggestions = HQ.debounce(function () {
    var productIds = C.lines.map(function (l) { return l.product_id; });
    // Giá đã hỏi (mọi mã sale) hiện dưới từng sản phẩm — để khỏi hỏi trùng.
    HQ.fetchPriceHints(productIds).then(function (hints) {
      C.priceHints = hints;
      renderLines();
      renderSummary();  // có giá dùng lại thì nút đổi thành "Lên YCMH ngay"
    }).catch(function () { /* gợi ý phụ, lỗi thì thôi */ });
    if (!productIds.length) {
      C.suggestions = [];
      C.picks = {};
      renderSuggestions();
      return;
    }
    HQ.$("hq-suggestions").innerHTML = '<div class="hq-loading">Đang tìm NCC phù hợp…</div>';
    HQ.rpc("/api/hoi-gia-ncc/suggest", { product_ids: productIds }).then(function (res) {
      C.suggestions = res.suggestions || [];
      C.picks = res.picks || {};
      renderSuggestions();
      renderLines();
    }).catch(function (err) { HQ.toast(err.message); });
  }, 300);

  function isChosen(partnerId) {
    return C.chosen.some(function (v) { return v.id === partnerId; });
  }

  function toggleVendor(vendor) {
    C.chosen = isChosen(vendor.id)
      ? C.chosen.filter(function (v) { return v.id !== vendor.id; })
      : C.chosen.concat([{ id: vendor.id, name: vendor.name }]);
    renderSuggestions();
    renderSummary();
    renderLines();  // cột NCC trong bảng sản phẩm
  }

  /** Dưới bảng sản phẩm, cạnh ô thêm NCC: NCC gợi ý theo lịch sử mua CHƯA chọn ("+ Tên"), bấm là thêm thành cột.
      NCC đã chọn chỉ hiện ở cột bảng (bỏ bằng × trên tiêu đề) — chưa có sản phẩm (chưa có bảng) thì hiện ở đây. */
  function renderSuggestions() {
    var box = HQ.$("hq-suggestions");
    var chosenHere = C.lines.length ? "" : C.chosen.map(function (v) {
      return '<span class="hq-chip hq-chip-green">' + esc(v.name) +
        '<button type="button" class="hq-chip-x" data-unchoose-vendor="' + v.id + '" title="Bỏ NCC">×</button></span>';
    }).join("");
    var open = C.suggestions.filter(function (s) { return !isChosen(s.partner_id); });
    var visible = C.showAllSuggestions ? open : open.slice(0, SUGGEST_VISIBLE);
    var chips = visible.map(function (s) {
      var stats = s.matched + "/" + s.total + " SP · " + s.order_count + " đơn" + (s.from_pricelist ? " · bảng giá" : "");
      // Tên các sản phẩm NCC từng bán để trong tooltip, cho chip gọn.
      return '<button type="button" class="hq-vendor-chip" data-suggest="' + s.partner_id + '" title="Từng bán: ' +
        esc(s.matched_products) + (s.last_date ? " — mua gần nhất " + esc(s.last_date) : "") + '">+ ' + esc(s.name) +
        ' <span class="hq-ask-pick-why">' + esc(stats) + "</span></button>";
    }).join("");
    var more = open.length - visible.length;
    box.innerHTML = chosenHere + (chips ? '<span class="hq-muted hq-small">Gợi ý theo lịch sử mua:</span>' + chips : "") +
      (more > 0 ? '<button type="button" class="hq-link" data-more-suggest="1">Xem thêm ' + more + " gợi ý</button>" : "");
  }

  /** Giá đang chọn dùng lại cho dòng (còn hợp lệ với số lượng / ĐVT hiện tại) — hoặc null. */
  function pickedPrice(line) {
    var vendorId = C.reuse[line.product_id];
    var price = vendorId && ((C.priceHints || {})[line.product_id] || []).find(function (p) {
      return p.vendor_id === vendorId;
    });
    return price && !HQ.reuseProblem(price, line) ? price : null;
  }

  /** Mọi sản phẩm đều dùng lại giá → không cần hỏi ai, lên YCMH luôn. */
  function allReused() {
    return C.lines.length > 0 && C.lines.every(function (l) { return !!pickedPrice(l); });
  }

  function renderSummary() {
    var reused = C.lines.filter(function (l) { return !!pickedPrice(l); }).length;
    var direct = allReused();
    HQ.$("hq-summary").textContent = C.lines.length + " sản phẩm" + (reused ? " · " + reused + " dùng lại giá" : "") +
      (direct ? " — không cần hỏi NCC" : " · " + C.chosen.length + " nhà cung cấp");
    HQ.$("hq-submit").textContent = direct ? "Lên YCMH ngay" : "Gửi hỏi giá";
    HQ.$("hq-submit").disabled = !C.lines.length || (!direct && !C.chosen.length);
  }

  function pickReuse(productId, vendorId) {
    var price = ((C.priceHints || {})[productId] || []).find(function (p) { return p.vendor_id === vendorId; });
    if (!price) {
      return;
    }
    C.reuse[productId] = vendorId;
    if (!isChosen(vendorId)) {
      C.chosen.push({ id: vendorId, name: price.vendor });
    }
    renderLines();
    renderSuggestions();
    renderSummary();
  }

  /* ---------------- Gửi ---------------- */

  function submit() {
    HQ.showAlert("hq-modal-alert", "");
    // Dùng lại đủ giá là lên YCMH luôn — YCMH bắt buộc có mã sale (người yêu cầu).
    if (allReused() && createCode() === S.config.all_code) {
      HQ.showAlert("hq-modal-alert", "Chọn mã sale của phiếu — phiếu này lên YCMH luôn, YCMH cần người yêu cầu.");
      return;
    }
    // NCC nào hỏi mặt hàng nào. Lên YCMH luôn (dùng lại đủ giá) thì server tự lấy theo giá dùng lại.
    var plan = allReused() ? { ask: null, error: "" } : HQ.askPlan();
    if (plan.error) {
      HQ.showAlert("hq-modal-alert", plan.error);
      return;
    }
    HQ.$("hq-submit").disabled = true;
    var reuse = {};
    C.lines.forEach(function (l) {
      if (pickedPrice(l)) {
        reuse[l.product_id] = C.reuse[l.product_id];
      }
    });
    HQ.rpc("/api/hoi-gia-ncc/create", {
      code: createCode(),
      lines: C.lines,
      vendor_ids: C.chosen.map(function (v) { return v.id; }),
      reuse: reuse,
      request_now: allReused(),
      deadline: HQ.$("hq-deadline").value,
      note: HQ.$("hq-note").value,
      opportunity_ref: HQ.$("hq-opportunity").value,
      sale_order_id: C.saleOrder ? C.saleOrder.id : null,
      ask: plan.ask,
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
    HQ.$("hq-modal-title").textContent = res.request
      ? "Đã lên YCMH " + res.request + " — phiếu " + res.inquiry.name + " dùng lại giá, không hỏi NCC"
      : "Đã tạo phiếu " + res.inquiry.name + " — gửi cho " + results.length + " NCC";
    HQ.$("hq-modal-body").classList.add("hq-hidden");
    HQ.show("hq-modal-foot", false);
    removeResults();
    var box = document.createElement("div");
    box.id = "hq-results";
    box.className = "hq-modal-body";
    var missing = (res.reuse_missing || []).length
      ? '<div class="hq-alert">Không dùng lại được giá cho: ' + res.reuse_missing.map(esc).join(", ") +
        " (vừa hết hiệu lực hoặc có phiếu khác giữ) — NCC sẽ báo giá như bình thường.</div>" : "";
    box.innerHTML = missing + (res.request
      ? '<p class="hq-muted">Thu mua duyệt YCMH rồi tạo đơn mua với đúng NCC và giá đã dùng lại. Mở phiếu ' +
        esc(res.inquiry.name) + " để theo dõi.</p>"
      : '<p class="hq-muted">Copy tin nhắn dưới đây gửi Zalo cho từng NCC. ' +
        "NCC báo giá xong, mở phiếu để so giá và chọn NCC cho từng sản phẩm.</p>") +
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
    // Dòng cuối luôn là "tìm trên MISA CRM": hàng CRM có mà Odoo chưa có (sale_crm_product.js).
    HQ.bindPicker("hq-prod-search", "hq-prod-results", function (term) {
      return HQ.rpc("/api/hoi-gia-ncc/products", { search: term }).then(function (r) {
        return r.products.concat([{ crm_search: term, found: r.products.length }]);
      });
    }, function (p) {
      if (p.crm_search) {
        return '<span class="hq-crm-item">' + (p.found ? "Không thấy đúng hàng? " : "Odoo chưa có. ") +
          "Tìm “" + esc(p.crm_search) + "” trên MISA CRM</span>";
      }
      return esc(p.product) + ' <span class="hq-muted">' + esc(p.uom) + "</span>";
    }, function (product) {
      if (product.crm_search) {
        HQ.openCrmSearch(product.crm_search);
        return;
      }
      HQ.addCreateLines([product]);
    });

    // Không có trong danh bạ thì tạo nhanh bằng MST (sale_vendor_vat.js).
    HQ.bindPicker("hq-partner-search", "hq-partner-results", HQ.fetchVendors, HQ.vendorItemHtml, function (item) {
      return HQ.pickVendorItem(item, "hq-partner-search", function (partner) {
        if (!isChosen(partner.id)) {
          toggleVendor(partner);
        }
      });
    });

    var modal = HQ.$("hq-modal");
    HQ.on(modal, "click", "[data-reuse-pick]", function (el) {
      var parts = el.dataset.reusePick.split(":");
      pickReuse(+parts[0], +parts[1]);
    });
    HQ.on(modal, "click", "[data-reask]", function (el) {
      var parts = el.dataset.reask.split(":");
      var price = ((C.priceHints || {})[+parts[0]] || []).find(function (p) { return p.vendor_id === +parts[1]; });
      if (price && !isChosen(price.vendor_id)) {
        toggleVendor({ id: price.vendor_id, name: price.vendor });
      }
      HQ.toast("Đã thêm " + (price ? price.vendor : "NCC") + " — giá lần trước (trong 7 ngày) sẽ điền sẵn để NCC xác nhận");
    });
    HQ.on(modal, "click", "[data-reuse-unpick]", function (el) {
      delete C.reuse[+el.dataset.reuseUnpick];
      renderLines();
      renderSummary();
    });
    HQ.on(modal, "click", "[data-remove-line]", function (el) {
      var removed = C.lines[+el.dataset.removeLine];
      delete C.reuse[removed.product_id];
      C.lines.splice(+el.dataset.removeLine, 1);
      renderLines();
      renderSummary();
      refreshSuggestions();
    });
    HQ.on(modal, "change", ".hq-qty", function (el) {
      var line = C.lines[+el.dataset.line];
      line.qty = parseFloat(el.value) || 0;
      // Đổi số lượng có thể làm giá đang dùng lại hết hợp lệ (vượt số NCC đã báo) — vẽ lại.
      renderLines();
      renderSummary();
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
    HQ.bindAskEvents(function (vendor) {
      if (!isChosen(vendor.id)) {
        toggleVendor(vendor);
      }
    }, renderLines);
    HQ.on(modal, "click", "[data-unchoose-vendor]", function (el) {
      toggleVendor({ id: +el.dataset.unchooseVendor });
    });
    HQ.on(modal, "click", "[data-copy-result]", function (el) {
      HQ.copy(HQ.$("hq-result-" + el.dataset.copyResult).textContent);
    });
    HQ.$("hq-submit").addEventListener("click", submit);
  };
})(window.HlvQuote);
