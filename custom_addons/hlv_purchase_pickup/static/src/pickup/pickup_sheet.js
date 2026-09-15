/** @odoo-module ignore */
/* Tấm trượt dưới đáy màn hình (bottom sheet) cho bước "Đi nhận".

   Ba nấc: peek (chỉ thấy điểm kế tiếp và nút chính) → half (nửa màn) → full (gần kín màn).
   Kéo được bằng ngón tay, và chạm vào thanh nắm thì chuyển nấc — trên xe rung lắc, kéo
   chính xác không dễ nên phải luôn có đường chạm.

   File này chỉ lo hình học của tấm trượt: không biết gì về chuyến, điểm hay đơn. */
window.HlvPickup = window.HlvPickup || {};

(function (HP) {
  "use strict";

  var SNAPS = ["peek", "half", "full"];
  var sheet = null;
  var grab = null;
  var snap = "peek";
  var drag = null;

  /** Chiều cao phần NHÌN THẤY của tấm trượt ở một nấc, tính bằng pixel. */
  function visibleAt(name) {
    var total = sheet.offsetHeight;
    if (name === "full") {
      return total;
    }
    if (name === "half") {
      return Math.min(Math.round(window.innerHeight * 0.5), total);
    }
    /* Nấc peek đo theo nội dung thật của phần đầu chứ không đặt cứng một con số: nút chính
       phải luôn nằm trọn trong tầm nhìn, mà phần đầu cao bao nhiêu là do nội dung quyết định. */
    var head = HP.$("pk-sheet-head");
    return Math.min(grab.offsetHeight + head.offsetHeight + 12, total);
  }

  function translateFor(name) {
    return sheet.offsetHeight - visibleAt(name);
  }

  function applyTransform(offset, animate) {
    sheet.style.transition = animate ? "transform .25s ease" : "none";
    sheet.style.transform = "translateY(" + Math.round(offset) + "px)";
  }

  /** Nấc gần nhất với độ cao đang nhìn thấy — dùng khi thả tay. */
  function nearestSnap(visible) {
    var best = SNAPS[0];
    var bestGap = Infinity;
    SNAPS.forEach(function (name) {
      var gap = Math.abs(visibleAt(name) - visible);
      if (gap < bestGap) {
        bestGap = gap;
        best = name;
      }
    });
    return best;
  }

  HP.sheet = {
    get snap() {
      return snap;
    },

    /** Đặt nấc và trượt tới đó. animate=false dùng khi vẽ lại nội dung, tránh giật. */
    setSnap: function (name, animate) {
      snap = SNAPS.indexOf(name) > -1 ? name : "peek";
      applyTransform(translateFor(snap), animate !== false);
    },

    /** Chạm thanh nắm: peek → half → full → peek. */
    cycle: function () {
      var index = SNAPS.indexOf(snap);
      HP.sheet.setSnap(SNAPS[(index + 1) % SNAPS.length]);
    },

    /** Mở tới nửa màn rồi cuộn tới một điểm — dùng khi chạm ghim trên bản đồ. */
    focusStop: function (stopId) {
      if (snap === "peek") {
        HP.sheet.setSnap("half");
      }
      var node = document.querySelector('.pk-stop[data-stop-id="' + stopId + '"]');
      if (!node) {
        return;
      }
      node.scrollIntoView({ behavior: "smooth", block: "start" });
      node.classList.add("pk-stop-flash");
      window.setTimeout(function () {
        node.classList.remove("pk-stop-flash");
      }, 1200);
    },

    /** Gọi lại sau khi nội dung phần đầu đổi, vì nấc peek đo theo chiều cao phần đầu. */
    refresh: function () {
      if (sheet) {
        applyTransform(translateFor(snap), false);
      }
    },

    init: function () {
      sheet = HP.$("pk-sheet");
      grab = HP.$("pk-sheet-grab");
      if (!sheet || !grab) {
        return;
      }
      HP.sheet.setSnap("peek", false);
      bindDrag();
      window.addEventListener("resize", HP.sheet.refresh);
    },
  };

  function bindDrag() {
    function start(event) {
      drag = {
        y: event.clientY,
        from: translateFor(snap),
        moved: false,
      };
      grab.setPointerCapture(event.pointerId);
    }

    function move(event) {
      if (!drag) {
        return;
      }
      var delta = event.clientY - drag.y;
      if (Math.abs(delta) > 4) {
        drag.moved = true;
      }
      var max = translateFor("peek");
      var offset = Math.min(Math.max(drag.from + delta, 0), max);
      applyTransform(offset, false);
    }

    function end() {
      if (!drag) {
        return;
      }
      var wasDrag = drag.moved;
      drag = null;
      if (!wasDrag) {
        /* Chạm chứ không kéo — chuyển nấc. */
        HP.sheet.cycle();
        return;
      }
      var current = sheet.offsetHeight -
        (parseFloat((sheet.style.transform || "").replace(/[^-\d.]/g, "")) || 0);
      HP.sheet.setSnap(nearestSnap(current));
    }

    grab.addEventListener("pointerdown", start);
    grab.addEventListener("pointermove", move);
    grab.addEventListener("pointerup", end);
    grab.addEventListener("pointercancel", end);
  }
})(window.HlvPickup);
