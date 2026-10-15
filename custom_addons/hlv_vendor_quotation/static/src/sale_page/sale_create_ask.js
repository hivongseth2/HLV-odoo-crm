/* Hộp lập phiếu — hỏi NCC nào cho TỪNG mặt hàng (không phải NCC nào cũng bán mọi mã), làm thẳng trên bảng
   sản phẩm ở bước 1 (sale_create.js renderLines ghép các phần ở đây, không vẽ bảng mặt hàng thứ hai):
   - mỗi NCC đã chọn một cột tick. Tick sẵn: NCC chỉ được hỏi các mặt hàng họ từng bán / có bảng giá; NCC chưa
     từng bán mặt hàng nào trong phiếu (tự tìm thêm) → hỏi mọi mặt hàng. Sale bỏ / thêm tick;
   - dưới tên mặt hàng: gợi ý NCC theo 3 tiêu chí (controllers/sale_page_create.py "suggest" → picks): rẻ nhất
     (giá mua thật lần gần nhất, hiện giá sau VAT), đã giao được hàng, mua gần nhất. Bấm gợi ý → thêm NCC (nếu
     chưa có) và tick ô đó — chỉ thêm, không bỏ (bỏ bằng ô tick, tránh bấm hai lần là mất);
   - nút "i": dẫn chứng — mọi NCC từng bán, giá + hạng, đơn mua gần nhất, số lần giao được;
   - gửi: {vendor_id: [product_id]} (HQ.askPlan) — server tạo mỗi NCC một báo giá chỉ gồm các mặt hàng đó. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var C = HQ.S.create;
  var esc = HQ.esc;
  var PICK_LABELS = [["cheapest", "rẻ nhất"], ["delivered", "đã giao"], ["recent", "mua gần nhất"]];

  function picks() {
    C.picks = C.picks || {};
    return C.picks;
  }

  /** Mặt hàng (trong phiếu) NCC từng bán / có bảng giá — theo gợi ý chung và gợi ý từng mặt hàng. */
  function covered(vendorId) {
    var ids = {};
    (C.suggestions || []).forEach(function (s) {
      if (s.partner_id === vendorId) {
        (s.product_ids || []).forEach(function (p) { ids[p] = true; });
      }
    });
    Object.keys(picks()).forEach(function (p) {
      if ((picks()[p].vendor_ids || []).indexOf(vendorId) >= 0) {
        ids[p] = true;
      }
    });
    return C.lines.filter(function (l) { return ids[l.product_id]; }).map(function (l) { return l.product_id; });
  }

  /** NCC vendorId có được hỏi mặt hàng productId không (tick tay > giá dùng lại > mặc định theo lịch sử). */
  function asked(vendorId, productId) {
    var own = (C.ask || {})[vendorId];
    if (own && own[productId] !== undefined) {
      return own[productId];
    }
    if (C.addTo) {
      return false;  // thêm vào phiếu đã gửi: sale tự tick, không đoán theo lịch sử
    }
    if (C.reuse[productId] === vendorId) {
      return true;
    }
    var cover = covered(vendorId);
    return !cover.length || cover.indexOf(productId) >= 0;
  }

  function setAsked(vendorId, productId, on) {
    C.ask = C.ask || {};
    C.ask[vendorId] = C.ask[vendorId] || {};
    C.ask[vendorId][productId] = on;
  }

  function isChosen(vendorId) {
    return C.chosen.some(function (v) { return v.id === vendorId; });
  }

  /** Gợi ý của một mặt hàng gộp theo NCC: [{id, name, labels: ["rẻ nhất 1.140.000 ₫", "mua gần nhất 14/07/2026"]}]. */
  function picksOf(productId) {
    var pick = picks()[productId];
    var vendors = [];
    if (!pick) {
      return vendors;
    }
    PICK_LABELS.forEach(function (entry) {
      var v = pick[entry[0]];
      if (!v) {
        return;
      }
      var label = entry[1] + (entry[0] === "cheapest" && v.price_incl ? " " + HQ.money(v.price_incl) : "") +
        (entry[0] === "delivered" && v.count > 1 ? " " + v.count + " lần" : "") +
        (entry[0] === "recent" && v.date ? " " + v.date : "");
      var found = vendors.find(function (x) { return x.id === v.id; });
      if (found) {
        found.labels.push(label);
      } else {
        vendors.push({ id: v.id, name: v.name, labels: [label] });
      }
    });
    return vendors;
  }

  function evidenceHtml(productId) {
    var rows = (picks()[productId] || {}).evidence || [];
    return '<div class="hq-ask-evidence"><table class="hq-table"><thead><tr><th>NCC</th>' +
      '<th class="hq-num">Giá mua lần gần nhất</th><th>Đơn mua gần nhất</th><th>Giao được</th></tr></thead><tbody>' +
      rows.map(function (e) {
        var net = Math.round(e.price) !== Math.round(e.price_incl)
          ? '<div class="hq-muted hq-small">chưa VAT ' + HQ.money(e.price) + "</div>" : "";
        return "<tr><td>" + esc(e.name) + '</td><td class="hq-num">' +
          (e.price_rank ? "<b>" + HQ.money(e.price_incl) + "</b>" + net + '<div class="hq-small">' +
            (e.price_rank === 1 ? "<b>rẻ nhất</b>" : "thứ " + e.price_rank) + " / " + e.priced_count + " NCC</div>"
            : '<span class="hq-muted">chưa có giá</span>') + "</td><td>" + esc(e.last_order) + " · " + esc(e.last_date) +
          "</td><td>" + (e.received_count ? e.received_count + " đơn, gần nhất " + esc(e.last_received)
            : '<span class="hq-muted">chưa nhận hàng</span>') + "</td></tr>";
      }).join("") + '</tbody></table><div class="hq-muted hq-small">Từ đơn mua đã xác nhận: giá lần mua gần nhất của ' +
      "mỗi NCC (đã trừ chiết khấu), quy về ĐVT sản phẩm; xếp theo giá chưa VAT.</div></div>";
  }

  /** Phần dưới tên mặt hàng: nút "i", chip gợi ý, dẫn chứng (khi mở), cảnh báo chưa tick NCC nào. */
  HQ.askLineExtras = function (line) {
    var pid = line.product_id;
    if (C.addTo) {
      var old = C.addTo.existing[pid];
      if (old) {
        return '<div class="hq-ask-warn">Đã có trong phiếu: <b>' + esc(old.name) + "</b> — " + HQ.qty(old.qty) + " " +
          esc(old.uom) + " → sau khi thêm " + HQ.qty(old.qty + (+line.qty || 0)) + " " + esc(old.uom) +
          (old.withdrawn.length ? ". Đang thu hồi với " + esc(old.withdrawn.join(", ")) + " — tick NCC để hỏi lại" : "") +
          "</div>";
      }
      return C.chosen.some(function (v) { return asked(v.id, pid); }) ? ""
        : '<div class="hq-ask-warn">Chưa tick NCC nào cho mặt hàng này</div>';
    }
    C.askInfo = C.askInfo || {};
    var hasEvidence = ((picks()[pid] || {}).evidence || []).length;
    var chips = picksOf(pid).map(function (v) {
      var on = isChosen(v.id) && asked(v.id, pid);
      return '<button type="button" class="hq-ask-pick' + (on ? " hq-ask-pick-on" : "") + '" data-ask-pick="' + v.id +
        ":" + pid + '"' + (on ? " disabled" : "") + ' title="' + esc(on ? "Đang hỏi NCC này" : "Thêm NCC này cho mặt hàng") +
        '">' + (on ? "✓ " : "+ ") + esc(v.name) + ' <span class="hq-ask-pick-why">' + esc(v.labels.join(" · ")) +
        "</span></button>";
    }).join("");
    var orphan = C.chosen.length && !C.chosen.some(function (v) { return asked(v.id, pid); });
    return '<div class="hq-ask-picks">' +
      (hasEvidence ? '<button type="button" class="hq-ask-info' + (C.askInfo[pid] ? " hq-ask-info-on" : "") +
        '" data-ask-info="' + pid + '" title="Xem dẫn chứng: giá, đơn mua, giao hàng của các NCC">i</button>' : "") +
      (chips || '<span class="hq-muted hq-small">Chưa từng mua</span>') + "</div>" +
      (C.askInfo[pid] ? evidenceHtml(pid) : "") +
      (orphan ? '<div class="hq-ask-warn">Chưa tick NCC nào cho mặt hàng này</div>' : "");
  };

  /** Ô tiêu đề cột cho từng NCC đã chọn — kèm × để bỏ NCC (sale_create.js data-unchoose-vendor). */
  HQ.askHeadCells = function () {
    return C.chosen.map(function (v) {
      return '<th class="hq-ask-col" title="' + esc(v.name) + ' — tick mặt hàng hỏi NCC này"><span class="hq-ask-col-name">' +
        esc(v.name) + "</span>" + (C.addTo ? "" : '<button type="button" class="hq-chip-x" data-unchoose-vendor="' +
        v.id + '" title="Bỏ NCC này">×</button>') + "</th>";
    }).join("");
  };

  HQ.askCells = function (line) {
    return C.chosen.map(function (v) {
      return '<td class="hq-ask-cell"><input type="checkbox" data-ask="' + v.id + ":" + line.product_id + '"' +
        (asked(v.id, line.product_id) ? " checked" : "") + ' aria-label="Hỏi ' + esc(v.name) + " — " +
        esc(line.name || line.product) + '"/></td>';
    }).join("");
  };

  /** Dòng cuối: mỗi NCC được hỏi mấy mặt hàng. lead: số cột trước các cột NCC; tail: số cột sau. */
  HQ.askFootRow = function (lead, tail) {
    if (!C.chosen.length) {
      return "";
    }
    return '<tfoot><tr><td colspan="' + lead + '" class="hq-num hq-muted hq-small">Số mặt hàng hỏi mỗi NCC</td>' +
      C.chosen.map(function (v) {
        var n = C.lines.filter(function (l) { return asked(v.id, l.product_id); }).length;
        return '<td class="hq-ask-cell' + (n ? "" : " hq-ask-warn") + '">' + n + "/" + C.lines.length + "</td>";
      }).join("") + (tail ? '<td colspan="' + tail + '"></td>' : "") + "</tr></tfoot>";
  };

  /**
   * Kế hoạch gửi: {ask: {vendor_id: [product_id]}, error: ""}. error khi còn mặt hàng không hỏi NCC nào hoặc
   * NCC không được hỏi mặt hàng nào.
   */
  HQ.askPlan = function () {
    var ask = {};
    C.chosen.forEach(function (v) {
      ask[v.id] = C.lines.filter(function (l) { return asked(v.id, l.product_id); }).map(function (l) { return l.product_id; });
    });
    // Thêm vào phiếu: mặt hàng đã có trong phiếu chỉ cộng SL, không bắt hỏi ai; NCC của phiếu không tick gì là bình thường.
    var orphans = C.lines.filter(function (l) {
      return !(C.addTo && C.addTo.productIds.indexOf(l.product_id) >= 0) &&
        !C.chosen.some(function (v) { return ask[v.id].indexOf(l.product_id) >= 0; });
    });
    var idle = C.addTo ? [] : C.chosen.filter(function (v) { return !ask[v.id].length; });
    var error = orphans.length
      ? "Chưa chọn NCC nào để hỏi: " + orphans.map(function (l) { return l.name || l.product; }).join(", ") + "."
      : idle.length ? "NCC chưa được hỏi mặt hàng nào: " + idle.map(function (v) { return v.name; }).join(", ") +
        " — tick mặt hàng hoặc bỏ NCC." : "";
    return { ask: ask, error: error };
  };

  /** onChoose(vendor): thêm NCC vào danh sách đã chọn; redraw(): vẽ lại bảng sản phẩm (sale_create.js). */
  HQ.bindAskEvents = function (onChoose, redraw) {
    var modal = HQ.$("hq-modal");
    HQ.on(modal, "change", "[data-ask]", function (el) {
      var parts = el.dataset.ask.split(":");
      setAsked(+parts[0], +parts[1], el.checked);
      redraw();
    });
    HQ.on(modal, "click", "[data-ask-info]", function (el) {
      C.askInfo[+el.dataset.askInfo] = !C.askInfo[+el.dataset.askInfo];
      redraw();
    });
    HQ.on(modal, "click", "[data-ask-pick]", function (el) {
      var parts = el.dataset.askPick.split(":");
      var vendorId = +parts[0];
      var productId = +parts[1];
      var vendor = picksOf(productId).find(function (v) { return v.id === vendorId; });
      setAsked(vendorId, productId, true);
      if (isChosen(vendorId)) {
        redraw();
      } else {
        onChoose({ id: vendorId, name: vendor ? vendor.name : "" });
      }
    });
  };
})(window.HlvQuote);
