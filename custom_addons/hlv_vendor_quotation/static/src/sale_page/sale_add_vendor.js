/* "Hỏi thêm NCC" trong ngăn phiếu: NCC đã hỏi báo hết hàng (kể cả khi phiếu đã lên YCMH) thì
   gửi các sản phẩm còn thiếu cho NCC khác — chọn sản phẩm, chọn NCC (gợi ý theo lịch sử mua +
   tự tìm), hạn & lời nhắn, gửi — rồi copy tin nhắn Zalo cho từng NCC mới.
   Ngăn phiếu vẽ lại cả khối mỗi khi có thay đổi (kể cả tải ngầm khi có tin mới), nên mọi thứ
   sale đã chọn / gõ trong hộp giữ ở A chứ không đọc lại từ DOM. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var DEFAULT_DEADLINE_DAYS = 2;
  var SUGGEST_VISIBLE = 5;
  var A = { inquiryId: null };

  function reset(d) {
    A = {
      inquiryId: d.id,
      open: false,
      busy: false,
      lineIds: defaultLines(d),
      chosen: [],         // [{id, name}]
      suggestions: [],
      deadline: HQ.addDays(HQ.S.config.today, DEFAULT_DEADLINE_DAYS),
      note: "",
      results: null,      // kết quả lần gửi gần nhất (tin nhắn Zalo)
    };
  }

  /** Tích sẵn sản phẩm chưa NCC nào báo được giá; không có thì mọi sản phẩm chưa lên đơn mua. */
  function defaultLines(d) {
    var open = d.lines.filter(function (l) { return !l.locked; });
    var needing = open.filter(function (l) { return l.needs_vendor; });
    return (needing.length ? needing : open).map(function (l) { return l.id; });
  }

  function askedIds(d) {
    return d.vendors.map(function (v) { return v.vendor_id; });
  }

  function isChosen(id) {
    return A.chosen.some(function (v) { return v.id === id; });
  }

  /** Khối hộp trong ngăn phiếu (ẩn tới khi bấm "Hỏi thêm NCC"). */
  HQ.addVendorBox = function (d) {
    if (A.inquiryId !== d.id) {
      reset(d);
    }
    if (!d.can_add_vendor) {
      return "";
    }
    return '<div class="hq-share hq-add-box' + (A.open ? "" : " hq-hidden") + '" id="hq-add-box">' +
      '<div class="hq-share-head"><b>Hỏi thêm nhà cung cấp</b><span class="hq-muted">Gửi các sản phẩm đã tích cho ' +
      "NCC mới. NCC đã hỏi giữ nguyên; giá NCC mới báo về hiện thêm cột trong bảng so giá.</span></div>" +
      '<div id="hq-add-done">' + renderResults() + "</div>" +
      '<div id="hq-add-lines" class="hq-add-lines">' + renderLines(d) + "</div>" +
      '<div class="hq-add-vendors"><div class="hq-picker">' +
      '<label class="hq-sr-only" for="hq-add-search">Tìm nhà cung cấp</label>' +
      '<input type="search" id="hq-add-search" class="hq-input w-100" autocomplete="off" ' +
      'placeholder="Tìm nhà cung cấp theo tên, MST…"/>' +
      '<div id="hq-add-results" class="hq-dropdown hq-hidden"></div></div>' +
      '<div id="hq-add-picked">' + renderPicked(d) + "</div></div>" +
      '<div class="hq-close-row"><label class="hq-add-field"><span class="hq-label">Hạn báo giá</span>' +
      '<input type="date" class="hq-input" data-add-field="deadline" min="' + esc(HQ.S.config.today) +
      '" value="' + esc(A.deadline) + '"/></label>' +
      '<label class="hq-add-field hq-close-note"><span class="hq-label">Lời nhắn gửi NCC</span>' +
      '<input type="text" class="hq-input" data-add-field="note" maxlength="500" value="' + esc(A.note) +
      '" placeholder="Trống = dùng lời nhắn của phiếu"/></label>' +
      '<button type="button" class="hq-btn hq-btn-primary" id="hq-add-submit" data-add-submit="1"' +
      (canSubmit() ? "" : " disabled") + ">" + submitLabel() + "</button>" +
      '<button type="button" class="hq-btn" data-add-toggle="1">Thôi</button></div></div>';
  };

  function canSubmit() {
    return A.chosen.length > 0 && A.lineIds.length > 0 && !A.busy;
  }

  function submitLabel() {
    return "Gửi hỏi giá" + (A.chosen.length ? " " + A.chosen.length + " NCC" : "");
  }

  function renderLines(d) {
    return d.lines.map(function (l) {
      var on = A.lineIds.indexOf(l.id) >= 0;
      return '<label class="hq-add-line' + (l.locked ? " hq-muted" : "") + '"><input type="checkbox" data-add-line="' +
        l.id + '"' + (on && !l.locked ? " checked" : "") + (l.locked ? " disabled" : "") + "/> " +
        '<span class="hq-strong">' + esc(l.name) + "</span> " +
        '<span class="hq-muted">' + HQ.qty(l.qty) + " " + esc(l.uom) +
        (l.locked ? " · đã lên đơn mua" : l.needs_vendor ? " · chưa NCC nào có giá" : "") + "</span></label>";
    }).join("");
  }

  /** NCC đã chọn (chip) + gợi ý theo lịch sử mua. */
  function renderPicked(d) {
    return '<div class="hq-chip-row">' + A.chosen.map(function (v) {
      return '<span class="hq-chip hq-chip-green">' + esc(v.name) +
        '<button type="button" class="hq-chip-x" data-add-unchoose="' + v.id + '">×</button></span>';
    }).join("") + "</div>" + renderSuggestions(d);
  }

  function renderSuggestions(d) {
    var asked = askedIds(d);
    var items = A.suggestions.filter(function (s) { return asked.indexOf(s.partner_id) < 0; })
      .slice(0, SUGGEST_VISIBLE);
    if (!items.length) {
      return "";
    }
    return '<div class="hq-muted hq-small">Gợi ý theo lịch sử mua:</div>' + items.map(function (s) {
      var on = isChosen(s.partner_id);
      return '<button type="button" class="hq-suggest' + (on ? " hq-suggest-on" : "") + '" data-add-suggest="' +
        s.partner_id + '" title="Từng bán: ' + esc(s.matched_products) + '">' +
        '<span class="hq-check-box">' + (on ? "✓" : "") + "</span>" +
        '<span class="hq-suggest-name">' + esc(s.name) + "</span>" +
        '<span class="hq-suggest-stats">' + esc(s.matched + "/" + s.total + " sản phẩm · " + s.order_count + " đơn") +
        "</span></button>";
    }).join("");
  }

  function renderResults() {
    if (!A.results) {
      return "";
    }
    return '<div class="hq-add-done">Đã gửi cho ' + A.results.length + " NCC. Copy tin nhắn gửi Zalo:</div>" +
      A.results.map(function (r, index) {
        return '<div class="hq-result"><div class="hq-share-head"><b>' + esc(r.vendor_name) + "</b>" +
          '<span class="hq-muted">' + esc(r.name) + "</span>" +
          (r.reused ? '<span class="hq-tag hq-tag-mine">Đã có giá — không cần gửi</span>' : "") +
          '<span class="hq-spacer"></span><button type="button" class="hq-btn hq-btn-mini hq-btn-primary" ' +
          'data-add-copy="' + index + '">Copy tin nhắn</button></div>' +
          '<pre class="hq-share-text">' + esc(r.share_message) + "</pre></div>";
      }).join("");
  }

  /** Vẽ lại các phần đổi theo lựa chọn (không tải lại phiếu). Không đụng ô tìm NCC, hạn, lời nhắn —
      gợi ý về chậm vẽ lại cả hộp là mất chữ sale đang gõ. */
  function redraw() {
    var box = HQ.$("hq-add-box");
    var d = HQ.addVendorDetail;
    if (!box || !d) {
      return;
    }
    box.classList.toggle("hq-hidden", !A.open);
    HQ.$("hq-add-done").innerHTML = renderResults();
    HQ.$("hq-add-lines").innerHTML = renderLines(d);
    HQ.$("hq-add-picked").innerHTML = renderPicked(d);
    HQ.$("hq-add-submit").disabled = !canSubmit();
    HQ.$("hq-add-submit").textContent = submitLabel();
  }

  var refreshSuggestions = HQ.debounce(function () {
    var d = HQ.addVendorDetail;
    var productIds = d.lines.filter(function (l) { return A.lineIds.indexOf(l.id) >= 0; })
      .map(function (l) { return l.product_id; });
    if (!productIds.length) {
      A.suggestions = [];
      redraw();
      return;
    }
    HQ.rpc("/api/hoi-gia-ncc/suggest", { product_ids: productIds }).then(function (res) {
      A.suggestions = res.suggestions || [];
      redraw();
    }).catch(function () { /* gợi ý phụ, lỗi thì thôi */ });
  }, 300);

  function toggleVendor(vendor) {
    A.chosen = isChosen(vendor.id)
      ? A.chosen.filter(function (v) { return v.id !== vendor.id; })
      : A.chosen.concat([{ id: vendor.id, name: vendor.name }]);
    redraw();
  }

  /** Ô tìm NCC nằm trong khối vẽ lại — gắn lại sau mỗi lần vẽ ngăn phiếu. */
  HQ.bindAddVendorPicker = function () {
    if (!HQ.$("hq-add-search")) {
      return;
    }
    HQ.bindPicker("hq-add-search", "hq-add-results", function (term) {
      return HQ.rpc("/api/hoi-gia-ncc/partners", { search: term }).then(function (r) { return r.partners; });
    }, function (p) {
      return esc(p.name) + (p.vat ? ' <span class="hq-muted">· MST ' + esc(p.vat) + "</span>" : "");
    }, function (partner) {
      if (askedIds(HQ.addVendorDetail).indexOf(partner.id) >= 0) {
        HQ.toast(partner.name + " đã được hỏi trong phiếu này");
      } else if (!isChosen(partner.id)) {
        toggleVendor(partner);
      }
    });
  };

  function submit() {
    A.busy = true;
    redraw();
    HQ.api("add_vendors", {
      inquiry_id: A.inquiryId,
      vendor_ids: A.chosen.map(function (v) { return v.id; }),
      line_ids: A.lineIds,
      deadline: A.deadline,
      note: A.note,
    }).then(function (detail) {
      var results = detail.add_results;
      reset(detail);
      A.open = true;
      A.results = results;
      HQ.renderInquiry(detail);
      HQ.reloadAll();
    }).catch(function (err) {
      A.busy = false;
      redraw();
      HQ.toast(err.message);
    });
  }

  HQ.bindAddVendorEvents = function () {
    var panel = HQ.$("hq-drawer-panel");
    HQ.on(panel, "click", "[data-add-toggle]", function () {
      A.open = !A.open;
      if (!A.open) {
        A.results = null;
      }
      redraw();
      if (A.open) {
        refreshSuggestions();
        HQ.$("hq-add-box").scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    });
    HQ.on(panel, "change", "[data-add-line]", function (el) {
      var id = +el.dataset.addLine;
      A.lineIds = el.checked ? A.lineIds.concat([id]) : A.lineIds.filter(function (x) { return x !== id; });
      redraw();
      refreshSuggestions();
    });
    HQ.on(panel, "change", "[data-add-field]", function (el) {
      A[el.dataset.addField] = el.value;
    });
    HQ.on(panel, "click", "[data-add-suggest]", function (el) {
      var id = +el.dataset.addSuggest;
      var item = A.suggestions.find(function (s) { return s.partner_id === id; });
      toggleVendor({ id: id, name: item ? item.name : "" });
    });
    HQ.on(panel, "click", "[data-add-unchoose]", function (el) {
      toggleVendor({ id: +el.dataset.addUnchoose });
    });
    HQ.on(panel, "click", "[data-add-copy]", function (el) {
      HQ.copy(A.results[+el.dataset.addCopy].share_message);
    });
    HQ.on(panel, "click", "[data-add-submit]", submit);
  };
})(window.HlvQuote);
