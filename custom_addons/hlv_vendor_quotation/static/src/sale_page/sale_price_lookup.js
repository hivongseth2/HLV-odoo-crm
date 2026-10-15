/* Trang /hoi-gia-ncc/tra-gia: chọn sản phẩm → dải tóm tắt (mua gần nhất / thấp nhất, báo giá
   còn dùng được) rồi 3 tab: lịch sử mua (chỉ lần đã nhập kho, có SL trả NCC), theo NCC, giá NCC
   đã báo. Chọn một NCC thì cả dải tóm tắt và các tab chỉ còn NCC đó.
   URL giữ ?p=<sản phẩm>&tab=<tab> để gửi link cho nhau. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var TABS = [
    ["purchases", "Lịch sử mua"],
    ["vendors", "Theo NCC"],
    ["quotes", "NCC đã báo giá"],
  ];
  var RETURN_TAG = {
    partial: '<span class="hq-tag hq-tag-warn">trả một phần</span>',
    full: '<span class="hq-tag hq-tag-danger">trả hết</span>',
  };
  var data = null;
  var vendorFilter = null;
  var tab = "purchases";

  function filtered(rows) {
    return vendorFilter ? rows.filter(function (r) { return r.vendor_id === vendorFilter; }) : rows;
  }

  /** Lần mua còn giữ hàng — lần đã trả hết không còn là giá mua thật. */
  function keptPurchases() {
    return filtered(data.purchases).filter(function (r) { return r.return_state !== "full"; });
  }

  function lowest(rows) {
    return rows.reduce(function (best, r) { return !best || r.price < best.price ? r : best; }, null);
  }

  function unitPrice(row) {
    return "<b>" + HQ.money(row.price) + "</b>" + (row.uom ? '<span class="hq-muted">/' + esc(row.uom) + "</span>" : "");
  }

  function priceCell(row) {
    if (!row) {
      return '<td class="hq-num hq-muted">—</td>';
    }
    return '<td class="hq-num">' + unitPrice(row) + '<div class="hq-muted hq-small">' + esc(row.date.split(" ").pop()) + "</div></td>";
  }

  function stat(label, row, note) {
    return '<div class="pl-stat"><div class="hq-muted hq-small">' + label + "</div>" +
      (row ? '<div class="pl-stat-value">' + unitPrice(row) + '</div><div class="hq-muted hq-small">' + note(row) + "</div>"
        : '<div class="pl-stat-value hq-muted">—</div>') + "</div>";
  }

  function renderStats() {
    var kept = keptPurchases();
    var reusable = filtered(data.quotes).filter(function (r) { return r.reusable; });
    var purchaseNote = function (r) { return esc(r.date) + " · " + esc(r.vendor); };
    return '<div class="pl-stats">' +
      stat("Mua gần nhất", kept[0], purchaseNote) +
      stat("Mua thấp nhất", lowest(kept), purchaseNote) +
      stat("Báo giá còn dùng được", lowest(reusable), function (r) {
        return reusable.length + " báo giá · thấp nhất " + esc(r.vendor);
      }) + "</div>";
  }

  function tabCount(key) {
    return filtered(data[key]).length;
  }

  function renderTabs() {
    var vendor = vendorFilter && data.vendors.concat(data.purchases, data.quotes).filter(function (r) {
      return r.vendor_id === vendorFilter;
    })[0];
    return '<div class="hq-panel-head hq-panel-head-wrap"><div class="hq-tabs" role="tablist">' +
      TABS.map(function (t) {
        return '<button type="button" role="tab" class="hq-btn hq-btn-mini' + (t[0] === tab ? " is-active" : "") +
          '" aria-selected="' + (t[0] === tab) + '" data-tab="' + t[0] + '">' + t[1] +
          ' <span class="hq-tab-count">' + tabCount(t[0]) + "</span></button>";
      }).join("") + "</div>" +
      (vendor ? '<span class="hq-push hq-small">NCC: <b>' + esc(vendor.vendor) + "</b></span>" +
        '<button type="button" class="hq-btn hq-btn-mini" data-vendor-filter="">Xem tất cả NCC</button>' : "") + "</div>";
  }

  function renderVendors() {
    var rows = filtered(data.vendors);
    if (!rows.length) {
      return '<div class="hq-empty">Sản phẩm này chưa từng được nhập kho hay hỏi giá.</div>';
    }
    return '<div class="hq-table-wrap"><table class="hq-table pl-vendors"><thead><tr><th>NCC <span class="hq-muted hq-small">' +
      "(giá sau VAT · bấm để xem riêng)</span></th>" +
      '<th class="hq-num">Mua gần nhất</th><th class="hq-num">Mua thấp nhất</th><th class="hq-num">Số lần mua</th>' +
      '<th class="hq-num">Báo gần nhất</th><th class="hq-num">Báo thấp nhất</th><th class="hq-num">Số lần báo</th></tr></thead><tbody>' +
      rows.map(function (v) {
        return '<tr class="pl-vendor-row' + (v.vendor_id === vendorFilter ? " is-active" : "") + '" data-vendor-filter="' +
          v.vendor_id + '"><td><button type="button" class="hq-link-btn">' + esc(v.vendor) + "</button></td>" +
          priceCell(v.last_purchase) + priceCell(v.min_purchase) +
          '<td class="hq-num">' + (v.purchase_count || "—") + "</td>" +
          priceCell(v.last_quote) + priceCell(v.min_quote) +
          '<td class="hq-num">' + (v.quote_count || "—") + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  function returnCell(r) {
    if (r.return_state === "none") {
      return '<td class="hq-num hq-muted">—</td>';
    }
    return '<td class="hq-num hq-nowrap">' + HQ.qty(r.qty_returned) + " " + RETURN_TAG[r.return_state] +
      '<div class="hq-muted hq-small">' + esc(r.returned) + "</div></td>";
  }

  function purchasePriceCell(r) {
    var foreign = r.currency && r.currency !== "VND" ? " " + esc(r.currency) : "";
    return '<td class="hq-num"><b>' + HQ.money(r.price) + "</b>" + foreign + '<div class="hq-muted hq-small">chưa VAT ' +
      HQ.money(r.price_untaxed) + (r.discount ? " · CK " + HQ.qty(r.discount) + "% từ " + HQ.money(r.price_unit) : "") + "</div></td>";
  }

  function renderPurchases() {
    var rows = filtered(data.purchases);
    if (!rows.length) {
      return '<div class="hq-empty">Chưa có lần nhập kho nào' + (vendorFilter ? " từ NCC này" : "") + ".</div>";
    }
    return '<p class="hq-muted hq-small pl-note">Chỉ lần mua đã nhập kho, mới nhất trước. Lần trả hết NCC hiện mờ và không tính ' +
      "vào giá gần nhất / thấp nhất.</p>" +
      '<div class="hq-table-wrap"><table class="hq-table"><thead><tr><th>Ngày đơn hàng</th><th>Ngày nhập</th><th>NCC</th>' +
      '<th>Đơn mua</th><th class="hq-num">SL mua</th><th class="hq-num">Đã nhập</th><th class="hq-num">Trả NCC</th>' +
      '<th class="hq-num">Giá sau VAT</th><th>Tên xuất HĐ</th></tr></thead><tbody>' +
      rows.map(function (r) {
        return "<tr" + (r.return_state === "full" ? ' class="pl-row-void"' : "") + '><td class="hq-nowrap">' + esc(r.date) +
          '</td><td class="hq-nowrap">' + esc(r.received) + "</td><td>" + esc(r.vendor) + '</td><td class="hq-nowrap">' +
          esc(r.order) + '</td><td class="hq-num hq-nowrap">' + HQ.qty(r.qty) + " " + esc(r.uom) + "</td>" +
          '<td class="hq-num">' + HQ.qty(r.qty_in) + "</td>" + returnCell(r) + purchasePriceCell(r) +
          "<td>" + esc(r.invoice_name) + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  function renderQuotes() {
    var rows = filtered(data.quotes);
    if (!rows.length) {
      return '<div class="hq-empty">Chưa có báo giá nào' + (vendorFilter ? " từ NCC này" : "") + ".</div>";
    }
    return '<div class="hq-table-wrap"><table class="hq-table"><thead><tr><th>Ngày báo</th><th>NCC</th>' +
      '<th>Phiếu · mã sale</th><th class="hq-num">SL hỏi</th><th class="hq-num">Sau VAT</th><th class="hq-num">Chưa VAT</th>' +
      '<th class="hq-num">Giao</th><th>Hiệu lực</th></tr></thead><tbody>' +
      rows.map(function (r) {
        var price = r.unavailable ? '<td class="hq-num hq-muted" colspan="2">Không có hàng</td>'
          : '<td class="hq-num"><b>' + HQ.money(r.price) + "</b>" + (r.chosen ? ' <span class="hq-tag hq-tag-ok">đã chọn</span>' : "") +
            '</td><td class="hq-num hq-muted">' + HQ.money(r.price_untaxed) + (r.vat ? " · " + esc(r.vat) : "") + "</td>";
        return "<tr" + (r.reusable ? "" : ' class="pl-row-void"') + '><td class="hq-nowrap">' + esc(r.date) + "</td><td>" +
          esc(r.vendor) + '</td><td class="hq-nowrap">' + esc(r.doc) + (r.sale_code ? '<div class="hq-muted hq-small">' +
          esc(HQ.saleName(r.sale_code)) + "</div>" : "") + '</td><td class="hq-num hq-nowrap">' + HQ.qty(r.qty) + " " + esc(r.uom) + "</td>" +
          price + '<td class="hq-num">' + (r.delivery_days ? r.delivery_days + " ngày" : "—") + "</td>" +
          "<td>" + (r.valid_until ? esc(r.valid_until) : "—") + (r.reusable
            ? '<div><span class="hq-tag hq-tag-ok">dùng lại được</span></div>'
            : '<div class="hq-muted hq-small">' + esc(r.reuse_note) + "</div>") + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  var TAB_BODY = { purchases: renderPurchases, vendors: renderVendors, quotes: renderQuotes };

  function syncUrl() {
    var url = new URL(window.location.href);
    url.searchParams.set("p", data.product.id);
    url.searchParams.set("tab", tab);
    window.history.replaceState(null, "", url);
  }

  function render() {
    var p = data.product;
    HQ.$("pl-result").innerHTML = '<section class="hq-panel hq-pad pl-head"><div class="pl-product"><h1 class="hq-h2">' +
      esc(p.name) + '</h1><span class="hq-muted">ĐVT mua ' + esc(p.uom) + "</span></div>" + renderStats() + "</section>" +
      '<section class="hq-panel">' + renderTabs() + '<div role="tabpanel">' + TAB_BODY[tab]() + "</div></section>";
    syncUrl();
  }

  function load(productId) {
    HQ.$("pl-result").innerHTML = '<div class="hq-loading">Đang tải…</div>';
    vendorFilter = null;
    HQ.rpc("/api/hoi-gia-ncc/product_prices", { product_id: productId }).then(function (res) {
      data = res;
      render();
    }).catch(function (err) {
      HQ.$("pl-result").innerHTML = '<div class="hq-alert">' + esc(err.message) + "</div>";
    });
  }

  /** Bấm một NCC ở tab "Theo NCC": lọc theo NCC đó và mở tab có dữ liệu của nó. */
  function pickVendor(vendorId) {
    vendorFilter = vendorId || null;
    if (vendorFilter && tab === "vendors") {
      tab = filtered(data.purchases).length ? "purchases" : "quotes";
    }
    render();
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
    HQ.on(app, "click", "[data-tab]", function (el) {
      tab = el.dataset.tab;
      render();
    });
    HQ.on(app, "click", "[data-vendor-filter]", function (el) {
      pickVendor(+el.dataset.vendorFilter);
    });
    var initialTab = new URL(window.location.href).searchParams.get("tab");
    if (TAB_BODY[initialTab]) {
      tab = initialTab;
    }
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
