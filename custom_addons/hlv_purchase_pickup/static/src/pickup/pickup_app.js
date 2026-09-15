/** @odoo-module ignore */
/* Khởi động trang /pickup: nạp cấu hình, điều hướng 4 bước, bắt sự kiện bấm nút.
   Phải nạp SAU các file khác vì gọi HP.render, HP.renderRunList, HP.send, HP.startQueueWatcher. */
window.HlvPickup = window.HlvPickup || {};

(function (HP) {
  "use strict";

  var S = HP.S;

  function setAlert(message, ok) {
    var box = HP.$("pk-alert");
    box.textContent = message || "";
    box.classList.toggle("pk-hidden", !message);
    box.classList.toggle("pk-alert-ok", !!ok);
  }

  function setBusy(on) {
    S.sending = on;
    HP.$("pk-loading").classList.toggle("pk-hidden", !on);
  }

  function showOffline() {
    var offline = window.navigator.onLine === false || HP.queueLength() > 0;
    HP.$("pk-offline").classList.toggle("pk-hidden", !offline);
  }

  /** Áp kết quả một lời gọi lên màn hình. */
  function apply(result) {
    if (!result) {
      return;
    }
    if (result.status === "error") {
      setAlert(result.message);
      return;
    }
    if (result.queued) {
      setAlert(result.message ||
        "Đã ghi lại, đang chờ có sóng để gửi lên. Cứ đi tiếp bình thường.");
      /* Vẽ lại để hiện dấu "đang chờ gửi" và giấu nút vừa bấm. Không vẽ lại thì màn hình
         không đổi gì, người dùng tưởng bấm hụt và bấm lần nữa. */
      HP.render(S.run);
      showOffline();
      return;
    }
    setAlert("");
    if (result.run !== undefined) {
      HP.render(result.run);
    }
    showOffline();
  }

  function send(url, params) {
    setBusy(true);
    return HP.send(url, params).then(function (result) {
      apply(result);
      return result;
    }).catch(function (error) {
      setAlert(error.message || "Không gửi được, thử lại sau ít giây.");
    }).finally(function () {
      setBusy(false);
    });
  }

  // ------------------------------------------------------------------
  // Điều hướng giữa các bước
  // ------------------------------------------------------------------
  /** Bước 1: nạp danh sách chuyến của ngày đang chọn. */
  function loadRunList() {
    S.forcePick = true;
    setBusy(true);
    return HP.rpc("/api/pickup/my_runs", { date: S.date }).then(function (result) {
      if (result.status === "error") {
        setAlert(result.message);
        return;
      }
      setAlert("");
      HP.renderRunList(result.runs || []);
      HP.render(null);
    }).catch(function (error) {
      setAlert(error.message || "Không tải được danh sách chuyến.");
    }).finally(function () {
      setBusy(false);
    });
  }

  /** Mở một chuyến cụ thể. Mở không được thì rơi về bước chọn chuyến chứ không để trang trắng. */
  function openRun(runId) {
    setBusy(true);
    return HP.rpc("/api/pickup/my_run", { run_id: runId }).then(function (result) {
      if (result.status === "error") {
        setAlert(result.message);
        return loadRunList();
      }
      setAlert("");
      if (!result.run) {
        return loadRunList();
      }
      S.forcePick = false;
      S.openedRunId = result.run.id;
      HP.render(result.run);
      showOffline();
      return null;
    }).catch(function (error) {
      setAlert(error.message || "Không tải được chuyến.");
    }).finally(function () {
      setBusy(false);
    });
  }

  /**
   * Tối ưu lộ trình các điểm CHƯA TỚI, tính từ chỗ đang đứng.
   *
   * Cố tình gọi thẳng chứ KHÔNG đẩy vào hàng đợi offline như các nút ghi mốc: xếp lại lộ
   * trình rồi để đó gửi sau là vô nghĩa — lúc gửi được thì người ta đã đi tiếp rồi. Mỗi lần
   * bấm cũng là một lượt gọi Google có tính phí nên phải hỏi lại trước.
   */
  function optimizeRoute() {
    if (S.sending || !S.run) {
      return Promise.resolve();
    }
    if (!window.confirm("Sắp lại thứ tự các điểm chưa tới cho gần nhất, tính từ chỗ bạn " +
        "đang đứng?")) {
      return Promise.resolve();
    }
    setBusy(true);
    return HP.currentPosition().then(function (gps) {
      return HP.rpc("/api/pickup/optimize", {
        run_id: S.run.id,
        gps: gps,
        client_event_id: HP.eventId(),
      });
    }).then(function (result) {
      if (result.status === "error") {
        setAlert(result.message);
        return;
      }
      setAlert("Đã sắp lại thứ tự đi.", true);
      HP.resetMapView();
      HP.render(result.run);
    }).catch(function (error) {
      setAlert(error.message || "Không tối ưu được lộ trình.");
    }).finally(function () {
      setBusy(false);
    });
  }

  /** Nút Tải lại: ở bước chọn thì tải lại danh sách, trong chuyến thì tải lại chuyến đó. */
  function reload() {
    return S.forcePick || !S.openedRunId ? loadRunList() : openRun(S.openedRunId);
  }

  // ------------------------------------------------------------------
  // Hộp thoại hỏi lý do — thay cho prompt() vốn bị chặn trên nhiều trình duyệt di động
  // ------------------------------------------------------------------
  var pendingAsk = null;

  function ask(title, text, placeholder) {
    return new Promise(function (resolve) {
      pendingAsk = resolve;
      HP.$("pk-modal-title").textContent = title;
      HP.$("pk-modal-text").textContent = text || "";
      var input = HP.$("pk-modal-input");
      input.value = "";
      input.placeholder = placeholder || "";
      HP.$("pk-modal-alert").classList.add("pk-hidden");
      HP.$("pk-modal").classList.remove("pk-hidden");
      input.focus();
    });
  }

  function closeAsk(value) {
    HP.$("pk-modal").classList.add("pk-hidden");
    var resolve = pendingAsk;
    pendingAsk = null;
    if (resolve) {
      resolve(value);
    }
  }

  function bindModal() {
    HP.$("pk-modal-cancel").addEventListener("click", function () {
      closeAsk(null);
    });
    HP.$("pk-modal-ok").addEventListener("click", function () {
      var value = HP.$("pk-modal-input").value.trim();
      if (!value) {
        var alertBox = HP.$("pk-modal-alert");
        alertBox.textContent = "Phải ghi lý do.";
        alertBox.classList.remove("pk-hidden");
        return;
      }
      closeAsk(value);
    });
  }

  // ------------------------------------------------------------------
  // Sự kiện
  // ------------------------------------------------------------------
  var HANDLERS = {
    "open-run": function (node) {
      return openRun(parseInt(node.dataset.runId, 10));
    },

    pick: function () {
      return loadRunList();
    },

    depart: function () {
      return send("/api/pickup/run_depart", { run_id: S.run.id });
    },

    finish: function () {
      var left = S.run.stop_count - S.run.done_stop_count;
      var question = left > 0
        ? "Còn " + left + " điểm chưa tới. Kết thúc chuyến bây giờ? Các điểm đó sẽ bị đánh " +
          "dấu bỏ qua."
        : "Kết thúc chuyến?";
      if (!window.confirm(question)) {
        return Promise.resolve();
      }
      return send("/api/pickup/run_finish", { run_id: S.run.id });
    },

    arrive: function (node) {
      /* Lấy GPS TRƯỚC khi gửi, nhưng không chờ quá lâu: currentPosition luôn trả về sau tối
         đa 6 giây, null nếu không lấy được. Mốc thời gian quan trọng hơn toạ độ. */
      return HP.currentPosition().then(function (gps) {
        return send("/api/pickup/stop_arrive", {
          stop_id: parseInt(node.dataset.stopId, 10),
          gps: gps,
        });
      });
    },

    "stop-done": function (node) {
      return send("/api/pickup/stop_done", { stop_id: parseInt(node.dataset.stopId, 10) });
    },

    skip: function (node) {
      return ask("Bỏ qua điểm này", "Vì sao không ghé điểm này?",
        "VD: nhà cung cấp báo chưa có hàng").then(function (reason) {
        if (!reason) {
          return null;
        }
        return send("/api/pickup/stop_skip", {
          stop_id: parseInt(node.dataset.stopId, 10),
          reason: reason,
        });
      });
    },

    "line-received": function (node) {
      return send("/api/pickup/line_state", {
        line_id: parseInt(node.dataset.lineId, 10),
        state: "received",
      });
    },

    "line-not-ready": function (node) {
      return ask("Chưa lấy được đơn này", "Nhà cung cấp nói gì?",
        "VD: hàng về chiều mai").then(function (reason) {
        if (!reason) {
          return null;
        }
        return send("/api/pickup/line_state", {
          line_id: parseInt(node.dataset.lineId, 10),
          state: "not_ready",
          note: reason,
        });
      });
    },
  };

  function bindClicks() {
    document.addEventListener("click", function (event) {
      var node = event.target.closest("[data-action]");
      if (!node || S.sending) {
        return;
      }
      var handler = HANDLERS[node.dataset.action];
      if (!handler) {
        return;
      }
      event.preventDefault();
      handler(node);
    });
  }

  function loadConfig() {
    return HP.rpc("/api/pickup/config", {}).then(function (result) {
      S.requireReturn = result.require_return !== false;
      S.isManager = !!result.is_manager;
    }).catch(function () {
      /* Không lấy được cấu hình thì dùng mặc định — không được để trang trắng chỉ vì một
         tuỳ chọn hiển thị. */
    });
  }

  function start() {
    var app = HP.$("pk-app");
    /* Có run_id nghĩa là vào từ mã QR trên tờ lịch in — mở thẳng chuyến đó, bỏ qua bước
       chọn ngày. Đây là toàn bộ lý do tồn tại của mã QR. */
    var fromQr = parseInt((app && app.dataset.runId) || "", 10) || null;

    S.date = HP.todayStr();
    HP.$("pk-date").value = S.date;

    bindModal();
    bindClicks();
    HP.sheet.init();
    HP.$("pk-refresh").addEventListener("click", reload);
    HP.$("pk-back").addEventListener("click", loadRunList);
    HP.$("pk-recenter").addEventListener("click", HP.centerOnMe);
    HP.$("pk-optimize").addEventListener("click", optimizeRoute);
    HP.$("pk-date").addEventListener("change", function (event) {
      S.date = event.target.value || HP.todayStr();
      loadRunList();
    });
    window.addEventListener("online", showOffline);
    window.addEventListener("offline", showOffline);
    HP.startQueueWatcher(function (run) {
      HP.render(run);
      showOffline();
    });

    loadConfig().then(function () {
      /* Không có mã QR thì LUÔN bắt đầu ở bước chọn chuyến, kể cả khi đang có chuyến dở.
         Một ngày có thể có chuyến sáng và chuyến chiều; tự mở giùm một chuyến là mời người
         đi nhận bấm mốc vào nhầm chuyến. Chuyến đang đi đã được xếp lên đầu danh sách nên
         mở lại cũng chỉ tốn một lần chạm. */
      return fromQr ? openRun(fromQr) : loadRunList();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})(window.HlvPickup);
