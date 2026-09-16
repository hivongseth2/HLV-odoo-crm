/** @odoo-module ignore */
/* Kéo thả đổi thứ tự điểm dừng, chạy bằng ngón tay trên điện thoại.

   Vì sao không dùng kéo thả HTML5: trên màn hình cảm ứng nó gần như không hoạt động.
   Vì sao phải có TAY NẮM riêng (.pk-drag) thay vì kéo cả thẻ: tấm trượt bên dưới cũng cuộn
   được, nên chạm vào thẻ phải là CUỘN còn chạm vào tay nắm mới là KÉO. Không tách hai việc
   này thì người dùng vừa định cuộn danh sách đã thành đổi thứ tự điểm.

   File này chỉ lo phần kéo. Nó không biết chuyến hay điểm là gì — thả xong thì gọi lại hàm
   được truyền vào kèm thứ tự id mới. */
window.HlvPickup = window.HlvPickup || {};

(function (HP) {
  "use strict";

  var MOVE_THRESHOLD = 4;
  var drag = null;
  var onDrop = null;

  function cardsIn(group) {
    return Array.prototype.filter.call(group.children, function (node) {
      return node.classList && node.classList.contains("pk-stop");
    });
  }

  function orderOf(group) {
    return cardsIn(group).map(function (node) {
      return parseInt(node.dataset.stopId, 10);
    });
  }

  function start(event) {
    var handle = event.target.closest(".pk-drag");
    if (!handle) {
      return;
    }
    var card = handle.closest(".pk-stop");
    var group = card && card.parentElement;
    if (!card || !group) {
      return;
    }
    /* Chặn cuộn của tấm trượt trong lúc kéo. */
    event.preventDefault();
    drag = {
      card: card,
      group: group,
      y: event.clientY,
      before: orderOf(group).join(","),
      moved: false,
    };
    card.classList.add("pk-dragging");
    handle.setPointerCapture(event.pointerId);
  }

  function move(event) {
    if (!drag) {
      return;
    }
    var delta = event.clientY - drag.y;
    if (Math.abs(delta) > MOVE_THRESHOLD) {
      drag.moved = true;
    }
    drag.card.style.transform = "translateY(" + delta + "px)";

    /* Vượt qua nửa thẻ bên cạnh thì đổi chỗ NGAY trong DOM — danh sách xê dịch theo ngón
       tay, không cần vẽ ô trống giả. Đổi chỗ xong thì lấy mốc lại từ đầu để thẻ vẫn nằm
       dưới ngón tay. */
    var rect = drag.card.getBoundingClientRect();
    var middle = rect.top + rect.height / 2;

    var siblings = cardsIn(drag.group).filter(function (node) {
      return node !== drag.card;
    });
    for (var i = 0; i < siblings.length; i++) {
      var other = siblings[i].getBoundingClientRect();
      var otherMiddle = other.top + other.height / 2;
      var goingUp = delta < 0 && middle < otherMiddle && other.top < rect.top;
      var goingDown = delta > 0 && middle > otherMiddle && other.top > rect.top;
      if (goingUp) {
        drag.group.insertBefore(drag.card, siblings[i]);
      } else if (goingDown) {
        drag.group.insertBefore(drag.card, siblings[i].nextSibling);
      } else {
        continue;
      }
      drag.y = event.clientY;
      drag.card.style.transform = "";
      return;
    }
  }

  function end() {
    if (!drag) {
      return;
    }
    var current = drag;
    drag = null;
    current.card.style.transform = "";
    current.card.classList.remove("pk-dragging");

    var after = orderOf(current.group);
    /* Chỉ báo ra ngoài khi thứ tự THẬT SỰ đổi: kéo lên rồi kéo về chỗ cũ không đáng một
       lượt gọi máy chủ. */
    if (current.moved && after.join(",") !== current.before && onDrop) {
      onDrop(after);
    }
  }

  /**
   * Bật kéo thả cho các thẻ nằm trong ``container``.
   * Gắn theo kiểu uỷ quyền nên gọi MỘT LẦN lúc khởi động là đủ, dù nội dung được vẽ lại
   * sau mỗi thao tác.
   * callback(ids): danh sách id điểm dừng theo thứ tự mới, chỉ trong nhóm vừa kéo.
   */
  HP.initReorder = function (container, callback) {
    if (!container) {
      return;
    }
    onDrop = callback;
    container.addEventListener("pointerdown", start);
    container.addEventListener("pointermove", move);
    container.addEventListener("pointerup", end);
    container.addEventListener("pointercancel", end);
  };
})(window.HlvPickup);
