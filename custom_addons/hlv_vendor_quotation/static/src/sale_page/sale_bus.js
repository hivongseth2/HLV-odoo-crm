/* Nhận tin trao đổi mới theo thời gian thực (websocket, xem js/odoo_bus.js).

   Tin trên bus chỉ chở id / tên chứng từ (kênh đoán được — xem services/chat_bus.py), nên
   nhận tin xong trang tự gọi lại API đã kiểm quyền: danh sách phiếu (badge tin nhắn), ngăn
   chi tiết đang mở, hộp trao đổi đang mở. Đổi mã sale thì đổi kênh. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var S = HQ.S;
  var bus = null;

  function channelOf(code) {
    var config = S.config.bus || {};
    return code === S.config.all_code ? config.all_channel : (config.channels || {})[code];
  }

  function isOpen(id) {
    return !HQ.$(id).classList.contains("hq-hidden");
  }

  function onChat(payload) {
    var reload = HQ.reloadChat(payload.model, payload.res_id);
    if (payload.from_vendor && window.HlvChatAlert) {
      window.HlvChatAlert.notify(payload.author + " (NCC) vừa nhắn");
    }
    if (payload.from_vendor && !reload) {
      HQ.toast(payload.author + " (NCC) vừa nhắn trên " + payload.name + " — bấm để xem", function () {
        HQ.openChat(payload.model, payload.res_id);
      });
    }
    // Hộp trao đổi đang mở thì đợi nó tải xong (đã ghi "đã xem") rồi mới đếm lại tin mới.
    (reload || Promise.resolve()).then(function () {
      if (isOpen("hq-drawer") && (payload.inquiry_ids || []).indexOf(S.openInquiryId) >= 0) {
        HQ.openInquiry(S.openInquiryId, true);
      }
      HQ.loadInquiries();
    });
  }

  /** NCC vừa gửi / cập nhật báo giá: chuông + popup + tiếng (sale_notify.js), rồi làm mới danh sách
      và ngăn phiếu đang mở nếu đúng phiếu đó. */
  function onQuoted(payload) {
    HQ.onQuoted(payload);
    if (isOpen("hq-drawer") && S.openInquiryId === payload.inquiry_id) {
      HQ.openInquiry(S.openInquiryId, true);
    }
    HQ.loadInquiries();
  }

  /** Nghe kênh của mã sale đang xem; gọi lại mỗi lần đổi mã. */
  HQ.listenBus = function () {
    var channel = channelOf(S.code);
    if (!channel || !window.HlvBus) {
      return;
    }
    if (bus) {
      bus.setChannels([channel]);
      return;
    }
    bus = window.HlvBus.listen({
      version: (S.config.bus || {}).version,
      channels: [channel],
      onMessage: function (type, payload) {
        if (type === "hlv_vq_chat") {
          onChat(payload);
        } else if (type === "hlv_vq_quoted") {
          onQuoted(payload);
        }
      },
    });
  };
})(window.HlvQuote);
