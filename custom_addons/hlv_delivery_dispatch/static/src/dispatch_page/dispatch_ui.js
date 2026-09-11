/* State dùng chung + những thứ có side effect: DOM và gọi API.
   Tách khỏi dispatch_utils.js để phần util giữ được tính thuần. */
window.HlvDispatch = window.HlvDispatch || {};

(function (HD) {
  "use strict";

  /* State dùng chung giữa các tab. Mỗi file feature chỉ đọc/ghi phần của mình. */
  HD.S = {
    date: "",
    warehouseId: "",
    warehouses: [],
    isDispatcher: false,

    plans: [],
    openTrips: {},        // trip_id -> chi tiết đã tải

    registrations: [],
    orders: [],
    selectedOrderId: null,

    profiles: [],         // khách sale phụ trách
    zones: [],
    vehicles: [],
    options: {},
    openProfileId: null,  // profile đang mở form sửa

    tab: "plan",
  };

  HD.$ = function (id) { return document.getElementById(id); };

  /**
   * Gọi endpoint JSON-RPC của Odoo.
   * Trả về Promise của `result`; lỗi phía server được ném thành Error có message đọc được.
   */
  HD.rpc = function (url, params) {
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

  HD.setLoading = function (on) {
    HD.$("dp-loading").classList.toggle("dp-hidden", !on);
  };

  HD.showAlert = function (message, ok) {
    var box = HD.$("dp-alert");
    box.textContent = message || "";
    box.classList.toggle("dp-hidden", !message);
    box.classList.toggle("dp-alert-ok", !!ok);
  };

  HD.showModalAlert = function (message) {
    var box = HD.$("dp-modal-alert");
    box.textContent = message || "";
    box.classList.toggle("dp-hidden", !message);
  };

  /** Gắn handler click cho mọi phần tử khớp selector trong `root`. */
  HD.onClick = function (root, selector, handler) {
    Array.prototype.forEach.call(root.querySelectorAll(selector), function (el) {
      el.addEventListener("click", function () { handler(el); });
    });
  };
})(window.HlvDispatch);
