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

  function priceRow(p) {
    return "<tr><td>" + esc(p.vendor) + (p.chosen ? ' <span class="hq-tag hq-tag-ok">đã chọn</span>' : "") + "</td>" +
      '<td class="hq-num">' + HQ.money(p.price_unit) + '</td><td class="hq-num hq-muted">' + HQ.money(p.price_incl) +
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
      box.classList.toggle("hq-hidden", !products.length);
      box.innerHTML = '<div class="hq-panel-head"><h2 class="hq-h3">Giá NCC đã báo cho sản phẩm khớp “' + esc(search) +
        '”</h2><span class="hq-muted hq-small">mọi mã sale · mới nhất trước</span></div>' +
        '<div class="hq-table-wrap"><table class="hq-table hq-price-table"><thead><tr><th>NCC</th>' +
        '<th class="hq-num">Chưa VAT</th><th class="hq-num">Sau VAT</th><th class="hq-num">Giao</th><th>Ngày báo</th>' +
        "<th>Phiếu · mã sale</th></tr></thead>" +
        products.map(function (g) {
          return '<tbody><tr class="hq-price-product"><th colspan="6">' + esc(g.product) + "</th></tr>" +
            g.prices.map(priceRow).join("") + "</tbody>";
        }).join("") + "</table></div>";
    }).catch(function () { box.classList.add("hq-hidden"); });
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

  /** Dòng gợi ý dưới sản phẩm trong hộp lập phiếu; chưa ai hỏi giá → "". */
  HQ.priceHintHtml = function (prices) {
    if (!prices || !prices.length) {
      return "";
    }
    return '<div class="hq-price-hint"><span class="hq-muted">Đã hỏi giá:</span> ' +
      prices.slice(0, HINT_PRICES).map(function (p) {
        return '<span class="hq-price-chip" title="' + esc(p.doc + (p.sale_code ? " · " + p.sale_code : "")) + '">' +
          esc(p.vendor) + " <b>" + HQ.money(p.price_unit) + "</b> · " + esc(p.date.split(" ").pop()) + "</span>";
      }).join("") + "</div>";
  };
})(window.HlvQuote);
