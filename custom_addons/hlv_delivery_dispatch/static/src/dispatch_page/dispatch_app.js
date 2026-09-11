/* Khởi động trang /delivery_plan: nạp cấu hình, nối thanh công cụ, chuyển tab.
   Phải nạp SAU các file feature vì gọi HD.loadPlan / HD.loadPoints / HD.bindRegisterEvents. */
window.HlvDispatch = window.HlvDispatch || {};

(function (HD) {
  "use strict";

  var S = HD.S;

  /* Kế hoạch có thể được điều phối công bố lại bất cứ lúc nào. Trang làm tươi định kỳ
     thay vì mở một kênh bus riêng — chuyến giao hàng đổi theo phút, không theo giây. */
  var REFRESH_MS = 60000;

  function loadConfig() {
    return HD.rpc("/api/dispatch/config", {}).then(function (res) {
      S.warehouses = res.warehouses || [];
      S.isDispatcher = !!res.is_dispatcher;
      HD.$("dp-user").textContent = res.user_name || "";

      var select = HD.$("dp-warehouse");
      select.innerHTML = '<option value="">Tất cả kho</option>' +
        S.warehouses.map(function (warehouse) {
          return '<option value="' + warehouse.id + '">' + HD.esc(warehouse.name) + "</option>";
        }).join("");
      if (S.warehouses.length === 1) {
        S.warehouseId = String(S.warehouses[0].id);
        select.value = S.warehouseId;
      }

      if (!res.has_saler_code && !res.is_dispatcher) {
        HD.showAlert("Tài khoản của bạn chưa được khai mã sale MISA nên chưa nhận diện được " +
          "đơn của bạn. Báo quản trị để bổ sung.");
      }
    });
  }

  function switchTab(tab) {
    S.tab = tab;
    Array.prototype.forEach.call(document.querySelectorAll(".dp-tab"), function (btn) {
      btn.classList.toggle("dp-tab-active", btn.dataset.tab === tab);
    });
    HD.$("dp-pane-plan").classList.toggle("dp-hidden", tab !== "plan");
    HD.$("dp-pane-mine").classList.toggle("dp-hidden", tab !== "mine");
    HD.$("dp-pane-points").classList.toggle("dp-hidden", tab !== "points");
    // Nút đăng ký chỉ có nghĩa khi đang xem kế hoạch hoặc đăng ký của mình.
    HD.$("dp-open-register").classList.toggle("dp-hidden", tab === "points");
  }

  function goToDate(dateStr) {
    S.date = dateStr || HD.todayStr();
    HD.$("dp-date").value = S.date;
    HD.loadPlan();
  }

  function bindToolbar() {
    HD.$("dp-date").addEventListener("change", function () { goToDate(this.value); });
    HD.$("dp-warehouse").addEventListener("change", function () {
      S.warehouseId = this.value;
      HD.loadPlan();
    });
    HD.$("dp-prev-day").addEventListener("click", function () {
      goToDate(HD.shiftDate(S.date, -1));
    });
    HD.$("dp-next-day").addEventListener("click", function () {
      goToDate(HD.shiftDate(S.date, 1));
    });
    HD.$("dp-today").addEventListener("click", function () { goToDate(HD.todayStr()); });
    HD.$("dp-refresh").addEventListener("click", function () {
      HD.showAlert("");
      HD.loadPlan();
      HD.loadRegistrations();
      HD.loadPoints();
    });
    Array.prototype.forEach.call(document.querySelectorAll(".dp-tab"), function (btn) {
      btn.addEventListener("click", function () { switchTab(btn.dataset.tab); });
    });
  }

  function init() {
    if (!HD.$("dp-app")) return;

    var params = new URLSearchParams(window.location.search);
    S.date = params.get("date") || HD.todayStr();
    HD.$("dp-date").value = S.date;

    bindToolbar();
    HD.bindRegisterEvents();

    var startTab = params.get("tab");
    if (startTab === "mine" || startTab === "points") switchTab(startTab);

    loadConfig()
      .then(HD.loadPlan)
      .then(HD.loadRegistrations)
      .then(HD.loadPoints)
      .catch(function (err) {
        HD.showAlert(err.message);
        HD.setLoading(false);
      });

    setInterval(function () { if (!document.hidden) HD.loadPlan(); }, REFRESH_MS);
    window.addEventListener("focus", function () { HD.loadPlan(); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window.HlvDispatch);
