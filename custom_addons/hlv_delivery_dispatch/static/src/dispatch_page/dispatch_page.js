/* Trang /delivery_plan cho sale — vanilla JS, không dùng framework.
   Trang này cố tình tách khỏi /sale_plan (module hlv_sale_delivery_planning) để không
   phải nhét thêm HTML vào chuỗi _PAGE vốn đã dài trong controller bên đó. */
(function () {
  "use strict";

  var S = {
    date: "",
    warehouseId: "",
    warehouses: [],
    plans: [],
    registrations: [],
    openTrips: {},        // trip_id -> chi tiết đã tải
    orders: [],
    selectedOrderId: null,
    tab: "plan",
    isDispatcher: false,
    profiles: [],         // khách sale phụ trách
    zones: [],
    vehicles: [],
    options: {},
    openProfileId: null,  // profile đang mở form sửa
  };

  var SESSION_LABEL = {
    morning: "Sáng", afternoon: "Chiều", flexible: "Linh hoạt", technical: "Kỹ thuật",
  };
  var STOCK_LABEL = {
    ready: "Đủ hàng", partial_ready: "Đủ một phần", out_of_stock: "Chưa có hàng",
    delivered: "Đã giao", unknown: "Chưa rõ",
  };
  var REG_STATE = {
    draft: ["Nháp", ""], submitted: ["Chờ duyệt", "dp-badge-blue"],
    accepted: ["Đã nhận", "dp-badge-green"], rejected: ["Từ chối", "dp-badge-red"],
    deferred: ["Dời lại", "dp-badge-amber"], cancelled: ["Đã huỷ", ""],
  };
  var PROCEDURE_LABEL = {
    customs: "Cần khai hải quan trước", register: "Cần đăng ký trước",
  };

  // ---------- tiện ích ----------
  function $(id) { return document.getElementById(id); }

  function esc(value) {
    var div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }

  function todayStr() {
    var d = new Date();
    return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2);
  }

  function shiftDate(dateStr, days) {
    var parts = (dateStr || todayStr()).split("-");
    var d = new Date(+parts[0], +parts[1] - 1, +parts[2]);
    d.setDate(d.getDate() + days);
    return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2);
  }

  function fmtDateTime(value) {
    if (!value) return "";
    var d = new Date(value.replace(" ", "T") + "Z");
    if (isNaN(d)) return value;
    return ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2) +
      " " + ("0" + d.getDate()).slice(-2) + "/" + ("0" + (d.getMonth() + 1)).slice(-2);
  }

  function fmtMinutes(total) {
    total = total || 0;
    if (total < 60) return total + " phút";
    return Math.floor(total / 60) + "h" + ("0" + (total % 60)).slice(-2);
  }

  function rpc(url, params) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: params || {} }),
    }).then(function (r) { return r.json(); }).then(function (payload) {
      if (payload.error) {
        var data = payload.error.data || {};
        throw new Error(data.message || payload.error.message || "Lỗi máy chủ");
      }
      return payload.result || {};
    });
  }

  function setLoading(on) { $("dp-loading").classList.toggle("dp-hidden", !on); }

  function showAlert(message, ok) {
    var box = $("dp-alert");
    box.textContent = message || "";
    box.classList.toggle("dp-hidden", !message);
    box.classList.toggle("dp-alert-ok", !!ok);
  }

  function showModalAlert(message) {
    var box = $("dp-modal-alert");
    box.textContent = message || "";
    box.classList.toggle("dp-hidden", !message);
  }

  function badge(text, cls) {
    return '<span class="dp-badge ' + (cls || "") + '">' + esc(text) + "</span>";
  }

  // ---------- tải dữ liệu ----------
  function loadConfig() {
    return rpc("/api/dispatch/config", {}).then(function (res) {
      S.warehouses = res.warehouses || [];
      S.isDispatcher = !!res.is_dispatcher;
      $("dp-user").textContent = res.user_name || "";
      var select = $("dp-warehouse");
      select.innerHTML = '<option value="">Tất cả kho</option>' + S.warehouses.map(function (w) {
        return '<option value="' + w.id + '">' + esc(w.name) + "</option>";
      }).join("");
      if (S.warehouses.length === 1) {
        S.warehouseId = String(S.warehouses[0].id);
        select.value = S.warehouseId;
      }
      if (!res.has_saler_code && !res.is_dispatcher) {
        showAlert("Tài khoản của bạn chưa được khai mã sale MISA nên chưa nhận diện được " +
          "đơn của bạn. Báo quản trị để bổ sung.");
      }
    });
  }

  function loadPlan() {
    setLoading(true);
    var params = { date: S.date };
    if (S.warehouseId) params.warehouse_id = parseInt(S.warehouseId, 10);
    return rpc("/api/dispatch/plan_day", params).then(function (res) {
      S.plans = res.plans || [];
      S.openTrips = {};
      renderPlan();
    }).catch(function (err) {
      showAlert(err.message);
    }).then(function () { setLoading(false); });
  }

  function loadRegistrations() {
    return rpc("/api/dispatch/my_registrations", {}).then(function (res) {
      S.registrations = res.registrations || [];
      var live = S.registrations.filter(function (r) {
        return r.state === "submitted" || r.state === "accepted";
      }).length;
      $("dp-mine-count").textContent = String(live);
      renderRegistrations();
    }).catch(function (err) { showAlert(err.message); });
  }

  // ---------- render kế hoạch ----------
  function renderPlan() {
    var pane = $("dp-pane-plan");
    if (!S.plans.length) {
      pane.innerHTML = '<div class="dp-empty"><b>Chưa có kế hoạch nào được công bố cho ngày này.</b>' +
        "<br/>Điều phối công bố xong thì kế hoạch sẽ hiện ở đây.</div>";
      return;
    }
    pane.innerHTML = S.plans.map(renderOnePlan).join("");
    bindPlanEvents();
  }

  function renderOnePlan(plan) {
    var head = '<div class="dp-plan-head"><h2>' + esc(plan.warehouse_name) + "</h2>" +
      '<span class="dp-trip-zone">' + plan.trips.length + " chuyến · bản " + plan.version +
      (plan.published_at ? " · công bố " + esc(fmtDateTime(plan.published_at)) : "") + "</span></div>";
    var note = plan.note ? '<div class="dp-plan-note">' + esc(plan.note) + "</div>" : "";
    var trips = plan.trips.length
      ? '<div class="dp-trips">' + plan.trips.map(renderTrip).join("") + "</div>"
      : '<div class="dp-empty">Kế hoạch này chưa có chuyến nào.</div>';
    return head + note + trips;
  }

  function renderTrip(trip) {
    var badges = [];
    if (trip.mine_stop_count) badges.push(badge(trip.mine_stop_count + " điểm của tôi", "dp-badge-blue"));
    if (trip.is_locked) badges.push(badge("Đã khoá", "dp-badge-red"));
    else if (trip.accepts_registration) badges.push(badge("Còn nhận đăng ký", "dp-badge-green"));
    else badges.push(badge("Hết hạn đăng ký", "dp-badge-amber"));
    if (trip.is_over_capacity) badges.push(badge("Vượt trần " + trip.max_stops + " điểm", "dp-badge-amber"));
    if (trip.waiting_count) badges.push(badge(trip.waiting_count + " đơn chờ hàng", "dp-badge-amber"));
    if (trip.state === "departed") badges.push(badge("Đã xuất phát", "dp-badge-blue"));
    if (trip.state === "done") badges.push(badge("Hoàn tất", "dp-badge-green"));

    var driver = trip.driver_name || "chưa gán";
    if (trip.driver_note) driver += " — " + trip.driver_note;

    var meta = [
      "<div><b>Cụm:</b> " + esc(trip.zone_name || "chưa gán") + " · " +
        esc(SESSION_LABEL[trip.session] || trip.session) + "</div>",
      "<div><b>Xe:</b> " + esc(trip.vehicle_name || "chưa gán") + " · <b>Tài xế:</b> " + esc(driver) + "</div>",
      "<div><b>Điểm:</b> " + trip.stop_count + (trip.max_stops ? "/" + trip.max_stops : "") +
        " · <b>Đơn:</b> " + trip.order_count +
        " · <b>Ước:</b> " + esc(fmtMinutes(trip.estimated_minutes)) + "</div>",
      trip.planned_depart_at
        ? "<div><b>Xuất phát:</b> " + esc(fmtDateTime(trip.planned_depart_at)) + "</div>" : "",
      trip.registration_deadline
        ? "<div><b>Hạn đăng ký:</b> " + esc(fmtDateTime(trip.registration_deadline)) + "</div>" : "",
      trip.is_locked && trip.lock_reason
        ? "<div><b>Lý do khoá:</b> " + esc(trip.lock_reason) + "</div>" : "",
    ].join("");

    var detail = S.openTrips[trip.id]
      ? renderStops(S.openTrips[trip.id])
      : "";

    var cls = "dp-trip" + (trip.mine_stop_count ? " dp-trip-mine" : "") +
      (trip.is_locked ? " dp-trip-locked" : "");
    return '<article class="' + cls + '" data-trip="' + trip.id + '">' +
      '<div class="dp-trip-head"><div><div class="dp-trip-name">' + esc(trip.name) + "</div>" +
      '<div class="dp-trip-zone">' + esc(trip.zone_name || "") + "</div></div></div>" +
      '<div class="dp-badges">' + badges.join("") + "</div>" +
      '<div class="dp-trip-meta">' + meta + "</div>" +
      '<div class="dp-trip-actions">' +
      '<button class="dp-btn dp-btn-sm dp-toggle-stops" data-trip="' + trip.id + '">' +
      (S.openTrips[trip.id] ? "Ẩn điểm giao" : "Xem điểm giao") + "</button>" +
      (trip.accepts_registration
        ? '<button class="dp-btn dp-btn-sm dp-btn-primary dp-register" data-trip="' + trip.id +
          '">Đăng ký chuyến này</button>'
        : "") +
      "</div>" + detail + "</article>";
  }

  function renderStops(trip) {
    var rows = (trip.stops || []).map(function (stop, index) {
      var tags = [];
      if (stop.is_mine) tags.push(badge("Đơn của tôi", "dp-badge-blue"));
      if (stop.procedure_before && stop.procedure_before !== "none") {
        tags.push(badge(PROCEDURE_LABEL[stop.procedure_before] || "Cần thủ tục", "dp-badge-red"));
      }
      if (stop.needs_technician) tags.push(badge("Cần kỹ thuật", "dp-badge-amber"));
      if (stop.state === "done") tags.push(badge("Đã giao", "dp-badge-green"));
      if (stop.state === "skipped") tags.push(badge("Bỏ qua", ""));

      var orders = (stop.orders || []).map(function (order) {
        return "<span" + (order.is_mine ? ' class="dp-order-name"' : "") + ">" +
          esc(order.name) + "</span>";
      }).join("");

      return '<div class="dp-stop' + (stop.is_mine ? " dp-stop-mine" : "") + '">' +
        '<div class="dp-stop-num">' + (index + 1) + "</div>" +
        '<div class="dp-stop-body">' +
        '<div class="dp-stop-name">' + esc(stop.point_name) + "</div>" +
        '<div class="dp-stop-sub">' + esc(stop.address || "") + "</div>" +
        '<div class="dp-badges">' + tags.join("") + "</div>" +
        '<div class="dp-stop-orders">' + orders +
        (stop.order_count > (stop.orders || []).length
          ? '<span class="dp-stop-sub">(+' + (stop.order_count - stop.orders.length) + " đơn khác)</span>"
          : "") +
        "</div></div></div>";
    }).join("");

    var hidden = trip.hidden_stop_count
      ? '<div class="dp-note">Còn ' + trip.hidden_stop_count +
        " điểm của sale khác — kho này đang tắt chế độ xem chéo.</div>"
      : "";

    var waiting = (trip.waiting || []).length
      ? '<div class="dp-note"><b>Chờ hàng:</b> ' + trip.waiting.map(function (w) {
          return esc(w.order_name) + " (" + esc(STOCK_LABEL[w.stock_state] || w.stock_state) + ")";
        }).join(", ") + "</div>"
      : "";

    return '<div class="dp-stops">' + (rows || '<div class="dp-note">Chuyến chưa có điểm nào.</div>') +
      hidden + waiting + "</div>";
  }

  function bindPlanEvents() {
    Array.prototype.forEach.call(document.querySelectorAll(".dp-toggle-stops"), function (btn) {
      btn.addEventListener("click", function () { toggleStops(parseInt(btn.dataset.trip, 10)); });
    });
    Array.prototype.forEach.call(document.querySelectorAll(".dp-register"), function (btn) {
      btn.addEventListener("click", function () { openModal(parseInt(btn.dataset.trip, 10)); });
    });
  }

  function toggleStops(tripId) {
    if (S.openTrips[tripId]) {
      delete S.openTrips[tripId];
      renderPlan();
      return;
    }
    setLoading(true);
    rpc("/api/dispatch/trip_detail", { trip_id: tripId }).then(function (res) {
      if (res.status !== "success") { showAlert(res.message); return; }
      S.openTrips[tripId] = res.trip;
      renderPlan();
    }).catch(function (err) { showAlert(err.message); })
      .then(function () { setLoading(false); });
  }

  // ---------- render đăng ký của tôi ----------
  function renderRegistrations() {
    var pane = $("dp-pane-mine");
    if (!S.registrations.length) {
      pane.innerHTML = '<div class="dp-empty">Bạn chưa đăng ký chuyến nào.</div>';
      return;
    }
    var rows = S.registrations.map(function (reg) {
      var state = REG_STATE[reg.state] || [reg.state, ""];
      var canCancel = reg.state === "submitted" || reg.state === "accepted";
      return "<tr><td>" + esc(reg.order_name) + "<div class=\"dp-stop-sub\">" +
        esc(reg.partner_name) + "</div></td>" +
        "<td>" + esc(reg.point_name || "—") + "</td>" +
        "<td>" + esc(reg.desired_date) + "<div class=\"dp-stop-sub\">" +
        esc(reg.trip_name || "điều phối tự xếp") + "</div></td>" +
        "<td>" + badge(state[0], state[1]) +
        (reg.auto_accepted ? " " + badge("tự nhận", "") : "") +
        (reg.is_waiting_goods ? " " + badge("chờ hàng", "dp-badge-amber") : "") +
        (reg.priority === "1" ? " " + badge("gấp", "dp-badge-red") : "") + "</td>" +
        "<td>" + esc(STOCK_LABEL[reg.stock_state] || reg.stock_state) + "</td>" +
        "<td>" + esc(reg.dispatcher_note || "") + "</td>" +
        "<td>" + (canCancel
          ? '<button class="dp-btn dp-btn-sm dp-cancel-reg" data-reg="' + reg.id + '">Huỷ</button>'
          : "") + "</td></tr>";
    }).join("");
    pane.innerHTML = '<div class="dp-table-wrap"><table class="dp-table"><thead><tr>' +
      "<th>Đơn</th><th>Điểm giao</th><th>Ngày / chuyến</th><th>Trạng thái</th>" +
      "<th>Hàng</th><th>Phản hồi điều phối</th><th></th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table></div>";

    Array.prototype.forEach.call(pane.querySelectorAll(".dp-cancel-reg"), function (btn) {
      btn.addEventListener("click", function () { cancelRegistration(parseInt(btn.dataset.reg, 10)); });
    });
  }

  function cancelRegistration(id) {
    if (!window.confirm("Huỷ đăng ký này?")) return;
    setLoading(true);
    rpc("/api/dispatch/cancel_registration", { registration_id: id }).then(function (res) {
      if (res.status !== "success") { showAlert(res.message); return; }
      showAlert("Đã huỷ đăng ký.", true);
      return Promise.all([loadRegistrations(), loadPlan()]);
    }).catch(function (err) { showAlert(err.message); })
      .then(function () { setLoading(false); });
  }

  // ---------- khách tôi phụ trách (thói quen giao hàng) ----------
  function loadPoints() {
    return rpc("/api/dispatch/my_points", {}).then(function (res) {
      if (res.status !== "success") { showAlert(res.message); return; }
      S.profiles = res.profiles || [];
      S.zones = res.zones || [];
      S.vehicles = res.vehicles || [];
      S.options = res.options || {};
      $("dp-points-count").textContent = String(res.open_task_count || 0);
      renderPoints();
    }).catch(function (err) { showAlert(err.message); });
  }

  function selectField(name, value, items, blankLabel) {
    var options = (blankLabel ? '<option value="">' + esc(blankLabel) + "</option>" : "") +
      items.map(function (item) {
        var id = String(item[0] !== undefined ? item[0] : item.id);
        var label = item[1] !== undefined ? item[1] : item.name;
        return '<option value="' + esc(id) + '"' +
          (String(value) === id ? " selected" : "") + ">" + esc(label) + "</option>";
      }).join("");
    return '<select data-field="' + name + '">' + options + "</select>";
  }

  function profileForm(profile) {
    function block(label, html, hint) {
      return '<div class="dp-field-block"><label>' + esc(label) + "</label>" + html +
        (hint ? '<span class="dp-stop-sub">' + esc(hint) + "</span>" : "") + "</div>";
    }
    var body =
      block("Cụm tuyến", selectField("zone_id", profile.zone_id, S.zones, "— chưa rõ —")) +
      block("Xe mặc định", selectField("default_vehicle_id", profile.default_vehicle_id,
        S.vehicles, "— tuỳ chuyến —")) +
      block("Hình thức giao", selectField("delivery_method", profile.delivery_method,
        S.options.delivery_method || [])) +
      block("Thủ tục trước khi giao", selectField("procedure_before", profile.procedure_before,
        S.options.procedure_before || []),
        "Khu chế xuất phải khai hải quan trước, có khách phải đăng ký trước mới vào được") +
      block("Thanh toán", selectField("payment_method", profile.payment_method,
        S.options.payment_method || [])) +
      block("Đứng tại điểm (phút)",
        '<input type="number" min="0" step="5" data-field="service_minutes" value="' +
        esc(profile.service_minutes || 0) + '"/>',
        "Để 0 thì dùng định mức chung của cụm") +
      block("Nhận hàng từ",
        '<input type="time" data-field="receiving_from" value="' +
        esc(profile.receiving_from) + '"/>') +
      block("Nhận hàng đến",
        '<input type="time" data-field="receiving_to" value="' +
        esc(profile.receiving_to) + '"/>') +
      block("Hàng quá khổ",
        '<input type="text" data-field="oversize_note" value="' +
        esc(profile.oversize_note) + '" placeholder="VD: thường có thanh thép dài 6m"/>') +
      '<div class="dp-field-block"><label class="dp-check">' +
      '<input type="checkbox" data-field="needs_technician"' +
      (profile.needs_technician ? " checked" : "") + "/> Cần kỹ thuật lắp đặt</label></div>" +
      block("Ghi chú tự do",
        '<textarea rows="2" data-field="free_note" placeholder="Cổng nào, gọi ai, giờ nghỉ trưa…">' +
        esc(profile.free_note) + "</textarea>");

    return '<div class="dp-profile-form" data-profile="' + profile.profile_id + '">' + body +
      '<div class="dp-trip-actions">' +
      '<button class="dp-btn dp-btn-sm dp-profile-save" data-profile="' + profile.profile_id +
      '">Lưu</button>' +
      '<button class="dp-btn dp-btn-sm dp-btn-primary dp-profile-confirm" data-profile="' +
      profile.profile_id + '">Lưu và xác nhận đã đúng</button>' +
      '<button class="dp-btn dp-btn-sm dp-profile-close" data-profile="' + profile.profile_id +
      '">Đóng</button></div></div>';
  }

  function renderPoints() {
    var pane = $("dp-pane-points");
    if (!S.profiles.length) {
      pane.innerHTML = '<div class="dp-empty">Bạn chưa được phân công khách nào.<br/>' +
        "Điều phối suy sale phụ trách từ mã sale của đơn gần nhất tại mỗi điểm giao.</div>";
      return;
    }
    var todo = S.profiles.filter(function (p) { return p.verification_state !== "confirmed"; });
    var head = '<div class="dp-plan-note"><b>' + S.profiles.length + " khách</b> bạn phụ trách · " +
      "<b>" + todo.length + "</b> khách chưa xác nhận thói quen giao hàng. " +
      "Dữ liệu này quyết định điều phối xếp chuyến đúng hay sai.</div>";

    var cards = S.profiles.map(function (profile) {
      var badges = [];
      if (profile.verification_state === "confirmed") badges.push(badge("Đã xác nhận", "dp-badge-green"));
      else if (profile.verification_state === "expired") badges.push(badge("Hết hạn soát lại", "dp-badge-amber"));
      else badges.push(badge("Chưa điền", "dp-badge-amber"));
      if (profile.task_state === "open") {
        badges.push(badge(profile.task_overdue ? "Quá hạn" : "Được giao điền",
          profile.task_overdue ? "dp-badge-red" : "dp-badge-blue"));
      }
      if (profile.task_state === "submitted") badges.push(badge("Chờ điều phối duyệt", "dp-badge-blue"));
      badges.push(badge(Math.round(profile.completeness) + "% đầy", ""));

      var meta = "<div><b>Cụm:</b> " + esc(profile.zone_name || "chưa rõ") +
        " · <b>Mã khách:</b> " + profile.partner_count + "</div>" +
        (profile.address ? "<div>" + esc(profile.address) + "</div>" : "") +
        (profile.missing_fields
          ? "<div><b>Còn thiếu:</b> " + esc(profile.missing_fields) + "</div>" : "") +
        (profile.task_deadline
          ? "<div><b>Hạn:</b> " + esc(profile.task_deadline) + "</div>" : "") +
        (profile.task_note ? "<div><b>Điều phối nhắn:</b> " + esc(profile.task_note) + "</div>" : "");

      var open = S.openProfileId === profile.profile_id;
      return '<article class="dp-trip' + (profile.task_state === "open" ? " dp-trip-mine" : "") +
        '"><div class="dp-trip-head"><div class="dp-trip-name">' + esc(profile.point_name) +
        "</div></div>" +
        '<div class="dp-badges">' + badges.join("") + "</div>" +
        '<div class="dp-trip-meta">' + meta + "</div>" +
        (open ? profileForm(profile)
          : '<div class="dp-trip-actions"><button class="dp-btn dp-btn-sm dp-profile-open" ' +
            'data-profile="' + profile.profile_id + '">Điền thói quen</button></div>') +
        "</article>";
    }).join("");

    pane.innerHTML = head + '<div class="dp-trips">' + cards + "</div>";
    bindPointEvents();
  }

  function bindPointEvents() {
    var pane = $("dp-pane-points");
    Array.prototype.forEach.call(pane.querySelectorAll(".dp-profile-open"), function (btn) {
      btn.addEventListener("click", function () {
        S.openProfileId = parseInt(btn.dataset.profile, 10);
        renderPoints();
      });
    });
    Array.prototype.forEach.call(pane.querySelectorAll(".dp-profile-close"), function (btn) {
      btn.addEventListener("click", function () { S.openProfileId = null; renderPoints(); });
    });
    Array.prototype.forEach.call(pane.querySelectorAll(".dp-profile-save"), function (btn) {
      btn.addEventListener("click", function () {
        saveProfile(parseInt(btn.dataset.profile, 10), false);
      });
    });
    Array.prototype.forEach.call(pane.querySelectorAll(".dp-profile-confirm"), function (btn) {
      btn.addEventListener("click", function () {
        saveProfile(parseInt(btn.dataset.profile, 10), true);
      });
    });
  }

  function collectProfileValues(profileId) {
    var form = document.querySelector('.dp-profile-form[data-profile="' + profileId + '"]');
    if (!form) return null;
    var values = {};
    Array.prototype.forEach.call(form.querySelectorAll("[data-field]"), function (el) {
      var name = el.dataset.field;
      values[name] = el.type === "checkbox" ? el.checked : el.value;
    });
    return values;
  }

  function saveProfile(profileId, confirm) {
    var values = collectProfileValues(profileId);
    if (!values) return;
    setLoading(true);
    rpc("/api/dispatch/profile_save", {
      profile_id: profileId, values: values, confirm: !!confirm,
    }).then(function (res) {
      if (res.status !== "success") { showAlert(res.message); return; }
      var updated = res.profile;
      S.profiles = S.profiles.map(function (p) {
        return p.profile_id === updated.profile_id ? updated : p;
      });
      if (confirm) S.openProfileId = null;
      showAlert(confirm ? "Đã lưu và xác nhận thói quen khách." : "Đã lưu.", true);
      renderPoints();
      return loadPoints();
    }).catch(function (err) { showAlert(err.message); })
      .then(function () { setLoading(false); });
  }

  // ---------- modal đăng ký ----------
  function openModal(tripId) {
    S.selectedOrderId = null;
    showModalAlert("");
    $("dp-modal-reason").value = "";
    $("dp-modal-urgent").checked = false;
    $("dp-modal-date").value = S.date;
    buildTripOptions(tripId);
    $("dp-modal").classList.remove("dp-hidden");
    searchOrders("");
  }

  function closeModal() { $("dp-modal").classList.add("dp-hidden"); }

  function allTrips() {
    var out = [];
    S.plans.forEach(function (plan) {
      plan.trips.forEach(function (trip) {
        if (trip.accepts_registration) out.push(trip);
      });
    });
    return out;
  }

  function buildTripOptions(selectedId) {
    var select = $("dp-modal-trip");
    var trips = allTrips();
    select.innerHTML = '<option value="">— Không chọn chuyến, điều phối tự xếp —</option>' +
      trips.map(function (trip) {
        var left = trip.max_stops ? " · còn " + trip.slots_left + " chỗ" : "";
        return '<option value="' + trip.id + '">' + esc(trip.name) +
          " (" + esc(trip.zone_name || "") + left + ")</option>";
      }).join("");
    if (selectedId) select.value = String(selectedId);
    toggleDateField();
  }

  function toggleDateField() {
    var hasTrip = !!$("dp-modal-trip").value;
    $("dp-modal-date-wrap").classList.toggle("dp-hidden", hasTrip);
  }

  function searchOrders(term) {
    rpc("/api/dispatch/my_orders", { search: term }).then(function (res) {
      if (res.status !== "success") { showModalAlert(res.message); return; }
      S.orders = res.orders || [];
      renderOrderList(res.note);
    }).catch(function (err) { showModalAlert(err.message); });
  }

  function renderOrderList(note) {
    var box = $("dp-order-list");
    if (!S.orders.length) {
      box.innerHTML = '<div class="dp-order-row dp-order-row-disabled">' +
        esc(note || "Không tìm thấy đơn nào của bạn.") + "</div>";
      return;
    }
    box.innerHTML = S.orders.map(function (order) {
      var blockers = [];
      if (order.already_registered) blockers.push("đã có đăng ký đang chờ");
      if (!order.has_point) blockers.push("khách chưa gắn điểm giao");
      if (order.blocked) blockers.push(order.block_reason);
      var disabled = order.already_registered || !order.has_point;
      var sub = [
        order.partner_name,
        order.point_name || "chưa có điểm",
        STOCK_LABEL[order.stock_state] || order.stock_state,
      ].filter(Boolean).join(" · ");
      return '<div class="dp-order-row' + (disabled ? " dp-order-row-disabled" : "") +
        (S.selectedOrderId === order.id ? " dp-order-row-active" : "") +
        '" data-order="' + order.id + '" data-disabled="' + (disabled ? "1" : "") + '">' +
        '<div class="dp-order-name">' + esc(order.name) + "</div>" +
        '<div class="dp-order-sub">' + esc(sub) + "</div>" +
        (blockers.length
          ? '<div class="dp-order-sub" style="color:#b45309">' + esc(blockers.join(" · ")) + "</div>"
          : "") + "</div>";
    }).join("");

    Array.prototype.forEach.call(box.querySelectorAll(".dp-order-row"), function (row) {
      row.addEventListener("click", function () {
        if (row.dataset.disabled) return;
        S.selectedOrderId = parseInt(row.dataset.order, 10);
        renderOrderList();
      });
    });
  }

  function submitRegistration() {
    if (!S.selectedOrderId) { showModalAlert("Chọn một đơn trước đã."); return; }
    var tripId = $("dp-modal-trip").value;
    var params = {
      order_id: S.selectedOrderId,
      reason: $("dp-modal-reason").value,
      priority: $("dp-modal-urgent").checked ? "1" : "0",
    };
    if (tripId) params.trip_id = parseInt(tripId, 10);
    else params.desired_date = $("dp-modal-date").value;
    if (!tripId && !params.desired_date) { showModalAlert("Chọn ngày mong muốn."); return; }

    $("dp-modal-submit").disabled = true;
    rpc("/api/dispatch/register", params).then(function (res) {
      if (res.status !== "success") { showModalAlert(res.message); return; }
      closeModal();
      var state = (res.registration || {}).state;
      showAlert(state === "accepted"
        ? "Đăng ký đã được nhận vào chuyến."
        : "Đã gửi đăng ký, chờ điều phối duyệt.", true);
      return Promise.all([loadRegistrations(), loadPlan()]);
    }).catch(function (err) { showModalAlert(err.message); })
      .then(function () { $("dp-modal-submit").disabled = false; });
  }

  // ---------- tab ----------
  function switchTab(tab) {
    S.tab = tab;
    Array.prototype.forEach.call(document.querySelectorAll(".dp-tab"), function (btn) {
      btn.classList.toggle("dp-tab-active", btn.dataset.tab === tab);
    });
    $("dp-pane-plan").classList.toggle("dp-hidden", tab !== "plan");
    $("dp-pane-mine").classList.toggle("dp-hidden", tab !== "mine");
    $("dp-pane-points").classList.toggle("dp-hidden", tab !== "points");
    // Thanh công cụ ngày/kho chỉ có nghĩa với tab kế hoạch.
    $("dp-open-register").classList.toggle("dp-hidden", tab === "points");
  }

  // ---------- khởi động ----------
  function init() {
    if (!$("dp-app")) return;
    var params = new URLSearchParams(window.location.search);
    S.date = params.get("date") || todayStr();
    $("dp-date").value = S.date;

    $("dp-date").addEventListener("change", function () {
      S.date = this.value || todayStr();
      loadPlan();
    });
    $("dp-warehouse").addEventListener("change", function () {
      S.warehouseId = this.value;
      loadPlan();
    });
    $("dp-prev-day").addEventListener("click", function () {
      S.date = shiftDate(S.date, -1); $("dp-date").value = S.date; loadPlan();
    });
    $("dp-next-day").addEventListener("click", function () {
      S.date = shiftDate(S.date, 1); $("dp-date").value = S.date; loadPlan();
    });
    $("dp-today").addEventListener("click", function () {
      S.date = todayStr(); $("dp-date").value = S.date; loadPlan();
    });
    $("dp-refresh").addEventListener("click", function () {
      showAlert(""); loadPlan(); loadRegistrations(); loadPoints();
    });
    $("dp-open-register").addEventListener("click", function () { openModal(null); });
    $("dp-modal-close").addEventListener("click", closeModal);
    $("dp-modal-cancel").addEventListener("click", closeModal);
    $("dp-modal-submit").addEventListener("click", submitRegistration);
    $("dp-modal-trip").addEventListener("change", toggleDateField);

    var searchTimer = null;
    $("dp-order-search").addEventListener("input", function () {
      var term = this.value;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () { searchOrders(term); }, 250);
    });

    Array.prototype.forEach.call(document.querySelectorAll(".dp-tab"), function (btn) {
      btn.addEventListener("click", function () { switchTab(btn.dataset.tab); });
    });

    var startTab = params.get("tab");
    if (startTab === "mine" || startTab === "points") switchTab(startTab);

    loadConfig().then(loadPlan).then(loadRegistrations).then(loadPoints)
      .catch(function (err) {
        showAlert(err.message);
        setLoading(false);
      });

    // Kế hoạch đổi khi điều phối công bố lại; làm tươi nhẹ thay vì mở kênh bus riêng
    // cho trang này.
    setInterval(function () { if (!document.hidden) loadPlan(); }, 60000);
    window.addEventListener("focus", function () { loadPlan(); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
