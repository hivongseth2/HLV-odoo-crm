/* Hộp trao đổi với NCC trên một báo giá / đơn mua. Server chỉ trả tin thuộc kênh trao đổi
   (bỏ tin hệ thống); tin của sale không gửi email — NCC đọc trên trang báo giá của họ. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var current = null;  // {model: "quote" | "order", id}

  function render(res) {
    HQ.$("hq-chat-title").textContent = "Trao đổi với NCC — " + res.title;
    var list = HQ.$("hq-chat-list");
    list.innerHTML = res.messages.length ? res.messages.map(function (m) {
      return '<div class="hq-msg' + (m.from_vendor ? " hq-msg-vendor" : "") + '">' +
        '<div class="hq-msg-head"><b>' + esc(m.author) + "</b>" +
        (m.from_vendor ? ' <span class="hq-tag hq-tag-warn">NCC</span>' : "") +
        ' <span class="hq-muted">' + esc(m.date) + "</span></div>" +
        '<div class="hq-msg-body">' + esc(m.body) + "</div></div>";
    }).join("") : '<div class="hq-empty">Chưa có tin nhắn nào.</div>';
    list.scrollTop = list.scrollHeight;
  }

  HQ.openChat = function (model, id) {
    current = { model: model, id: id };
    HQ.$("hq-chat-list").innerHTML = '<div class="hq-loading">Đang tải…</div>';
    HQ.$("hq-chat-input").value = "";
    HQ.show("hq-chat", true);
    HQ.api("chat", { model: model, res_id: id }).then(render).catch(function (err) { HQ.toast(err.message); });
  };

  function send() {
    var input = HQ.$("hq-chat-input");
    if (!current || !input.value.trim()) {
      return;
    }
    HQ.$("hq-chat-send").disabled = true;
    HQ.api("chat_post", { model: current.model, res_id: current.id, body: input.value }).then(function (res) {
      input.value = "";
      render(res);
    }).catch(function (err) {
      HQ.toast(err.message);
    }).finally(function () {
      HQ.$("hq-chat-send").disabled = false;
    });
  }

  function close() {
    HQ.show("hq-chat", false);
    current = null;
    // Cập nhật số tin trên ngăn chi tiết.
    if (HQ.S.openInquiryId) {
      HQ.openInquiry(HQ.S.openInquiryId);
    }
  }

  HQ.bindChatEvents = function () {
    HQ.$("hq-chat-send").addEventListener("click", send);
    HQ.$("hq-chat-input").addEventListener("keydown", function (event) {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        send();
      }
    });
    HQ.on(HQ.$("hq-chat"), "click", "[data-close-chat]", close);
    HQ.on(HQ.$("hq-app"), "click", "[data-chat-model]", function (el) {
      HQ.openChat(el.dataset.chatModel, +el.dataset.chatId);
    });
  };
})(window.HlvQuote);
