/* Danh sách NCC bên trái, danh sách yêu cầu báo giá, và ngăn chi tiết một báo giá. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var S = HQ.S;
  var esc = HQ.esc;

  function currentVendor() {
    return S.vendors.find(function (v) { return v.id === S.vendorId; }) || null;
  }

  /* ---------------- NCC ---------------- */

  HQ.loadVendors = function () {
    return HQ.rpc("/api/hoi-gia-ncc/vendors", {
      search: HQ.$("hq-vendor-search").value,
      mine: S.mine,
      include_id: S.vendorId,
    }).then(function (res) {
      S.vendors = res.vendors || [];
      renderVendors();
      renderVendorCard();
    });
  };

  function renderVendors() {
    document.querySelector(".hq-vendor-all").classList.toggle("is-active", !S.vendorId);
    HQ.$("hq-vendor-list").innerHTML = S.vendors.length ? S.vendors.map(function (v) {
      var counters = (v.quoted ? '<span class="hq-tag hq-tag-ok" title="NCC đã báo giá">' +
        v.quoted + " đã báo</span>" : "") +
        (v.waiting ? '<span class="hq-tag hq-tag-warn" title="Chờ NCC báo giá">' +
        v.waiting + " chờ</span>" : "");
      return '<button type="button" class="hq-vendor' + (v.id === S.vendorId ? " is-active" : "") +
        '" data-vendor="' + v.id + '">' +
        '<span class="hq-vendor-name">' + esc(v.name) + "</span>" +
        '<span class="hq-vendor-counts">' + counters + "</span></button>";
    }).join("") : '<div class="hq-empty">Chưa có NCC nào</div>';
  }

  function renderVendorCard() {
    var vendor = currentVendor();
    HQ.$("hq-title").textContent = vendor ? vendor.name : "Tất cả nhà cung cấp";
    var card = HQ.$("hq-vendor-card");
    card.classList.toggle("hq-hidden", !vendor);
    if (!vendor) {
      return;
    }
    card.innerHTML =
      '<span class="hq-muted">Link NCC</span><code class="hq-code hq-ellipsis">' + esc(vendor.portal_url) + "</code>" +
      '<button type="button" class="hq-btn hq-btn-mini" data-copy="' + esc(vendor.portal_url) + '">Copy link</button>' +
      '<span class="hq-muted">Mật khẩu</span><code class="hq-code">' + esc(vendor.password) + "</code>" +
      '<button type="button" class="hq-btn hq-btn-mini" data-copy="' + esc(vendor.password) + '">Copy</button>' +
      '<button type="button" class="hq-btn hq-btn-soft hq-push" id="hq-new-for-vendor">Hỏi giá NCC này</button>';
  }

  HQ.selectVendor = function (vendorId) {
    S.vendorId = vendorId || null;
    S.page = 1;
    var url = new URL(window.location.href);
    if (S.vendorId) {
      url.searchParams.set("ncc", S.vendorId);
    } else {
      url.searchParams.delete("ncc");
    }
    window.history.replaceState(null, "", url);
    renderVendors();
    renderVendorCard();
    return HQ.loadQuotes();
  };

  /* ---------------- Danh sách báo giá ---------------- */

  HQ.loadQuotes = function () {
    HQ.$("hq-quote-list").classList.add("is-loading");
    return HQ.rpc("/api/hoi-gia-ncc/quotes", {
      vendor_id: S.vendorId,
      status: S.status,
      search: S.search,
      mine: S.mine,
      page: S.page,
    }).then(function (res) {
      S.counts = res.counts || {};
      S.pager = res.pager || {};
      S.status = res.status;
      renderTabs();
      renderKpis();
      renderQuotes(res.quotes || []);
      renderPager();
      HQ.showAlert("hq-alert", "");
    }).catch(function (err) {
      HQ.showAlert("hq-alert", err.message);
    }).finally(function () {
      HQ.$("hq-quote-list").classList.remove("is-loading");
    });
  };

  function renderTabs() {
    HQ.$("hq-tabs").innerHTML = (S.config.status_tabs || []).filter(function (tab) {
      // Nháp / Đã huỷ chỉ hiện khi có, cho thanh tab gọn.
      return !(tab[0] === "draft" || tab[0] === "cancel") || S.counts[tab[0]] || S.status === tab[0];
    }).map(function (tab) {
      return '<button type="button" class="hq-btn hq-btn-mini' + (tab[0] === S.status ? " is-active" : "") +
        '" data-status="' + tab[0] + '">' + esc(tab[1]) +
        ' <span class="hq-tab-count">' + (S.counts[tab[0]] || 0) + "</span></button>";
    }).join("");
  }

  function renderKpis() {
    HQ.$("hq-kpis").innerHTML = HQ.KPIS.map(function (kpi) {
      var count = S.counts[kpi[0]] || 0;
      return '<button type="button" class="hq-kpi' + (kpi[0] === "expired" && count ? " is-warn" : "") +
        (S.status === kpi[0] ? " is-active" : "") + '" data-status="' + kpi[0] + '">' +
        '<span class="hq-kpi-num">' + count + "</span>" +
        '<span class="hq-kpi-label">' + esc(kpi[1]) + "</span></button>";
    }).join("");
  }

  function renderQuotes(quotes) {
    var body = HQ.$("hq-quote-list");
    if (!quotes.length) {
      body.innerHTML = '<tr><td colspan="7" class="hq-empty">Không có yêu cầu báo giá nào. ' +
        'Bấm "Hỏi giá NCC" để gửi yêu cầu.</td></tr>';
      return;
    }
    body.innerHTML = quotes.map(function (q) {
      var refs = [q.request_name, q.sale_order || q.origin].filter(Boolean).map(esc).join(" · ");
      var items = q.state === "quoted" || q.state === "done"
        ? q.offered_count + "/" + q.line_count + " có giá"
        : q.line_count + " mặt hàng";
      return '<tr class="hq-row" data-quote="' + q.id + '">' +
        '<td class="hq-nowrap"><span class="hq-ref">' + esc(q.name) + "</span></td>" +
        '<td class="hq-cell-vendor"><span class="hq-ellipsis">' + esc(q.vendor_name) + "</span></td>" +
        '<td class="hq-muted">' + (refs || "—") + "</td>" +
        '<td class="hq-nowrap">' + items +
        (q.selected_count ? '<div class="hq-muted">thu mua đã chọn ' + q.selected_count + "</div>" : "") + "</td>" +
        '<td class="hq-nowrap hq-num">' + esc(q.deadline || "—") + "</td>" +
        '<td><span class="hq-tag ' + (HQ.STATE_CLASS[q.state] || "") + '">' + esc(q.state_label) + "</span>" +
        (q.submit_date ? '<div class="hq-muted">gửi ' + esc(q.submit_date) + "</div>" : "") + "</td>" +
        '<td class="hq-right hq-num">' + (q.amount_untaxed ? HQ.money(q.amount_untaxed) : "—") + "</td></tr>";
    }).join("");
  }

  function renderPager() {
    var p = S.pager;
    HQ.$("hq-pager").innerHTML = p.page_count > 1
      ? '<button type="button" class="hq-btn hq-btn-mini" data-page="' + (p.page - 1) + '"' +
        (p.page <= 1 ? " disabled" : "") + ">‹ Trước</button>" +
        '<span class="hq-muted">Trang ' + p.page + " / " + p.page_count + "</span>" +
        '<button type="button" class="hq-btn hq-btn-mini" data-page="' + (p.page + 1) + '"' +
        (p.page >= p.page_count ? " disabled" : "") + ">Sau ›</button>"
      : "";
  }

  /* ---------------- Chi tiết ---------------- */

  HQ.openQuote = function (quoteId) {
    S.openQuoteId = quoteId;
    HQ.show("hq-drawer", true);
    HQ.$("hq-drawer-panel").innerHTML = '<div class="hq-loading">Đang tải…</div>';
    return HQ.rpc("/api/hoi-gia-ncc/quote", { quote_id: quoteId }).then(renderDrawer)
      .catch(function (err) { HQ.$("hq-drawer-panel").innerHTML = '<div class="hq-alert">' + esc(err.message) + "</div>"; });
  };

  HQ.quoteAction = function (action) {
    var labels = { close: "Đóng báo giá — NCC không sửa được nữa?", cancel: "Huỷ yêu cầu báo giá này?" };
    if (labels[action] && !window.confirm(labels[action])) {
      return;
    }
    HQ.rpc("/api/hoi-gia-ncc/quote_action", { quote_id: S.openQuoteId, action: action })
      .then(function (detail) {
        renderDrawer(detail);
        HQ.loadQuotes();
        HQ.loadVendors();
      }).catch(function (err) { HQ.toast(err.message); });
  };

  function renderDrawer(q) {
    var lines = q.lines.map(function (l, index) {
      var priced = l.price_unit && !l.unavailable;
      var tags = (l.selected ? '<span class="hq-tag hq-tag-ok">Thu mua đã chọn</span>' : "") +
        (l.is_best && !l.selected ? '<span class="hq-tag hq-tag-mine">Rẻ nhất</span>' : "") +
        (!l.linked && q.request_name ? '<span class="hq-tag hq-tag-soft">Chưa ghép YCMH</span>' : "");
      return '<tr class="' + (l.unavailable ? "hq-row-muted" : "") + (l.selected ? " hq-row-selected" : "") + '">' +
        "<td>" + (index + 1) + "</td>" +
        '<td><img class="hq-thumb" loading="lazy" src="/web/image/product.product/' + l.product_id +
        '/image_128" alt=""/></td>' +
        '<td><div class="hq-strong">' + esc(l.name || l.product) + "</div>" + tags +
        (l.vendor_note ? '<div class="hq-muted hq-small">NCC: ' + esc(l.vendor_note) + "</div>" : "") + "</td>" +
        '<td class="hq-num">' + HQ.qty(l.qty) + " " + esc(l.uom) + "</td>" +
        '<td class="hq-num">' + (l.unavailable ? '<span class="hq-muted">Không có hàng</span>'
          : priced ? HQ.money(l.price_unit) : "—") + "</td>" +
        "<td>" + esc(l.vat) + "</td>" +
        '<td class="hq-num">' + (l.delivery_days ? l.delivery_days + " ngày" : "") + "</td>" +
        '<td class="hq-num hq-strong">' + (priced ? HQ.money(l.subtotal) : "") + "</td></tr>";
    }).join("");

    var actions = (q.can_close ? '<button type="button" class="hq-btn" data-action="close">Đóng báo giá</button>' : "") +
      (q.can_reopen ? '<button type="button" class="hq-btn" data-action="reopen">Mở lại cho NCC sửa</button>' : "") +
      (q.can_cancel ? '<button type="button" class="hq-btn hq-btn-danger" data-action="cancel">Huỷ</button>' : "") +
      (S.config.can_select ? '<a class="hq-btn" target="_blank" href="' + esc(q.backend_url) +
        '">So sánh &amp; chọn trong Odoo</a>' : "");

    HQ.$("hq-drawer-panel").innerHTML =
      '<div class="hq-drawer-head"><div><div class="hq-muted hq-small">' + esc(q.vendor_name) + "</div>" +
      '<h2 class="hq-h2">' + esc(q.name) + ' <span class="hq-tag ' + (HQ.STATE_CLASS[q.state] || "") + '">' +
      esc(q.state_label) + "</span></h2></div>" +
      '<button type="button" class="btn-close" data-close="drawer" aria-label="Đóng"></button></div>' +
      '<div class="hq-facts">' +
      fact("YCMH", q.request_name || "Chưa gắn") + fact("Đơn bán", q.sale_order || q.origin) +
      fact("Hạn báo giá", q.deadline) + fact("NCC gửi lúc", q.submit_date) + fact("Người hỏi giá", q.user_name) +
      "</div>" +
      (q.share_message ? '<div class="hq-share"><div class="hq-share-head"><b>Tin nhắn gửi NCC</b>' +
        '<button type="button" class="hq-btn hq-btn-mini hq-btn-primary" data-copy-share="1">Copy tin nhắn</button>' +
        '<a class="hq-btn hq-btn-mini" target="_blank" href="' + esc(q.portal_url) + '">Mở trang NCC</a></div>' +
        '<pre class="hq-share-text" id="hq-share-text">' + esc(q.share_message) + "</pre></div>" : "") +
      (q.note ? '<div class="hq-note"><span class="hq-label">Lời nhắn gửi NCC</span>' + esc(q.note) + "</div>" : "") +
      (q.vendor_note ? '<div class="hq-note"><span class="hq-label">NCC ghi chú</span>' +
        esc(q.vendor_note) + "</div>" : "") +
      '<div class="hq-table-wrap"><table class="hq-table"><thead><tr><th>#</th><th></th><th>Mặt hàng</th>' +
      '<th class="hq-num">SL</th><th class="hq-num">Đơn giá chưa VAT</th><th>VAT</th>' +
      '<th class="hq-num">Giao</th><th class="hq-num">Thành tiền</th></tr></thead><tbody>' + lines +
      '</tbody><tfoot><tr><td colspan="7" class="hq-num">Tổng chưa VAT</td><td class="hq-num hq-strong">' +
      HQ.money(q.amount_untaxed) + "</td></tr></tfoot></table></div>" +
      '<div class="hq-drawer-actions">' + actions + "</div>";
  }

  function fact(label, value) {
    return value ? '<div class="hq-fact"><span class="hq-label">' + esc(label) + "</span>" + esc(value) + "</div>" : "";
  }
})(window.HlvQuote);
