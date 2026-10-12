/* Hộp lập phiếu, bước 2 — hỏi NCC nào cho TỪNG mặt hàng (không phải NCC nào cũng bán mọi mã):
   - bảng mặt hàng × NCC đã chọn, mỗi ô một ô tick. Tick sẵn: NCC chỉ được hỏi các mặt hàng họ từng bán / có
     bảng giá; NCC chưa từng bán mặt hàng nào trong phiếu (tự tìm thêm) → hỏi mọi mặt hàng. Sale bỏ / thêm tick;
   - dưới tên mỗi mặt hàng: gợi ý NCC theo 3 tiêu chí (controllers/sale_page_create.py "suggest" → picks):
     rẻ nhất (giá mua thật lần gần nhất — chỉ xếp hạng, không hiện giá), đã giao được hàng, mua gần nhất.
     Bấm gợi ý → thêm NCC (nếu chưa có) và tick đúng ô đó;
   - gửi: {vendor_id: [product_id]} (HQ.askPlan) — server tạo mỗi NCC một báo giá chỉ gồm các mặt hàng đó. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var C = HQ.S.create;
  var esc = HQ.esc;
  var PICK_LABELS = [["cheapest", "rẻ nhất"], ["delivered", "đã giao"], ["recent", "mua gần nhất"]];

  /** Mặt hàng (trong phiếu) NCC từng bán / có bảng giá — theo gợi ý chung và gợi ý từng mặt hàng. */
  function covered(vendorId) {
    var ids = {};
    (C.suggestions || []).forEach(function (s) {
      if (s.partner_id === vendorId) {
        (s.product_ids || []).forEach(function (p) { ids[p] = true; });
      }
    });
    Object.keys(C.picks || {}).forEach(function (p) {
      if ((C.picks[p].vendor_ids || []).indexOf(vendorId) >= 0) {
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

  /** Gợi ý của một mặt hàng gộp theo NCC: [{id, name, labels: ["rẻ nhất", "mua gần nhất"]}]. */
  function picksOf(productId) {
    var pick = (C.picks || {})[productId];
    var vendors = [];
    if (!pick) {
      return vendors;
    }
    PICK_LABELS.forEach(function (entry) {
      var v = pick[entry[0]];
      if (!v) {
        return;
      }
      var found = vendors.find(function (x) { return x.id === v.id; });
      var label = entry[1] + (entry[0] === "delivered" && v.count > 1 ? " " + v.count + " lần" : "") +
        (entry[0] === "recent" && v.date ? " " + v.date : "");
      if (found) {
        found.labels.push(label);
      } else {
        vendors.push({ id: v.id, name: v.name, labels: [label] });
      }
    });
    return vendors;
  }

  function isChosen(vendorId) {
    return C.chosen.some(function (v) { return v.id === vendorId; });
  }

  function pickChips(productId) {
    return picksOf(productId).map(function (v) {
      var on = isChosen(v.id) && asked(v.id, productId);
      return '<button type="button" class="hq-ask-pick' + (on ? " hq-ask-pick-on" : "") + '" data-ask-pick="' +
        v.id + ":" + productId + '" title="' + esc(on ? "Đang hỏi NCC này" : "Thêm NCC này cho mặt hàng") + '">' +
        (on ? "✓ " : "+ ") + esc(v.name) + ' <span class="hq-ask-pick-why">' + esc(v.labels.join(" · ")) +
        "</span></button>";
    }).join("");
  }

  HQ.renderAskMatrix = function () {
    var box = HQ.$("hq-ask");
    if (!box) {
      return;
    }
    if (!C.lines.length) {
      box.innerHTML = "";
      return;
    }
    var vendors = C.chosen;
    var head = "<tr><th>Mặt hàng · gợi ý NCC</th>" + vendors.map(function (v) {
      return '<th class="hq-ask-col" title="' + esc(v.name) + '">' + esc(v.name) + "</th>";
    }).join("") + "</tr>";
    var body = C.lines.map(function (line) {
      var count = vendors.filter(function (v) { return asked(v.id, line.product_id); }).length;
      return "<tr" + (count ? "" : ' class="hq-ask-orphan"') + '><td><div class="hq-strong">' +
        esc(line.name || line.product) + "</div>" +
        '<div class="hq-ask-picks">' + (pickChips(line.product_id) || '<span class="hq-muted hq-small">Chưa từng mua</span>') +
        "</div>" + (count ? "" : '<div class="hq-ask-warn">Chưa hỏi NCC nào</div>') + "</td>" +
        vendors.map(function (v) {
          var on = asked(v.id, line.product_id);
          return '<td class="hq-ask-cell"><input type="checkbox" data-ask="' + v.id + ":" + line.product_id + '"' +
            (on ? " checked" : "") + ' aria-label="Hỏi ' + esc(v.name) + " — " + esc(line.name || line.product) + '"/></td>';
        }).join("") + "</tr>";
    }).join("");
    var foot = vendors.length ? '<tr><td class="hq-muted hq-small">Số mặt hàng hỏi</td>' + vendors.map(function (v) {
      var n = C.lines.filter(function (l) { return asked(v.id, l.product_id); }).length;
      return '<td class="hq-ask-cell' + (n ? "" : " hq-ask-warn") + '">' + n + "/" + C.lines.length + "</td>";
    }).join("") + "</tr>" : "";
    box.innerHTML = '<div class="hq-ask-title"><b>Hỏi NCC nào cho từng mặt hàng</b> <span class="hq-muted hq-small">' +
      "Tick sẵn mặt hàng NCC từng bán; NCC chưa từng bán thì hỏi hết. Gợi ý theo giá mua rẻ nhất, NCC đã giao, " +
      "NCC mua gần nhất — bấm để thêm.</span></div>" +
      '<div class="hq-table-wrap"><table class="hq-table hq-ask-table"><thead>' + head + "</thead><tbody>" + body +
      "</tbody>" + (foot ? "<tfoot>" + foot + "</tfoot>" : "") + "</table></div>";
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
    var orphans = C.lines.filter(function (l) {
      return !C.chosen.some(function (v) { return ask[v.id].indexOf(l.product_id) >= 0; });
    });
    var idle = C.chosen.filter(function (v) { return !ask[v.id].length; });
    var error = orphans.length
      ? "Chưa chọn NCC nào để hỏi: " + orphans.map(function (l) { return l.name || l.product; }).join(", ") + "."
      : idle.length ? "NCC chưa được hỏi mặt hàng nào: " + idle.map(function (v) { return v.name; }).join(", ") +
        " — tick mặt hàng hoặc bỏ NCC." : "";
    return { ask: ask, error: error };
  };

  /** onChoose(vendor): hộp lập phiếu thêm NCC vào danh sách đã chọn (sale_create.js). */
  HQ.bindAskEvents = function (onChoose) {
    var modal = HQ.$("hq-modal");
    HQ.on(modal, "change", "[data-ask]", function (el) {
      var parts = el.dataset.ask.split(":");
      setAsked(+parts[0], +parts[1], el.checked);
      HQ.renderAskMatrix();
    });
    HQ.on(modal, "click", "[data-ask-pick]", function (el) {
      var parts = el.dataset.askPick.split(":");
      var vendorId = +parts[0];
      var productId = +parts[1];
      var vendor = picksOf(productId).find(function (v) { return v.id === vendorId; });
      if (isChosen(vendorId) && asked(vendorId, productId)) {
        setAsked(vendorId, productId, false);
      } else {
        setAsked(vendorId, productId, true);
        if (!isChosen(vendorId)) {
          onChoose({ id: vendorId, name: vendor ? vendor.name : "" });
        }
      }
      HQ.renderAskMatrix();
    });
  };
})(window.HlvQuote);
