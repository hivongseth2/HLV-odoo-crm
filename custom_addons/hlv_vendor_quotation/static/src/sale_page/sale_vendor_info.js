/* Thông tin một NCC (bấm tên NCC trong phiếu): công ty, người liên hệ, link chung + mật khẩu
   của NCC và tin nhắn soạn sẵn — để sale copy gửi lại khi NCC mất link / quên mật khẩu, hoặc
   gửi thẳng qua email (nội dung điền sẵn từ tin nhắn, sửa được). */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var currentQuote = null;  // báo giá đang mở trong hộp — để gửi email đúng NCC

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
        (v.mail ? '<button type="button" class="hq-btn hq-btn-mini" data-mail-toggle="1">Gửi email…</button>' : "") +
        '</div><pre class="hq-share-text">' + esc(v.share_message) + "</pre></div>" +
        (v.mail ? renderMail(v.mail, v.share_message) : "") : "");
  }

  /** Hộp gửi email (ẩn tới khi bấm "Gửi email…"): nội dung = tin nhắn Zalo, sửa được. */
  function renderMail(mail, body) {
    var chips = mail.suggestions.length > 1 ? '<div class="hq-mail-chips">' + mail.suggestions.map(function (email) {
      return '<button type="button" class="hq-chip" data-mail-add="' + esc(email) + '">+ ' + esc(email) + "</button>";
    }).join("") + "</div>" : "";
    return '<form class="hq-mail hq-hidden" id="hq-mail-form">' +
      '<div class="hq-share-head"><b>Gửi email cho NCC</b></div>' +
      '<label class="hq-mail-row"><span class="hq-label">Gửi tới</span>' +
      '<input type="text" class="hq-input" name="to" value="' + esc(mail.to) + '" placeholder="email@ncc.vn, nhiều địa chỉ cách nhau dấu phẩy"/></label>' +
      chips +
      '<label class="hq-mail-row"><span class="hq-label">CC</span>' +
      '<input type="text" class="hq-input" name="cc" value="' + esc(mail.cc) + '" placeholder="Không bắt buộc"/></label>' +
      '<label class="hq-mail-row"><span class="hq-label">Tiêu đề</span>' +
      '<input type="text" class="hq-input" name="subject" maxlength="200" value="' + esc(mail.subject) + '"/></label>' +
      '<label class="hq-mail-row hq-mail-body"><span class="hq-label">Nội dung</span>' +
      '<textarea class="hq-input" name="body" rows="7">' + esc(body) + "</textarea></label>" +
      '<div class="hq-mail-foot"><span class="hq-muted" id="hq-mail-status"></span>' +
      '<button type="submit" class="hq-btn hq-btn-primary">Gửi email</button></div></form>';
  }

  function addRecipient(form, email) {
    var input = form.elements.to;
    var current = input.value.split(/[,;\s]+/).filter(Boolean);
    if (current.map(function (e) { return e.toLowerCase(); }).indexOf(email.toLowerCase()) < 0) {
      input.value = current.concat([email]).join(", ");
    }
  }

  function sendMail(form) {
    var status = HQ.$("hq-mail-status");
    var button = form.querySelector('[type="submit"]');
    button.disabled = true;
    status.textContent = "Đang gửi…";
    status.classList.remove("hq-error");
    HQ.api("send_mail", {
      quote_id: currentQuote,
      to: form.elements.to.value,
      cc: form.elements.cc.value,
      subject: form.elements.subject.value,
      body: form.elements.body.value,
    }).then(function (res) {
      status.textContent = (res.state === "sent" ? "Đã gửi tới " : "Đã xếp hàng gửi tới ") + res.to.join(", ");
    }).catch(function (err) {
      status.textContent = err.message;
      status.classList.add("hq-error");
    }).then(function () {
      button.disabled = false;
    });
  }

  HQ.openVendorInfo = function (quoteId) {
    currentQuote = quoteId;
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
    var box = HQ.$("hq-vendor");
    HQ.on(box, "click", "[data-close-vendor]", function () {
      HQ.show("hq-vendor", false);
    });
    HQ.on(box, "click", "[data-mail-toggle]", function () {
      var form = HQ.$("hq-mail-form");
      form.classList.toggle("hq-hidden");
      if (!form.classList.contains("hq-hidden")) {
        form.elements.to.focus();
      }
    });
    HQ.on(box, "click", "[data-mail-add]", function (el) {
      addRecipient(HQ.$("hq-mail-form"), el.dataset.mailAdd);
    });
    box.addEventListener("submit", function (event) {
      if (event.target.id === "hq-mail-form") {
        event.preventDefault();
        sendMail(event.target);
      }
    });
  };
})(window.HlvQuote);
