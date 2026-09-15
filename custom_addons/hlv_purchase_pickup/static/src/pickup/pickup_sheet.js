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
    /* Công bố chiều cao đang che cho CSS dùng: nút tròn và dòng ghi chú trên bản đồ phải
       nằm TRÊN mép tấm trượt, không thì chúng bị che mất tiêu — đúng lỗi "nút tối ưu lộ
       trình đâu rồi". */
    var app = HP.$("pk-app");
    if (app) {
      app.style.setProperty("--pk-sheet-visible",
        Math.round(sheet.offsetHeight - offset) + "px");
    }
  }

  /**
   * Đặt lại vị trí tấm trượt, nhưng ĐO Ở KHUNG HÌNH SAU.
   *
   * Đo ngay lúc vừa gán innerHTML là nguồn của lỗi "tấm trượt hở cả phần thân": lúc
   * ``init()`` chạy thì màn hình bước 3 còn đang ẩn nên mọi phép đo ra 0, và ngay cả khi đã
   * hiện, chiều cao phần đầu chỉ đúng sau khi trình duyệt bố trí lại. Hoãn sang
   * requestAnimationFrame thì lúc đo luôn có số thật.
   */
  function scheduleApply(animate) {
    window.requestAnimationFrame(function () {
      /* Màn hình đang ẩn thì đo không có nghĩa — để nguyên, lần hiện sau sẽ đặt lại. */
      if (!sheet || !sheet.offsetHeight) {
        return;
      }
      applyTransform(translateFor(snap), animate);
    });
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
      scheduleApply(animate !== false);
    },

    /** Chạm thanh nắm: peek → half → full → peek. */
    cycle: function () {
      var index = SNAPS.indexOf(snap);
      HP.sheet.setSnap(SNAPS[(index + 1) % SNAPS.length]);
    },

    /** Mở tới nửa màn rồi cuộn tới một điểm — dùng khi chạm ghim trên bản đồ. */
    focusStop: function (stopId) {
      /* Ghim của điểm ĐANG LÀM không có thẻ trong danh sách (nó ở đầu tấm trượt), nên thu
         gọn lại là vừa đủ thấy nó. */
      var node = HP.$("pk-sheet-body")
        .querySelector('.pk-stop[data-stop-id="' + stopId + '"]');
      if (!node) {
        HP.sheet.setSnap("peek");
        return;
      }
      if (snap === "peek") {
        HP.sheet.setSnap("half");
      }
      node.scrollIntoView({ behavior: "smooth", block: "start" });
      node.classList.add("pk-stop-flash");
      window.setTimeout(function () {
        node.classList.remove("pk-stop-flash");
      }, 1200);
    },

    /** Gọi lại sau khi nội dung phần đầu đổi, vì nấc peek đo theo chiều cao phần đầu. */
    refresh: function () {
      scheduleApply(false);
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

      /* Phần đầu đổi chiều cao mỗi khi sang điểm khác (tên dài ngắn khác nhau, có/không có
         giờ dự kiến). Theo dõi trực tiếp thay vì trông chờ nơi gọi nhớ refresh — quên một
         chỗ là tấm trượt hở ra phần thân đúng như lỗi đã gặp. */
      if (window.ResizeObserver) {
        new window.ResizeObserver(function () {
          HP.sheet.refresh();
        }).observe(HP.$("pk-sheet-head"));
      }
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
