/* Gọi server và hàng đợi offline cho trang /pickup.

   Người đi nhận đứng trong khu công nghiệp, sóng chập chờn. Nguyên tắc: BẤM LÀ XONG — thao
   tác được ghi vào hàng đợi ngay lập tức kèm mã lần bấm và giờ bấm, rồi mới thử gửi. Mất
   mạng thì nằm trong hàng đợi tới khi có sóng; server bỏ qua các lần gửi lại nhờ mã lần bấm
   nên gửi mấy lần cũng chỉ tính một. */
window.HlvPickup = window.HlvPickup || {};

(function (HP) {
  "use strict";

  var QUEUE_KEY = "hlv_pickup_queue";
  var RETRY_MS = 15000;
  /* Chỉ gửi một thao tác tại một thời điểm: thứ tự các mốc là thứ tự có ý nghĩa, gửi vượt
     mặt nhau sẽ ra chuyến đi lộn xộn. */
  var sending = false;

  /* State dùng chung của cả trang. Chỉ file này và pickup_app.js được ghi vào đây. */
  HP.S = {
    run: null,
    requireReturn: true,
    isManager: false,
    sending: false,
  };

  HP.$ = function (id) {
    return document.getElementById(id);
  };

  /** Gọi một route json của Odoo. Trả promise, reject kèm Error có message tiếng Việt. */
  HP.rpc = function (url, params) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: params || {} }),
    }).then(function (response) {
      return response.json();
    }).then(function (payload) {
      if (payload.error) {
        var data = payload.error.data || {};
        throw new Error(data.message || payload.error.message || "Lỗi máy chủ");
      }
      return payload.result || {};
    });
  };

  /* ----------------------------------------------------------------
     Hàng đợi
     ---------------------------------------------------------------- */
  /* Hàng đợi thật nằm trong bộ nhớ; localStorage chỉ là bản sao để sống sót qua việc đóng
     trang. Nếu lấy localStorage làm nguồn sự thật thì trình duyệt chặn lưu trữ (chế độ
     riêng tư) sẽ làm thao tác vừa bấm biến mất — đúng thứ hàng đợi này sinh ra để chống. */
  var queue = restoreQueue();

  function restoreQueue() {
    try {
      var saved = JSON.parse(window.localStorage.getItem(QUEUE_KEY) || "[]");
      return Array.isArray(saved) ? saved : [];
    } catch (error) {
      return [];
    }
  }

  function persistQueue() {
    try {
      window.localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
    } catch (error) {
      /* Hết chỗ hoặc bị chặn: thao tác vẫn nằm trong bộ nhớ và vẫn gửi được, chỉ mất khả
         năng gửi lại sau khi đóng trang. Không được để lỗi này chặn việc bấm nút. */
    }
  }

  HP.queueLength = function () {
    return queue.length;
  };

  /**
   * Các bản ghi đang chờ gửi, để màn hình đánh dấu "đã bấm, chờ gửi".
   * Trả về {stops: {id: true}, lines: {id: true}, runs: {id: true}}.
   * Thiếu cái này thì mất sóng xong màn hình không đổi gì, người dùng tưởng hụt và bấm lại
   * — mỗi lần bấm là một mã lần bấm mới nên server sẽ tính thành hai thao tác thật.
   */
  HP.queuedKeys = function () {
    var keys = { stops: {}, lines: {}, runs: {} };
    queue.forEach(function (item) {
      if (item.params.stop_id) {
        keys.stops[item.params.stop_id] = true;
      }
      if (item.params.line_id) {
        keys.lines[item.params.line_id] = true;
      }
      if (item.params.run_id) {
        keys.runs[item.params.run_id] = true;
      }
    });
    return keys;
  };

  /**
   * Gửi một thao tác có ghi nhận.
   * url: route json. params: tham số, KHÔNG cần tự thêm client_event_id/client_ts.
   * Trả promise resolve với payload server, hoặc với {queued: true} khi đang mất mạng.
   */
  HP.send = function (url, params) {
    var item = {
      url: url,
      params: Object.assign({}, params || {}, {
        /* Sinh MỘT LẦN ở đây. Mọi lần gửi lại đều dùng lại đúng mã này — sinh mã mới khi
           retry sẽ làm server tưởng là hai lần bấm khác nhau. */
        client_event_id: HP.eventId(),
        client_ts: HP.nowIso(),
      }),
    };
    queue.push(item);
    persistQueue();
    return HP.flushQueue();
  };

  /**
   * Gửi hết hàng đợi theo đúng thứ tự đã bấm.
   * Dừng ngay ở thao tác đầu tiên gặp lỗi mạng và giữ lại phần còn lại: thứ tự các mốc là
   * thứ tự có ý nghĩa, gửi vượt mặt nhau sẽ ra chuyến đi lộn xộn.
   * Trả promise resolve với kết quả của thao tác cuối cùng gửi được, hoặc {queued: true}.
   */
  HP.flushQueue = function () {
    if (!queue.length || sending) {
      return Promise.resolve({});
    }
    sending = true;

    var item = queue[0];
    return HP.rpc(item.url, item.params).then(function (result) {
      /* Xoá theo THAM CHIẾU chứ không theo chỉ số: trong lúc chờ trả lời có thể có thao tác
         mới được đẩy vào hàng đợi. */
      var index = queue.indexOf(item);
      if (index > -1) {
        queue.splice(index, 1);
      }
      persistQueue();
      sending = false;
      if (result && result.status === "error") {
        /* Server từ chối vì lý do nghiệp vụ (VD chuyến đã đóng). Gửi lại cũng vẫn bị từ
           chối, nên bỏ khỏi hàng đợi và báo cho người dùng biết. */
        return result;
      }
      return HP.flushQueue().then(function (next) {
        return next && next.run ? next : result;
      });
    }).catch(function (error) {
      sending = false;
      /* Giữ nguyên trong hàng đợi để thử lại. Mã lần bấm không đổi nên gửi lại an toàn. */
      if (window.navigator.onLine === false) {
        return { queued: true };
      }
      return { queued: true, message: error.message };
    });
  };

  /** Tự gửi lại hàng đợi khi có sóng trở lại và theo nhịp cố định. */
  HP.startQueueWatcher = function (onFlushed) {
    function flush() {
      if (!HP.queueLength()) {
        return;
      }
      HP.flushQueue().then(function (result) {
        if (result && result.run && onFlushed) {
          onFlushed(result.run);
        }
      });
    }
    window.addEventListener("online", flush);
    window.setInterval(flush, RETRY_MS);
  };

  /**
   * Vị trí hiện tại của thiết bị.
   * Trả promise LUÔN resolve: null khi không lấy được. Không bao giờ reject — thiếu GPS
   * không được phép chặn việc ghi mốc thời gian, mốc mới là thứ quan trọng.
   */
  HP.currentPosition = function () {
    return new Promise(function (resolve) {
      if (!window.navigator.geolocation) {
        resolve(null);
        return;
      }
      var settled = false;
      function finish(value) {
        if (!settled) {
          settled = true;
          resolve(value);
        }
      }
      window.setTimeout(function () {
        finish(null);
      }, 6000);
      window.navigator.geolocation.getCurrentPosition(function (position) {
        finish({
          lat: position.coords.latitude,
          lng: position.coords.longitude,
          accuracy: Math.round(position.coords.accuracy || 0),
        });
      }, function () {
        finish(null);
      }, { enableHighAccuracy: true, timeout: 5000, maximumAge: 30000 });
    });
  };
})(window.HlvPickup);
