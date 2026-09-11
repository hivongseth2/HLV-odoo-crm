/* Đăng ký chuyến: modal chọn đơn + tab "Đăng ký của tôi". */
window.HlvDispatch = window.HlvDispatch || {};

(function (HD) {
  "use strict";

  var S = HD.S;
  var esc = HD.esc;
  var badge = HD.badge;

  // ------------------------------------------------------------------
  // Tab "Đăng ký của tôi"
  // ------------------------------------------------------------------
  HD.loadRegistrations = function () {
    return HD.rpc("/api/dispatch/my_registrations", {}).then(function (res) {
      S.registrations = res.registrations || [];
      var live = S.registrations.filter(function (reg) {
        return reg.state === "submitted" || reg.state === "accepted";
      }).length;
      HD.$("dp-mine-count").textContent = String(live);
      renderRegistrations();
    }).catch(function (err) { HD.showAlert(err.message); });
  };

  function registrationRow(reg) {
    var state = HD.LABEL.REG_STATE[reg.state] || [reg.state, ""];
    var canCancel = reg.state === "submitted" || reg.state === "accepted";
    return "<tr>" +
      "<td>" + esc(reg.order_name) +
      '<div class="dp-stop-sub">' + esc(reg.partner_name) + "</div></td>" +
      "<td>" + esc(reg.point_name || "—") + "</td>" +
      "<td>" + esc(reg.desired_date) +
      '<div class="dp-stop-sub">' + esc(reg.trip_name || "điều phối tự xếp") + "</div></td>" +
      "<td>" + badge(state[0], state[1]) +
      (reg.auto_accepted ? " " + badge("tự nhận", "") : "") +
      (reg.is_waiting_goods ? " " + badge("chờ hàng", "dp-badge-amber") : "") +
      (reg.priority === "1" ? " " + badge("gấp", "dp-badge-red") : "") + "</td>" +
      "<td>" + esc(HD.LABEL.STOCK[reg.stock_state] || reg.stock_state) + "</td>" +
      "<td>" + esc(reg.dispatcher_note || "") + "</td>" +
      "<td>" + (canCancel
        ? '<button class="dp-btn dp-btn-sm dp-cancel-reg" data-reg="' + reg.id + '">Huỷ</button>'
        : "") + "</td></tr>";
  }

  function renderRegistrations() {
    var pane = HD.$("dp-pane-mine");
    if (!S.registrations.length) {
      pane.innerHTML = '<div class="dp-empty">Bạn chưa đăng ký chuyến nào.</div>';
      return;
    }
    pane.innerHTML = '<div class="dp-table-wrap"><table class="dp-table"><thead><tr>' +
      "<th>Đơn</th><th>Điểm giao</th><th>Ngày / chuyến</th><th>Trạng thái</th>" +
      "<th>Hàng</th><th>Phản hồi điều phối</th><th></th>" +
      "</tr></thead><tbody>" + S.registrations.map(registrationRow).join("") +
      "</tbody></table></div>";
    HD.onClick(pane, ".dp-cancel-reg", function (btn) {
      cancelRegistration(parseInt(btn.dataset.reg, 10));
    });
  }

  function cancelRegistration(id) {
    if (!window.confirm("Huỷ đăng ký này?")) return;
    HD.setLoading(true);
    HD.rpc("/api/dispatch/cancel_registration", { registration_id: id }).then(function (res) {
      if (res.status !== "success") { HD.showAlert(res.message); return; }
      HD.showAlert("Đã huỷ đăng ký.", true);
      return Promise.all([HD.loadRegistrations(), HD.loadPlan()]);
    }).catch(function (err) { HD.showAlert(err.message); })
      .then(function () { HD.setLoading(false); });
  }

  // ------------------------------------------------------------------
  // Modal đăng ký
  // ------------------------------------------------------------------
  HD.openRegisterModal = function (tripId) {
    S.selectedOrderId = null;
    HD.showModalAlert("");
    HD.$("dp-modal-reason").value = "";
    HD.$("dp-modal-urgent").checked = false;
    HD.$("dp-modal-date").value = S.date;
    buildTripOptions(tripId);
    HD.$("dp-modal").classList.remove("dp-hidden");
    searchOrders("");
  };

  function closeModal() { HD.$("dp-modal").classList.add("dp-hidden"); }

  function buildTripOptions(selectedId) {
    var select = HD.$("dp-modal-trip");
    var trips = HD.openTripsForRegistration();
    select.innerHTML = '<option value="">— Không chọn chuyến, điều phối tự xếp —</option>' +
      trips.map(function (trip) {
        var left = trip.max_stops ? " · còn " + trip.slots_left + " chỗ" : "";
        return '<option value="' + trip.id + '">' + esc(trip.name) +
          " (" + esc(trip.zone_name || "") + left + ")</option>";
      }).join("");
    if (selectedId) select.value = String(selectedId);
    toggleDateField();
  }

  /* Chọn chuyến rồi thì ngày đã xác định — ẩn ô ngày đi cho khỏi mâu thuẫn. */
  function toggleDateField() {
    var hasTrip = !!HD.$("dp-modal-trip").value;
    HD.$("dp-modal-date-wrap").classList.toggle("dp-hidden", hasTrip);
  }

  function searchOrders(term) {
    HD.rpc("/api/dispatch/my_orders", { search: term }).then(function (res) {
      if (res.status !== "success") { HD.showModalAlert(res.message); return; }
      S.orders = res.orders || [];
      renderOrderList(res.note);
    }).catch(function (err) { HD.showModalAlert(err.message); });
  }

  function orderRow(order) {
    var blockers = [];
    if (order.already_registered) blockers.push("đã có đăng ký đang chờ");
    if (!order.has_point) blockers.push("khách chưa gắn điểm giao");
    if (order.blocked) blockers.push(order.block_reason);
    var disabled = order.already_registered || !order.has_point;
    var sub = [
      order.partner_name,
      order.point_name || "chưa có điểm",
      HD.LABEL.STOCK[order.stock_state] || order.stock_state,
    ].filter(Boolean).join(" · ");
    return '<div class="dp-order-row' + (disabled ? " dp-order-row-disabled" : "") +
      (S.selectedOrderId === order.id ? " dp-order-row-active" : "") +
      '" data-order="' + order.id + '" data-disabled="' + (disabled ? "1" : "") + '">' +
      '<div class="dp-order-name">' + esc(order.name) + "</div>" +
      '<div class="dp-order-sub">' + esc(sub) + "</div>" +
      (blockers.length
        ? '<div class="dp-order-sub dp-order-blocker">' + esc(blockers.join(" · ")) + "</div>"
        : "") + "</div>";
  }

  function renderOrderList(note) {
    var box = HD.$("dp-order-list");
    if (!S.orders.length) {
      box.innerHTML = '<div class="dp-order-row dp-order-row-disabled">' +
        esc(note || "Không tìm thấy đơn nào của bạn.") + "</div>";
      return;
    }
    box.innerHTML = S.orders.map(orderRow).join("");
    HD.onClick(box, ".dp-order-row", function (row) {
      if (row.dataset.disabled) return;
      S.selectedOrderId = parseInt(row.dataset.order, 10);
      renderOrderList();
    });
  }

  function submitRegistration() {
    if (!S.selectedOrderId) { HD.showModalAlert("Chọn một đơn trước đã."); return; }
    var tripId = HD.$("dp-modal-trip").value;
    var params = {
      order_id: S.selectedOrderId,
      reason: HD.$("dp-modal-reason").value,
      priority: HD.$("dp-modal-urgent").checked ? "1" : "0",
    };
    if (tripId) params.trip_id = parseInt(tripId, 10);
    else params.desired_date = HD.$("dp-modal-date").value;
    if (!tripId && !params.desired_date) {
      HD.showModalAlert("Chọn ngày mong muốn.");
      return;
    }

    HD.$("dp-modal-submit").disabled = true;
    HD.rpc("/api/dispatch/register", params).then(function (res) {
      if (res.status !== "success") { HD.showModalAlert(res.message); return; }
      closeModal();
      var state = (res.registration || {}).state;
      HD.showAlert(state === "accepted"
        ? "Đăng ký đã được nhận vào chuyến."
        : "Đã gửi đăng ký, chờ điều phối duyệt.", true);
      return Promise.all([HD.loadRegistrations(), HD.loadPlan()]);
    }).catch(function (err) { HD.showModalAlert(err.message); })
      .then(function () { HD.$("dp-modal-submit").disabled = false; });
  }

  HD.bindRegisterEvents = function () {
    HD.$("dp-open-register").addEventListener("click", function () { HD.openRegisterModal(null); });
    HD.$("dp-modal-close").addEventListener("click", closeModal);
    HD.$("dp-modal-cancel").addEventListener("click", closeModal);
    HD.$("dp-modal-submit").addEventListener("click", submitRegistration);
    HD.$("dp-modal-trip").addEventListener("change", toggleDateField);

    var searchTimer = null;
    HD.$("dp-order-search").addEventListener("input", function () {
      var term = this.value;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () { searchOrders(term); }, 250);
    });
  };
})(window.HlvDispatch);
