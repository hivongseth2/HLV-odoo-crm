/* Trang một hướng dẫn /huong-dan/<slug>/: khai HlvGuide.viewer (cùng giao diện với guide_index.js)
   cho ngăn hỏi đáp bên phải. Hướng dẫn đang mở lấy từ data-guide-* trên <body>. */
(function (ns) {
  "use strict";

  // Hướng dẫn có link sang hướng dẫn khác thì trang này có thể bị mở bên trong khung xem — chuyển
  // sang bản nội dung trơn để không lồng thêm một thanh trên và ngăn hỏi đáp nữa.
  if (window.self !== window.top) {
    location.replace(location.pathname + "?embed=1");
    return;
  }

  var data = document.body.dataset;
  var current = { id: Number(data.guideId), slug: data.guideSlug, name: data.guideName, url: location.pathname };

  ns.viewer = {
    single: true,
    current: current,
    /** Trang chỉ có một hướng dẫn: hướng dẫn khác phải chuyển trang. */
    canShowInline: function () { return false; },
    /** Hướng dẫn đang mở → true; hướng dẫn khác → chuyển sang trang của nó (kèm ?t=ticketId), false. */
    show: function (slug, ticketId) {
      if (slug === current.slug) {
        return true;
      }
      location.href = "/huong-dan/" + encodeURIComponent(slug) + "/" + (ticketId ? "?t=" + ticketId : "");
      return false;
    },
    /** Chọn hướng dẫn khi tạo ticket: chỉ hướng dẫn này (hoặc để chung). */
    guides: function () { return [current]; },
  };
})(window.HlvGuide = window.HlvGuide || {});
