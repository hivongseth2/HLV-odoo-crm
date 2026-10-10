/* Chuông thông báo + popup khi NCC gửi / cập nhật báo giá, và khi tiến độ đơn mua đổi (NCC đóng gói /
   gửi hàng, kho nhận hàng).

   - Chuông (thanh trên cùng): báo giá NCC gửi và đơn mua đổi tiến độ trong 14 ngày
     (services/sale_feed.py), số đỏ = sau lần cuối mở chuông. Mở chuông là đánh dấu đã xem; bấm một mục để mở phiếu.
   - Có báo giá mới / đơn mua đổi tiến độ (tin "hlv_vq_quoted" / "hlv_vq_order" — sale_bus.js): popup góc phải dưới (bấm để
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
    HQ.$("hq-bell").setAttribute("aria-label", data.unread ? data.unread + " thông báo mới" : "Thông báo báo giá / đơn mua NCC");
    HQ.$("hq-bell-list").innerHTML = data.items.length ? data.items.map(itemHtml).join("")
      : '<div class="hq-bell-empty">Chưa có báo giá hay đơn mua nào đổi trong 14 ngày qua.</div>';
    HQ.show("hq-bell-permission", "Notification" in window && window.Notification.permission === "default");
  }

  function itemHtml(item) {
    var head = '<button type="button" class="hq-bell-item' + (item.unread ? " is-new" : "") + '" data-bell-inquiry="' +
      item.inquiry_id + '">';
    if (item.kind === "order") {
      return head + '<span class="hq-bell-title"><b>' + esc(item.vendor) + "</b> · " + HQ.docChip(item.order_name) +
        ': <span class="hq-tag hq-tag-ok">' + esc(item.status) + '</span></span><span class="hq-bell-meta">' +
        esc([item.inquiry_name, item.ship, item.date].filter(Boolean).join(" · ")) + "</span></button>";
    }
    return head + '<span class="hq-bell-title"><b>' + esc(item.vendor) + "</b> đã báo giá " +
      esc(item.inquiry_name) + '</span><span class="hq-bell-meta">' + HQ.docChip(item.quote_name) + " " + item.offered + "/" +
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

  /** note: {title, text, meta, inquiryId} — bấm popup mở phiếu hỏi giá inquiryId. */
  function showPopup(note) {
    var box = HQ.$("hq-popups");
    var popup = document.createElement("div");
    popup.className = "hq-popup";
    popup.setAttribute("role", "status");
    popup.innerHTML = '<button type="button" class="hq-popup-x" aria-label="Đóng thông báo">×</button>' +
      '<div class="hq-popup-title">' + esc(note.title) + "</div>" +
      '<div class="hq-popup-text">' + esc(note.text) + "</div>" +
      '<div class="hq-popup-meta">' + esc(note.meta) + " — bấm để mở phiếu</div>";
    popup.addEventListener("click", function (event) {
      popup.remove();
      if (!event.target.closest(".hq-popup-x") && note.inquiryId) {
        HQ.openInquiry(note.inquiryId);
      }
    });
    box.appendChild(popup);
    while (box.children.length > POPUP_MAX) {
      box.firstChild.remove();
    }
    setTimeout(function () { popup.remove(); }, POPUP_MS);
  }

  /** Thông báo của hệ điều hành — chỉ khi tab đang ẩn (đang mở trang thì đã có popup). */
  function desktopNotify(note, tag) {
    if (!document.hidden || !("Notification" in window) || window.Notification.permission !== "granted") {
      return;
    }
    var desktop = new window.Notification(note.title, { body: note.text, tag: tag });
    desktop.onclick = function () {
      window.focus();
      if (note.inquiryId) {
        HQ.openInquiry(note.inquiryId);
      }
      desktop.close();
    };
  }

  /** Popup + tiếng + thông báo máy tính + tải lại chuông — chung cho mọi tin. */
  function announce(note, tag) {
    showPopup(note);
    if (window.HlvChatAlert) {
      window.HlvChatAlert.notify(note.text);
    }
    desktopNotify(note, tag);
    HQ.loadBell();
  }

  /** Tin "NCC đã báo giá" từ websocket (sale_bus.js). */
  HQ.onQuoted = function (payload) {
    announce({
      title: payload.resubmitted ? "NCC cập nhật báo giá" : "NCC đã báo giá",
      text: quotedText(payload), meta: payload.name, inquiryId: payload.inquiry_id,
    }, "hlv-vq-quote-" + payload.quote_id);
  };

  /** Tin "tiến độ đơn mua đổi" từ websocket (sale_bus.js): NCC đóng gói / gửi hàng, kho nhận hàng. */
  HQ.onOrderStatus = function (payload) {
    announce({
      title: "Đơn mua " + payload.name + ": " + payload.status,
      text: payload.vendor + " — " + payload.status + (payload.ship ? " (" + payload.ship + ")" : ""),
      meta: payload.inquiry_name, inquiryId: (payload.inquiry_ids || [])[0],
    }, "hlv-vq-order-" + payload.order_id + "-" + payload.status);
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
