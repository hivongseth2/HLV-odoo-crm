/** @odoo-module ignore */
/* Util thuần cho trang /pickup: vào gì ra nấy, không đụng DOM, không gọi mạng, không đọc
   state. Mọi thứ có side effect nằm ở pickup_api.js, pickup_map.js và pickup_render.js. */
window.HlvPickup = window.HlvPickup || {};

(function (HP) {
  "use strict";

  /* Nhãn hiển thị — giữ trùng khớp với selection khai trong model Python. */
  HP.LABEL = {
    /* state -> [nhãn, class badge] */
    STOP: {
      pending: ["Chưa tới", "pk-badge-grey"],
      arrived: ["Đang ở đây", "pk-badge-blue"],
      done: ["Đã nhận xong", "pk-badge-green"],
      skipped: ["Bỏ qua", "pk-badge-grey"],
      failed: ["Không nhận được", "pk-badge-red"],
    },
    LINE: {
      pending: ["Chưa xử lý", "pk-badge-grey"],
      received: ["Đã nhận", "pk-badge-green"],
      partial: ["Nhận một phần", "pk-badge-amber"],
      not_ready: ["Chưa có hàng", "pk-badge-amber"],
      cancelled: ["Bỏ đơn", "pk-badge-grey"],
    },
    RUN: {
      draft: "Nháp",
      assigned: "Chưa xuất phát",
      departed: "Đang đi",
      done: "Đã xong",
      cancelled: "Đã huỷ",
    },
    /* Cùng nội dung với RUN nhưng kèm màu, dùng cho thẻ chuyến ở màn hình chọn. */
    RUN_BADGE: {
      draft: ["Nháp", "pk-badge-grey"],
      assigned: ["Chưa xuất phát", "pk-badge-grey"],
      departed: ["Đang đi", "pk-badge-blue"],
      done: ["Đã xong", "pk-badge-green"],
      cancelled: ["Đã huỷ", "pk-badge-red"],
    },
  };

  /** Ngày hôm nay theo giờ máy người dùng, dạng "YYYY-MM-DD" (khớp input type=date). */
  HP.todayStr = function () {
    var now = new Date();
    return now.getFullYear() +
      "-" + ("0" + (now.getMonth() + 1)).slice(-2) +
      "-" + ("0" + now.getDate()).slice(-2);
  };

  /**
   * Escape HTML. Nhận mọi kiểu; null/undefined ra chuỗi rỗng.
   * Mọi dữ liệu từ server đều phải đi qua đây trước khi nhét vào innerHTML.
   */
  HP.esc = function (value) {
    var div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  };

  /**
   * Datetime UTC của Odoo ("YYYY-MM-DD HH:MM:SS") -> "HH:MM" giờ địa phương.
   * Chuỗi rỗng trả về chuỗi rỗng; chuỗi không parse được trả lại nguyên văn để không nuốt
   * mất thông tin.
   */
  HP.timeOf = function (value) {
    if (!value) {
      return "";
    }
    var date = new Date(String(value).replace(" ", "T") + "Z");
    if (isNaN(date.getTime())) {
      return String(value);
    }
    return ("0" + date.getHours()).slice(-2) + ":" + ("0" + date.getMinutes()).slice(-2);
  };

  /** Số phút -> "1h05" hoặc "24'". 0 hoặc rỗng trả về chuỗi rỗng. */
  HP.duration = function (minutes) {
    var total = parseInt(minutes, 10);
    if (!total || total < 0) {
      return "";
    }
    if (total < 60) {
      return total + "'";
    }
    return Math.floor(total / 60) + "h" + ("0" + (total % 60)).slice(-2);
  };

  /**
   * Mã một lần BẤM, dùng để server bỏ qua các lần gửi lại.
   * Sinh một lần cho mỗi lần bấm — không được sinh lại khi thử gửi lại, nếu không việc
   * chống bấm trùng mất tác dụng.
   */
  HP.eventId = function () {
    if (window.crypto && window.crypto.randomUUID) {
      return window.crypto.randomUUID();
    }
    return "pk-" + Date.now() + "-" + Math.random().toString(36).slice(2, 10);
  };

  /** Giờ hiện tại dạng ISO để gửi lên server làm mốc bấm. */
  HP.nowIso = function () {
    return new Date().toISOString();
  };

  /**
   * Điểm kế tiếp cần thao tác trong danh sách điểm của chuyến.
   * Trả về điểm đang ở (state 'arrived') nếu có, không thì điểm chưa tới đầu tiên.
   * Không có điểm nào cần làm nữa thì trả null.
   */
  HP.nextStop = function (stops) {
    var list = stops || [];
    var current = null;
    var i;
    for (i = 0; i < list.length; i++) {
      if (list[i].state === "arrived") {
        return list[i];
      }
      if (!current && list[i].state === "pending") {
        current = list[i];
      }
    }
    return current;
  };

  /* Google Maps URL API nhận tối đa 9 điểm trung gian, cộng điểm đến là 10. Quá số này thì
     phải cắt bớt — không có cách nào nhồi thêm vào một đường link. */
  HP.MAX_DIR_POINTS = 10;

  /** Một điểm dừng thành tham số cho Google Maps: ưu tiên toạ độ, không có thì địa chỉ chữ. */
  function placeOf(stop) {
    if (stop.lat && stop.lng) {
      return stop.lat + "," + stop.lng;
    }
    return stop.address || stop.point_name || "";
  }

  /** Link chỉ đường Google Maps tới MỘT điểm. */
  HP.directionsUrl = function (stop) {
    return "https://www.google.com/maps/dir/?api=1&destination=" +
      encodeURIComponent(placeOf(stop));
  };

  /**
   * Các điểm còn phải đi, theo thứ tự đang xếp.
   * Điểm đã xong / bỏ qua không tính; điểm không có cả toạ độ lẫn địa chỉ cũng bỏ vì không
   * chỉ đường tới được.
   */
  HP.remainingStops = function (stops) {
    return (stops || []).filter(function (stop) {
      var todo = stop.state === "pending" || stop.state === "arrived";
      return todo && placeOf(stop);
    });
  };

  /**
   * Link chỉ đường Google Maps qua TẤT CẢ các điểm còn lại, theo đúng thứ tự đang xếp.
   *
   * Cố tình KHÔNG truyền điểm xuất phát: để trống thì Google Maps tự lấy vị trí hiện tại
   * của điện thoại. Truyền toạ độ mình đo được thì nó thành vị trí lúc bấm, sai ngay khi xe
   * chạy tiếp — mà việc dẫn đường đã giao cho Google, không phải việc của trang này.
   *
   * Trả về chuỗi rỗng khi không còn điểm nào chỉ đường được.
   */
  HP.directionsAllUrl = function (stops) {
    var places = HP.remainingStops(stops).map(placeOf).slice(0, HP.MAX_DIR_POINTS);
    if (!places.length) {
      return "";
    }
    var url = "https://www.google.com/maps/dir/?api=1&travelmode=driving&destination=" +
      encodeURIComponent(places[places.length - 1]);
    var waypoints = places.slice(0, -1);
    if (waypoints.length) {
      /* Dấu | phân tách các chặng nên phải để nguyên; chỉ mã hoá từng chặng. */
      url += "&waypoints=" + waypoints.map(encodeURIComponent).join("|");
    }
    return url;
  };
})(window.HlvPickup);
