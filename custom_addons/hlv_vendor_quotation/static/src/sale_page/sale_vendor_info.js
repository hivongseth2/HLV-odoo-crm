/* Thông tin một NCC (bấm tên NCC trong phiếu): công ty, người liên hệ, link chung + mật khẩu
   của NCC và tin nhắn soạn sẵn — để sale copy gửi lại khi NCC mất link / quên mật khẩu. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;

  function fact(label, value) {
    return value ? '<div class="hq-fact"><span class="hq-label">' + esc(label) + "</span>" + value + "</div>" : "";
  }

  function link(href, text) {
    return '<a href="' + esc(href) + '">' + esc(text) + "</a>";
  }

  function renderAccess(v) {
    if (!v.portal_url) {
      return '<div class="hq-alert">NCC này chưa có link báo giá.</div>';
    }
    return '<div class="hq-access">' +
      '<span class="hq-label">Link NCC</span><code class="hq-code" title="' + esc(v.portal_url) + '">' +
      esc(v.portal_url) + "</code>" +
      '<button type="button" class="hq-btn hq-btn-mini" data-copy="' + esc(v.portal_url) + '">Copy link</button>' +
      // Mật khẩu rỗng = đang tắt mật khẩu trong Cài đặt: NCC mở link là vào, không cần gửi.
      (v.password ? '<span class="hq-label">Mật khẩu</span><code class="hq-code hq-access-pass">' + esc(v.password) +
        "</code>" + '<button type="button" class="hq-btn hq-btn-mini" data-copy="' + esc(v.password) + '">Copy</button>' : "") +
      "</div>";
  }

  function renderContacts(contacts) {
    if (!contacts.length) {
      return "";
    }
    return '<div class="hq-table-wrap"><table class="hq-table"><thead><tr><th>Người liên hệ</th><th>Điện thoại</th>' +
      "<th>Email</th></tr></thead><tbody>" + contacts.map(function (c) {
        return "<tr><td>" + esc(c.name) + (c.function ? '<div class="hq-muted">' + esc(c.function) + "</div>" : "") +
          "</td><td>" + (c.phone ? link("tel:" + c.phone, c.phone) : "") + "</td><td>" +
          (c.email ? link("mailto:" + c.email, c.email) : "") + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  function render(v) {
    HQ.$("hq-vendor-title").textContent = v.name;
    HQ.$("hq-vendor-body").innerHTML =
      renderAccess(v) +
      '<div class="hq-facts">' +
      fact("Mã số thuế", esc(v.vat)) +
      fact("Điện thoại", v.phone ? link("tel:" + v.phone, v.phone) : "") +
      fact("Di động", v.mobile ? link("tel:" + v.mobile, v.mobile) : "") +
      fact("Email", v.email ? link("mailto:" + v.email, v.email) : "") +
      fact("Website", esc(v.website)) +
      fact("Địa chỉ", esc(v.address)) +
      "</div>" +
      renderContacts(v.contacts) +
      (v.share_message ? '<div class="hq-share"><div class="hq-share-head"><b>Tin nhắn gửi NCC (Zalo)</b>' +
        '<button type="button" class="hq-btn hq-btn-mini" data-copy="' + esc(v.share_message) + '">Copy tin nhắn</button>' +
        '</div><pre class="hq-share-text">' + esc(v.share_message) + "</pre></div>" : "");
  }

  HQ.openVendorInfo = function (quoteId) {
    HQ.$("hq-vendor-title").textContent = "Nhà cung cấp";
    HQ.$("hq-vendor-body").innerHTML = '<div class="hq-loading">Đang tải…</div>';
    HQ.show("hq-vendor", true);
    HQ.api("vendor_info", { quote_id: quoteId }).then(render).catch(function (err) {
      HQ.$("hq-vendor-body").innerHTML = '<div class="hq-alert">' + esc(err.message) + "</div>";
    });
  };

  HQ.bindVendorInfoEvents = function () {
    HQ.on(HQ.$("hq-app"), "click", "[data-vendor-info]", function (el) {
      HQ.openVendorInfo(+el.dataset.vendorInfo);
    });
    HQ.on(HQ.$("hq-vendor"), "click", "[data-close-vendor]", function () {
      HQ.show("hq-vendor", false);
    });
  };
})(window.HlvQuote);
