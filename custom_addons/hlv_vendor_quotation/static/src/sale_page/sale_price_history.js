/* Giá NCC đã báo cho sản phẩm — của MỌI mã sale (services/price_history.py), để sale biết sản
   phẩm đã có người hỏi giá và khỏi hỏi trùng:
   - ô tìm đầu trang: khung "Giá đã hỏi" trên bảng phiếu, theo sản phẩm khớp chữ tìm;
   - hộp lập phiếu: dòng gợi ý dưới mỗi sản phẩm vừa thêm. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var MIN_SEARCH = 2;
  var HINT_PRICES = 3;

  function fetchPrices(params) {
    return HQ.rpc("/api/hoi-gia-ncc/price_history", params).then(function (r) { return r.products || []; });
  }

  var shown = [];  // nhóm sản phẩm đang hiện — nút "Dùng giá này" lấy lại theo chỉ số

  function priceRow(p, groupIndex) {
    var validity = (p.valid_until ? '<div class="hq-muted">' + (p.valid ? "hiệu lực đến " : "hết hiệu lực ") +
        esc(p.valid_until) + "</div>" : "") +
      (p.reusable
        ? '<button type="button" class="hq-btn hq-btn-mini" data-reuse-price="' + groupIndex + ":" + p.vendor_id +
          '" title="Lập phiếu với NCC này — tối đa ' + HQ.qty(p.qty) + ' như đã hỏi, giá được điền sẵn, không hỏi lại NCC">' +
          "Dùng giá này</button>"
        : '<div class="hq-expired">Không dùng lại được: ' + esc(p.reuse_note) + "</div>");
    return "<tr" + (p.reusable ? "" : ' class="hq-price-old"') + "><td>" + esc(p.vendor) +
      (p.chosen ? ' <span class="hq-tag hq-tag-ok">đã chọn</span>' : "") + validity + "</td>" +
      '<td class="hq-num">' + HQ.money(p.price_unit) + '<div class="hq-muted">cho ' + HQ.qty(p.qty) + "</div>" +
      '</td><td class="hq-num hq-muted">' + HQ.money(p.price_incl) +
      (p.vat ? " · " + esc(p.vat) : "") + "</td>" +
      '<td class="hq-num">' + (p.delivery_days ? p.delivery_days + " ngày" : "—") + "</td>" +
      '<td class="hq-nowrap">' + esc(p.date) + "</td>" +
      '<td class="hq-nowrap">' + esc(p.doc) + (p.sale_code ? '<div class="hq-muted">' + esc(p.sale_code) + "</div>" : "") +
      "</td></tr>";
  }

  /** Khung "Giá đã hỏi" theo chữ tìm ở đầu trang (ẩn khi chữ tìm ngắn / không có giá nào). */
  HQ.loadPriceHistory = function (search) {
    var box = HQ.$("hq-price-history");
    if (!box) {
      return;
    }
    if (!search || search.length < MIN_SEARCH) {
      box.classList.add("hq-hidden");
      return;
    }
    fetchPrices({ search: search }).then(function (products) {
      if (search !== HQ.S.search) {
        return;  // người dùng đã gõ tiếp — kết quả cũ
      }
      shown = products;
      box.classList.toggle("hq-hidden", !products.length);
      box.innerHTML = '<div class="hq-panel-head"><h2 class="hq-h3">Giá NCC đã báo cho sản phẩm khớp “' + esc(search) +
        '”</h2><span class="hq-muted hq-small">mọi mã sale · mới nhất trước</span></div>' +
        '<div class="hq-table-wrap"><table class="hq-table hq-price-table"><thead><tr><th>NCC</th>' +
        '<th class="hq-num">Chưa VAT</th><th class="hq-num">Sau VAT</th><th class="hq-num">Giao</th><th>Ngày báo</th>' +
        "<th>Phiếu · mã sale</th></tr></thead>" +
        products.map(function (g, index) {
          return '<tbody><tr class="hq-price-product"><th colspan="6">' + esc(g.product) +
            ' <a class="hq-small" href="/hoi-gia-ncc/tra-gia?p=' + g.product_id + '">xem mọi giá đã mua / đã báo →</a>' +
            "</th></tr>" +
            g.prices.map(function (p) { return priceRow(p, index); }).join("") + "</tbody>";
        }).join("") + "</table></div>";
    }).catch(function () { box.classList.add("hq-hidden"); });
  };

  HQ.bindPriceHistoryEvents = function () {
    HQ.on(HQ.$("hq-app"), "click", "[data-reuse-price]", function (el) {
      var parts = el.dataset.reusePrice.split(":");
      var group = shown[+parts[0]];
      var price = group && group.prices.find(function (p) { return p.vendor_id === +parts[1] && p.reusable; });
      if (!price) {
        return;
      }
      HQ.openCreateWith(
        // Số lượng = số NCC đã báo (tối đa được dùng lại); sale giảm nếu cần ít hơn.
        [{ product_id: group.product_id, product: group.product, name: group.name, qty: price.qty,
           uom_id: group.uom_id, uom: group.uom }],
        [{ id: price.vendor_id, name: price.vendor }],
        { [group.product_id]: price.vendor_id }
      );
    });
  };

  /** {product_id: [giá…]} cho hộp lập phiếu. */
  HQ.fetchPriceHints = function (productIds) {
    if (!productIds.length) {
      return Promise.resolve({});
    }
    return fetchPrices({ product_ids: productIds }).then(function (products) {
      var map = {};
      products.forEach(function (g) { map[g.product_id] = g.prices; });
      return map;
    });
  };

  /**
   * Lý do giá p KHÔNG dùng được cho dòng line của phiếu đang lập; dùng được → "". Ngoài luật
   * chung của server (p.reuse_note) còn xét theo dòng: cùng ĐVT, số lượng ≤ số NCC đã báo.
   */
  HQ.reuseProblem = function (p, line) {
    if (!p.reusable) {
      return p.reuse_note;
    }
    if (p.uom_id !== line.uom_id) {
      return "NCC báo theo " + p.uom + ", phiếu đang hỏi theo " + line.uom;
    }
    if (line.qty > p.qty) {
      return "chỉ dùng được tối đa " + HQ.qty(p.qty) + " " + p.uom + " (sale trước hỏi " + HQ.qty(p.qty) + ")";
    }
    return "";
  };

  /**
   * Giá đã hỏi dưới một sản phẩm trong hộp lập phiếu. Xanh = dùng lại được (bấm "Dùng giá
   * này" là chọn NCC đó, khỏi hỏi lại); xanh đậm = đang dùng; xám = không dùng được, kèm lý do.
   * pickedVendorId: NCC sale đang chọn dùng lại cho sản phẩm này (hoặc rỗng).
   */
  HQ.priceReuseHtml = function (prices, line, pickedVendorId) {
    if (!prices || !prices.length) {
      return "";
    }
    return '<div class="hq-reuse"><div class="hq-reuse-title">Đã có người hỏi giá</div>' +
      prices.slice(0, HINT_PRICES).map(function (p) {
        var problem = HQ.reuseProblem(p, line);
        var picked = !problem && p.vendor_id === pickedVendorId;
        var state = picked ? "is-picked" : problem ? "is-off" : "is-ok";
        var action = picked
          ? '<button type="button" class="hq-btn hq-btn-mini" data-reuse-unpick="' + line.product_id + '">Bỏ</button>'
          : problem ? ""
          : '<button type="button" class="hq-btn hq-btn-mini hq-btn-primary" data-reuse-pick="' + line.product_id + ":" +
            p.vendor_id + '">Dùng giá này</button>';
        return '<div class="hq-reuse-row ' + state + '"><div class="hq-reuse-main">' +
          (picked ? '<span class="hq-reuse-check">✓ Đang dùng</span> ' : "") +
          "<b>" + esc(p.vendor) + "</b> · <b>" + HQ.money(p.price_unit) + "</b> chưa VAT" +
          (p.vat ? " (" + esc(p.vat) + ")" : "") + " · báo cho " + HQ.qty(p.qty) + " " + esc(p.uom) +
          (p.valid_until ? " · hiệu lực đến " + esc(p.valid_until) : "") +
          '<div class="hq-reuse-sub">' + esc(p.doc) + (p.sale_code ? " · " + esc(p.sale_code) : "") + " · " +
          (problem ? "không dùng được: " + esc(problem) : esc(p.origin_status)) + "</div></div>" + action + "</div>";
      }).join("") + "</div>";
  };
})(window.HlvQuote);
