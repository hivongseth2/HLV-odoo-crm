/* Chuông thông báo + popup khi NCC gửi / cập nhật báo giá.

   - Chuông (thanh trên cùng): báo giá NCC gửi trong 14 ngày (services/sale_feed.py), số đỏ = gửi
     sau lần cuối mở chuông. Mở chuông là đánh dấu đã xem; bấm một mục để mở phiếu.
   - Có báo giá mới (tin "hlv_vq_quoted" trên websocket — sale_bus.js): popup góc phải dưới (bấm để
     mở phiếu), tiếng "ting" + nháy tiêu đề tab (js/chat_alert.js), và thông báo của hệ điều hành
     khi đang ở tab khác — nếu sale đã bấm "Bật thông báo trên máy tính" trong chuông. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var POPUP_MS = 10000;
  var POPUP_MAX = 3;
  var feed = { items: [], unread: 0 };

  HQ.loadBell = function () {
    if (!HQ.$("hq-bell")) {
      return Promise.resolve();
    }
    return HQ.api("notifications").then(render).catch(function () { /* chuông phụ, lỗi thì thôi */ });
  };

  function render(data) {
    feed = data;
    var count = HQ.$("hq-bell-count");
    count.textContent = data.unread > 99 ? "99+" : String(data.unread);
    count.classList.toggle("hq-hidden", !data.unread);
    HQ.$("hq-bell").setAttribute("aria-label", data.unread ? data.unread + " báo giá NCC mới" : "Thông báo báo giá NCC");
    HQ.$("hq-bell-list").innerHTML = data.items.length ? data.items.map(itemHtml).join("")
      : '<div class="hq-bell-empty">Chưa có NCC nào báo giá trong 14 ngày qua.</div>';
    HQ.show("hq-bell-permission", "Notification" in window && window.Notification.permission === "default");
  }

  function itemHtml(item) {
    return '<button type="button" class="hq-bell-item' + (item.unread ? " is-new" : "") + '" data-bell-inquiry="' +
      item.inquiry_id + '"><span class="hq-bell-title"><b>' + esc(item.vendor) + "</b> đã báo giá " +
      esc(item.inquiry_name) + '</span><span class="hq-bell-meta">' + esc(item.quote_name) + " · " + item.offered + "/" +
      item.total + " mặt hàng" + (item.amount_total ? " · " + HQ.money(item.amount_total) + " sau VAT" : "") +
      " · " + esc(item.date) + "</span></button>";
  }

  function setPanel(open) {
    HQ.show("hq-bell-panel", open);
    HQ.$("hq-bell").setAttribute("aria-expanded", String(open));
    if (open && feed.unread) {
      // Đã xem: tắt số đỏ ngay; các mục đang hiện giữ nền "mới" tới lần tải sau cho dễ nhìn.
      var items = feed.items;
      HQ.api("notifications_seen").then(function (data) {
        render(Object.assign({}, data, { items: items }));
      }).catch(function (err) { HQ.toast(err.message); });
    }
  }

  function quotedText(payload) {
    return payload.vendor + (payload.resubmitted ? " vừa cập nhật báo giá " : " vừa báo giá ") + payload.inquiry_name;
  }

  function showPopup(payload, text) {
    var box = HQ.$("hq-popups");
    var popup = document.createElement("div");
    popup.className = "hq-popup";
    popup.setAttribute("role", "status");
    popup.innerHTML = '<button type="button" class="hq-popup-x" aria-label="Đóng thông báo">×</button>' +
      '<div class="hq-popup-title">' + (payload.resubmitted ? "NCC cập nhật báo giá" : "NCC đã báo giá") + "</div>" +
      '<div class="hq-popup-text">' + esc(text) + "</div>" +
      '<div class="hq-popup-meta">' + esc(payload.name) + " — bấm để mở phiếu</div>";
    popup.addEventListener("click", function (event) {
      popup.remove();
      if (!event.target.closest(".hq-popup-x")) {
        HQ.openInquiry(payload.inquiry_id);
      }
    });
    box.appendChild(popup);
    while (box.children.length > POPUP_MAX) {
      box.firstChild.remove();
    }
    setTimeout(function () { popup.remove(); }, POPUP_MS);
  }

  /** Thông báo của hệ điều hành — chỉ khi tab đang ẩn (đang mở trang thì đã có popup). */
  function desktopNotify(payload, text) {
    if (!document.hidden || !("Notification" in window) || window.Notification.permission !== "granted") {
      return;
    }
    var note = new window.Notification("Báo giá NCC", { body: text, tag: "hlv-vq-quote-" + payload.quote_id });
    note.onclick = function () {
      window.focus();
      HQ.openInquiry(payload.inquiry_id);
      note.close();
    };
  }

  /** Tin "NCC đã báo giá" từ websocket (sale_bus.js). */
  HQ.onQuoted = function (payload) {
    var text = quotedText(payload);
    showPopup(payload, text);
    if (window.HlvChatAlert) {
      window.HlvChatAlert.notify(text);
    }
    desktopNotify(payload, text);
    HQ.loadBell();
  };

  HQ.bindBellEvents = function () {
    var bell = HQ.$("hq-bell");
    var panel = HQ.$("hq-bell-panel");
    if (!bell) {
      return;  // chuông nằm ở thanh trên — thiếu thì chỉ mất chuông, không làm hỏng cả trang
    }
    bell.addEventListener("click", function () { setPanel(panel.classList.contains("hq-hidden")); });
    document.addEventListener("click", function (event) {
      if (!panel.classList.contains("hq-hidden") && !event.target.closest("#hq-bell, #hq-bell-panel")) {
        setPanel(false);
      }
    });
    HQ.on(panel, "click", "[data-bell-inquiry]", function (el) {
      setPanel(false);
      HQ.openInquiry(+el.dataset.bellInquiry);
    });
    HQ.on(panel, "click", "[data-bell-permission]", function () {
      window.Notification.requestPermission().then(function () { render(feed); });
    });
  };
})(window.HlvQuote);
