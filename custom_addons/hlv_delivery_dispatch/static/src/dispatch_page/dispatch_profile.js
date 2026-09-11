/* Tab "Khách tôi phụ trách": sale điền thói quen giao hàng của khách mình phụ trách.
   Server mới là nơi quyết định field nào được ghi — danh sách ở đây chỉ để dựng form. */
window.HlvDispatch = window.HlvDispatch || {};

(function (HD) {
  "use strict";

  var S = HD.S;
  var esc = HD.esc;
  var badge = HD.badge;

  HD.loadPoints = function () {
    return HD.rpc("/api/dispatch/my_points", {}).then(function (res) {
      if (res.status !== "success") { HD.showAlert(res.message); return; }
      S.profiles = res.profiles || [];
      S.zones = res.zones || [];
      S.vehicles = res.vehicles || [];
      S.options = res.options || {};
      HD.$("dp-points-count").textContent = String(res.open_task_count || 0);
      renderPoints();
    }).catch(function (err) { HD.showAlert(err.message); });
  };

  function fieldBlock(label, html, hint) {
    return '<div class="dp-field-block"><label>' + esc(label) + "</label>" + html +
      (hint ? '<span class="dp-stop-sub">' + esc(hint) + "</span>" : "") + "</div>";
  }

  function textInput(name, value, placeholder) {
    return '<input type="text" data-field="' + name + '" value="' + esc(value || "") +
      '" placeholder="' + esc(placeholder || "") + '"/>';
  }

  function profileForm(profile) {
    var body =
      fieldBlock("Cụm tuyến", HD.selectHtml("zone_id", profile.zone_id, S.zones, "— chưa rõ —")) +
      fieldBlock("Xe mặc định",
        HD.selectHtml("default_vehicle_id", profile.default_vehicle_id, S.vehicles, "— tuỳ chuyến —")) +
      fieldBlock("Hình thức giao",
        HD.selectHtml("delivery_method", profile.delivery_method, S.options.delivery_method)) +
      fieldBlock("Thanh toán",
        HD.selectHtml("payment_method", profile.payment_method, S.options.payment_method)) +
      fieldBlock("Đứng tại điểm (phút)",
        '<input type="number" min="0" step="5" data-field="service_minutes" value="' +
        esc(profile.service_minutes || 0) + '"/>',
        "Để 0 thì dùng định mức chung của cụm") +
      fieldBlock("Nhận hàng từ",
        '<input type="time" data-field="receiving_from" value="' + esc(profile.receiving_from) + '"/>') +
      fieldBlock("Nhận hàng đến",
        '<input type="time" data-field="receiving_to" value="' + esc(profile.receiving_to) + '"/>') +
      fieldBlock("Hàng quá khổ",
        textInput("oversize_note", profile.oversize_note, "VD: thường có thanh thép dài 6m")) +
      '<div class="dp-field-block"><label class="dp-check">' +
      '<input type="checkbox" data-field="needs_technician"' +
      (profile.needs_technician ? " checked" : "") + "/> Cần kỹ thuật lắp đặt</label></div>" +
      fieldBlock("Ghi chú tự do",
        '<textarea rows="2" data-field="free_note" ' +
        'placeholder="Cổng nào, gọi ai, giờ nghỉ trưa…">' + esc(profile.free_note) + "</textarea>");

    return '<div class="dp-profile-form" data-profile="' + profile.profile_id + '">' + body +
      '<div class="dp-trip-actions">' +
      '<button class="dp-btn dp-btn-sm dp-profile-save" data-profile="' +
      profile.profile_id + '">Lưu</button>' +
      '<button class="dp-btn dp-btn-sm dp-btn-primary dp-profile-confirm" data-profile="' +
      profile.profile_id + '">Lưu và xác nhận đã đúng</button>' +
      '<button class="dp-btn dp-btn-sm dp-profile-close" data-profile="' +
      profile.profile_id + '">Đóng</button></div></div>';
  }

  function profileBadges(profile) {
    var out = [];
    if (profile.verification_state === "confirmed") out.push(badge("Đã xác nhận", "dp-badge-green"));
    else if (profile.verification_state === "expired") out.push(badge("Hết hạn soát lại", "dp-badge-amber"));
    else out.push(badge("Chưa điền", "dp-badge-amber"));
    if (profile.task_state === "open") {
      out.push(badge(profile.task_overdue ? "Quá hạn" : "Được giao điền",
        profile.task_overdue ? "dp-badge-red" : "dp-badge-blue"));
    }
    if (profile.task_state === "submitted") out.push(badge("Chờ điều phối duyệt", "dp-badge-blue"));
    out.push(badge(Math.round(profile.completeness) + "% đầy", ""));
    return out;
  }

  function profileMeta(profile) {
    return "<div><b>Cụm:</b> " + esc(profile.zone_name || "chưa rõ") +
      " · <b>Mã khách:</b> " + profile.partner_count + "</div>" +
      (profile.address ? "<div>" + esc(profile.address) + "</div>" : "") +
      (profile.missing_fields
        ? "<div><b>Còn thiếu:</b> " + esc(profile.missing_fields) + "</div>" : "") +
      (profile.task_deadline
        ? "<div><b>Hạn:</b> " + esc(profile.task_deadline) + "</div>" : "") +
      (profile.task_note
        ? "<div><b>Điều phối nhắn:</b> " + esc(profile.task_note) + "</div>" : "");
  }

  function renderPoints() {
    var pane = HD.$("dp-pane-points");
    if (!S.profiles.length) {
      pane.innerHTML = '<div class="dp-empty">Bạn chưa được phân công khách nào.<br/>' +
        "Điều phối suy sale phụ trách từ mã sale của đơn gần nhất tại mỗi điểm giao.</div>";
      return;
    }
    var todo = S.profiles.filter(function (profile) {
      return profile.verification_state !== "confirmed";
    });
    var head = '<div class="dp-plan-note"><b>' + S.profiles.length + " khách</b> bạn phụ trách · " +
      "<b>" + todo.length + "</b> khách chưa xác nhận thói quen giao hàng. " +
      "Dữ liệu này quyết định điều phối xếp chuyến đúng hay sai.</div>";

    var cards = S.profiles.map(function (profile) {
      var open = S.openProfileId === profile.profile_id;
      return '<article class="dp-trip' + (profile.task_state === "open" ? " dp-trip-mine" : "") +
        '"><div class="dp-trip-head"><div class="dp-trip-name">' + esc(profile.point_name) +
        "</div></div>" +
        '<div class="dp-badges">' + profileBadges(profile).join("") + "</div>" +
        '<div class="dp-trip-meta">' + profileMeta(profile) + "</div>" +
        (open
          ? profileForm(profile)
          : '<div class="dp-trip-actions"><button class="dp-btn dp-btn-sm dp-profile-open" ' +
            'data-profile="' + profile.profile_id + '">Điền thói quen</button></div>') +
        "</article>";
    }).join("");

    pane.innerHTML = head + '<div class="dp-trips">' + cards + "</div>";
    bindPointEvents(pane);
  }

  function bindPointEvents(pane) {
    HD.onClick(pane, ".dp-profile-open", function (btn) {
      S.openProfileId = parseInt(btn.dataset.profile, 10);
      renderPoints();
    });
    HD.onClick(pane, ".dp-profile-close", function () {
      S.openProfileId = null;
      renderPoints();
    });
    HD.onClick(pane, ".dp-profile-save", function (btn) {
      saveProfile(parseInt(btn.dataset.profile, 10), false);
    });
    HD.onClick(pane, ".dp-profile-confirm", function (btn) {
      saveProfile(parseInt(btn.dataset.profile, 10), true);
    });
  }

  /** Gom giá trị đang nhập trong form của một profile. Trả null nếu form không mở. */
  function collectProfileValues(profileId) {
    var form = document.querySelector('.dp-profile-form[data-profile="' + profileId + '"]');
    if (!form) return null;
    var values = {};
    Array.prototype.forEach.call(form.querySelectorAll("[data-field]"), function (el) {
      values[el.dataset.field] = el.type === "checkbox" ? el.checked : el.value;
    });
    return values;
  }

  function saveProfile(profileId, confirm) {
    var values = collectProfileValues(profileId);
    if (!values) return;
    HD.setLoading(true);
    HD.rpc("/api/dispatch/profile_save", {
      profile_id: profileId, values: values, confirm: !!confirm,
    }).then(function (res) {
      if (res.status !== "success") { HD.showAlert(res.message); return; }
      if (confirm) S.openProfileId = null;
      HD.showAlert(confirm ? "Đã lưu và xác nhận thói quen khách." : "Đã lưu.", true);
      return HD.loadPoints();
    }).catch(function (err) { HD.showAlert(err.message); })
      .then(function () { HD.setLoading(false); });
  }
})(window.HlvDispatch);
