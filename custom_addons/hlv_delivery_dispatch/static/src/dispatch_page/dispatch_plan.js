/* Tab "Kế hoạch": danh sách chuyến đã công bố và chi tiết điểm giao của từng chuyến. */
window.HlvDispatch = window.HlvDispatch || {};

(function (HD) {
  "use strict";

  var S = HD.S;
  var esc = HD.esc;
  var badge = HD.badge;

  HD.loadPlan = function () {
    HD.setLoading(true);
    var params = { date: S.date };
    if (S.warehouseId) params.warehouse_id = parseInt(S.warehouseId, 10);
    return HD.rpc("/api/dispatch/plan_day", params).then(function (res) {
      S.plans = res.plans || [];
      S.openTrips = {};
      HD.renderPlan();
    }).catch(function (err) {
      HD.showAlert(err.message);
    }).then(function () { HD.setLoading(false); });
  };

  HD.renderPlan = function () {
    var pane = HD.$("dp-pane-plan");
    if (!S.plans.length) {
      pane.innerHTML = '<div class="dp-empty"><b>Chưa có kế hoạch nào được công bố cho ngày này.</b>' +
        "<br/>Điều phối công bố xong thì kế hoạch sẽ hiện ở đây.</div>";
      return;
    }
    pane.innerHTML = S.plans.map(renderOnePlan).join("");
    bindPlanEvents(pane);
  };

  function renderOnePlan(plan) {
    var head = '<div class="dp-plan-head"><h2>' + esc(plan.warehouse_name) + "</h2>" +
      '<span class="dp-trip-zone">' + plan.trips.length + " chuyến · bản " + plan.version +
      (plan.published_at ? " · công bố " + esc(HD.fmtDateTime(plan.published_at)) : "") +
      "</span></div>";
    var note = plan.note ? '<div class="dp-plan-note">' + esc(plan.note) + "</div>" : "";
    var trips = plan.trips.length
      ? '<div class="dp-trips">' + plan.trips.map(renderTrip).join("") + "</div>"
      : '<div class="dp-empty">Kế hoạch này chưa có chuyến nào.</div>';
    return head + note + trips;
  }

  function tripBadges(trip) {
    var out = [];
    if (trip.mine_stop_count) out.push(badge(trip.mine_stop_count + " điểm của tôi", "dp-badge-blue"));
    if (trip.is_locked) out.push(badge("Đã khoá", "dp-badge-red"));
    else if (trip.accepts_registration) out.push(badge("Còn nhận đăng ký", "dp-badge-green"));
    else out.push(badge("Hết hạn đăng ký", "dp-badge-amber"));
    if (trip.is_over_capacity) out.push(badge("Vượt trần " + trip.max_stops + " điểm", "dp-badge-amber"));
    if (trip.waiting_count) out.push(badge(trip.waiting_count + " đơn chờ hàng", "dp-badge-amber"));
    if (trip.state === "departed") out.push(badge("Đã xuất phát", "dp-badge-blue"));
    if (trip.state === "done") out.push(badge("Hoàn tất", "dp-badge-green"));
    return out;
  }

  function tripMeta(trip) {
    var driver = trip.driver_name || "chưa gán";
    if (trip.driver_note) driver += " — " + trip.driver_note;
    return [
      "<div><b>Cụm:</b> " + esc(trip.zone_name || "chưa gán") + " · " +
        esc(HD.LABEL.SESSION[trip.session] || trip.session) + "</div>",
      "<div><b>Xe:</b> " + esc(trip.vehicle_name || "chưa gán") +
        " · <b>Tài xế:</b> " + esc(driver) + "</div>",
      "<div><b>Điểm:</b> " + trip.stop_count + (trip.max_stops ? "/" + trip.max_stops : "") +
        " · <b>Đơn:</b> " + trip.order_count +
        " · <b>Ước:</b> " + esc(HD.fmtMinutes(trip.estimated_minutes)) + "</div>",
      trip.planned_depart_at
        ? "<div><b>Xuất phát:</b> " + esc(HD.fmtDateTime(trip.planned_depart_at)) + "</div>" : "",
      trip.registration_deadline
        ? "<div><b>Hạn đăng ký:</b> " + esc(HD.fmtDateTime(trip.registration_deadline)) + "</div>" : "",
      trip.is_locked && trip.lock_reason
        ? "<div><b>Lý do khoá:</b> " + esc(trip.lock_reason) + "</div>" : "",
    ].join("");
  }

  function renderTrip(trip) {
    var detail = S.openTrips[trip.id] ? renderStops(S.openTrips[trip.id]) : "";
    var cls = "dp-trip" + (trip.mine_stop_count ? " dp-trip-mine" : "") +
      (trip.is_locked ? " dp-trip-locked" : "");
    return '<article class="' + cls + '" data-trip="' + trip.id + '">' +
      '<div class="dp-trip-head"><div><div class="dp-trip-name">' + esc(trip.name) + "</div>" +
      '<div class="dp-trip-zone">' + esc(trip.zone_name || "") + "</div></div></div>" +
      '<div class="dp-badges">' + tripBadges(trip).join("") + "</div>" +
      '<div class="dp-trip-meta">' + tripMeta(trip) + "</div>" +
      '<div class="dp-trip-actions">' +
      '<button class="dp-btn dp-btn-sm dp-toggle-stops" data-trip="' + trip.id + '">' +
      (S.openTrips[trip.id] ? "Ẩn điểm giao" : "Xem điểm giao") + "</button>" +
      (trip.accepts_registration
        ? '<button class="dp-btn dp-btn-sm dp-btn-primary dp-register" data-trip="' + trip.id +
          '">Đăng ký chuyến này</button>'
        : "") +
      "</div>" + detail + "</article>";
  }

  function renderStop(stop, index) {
    var tags = [];
    if (stop.is_mine) tags.push(badge("Đơn của tôi", "dp-badge-blue"));
    if (stop.has_pending_procedure) {
      tags.push(badge("Chờ thủ tục: " + (stop.pending_procedure_orders || "có đơn"),
        "dp-badge-red"));
    }
    if (stop.needs_technician) tags.push(badge("Cần kỹ thuật", "dp-badge-amber"));
    if (stop.state === "done") tags.push(badge("Đã giao", "dp-badge-green"));
    if (stop.state === "skipped") tags.push(badge("Bỏ qua", ""));

    var shown = stop.orders || [];
    var orders = shown.map(function (order) {
      return "<span" + (order.is_mine ? ' class="dp-order-name"' : "") + ">" +
        esc(order.name) + "</span>";
    }).join("");
    var hiddenOrders = stop.order_count > shown.length
      ? '<span class="dp-stop-sub">(+' + (stop.order_count - shown.length) + " đơn khác)</span>"
      : "";

    return '<div class="dp-stop' + (stop.is_mine ? " dp-stop-mine" : "") + '">' +
      '<div class="dp-stop-num">' + (index + 1) + "</div>" +
      '<div class="dp-stop-body">' +
      '<div class="dp-stop-name">' + esc(stop.point_name) + "</div>" +
      '<div class="dp-stop-sub">' + esc(stop.address || "") + "</div>" +
      '<div class="dp-badges">' + tags.join("") + "</div>" +
      '<div class="dp-stop-orders">' + orders + hiddenOrders + "</div></div></div>";
  }

  function renderStops(trip) {
    var rows = (trip.stops || []).map(renderStop).join("");
    var hidden = trip.hidden_stop_count
      ? '<div class="dp-note">Còn ' + trip.hidden_stop_count +
        " điểm của sale khác — kho này đang tắt chế độ xem chéo.</div>"
      : "";
    var waiting = (trip.waiting || []).length
      ? '<div class="dp-note"><b>Chờ hàng:</b> ' + trip.waiting.map(function (row) {
          return esc(row.order_name) + " (" +
            esc(HD.LABEL.STOCK[row.stock_state] || row.stock_state) + ")";
        }).join(", ") + "</div>"
      : "";
    return '<div class="dp-stops">' +
      (rows || '<div class="dp-note">Chuyến chưa có điểm nào.</div>') +
      hidden + waiting + "</div>";
  }

  function bindPlanEvents(pane) {
    HD.onClick(pane, ".dp-toggle-stops", function (btn) {
      toggleStops(parseInt(btn.dataset.trip, 10));
    });
    HD.onClick(pane, ".dp-register", function (btn) {
      HD.openRegisterModal(parseInt(btn.dataset.trip, 10));
    });
  }

  function toggleStops(tripId) {
    if (S.openTrips[tripId]) {
      delete S.openTrips[tripId];
      HD.renderPlan();
      return;
    }
    HD.setLoading(true);
    HD.rpc("/api/dispatch/trip_detail", { trip_id: tripId }).then(function (res) {
      if (res.status !== "success") { HD.showAlert(res.message); return; }
      S.openTrips[tripId] = res.trip;
      HD.renderPlan();
    }).catch(function (err) { HD.showAlert(err.message); })
      .then(function () { HD.setLoading(false); });
  }

  /** Các chuyến còn nhận đăng ký, dùng để đổ vào ô chọn chuyến của modal. */
  HD.openTripsForRegistration = function () {
    var out = [];
    S.plans.forEach(function (plan) {
      plan.trips.forEach(function (trip) {
        if (trip.accepts_registration) out.push(trip);
      });
    });
    return out;
  };
})(window.HlvDispatch);
