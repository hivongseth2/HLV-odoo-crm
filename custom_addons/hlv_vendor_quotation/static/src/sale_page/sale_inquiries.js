/* Cột NCC bên trái (chỉ NCC đã được hỏi giá), dải số, tab và bảng phiếu hỏi giá. */
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
    return HQ.api("vendors", {
      search: HQ.$("hq-vendor-search").value,
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
    }).join("") : '<div class="hq-empty">Chưa hỏi giá NCC nào</div>';
  }

  function renderVendorCard() {
    var vendor = currentVendor();
    HQ.$("hq-title").textContent = vendor ? vendor.name : "Phiếu hỏi giá";
    var card = HQ.$("hq-vendor-card");
    card.classList.toggle("hq-hidden", !vendor || !vendor.portal_url);
    if (!vendor || !vendor.portal_url) {
      return;
    }
    card.innerHTML =
      '<span class="hq-muted">Link NCC</span><code class="hq-code hq-ellipsis">' + esc(vendor.portal_url) + "</code>" +
      '<button type="button" class="hq-btn hq-btn-mini" data-copy="' + esc(vendor.portal_url) + '">Copy link</button>' +
      (vendor.password ? '<span class="hq-muted">Mật khẩu</span><code class="hq-code">' + esc(vendor.password) + "</code>" +
        '<button type="button" class="hq-btn hq-btn-mini" data-copy="' + esc(vendor.password) + '">Copy</button>' : "");
  }

  HQ.selectVendor = function (vendorId) {
    S.vendorId = vendorId || null;
    S.page = 1;
    HQ.syncUrl();
    renderVendors();
    renderVendorCard();
    return HQ.loadInquiries();
  };

  /* ---------------- Danh sách phiếu ---------------- */

  HQ.loadInquiries = function () {
    HQ.$("hq-quote-list").classList.add("is-loading");
    return HQ.api("inquiries", {
      vendor_id: S.vendorId,
      status: S.status,
      search: S.search,
      page: S.page,
    }).then(function (res) {
      S.counts = res.counts || {};
      S.pager = res.pager || {};
      S.status = res.status;
      renderTabs();
      renderKpis();
      renderInquiries(res.inquiries || []);
      renderPager();
      renderLegend();
      HQ.showAlert("hq-alert", "");
    }).catch(function (err) {
      HQ.showAlert("hq-alert", err.message);
    }).finally(function () {
      HQ.$("hq-quote-list").classList.remove("is-loading");
    });
  };

  /** Tải lại cả cột NCC và bảng phiếu — sau khi tạo / đổi phiếu. */
  HQ.reloadAll = function () {
    return Promise.all([HQ.loadVendors(), HQ.loadInquiries()]);
  };

  function renderTabs() {
    HQ.$("hq-tabs").innerHTML = (S.config.status_tabs || []).filter(function (tab) {
      // Tab "Đã huỷ" chỉ hiện khi có, cho thanh tab gọn.
      return tab[0] !== "cancel" || S.counts.cancel || S.status === "cancel";
    }).map(function (tab) {
      return '<button type="button" class="hq-btn hq-btn-mini' + (tab[0] === S.status ? " is-active" : "") +
        '" data-status="' + tab[0] + '">' + esc(tab[1]) +
        ' <span class="hq-tab-count">' + (S.counts[tab[0]] || 0) + "</span></button>";
    }).join("");
  }

  function renderKpis() {
    HQ.$("hq-kpis").innerHTML = HQ.KPIS.map(function (kpi) {
      return '<button type="button" class="hq-kpi' + (S.status === kpi[0] ? " is-active" : "") +
        (kpi[0] === "quoted" && S.counts.quoted ? " is-warn" : "") + '" data-status="' + kpi[0] + '">' +
        '<span class="hq-kpi-num">' + (S.counts[kpi[0]] || 0) + "</span>" +
        '<span class="hq-kpi-label">' + esc(kpi[1]) + "</span></button>";
    }).join("");
  }

  function renderInquiries(inquiries) {
    var body = HQ.$("hq-quote-list");
    if (!inquiries.length) {
      body.innerHTML = '<tr><td colspan="8" class="hq-empty">Chưa có phiếu hỏi giá nào.</td></tr>';
      return;
    }
    body.innerHTML = inquiries.map(function (q) {
      var requests = q.requests.map(function (r) {
        return HQ.requestButton(r.id, HQ.colorChip(r.name, HQ.REQUEST_STATE_CLASS[r.state], r.label));
      });
      // Ghi chú kho (giờ hàng về) nằm trong chip của đúng đơn đó.
      var orders = q.orders.map(function (o) {
        return HQ.colorChip(o.name, HQ.ORDER_PROGRESS_CLASS[o.progress],
          o.progress_label + (o.note ? " · Ghi chú kho: " + o.note : ""), o.note);
      });
      var none = '<span class="hq-muted">—</span>';
      // Có tin NCC chưa xem: tô cả dòng + icon tin nhắn nền cam có số — nhìn bảng là biết phiếu nào cần vào xem.
      var chat = HQ.chatIcon(q.chat_count, q.chat_unread);
      return '<tr class="hq-row' + (q.chat_unread ? " hq-row-new" : "") + (q.request_rejected ? " hq-row-alert" : "") +
        '" data-inquiry="' + q.id + '">' +
        '<td class="hq-nowrap"><span class="hq-ref">' + esc(q.name) + "</span>" + (chat ? " " + chat : "") +
        (q.opportunity_ref ? '<div class="hq-muted" title="Số cơ hội">' + esc(q.opportunity_ref) + "</div>" : "") +
        (q.sale_code ? '<div class="hq-muted">' + esc(HQ.saleName(q.sale_code)) + "</div>" : "") + "</td>" +
        '<td class="hq-cell-vendor"><span class="hq-ellipsis">' + esc(q.products) + "</span>" +
        (q.sale_order ? '<div class="hq-docs">' + HQ.docChip(q.sale_order) + "</div>" : "") + "</td>" +
        '<td class="hq-nowrap hq-num">' + q.quoted_count + "/" + q.vendor_count + " NCC</td>" +
        '<td class="hq-nowrap hq-num">' + q.chosen_count + "/" + q.line_count + " sản phẩm</td>" +
        '<td><div class="hq-docs">' + (requests.join("") || none) + "</div></td>" +
        '<td><div class="hq-docs hq-docs-stack">' + (orders.join("") || none) + "</div></td>" +
        '<td class="hq-nowrap hq-num">' + esc(q.deadline || "—") + "</td>" +
        '<td><span class="hq-tag ' + (HQ.SALE_STATUS_CLASS[q.sale_status] || "") + '">' +
        esc(q.sale_status_label) + "</span>" +
        (q.close_reason ? '<div class="hq-muted hq-small">' + esc(q.close_reason) + "</div>" : "") + "</td></tr>";
    }).join("");
  }

  /** Chú thích màu chip YCMH / đơn mua dưới bảng (chip chỉ có màu, không ghi trạng thái). */
  function renderLegend() {
    var legend = HQ.$("hq-list-legend");
    if (!legend || legend.childElementCount) {
      return;
    }
    var row = function (title, items) {
      return '<div><span class="hq-muted">' + title + ":</span> " + items.map(function (item) {
        return '<span class="hq-doc ' + item[0] + '">' + esc(item[1]) + "</span>";
      }).join(" ") + "</div>";
    };
    legend.innerHTML = row("YCMH", HQ.REQUEST_LEGEND) + row("Đơn mua", HQ.ORDER_LEGEND);
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
})(window.HlvQuote);
