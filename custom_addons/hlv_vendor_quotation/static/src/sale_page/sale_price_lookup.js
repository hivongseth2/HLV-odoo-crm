/* Trang /hoi-gia-ncc/tra-gia: chọn sản phẩm → bảng tóm tắt theo NCC (giá mua gần nhất / thấp
   nhất, giá báo gần nhất / thấp nhất), rồi chi tiết từng lần mua và từng lần NCC báo giá.
   Bấm một NCC để lọc chi tiết theo NCC đó. URL giữ ?p=<sản phẩm> để gửi link cho nhau. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var data = null;
  var vendorFilter = null;

  function priceCell(row, unit) {
    if (!row) {
      return '<td class="hq-num hq-muted">—</td>';
    }
    return '<td class="hq-num"><b>' + HQ.money(row.price) + "</b>" + (unit && row.uom ? '<span class="hq-muted">/' +
      esc(row.uom) + "</span>" : "") + '<div class="hq-muted hq-small">' + esc(row.date.split(" ").pop()) + "</div></td>";
  }

  function renderVendors() {
    if (!data.vendors.length) {
      return '<section class="hq-panel hq-pad"><div class="hq-empty">Sản phẩm này chưa từng được mua hay hỏi giá.</div></section>';
    }
    return '<section class="hq-panel"><div class="hq-panel-head"><h2 class="hq-h3">Theo nhà cung cấp</h2>' +
      '<span class="hq-muted hq-small">bấm một NCC để xem riêng</span>' +
      (vendorFilter ? '<button type="button" class="hq-btn hq-btn-mini hq-push" data-vendor-filter="">Xem tất cả NCC</button>' : "") +
      '</div><div class="hq-table-wrap"><table class="hq-table pl-vendors"><thead><tr><th>NCC <span class="hq-muted hq-small">(giá sau VAT)</span></th>' +
      '<th class="hq-num">Mua gần nhất</th><th class="hq-num">Mua thấp nhất</th><th class="hq-num">Số lần mua</th>' +
      '<th class="hq-num">Báo gần nhất</th><th class="hq-num">Báo thấp nhất</th><th class="hq-num">Số lần báo</th></tr></thead><tbody>' +
      data.vendors.map(function (v) {
        return '<tr class="pl-vendor-row' + (v.vendor_id === vendorFilter ? " is-active" : "") + '" data-vendor-filter="' +
          v.vendor_id + '"><td><button type="button" class="hq-link-btn">' + esc(v.vendor) + "</button></td>" +
          priceCell(v.last_purchase, true) + priceCell(v.min_purchase, true) +
          '<td class="hq-num">' + (v.purchase_count || "—") + "</td>" +
          priceCell(v.last_quote, true) + priceCell(v.min_quote, true) +
          '<td class="hq-num">' + (v.quote_count || "—") + "</td></tr>";
      }).join("") + "</tbody></table></div></section>";
  }

  function filtered(rows) {
    return vendorFilter ? rows.filter(function (r) { return r.vendor_id === vendorFilter; }) : rows;
  }

  function renderPurchases() {
    var rows = filtered(data.purchases);
    return '<section class="hq-panel"><div class="hq-panel-head"><h2 class="hq-h3">Giá đã mua</h2>' +
      '<span class="hq-muted hq-small">' + rows.length + " lần · đơn mua đã xác nhận, mới nhất trước</span></div>" +
      (rows.length ? '<div class="hq-table-wrap"><table class="hq-table"><thead><tr><th>Ngày</th><th>NCC</th><th>Đơn mua</th>' +
        '<th class="hq-num">SL</th><th class="hq-num">Đơn giá (chưa VAT)</th><th class="hq-num">Thực mua sau VAT</th><th>Tên xuất HĐ</th></tr></thead><tbody>' +
        rows.map(function (r) {
          return "<tr><td class=\"hq-nowrap\">" + esc(r.date) + "</td><td>" + esc(r.vendor) + "</td><td>" + esc(r.order) + "</td>" +
            '<td class="hq-num hq-nowrap">' + HQ.qty(r.qty) + " " + esc(r.uom) +
            (r.qty_received ? '<div class="hq-muted hq-small">đã nhận ' + HQ.qty(r.qty_received) + "</div>" : "") + "</td>" +
            '<td class="hq-num">' + HQ.money(r.price_unit) + (r.currency && r.currency !== "VND" ? " " + esc(r.currency) : "") +
            (r.discount ? '<div class="hq-muted hq-small">CK ' + HQ.qty(r.discount) + "%</div>" : "") + "</td>" +
            '<td class="hq-num"><b>' + HQ.money(r.price) + '</b><div class="hq-muted hq-small">chưa VAT ' +
            HQ.money(r.price_untaxed) + "</div></td><td>" + esc(r.invoice_name) + "</td></tr>";
        }).join("") + "</tbody></table></div>"
        : '<div class="hq-empty">Chưa có lần mua nào' + (vendorFilter ? " từ NCC này" : "") + ".</div>") + "</section>";
  }

  function renderQuotes() {
    var rows = filtered(data.quotes);
    return '<section class="hq-panel"><div class="hq-panel-head"><h2 class="hq-h3">Giá NCC đã báo</h2>' +
      '<span class="hq-muted hq-small">' + rows.length + " lần · mọi sale, mới nhất trước</span></div>" +
      (rows.length ? '<div class="hq-table-wrap"><table class="hq-table"><thead><tr><th>Ngày báo</th><th>NCC</th>' +
        '<th>Phiếu · mã sale</th><th class="hq-num">SL hỏi</th><th class="hq-num">Sau VAT</th><th class="hq-num">Chưa VAT</th>' +
        '<th class="hq-num">Giao</th><th>Hiệu lực</th></tr></thead><tbody>' +
        rows.map(function (r) {
          var price = r.unavailable ? '<td class="hq-num hq-muted" colspan="2">Không có hàng</td>'
            : '<td class="hq-num"><b>' + HQ.money(r.price) + "</b>" + (r.chosen ? ' <span class="hq-tag hq-tag-ok">đã chọn</span>' : "") +
              '</td><td class="hq-num hq-muted">' + HQ.money(r.price_untaxed) + (r.vat ? " · " + esc(r.vat) : "") + "</td>";
          return "<tr" + (r.reusable ? "" : ' class="pl-quote-old"') + '><td class="hq-nowrap">' + esc(r.date) + "</td><td>" +
            esc(r.vendor) + '</td><td class="hq-nowrap">' + esc(r.doc) + (r.sale_code ? '<div class="hq-muted hq-small">' +
            esc(HQ.saleName(r.sale_code)) + "</div>" : "") + '</td><td class="hq-num hq-nowrap">' + HQ.qty(r.qty) + " " + esc(r.uom) + "</td>" +
            price + '<td class="hq-num">' + (r.delivery_days ? r.delivery_days + " ngày" : "—") + "</td>" +
            "<td>" + (r.valid_until ? esc(r.valid_until) : "—") + (r.reusable
              ? '<div><span class="hq-tag hq-tag-ok">dùng lại được</span></div>'
              : '<div class="hq-muted hq-small">' + esc(r.reuse_note) + "</div>") + "</td></tr>";
        }).join("") + "</tbody></table></div>"
        : '<div class="hq-empty">Chưa có báo giá nào' + (vendorFilter ? " từ NCC này" : "") + ".</div>") + "</section>";
  }

  function render() {
    var p = data.product;
    HQ.$("pl-result").innerHTML = '<div class="pl-product"><h1 class="hq-h2">' + esc(p.name) + "</h1>" +
      '<span class="hq-muted">ĐVT mua ' + esc(p.uom) + "</span></div>" +
      renderVendors() + renderPurchases() + renderQuotes();
  }

  function load(productId) {
    HQ.$("pl-result").innerHTML = '<div class="hq-loading">Đang tải…</div>';
    vendorFilter = null;
    HQ.rpc("/api/hoi-gia-ncc/product_prices", { product_id: productId }).then(function (res) {
      data = res;
      render();
      var url = new URL(window.location.href);
      url.searchParams.set("p", productId);
      window.history.replaceState(null, "", url);
    }).catch(function (err) {
      HQ.$("pl-result").innerHTML = '<div class="hq-alert">' + esc(err.message) + "</div>";
    });
  }

  function searchProducts(term) {
    return HQ.rpc("/api/hoi-gia-ncc/products", { search: term }).then(function (r) { return r.products; });
  }

  function start() {
    var app = HQ.$("hq-app");
    if (!app || !HQ.$("pl-search")) {
      return;
    }
    try {
      HQ.saleNames = JSON.parse(app.dataset.saleNames || "{}");
    } catch (e) {
      HQ.saleNames = {};  // danh bạ hỏng: vẫn hiện mã sale như cũ
    }
    HQ.bindPicker("pl-search", "pl-results", searchProducts, function (p) {
      return esc(p.product);
    }, function (product) {
      load(product.product_id);
      return product.product;
    });
    // Gõ đúng mã rồi Enter: khớp đúng một sản phẩm thì mở luôn.
    HQ.$("pl-search").addEventListener("keydown", function (event) {
      if (event.key !== "Enter") {
        return;
      }
      event.preventDefault();
      searchProducts(event.target.value.trim()).then(function (products) {
        if (products.length === 1) {
          HQ.$("pl-results").classList.add("hq-hidden");
          load(products[0].product_id);
        }
      });
    });
    HQ.on(app, "click", "[data-vendor-filter]", function (el) {
      vendorFilter = +el.dataset.vendorFilter || null;
      render();
    });
    if (+app.dataset.initialProduct) {
      load(+app.dataset.initialProduct);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})(window.HlvQuote);
