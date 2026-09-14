/* Khởi động trang /pickup: nạp cấu hình, nạp chuyến, bắt sự kiện bấm nút.
   Phải nạp SAU các file khác vì gọi HP.render, HP.send, HP.startQueueWatcher. */
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

  /** Áp kết quả một lời gọi lên màn hình. Kết quả không kèm chuyến thì giữ nguyên màn hình. */
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

  function loadRun() {
    setBusy(true);
    return HP.rpc("/api/pickup/my_run", {}).then(function (result) {
      if (result.status === "error") {
        setAlert(result.message);
        return;
      }
      setAlert("");
      HP.render(result.run || null);
      showOffline();
    }).catch(function (error) {
      setAlert(error.message || "Không tải được chuyến.");
    }).finally(function () {
      setBusy(false);
    });
  }

  /* ----------------------------------------------------------------
     Hộp thoại hỏi lý do — thay cho prompt() vốn bị chặn trên nhiều trình duyệt di động
     ---------------------------------------------------------------- */
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

  /* ----------------------------------------------------------------
     Sự kiện
     ---------------------------------------------------------------- */
  var HANDLERS = {
    depart: function () {
      return send("/api/pickup/run_depart", { run_id: S.run.id });
    },

    finish: function () {
      if (!window.confirm("Kết thúc chuyến? Các điểm chưa tới sẽ bị đánh dấu bỏ qua.")) {
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
    bindModal();
    bindClicks();
    HP.$("pk-refresh").addEventListener("click", loadRun);
    window.addEventListener("online", showOffline);
    window.addEventListener("offline", showOffline);
    HP.startQueueWatcher(function (run) {
      HP.render(run);
      showOffline();
    });
    loadConfig().then(loadRun);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})(window.HlvPickup);
