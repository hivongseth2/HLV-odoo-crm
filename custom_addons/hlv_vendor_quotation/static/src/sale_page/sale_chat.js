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
        '<div class="hq-msg-head"><b>' + esc(m.from_vendor ? m.author : m.sale_code || "Bên mình") + "</b>" +
        (m.from_vendor ? ' <span class="hq-tag hq-tag-warn">NCC</span>' : "") +
        ' <span class="hq-muted">' + esc(m.date) + "</span></div>" +
        (m.body ? '<div class="hq-msg-body">' + esc(m.body) + "</div>" : "") +
        (m.attachments.length ? '<div class="hq-msg-files">' + m.attachments.map(function (f) {
          return f.is_image
            ? '<a class="hq-msg-img" target="_blank" href="' + esc(f.url) + '" title="' + esc(f.name) + '">' +
              '<img loading="lazy" src="' + esc(f.url) + '" alt="' + esc(f.name) + '"/></a>'
            : '<a class="hq-chip hq-chip-blue" target="_blank" href="' + esc(f.url) + '">' + esc(f.name) + "</a>";
        }).join("") + "</div>" : "") + "</div>";
    }).join("") : '<div class="hq-empty">Chưa có tin nhắn nào.</div>';
    list.scrollTop = list.scrollHeight;
  }

  HQ.openChat = function (model, id) {
    current = { model: model, id: id };
    HQ.$("hq-chat-list").innerHTML = '<div class="hq-loading">Đang tải…</div>';
    HQ.$("hq-chat-input").value = "";
    clearFiles();
    HQ.show("hq-chat", true);
    HQ.api("chat", { model: model, res_id: id }).then(render).catch(function (err) { HQ.toast(err.message); });
  };

  /** Có tin mới trên model/id: đang mở đúng hộp đó thì tải lại (server ghi luôn "đã xem") và
      trả Promise; không mở thì trả null. */
  HQ.reloadChat = function (model, id) {
    if (!current || current.model !== model || current.id !== id) {
      return null;
    }
    return HQ.api("chat", { model: model, res_id: id }).then(render).catch(function () { /* lần tin sau tải lại */ });
  };

  function clearFiles() {
    HQ.$("hq-chat-files").value = "";
    HQ.$("hq-chat-picked").textContent = "";
  }

  /** Đọc tệp đã chọn thành base64 để gửi kèm trong JSON. Server kiểm loại + cỡ. */
  function readFiles(fileList) {
    return Promise.all(Array.prototype.map.call(fileList, function (file) {
      return new Promise(function (resolve, reject) {
        var reader = new FileReader();
        reader.onload = function () {
          resolve({ name: file.name, data: String(reader.result).split(",")[1] || "" });
        };
        reader.onerror = function () { reject(new Error("Không đọc được tệp " + file.name)); };
        reader.readAsDataURL(file);
      });
    }));
  }

  function send() {
    var input = HQ.$("hq-chat-input");
    var picked = HQ.$("hq-chat-files").files;
    if (!current || (!input.value.trim() && !picked.length)) {
      return;
    }
    HQ.$("hq-chat-send").disabled = true;
    readFiles(picked).then(function (files) {
      return HQ.api("chat_post", { model: current.model, res_id: current.id, body: input.value, files: files });
    }).then(function (res) {
      input.value = "";
      clearFiles();
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
    // Vừa xem xong: bớt số "tin mới" trên ngăn chi tiết và bảng phiếu.
    if (HQ.S.openInquiryId && !HQ.$("hq-drawer").classList.contains("hq-hidden")) {
      HQ.openInquiry(HQ.S.openInquiryId, true);
    }
    HQ.loadInquiries();
  }

  HQ.bindChatEvents = function () {
    HQ.$("hq-chat-send").addEventListener("click", send);
    HQ.$("hq-chat-input").addEventListener("keydown", function (event) {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        send();
      }
    });
    HQ.on(HQ.$("hq-chat"), "click", "[data-close-chat]", close);
    if (window.HlvChatPaste) {
      window.HlvChatPaste.bind(HQ.$("hq-chat-input"), HQ.$("hq-chat-files"));
    }
    HQ.$("hq-chat-files").addEventListener("change", function (event) {
      HQ.$("hq-chat-picked").textContent = Array.prototype.map.call(event.target.files, function (f) {
        return f.name;
      }).join(", ");
    });
    HQ.on(HQ.$("hq-app"), "click", "[data-chat-model]", function (el) {
      HQ.openChat(el.dataset.chatModel, +el.dataset.chatId);
    });
  };
})(window.HlvQuote);
