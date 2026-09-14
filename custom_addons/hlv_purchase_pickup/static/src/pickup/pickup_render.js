/** @odoo-module ignore */
/* Dựng màn hình trang /pickup từ dữ liệu chuyến do server trả về.

   File này CHỈ vẽ. Không gọi mạng, không đổi state — mọi nút chỉ gắn data-action, việc xử lý
   nằm ở pickup_app.js. Vẽ lại toàn bộ sau mỗi thao tác thay vì sửa từng mẩu DOM: người dùng
   mất sóng giữa chừng, chỉ có dữ liệu server mới là sự thật. */
window.HlvPickup = window.HlvPickup || {};

(function (HP) {
  "use strict";

  function badge(map, state) {
    var entry = map[state] || [state, "pk-badge-grey"];
    return '<span class="pk-badge ' + entry[1] + '">' + HP.esc(entry[0]) + "</span>";
  }

  function renderHeader(run) {
    HP.$("pk-run-name").textContent = run ? run.name : "Không có chuyến";
    var meta = HP.$("pk-run-meta");
    if (!run) {
      meta.textContent = "";
      return;
    }
    var parts = [run.date, HP.LABEL.RUN[run.state] || run.state,
      run.done_stop_count + "/" + run.stop_count + " điểm"];
    if (run.vehicle_note) {
      parts.push(run.vehicle_note);
    }
    meta.textContent = parts.join(" · ");
  }

  function renderActionBar(run, queued) {
    var bar = HP.$("pk-actionbar");
    if (!run) {
      bar.innerHTML = "";
      return;
    }
    if (queued.runs[run.id]) {
      bar.innerHTML = pendingMark();
      return;
    }
    var html = "";
    if (!run.depart_at && run.state !== "cancelled") {
      html += '<button class="pk-btn pk-btn-primary pk-btn-wide" data-action="depart" type="button">' +
        "Xuất phát</button>";
    }
    if (run.depart_at) {
      html += '<span class="pk-since">Xuất phát ' + HP.esc(HP.timeOf(run.depart_at)) + "</span>";
    }
    if (run.state === "departed" && HP.S.requireReturn) {
      html += '<button class="pk-btn pk-btn-ghost" data-action="finish" type="button">' +
        "Đã về kho</button>";
    }
    bar.innerHTML = html;
  }

  /* Thao tác đã bấm nhưng chưa gửi được. Phải hiện ra và phải GIẤU nút đi: không hiện gì
     thì người dùng tưởng bấm hụt và bấm lại, mà mỗi lần bấm là một mã lần bấm mới nên server
     sẽ tính thành hai thao tác thật — đúng thứ cơ chế chống bấm trùng không cứu được. */
  function pendingMark() {
    return '<div class="pk-pending">⏳ Đã bấm, đang chờ có sóng để gửi lên.</div>';
  }

  function renderLine(line, stopState, queued) {
    var html = '<div class="pk-line" data-line-id="' + line.id + '">';
    html += '<div class="pk-line-head"><span class="pk-po">' + HP.esc(line.po_name) + "</span>" +
      badge(HP.LABEL.LINE, line.state) + "</div>";
    if (line.note) {
      html += '<div class="pk-line-note">' + HP.esc(line.note) + "</div>";
    }
    if (queued.lines[line.id]) {
      return html + pendingMark() + "</div>";
    }
    /* Nút chỉ hiện khi đang đứng tại điểm: bấm "đã nhận" từ trên xe, cách đó 10km, là cách
       nhanh nhất để số liệu đo được thành vô nghĩa. */
    if (stopState === "arrived" && line.state === "pending") {
      html += '<div class="pk-line-actions">' +
        '<button class="pk-btn pk-btn-green" data-action="line-received" data-line-id="' +
        line.id + '" type="button">Đã nhận</button>' +
        '<button class="pk-btn pk-btn-ghost" data-action="line-not-ready" data-line-id="' +
        line.id + '" type="button">Chưa có hàng</button>' +
        "</div>";
    }
    return html + "</div>";
  }

  function renderStop(stop, index, isNext, queued) {
    var classes = ["pk-stop", "pk-stop-" + stop.state];
    if (isNext) {
      classes.push("pk-stop-next");
    }
    var html = '<section class="' + classes.join(" ") + '" data-stop-id="' + stop.id + '">';

    html += '<div class="pk-stop-head">' +
      '<span class="pk-stop-no">' + (index + 1) + "</span>" +
      '<span class="pk-stop-name">' + HP.esc(stop.point_name) + "</span>" +
      badge(HP.LABEL.STOP, stop.state) + "</div>";

    var facts = [];
    if (stop.arrived_at) {
      facts.push("tới " + HP.timeOf(stop.arrived_at));
    }
    if (stop.done_at) {
      facts.push("rời " + HP.timeOf(stop.done_at));
    }
    if (stop.travel_minutes) {
      facts.push("đi " + HP.duration(stop.travel_minutes));
    }
    if (stop.service_minutes) {
      facts.push("nhận " + HP.duration(stop.service_minutes));
    }
    if (!stop.arrived_at && stop.planned_arrival) {
      facts.push("dự kiến tới " + HP.timeOf(stop.planned_arrival));
    }
    if (!stop.arrived_at && stop.expected_service_minutes && stop.sample_count >= 3) {
      facts.push("thường mất " + HP.duration(stop.expected_service_minutes));
    }
    if (facts.length) {
      html += '<div class="pk-stop-facts">' + HP.esc(facts.join(" · ")) + "</div>";
    }

    if (stop.address) {
      html += '<div class="pk-stop-address">' + HP.esc(stop.address) + "</div>";
    }
    if (stop.point_note) {
      html += '<div class="pk-stop-note">⚠ ' + HP.esc(stop.point_note) + "</div>";
    }
    if (stop.skip_reason) {
      html += '<div class="pk-stop-note">' + HP.esc(stop.skip_reason) + "</div>";
    }

    var contacts = [];
    if (stop.contact_phone) {
      contacts.push('<a class="pk-link" href="tel:' + HP.esc(stop.contact_phone) + '">' +
        HP.esc(stop.contact_name || "Gọi") + " · " + HP.esc(stop.contact_phone) + "</a>");
    }
    contacts.push('<a class="pk-link" target="_blank" rel="noopener" href="' +
      HP.esc(HP.directionsUrl(stop)) + '">Chỉ đường</a>');
    html += '<div class="pk-stop-links">' + contacts.join("") + "</div>";

    html += '<div class="pk-lines">' + (stop.lines || []).map(function (line) {
      return renderLine(line, stop.state, queued);
    }).join("") + "</div>";

    if (queued.stops[stop.id]) {
      return html + pendingMark() + "</section>";
    }

    html += '<div class="pk-stop-actions">';
    if (stop.state === "pending") {
      html += '<button class="pk-btn pk-btn-primary pk-btn-wide" data-action="arrive" ' +
        'data-stop-id="' + stop.id + '" type="button">Đã tới</button>';
      html += '<button class="pk-btn pk-btn-ghost" data-action="skip" data-stop-id="' +
        stop.id + '" type="button">Bỏ qua</button>';
    } else if (stop.state === "arrived") {
      html += '<button class="pk-btn pk-btn-green pk-btn-wide" data-action="stop-done" ' +
        'data-stop-id="' + stop.id + '" type="button">Đã nhận xong — rời điểm</button>';
    }
    html += "</div></section>";
    return html;
  }

  function renderFooter(run) {
    var footer = HP.$("pk-footer");
    if (!run || !run.depart_at) {
      footer.textContent = "";
      return;
    }
    var parts = [
      "Di chuyển " + (HP.duration(run.total_travel_minutes) || "0'"),
      "Nhận hàng " + (HP.duration(run.total_service_minutes) || "0'"),
      "Cả chuyến " + (HP.duration(run.total_minutes) || "0'"),
      run.received_line_count + "/" + run.line_count + " đơn",
    ];
    footer.textContent = parts.join(" · ");
  }

  /** Vẽ lại toàn bộ trang theo payload chuyến. run = null nghĩa là hôm nay không có chuyến. */
  HP.render = function (run) {
    HP.S.run = run;
    var queued = HP.queuedKeys();
    renderHeader(run);
    renderActionBar(run, queued);
    renderFooter(run);

    var container = HP.$("pk-stops");
    if (!run) {
      container.innerHTML = '<div class="pk-empty">Hôm nay bạn chưa được giao chuyến nào. ' +
        "Nếu chắc là có, bấm Tải lại hoặc hỏi người điều phối.</div>";
      HP.$("pk-map").classList.add("pk-hidden");
      return;
    }
    if (!run.stops.length) {
      container.innerHTML = '<div class="pk-empty">Chuyến chưa có điểm nào.</div>';
      return;
    }

    var next = HP.nextStop(run.stops);
    container.innerHTML = run.stops.map(function (stop, index) {
      return renderStop(stop, index, next && stop.id === next.id, queued);
    }).join("");
    HP.renderMap(run);
  };
})(window.HlvPickup);
