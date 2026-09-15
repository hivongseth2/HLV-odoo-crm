/** @odoo-module ignore */
/* Dựng màn hình trang /pickup từ dữ liệu chuyến do server trả về.

   Màn hình chia 4 BƯỚC, và bước hiện tại được SUY RA từ dữ liệu chuyến chứ không lưu riêng
   một biến: chỉ cần một chỗ sai đồng bộ là người đi nhận thấy nút không đúng với việc đang
   làm. Trình tự: chọn chuyến → xuất phát → đi từng điểm → về kho.

   File này CHỈ vẽ. Không gọi mạng, không đổi dữ liệu — mọi nút chỉ gắn data-action, việc xử
   lý nằm ở pickup_app.js. Vẽ lại toàn bộ sau mỗi thao tác thay vì sửa từng mẩu DOM: người
   dùng mất sóng giữa chừng, chỉ có dữ liệu server mới là sự thật. */
window.HlvPickup = window.HlvPickup || {};

(function (HP) {
  "use strict";

  var SCREENS = ["pick", "depart", "run", "done"];
  var STEP_LABEL = ["Chọn chuyến", "Xuất phát", "Đi nhận", "Về kho"];

  /**
   * Bước đang ở, suy ra từ chuyến.
   * Không có chuyến (hoặc người dùng bấm đổi chuyến) → "pick"; chưa bấm xuất phát →
   * "depart"; đang đi → "run"; chuyến đã đóng → "done".
   */
  HP.stepOf = function (run, forcePick) {
    if (forcePick || !run || run.state === "cancelled") {
      return "pick";
    }
    if (!run.depart_at) {
      return "depart";
    }
    return run.state === "done" ? "done" : "run";
  };

  function showScreen(step) {
    SCREENS.forEach(function (name) {
      HP.$("pk-screen-" + name).classList.toggle("pk-hidden", name !== step);
    });
    HP.$("pk-back").classList.toggle("pk-hidden", step === "pick");
    /* Bước "Đi nhận" chuyển cả trang sang chế độ bản đồ toàn màn: đầu trang nổi lên trên
       bản đồ, thanh bước ẩn đi. Các bước khác vẫn là trang cuộn bình thường. */
    HP.$("pk-app").classList.toggle("pk-run-mode", step === "run");
    HP.$("pk-steps").classList.toggle("pk-hidden", step === "run");
  }

  function renderSteps(step) {
    if (step === "run") {
      return;
    }
    var current = SCREENS.indexOf(step);
    HP.$("pk-steps").innerHTML = STEP_LABEL.map(function (label, index) {
      var cls = "pk-step";
      if (index === current) {
        cls += " pk-step-now";
      } else if (index < current) {
        cls += " pk-step-past";
      }
      return '<span class="' + cls + '">' + (index + 1) + ". " + HP.esc(label) + "</span>";
    }).join("");
    HP.$("pk-steps").classList.remove("pk-hidden");
  }

  function badge(map, state) {
    var entry = map[state] || [state, "pk-badge-grey"];
    return '<span class="pk-badge ' + entry[1] + '">' + HP.esc(entry[0]) + "</span>";
  }

  /* Thao tác đã bấm nhưng chưa gửi được. Phải hiện ra và phải GIẤU nút đi: không hiện gì
     thì người dùng tưởng bấm hụt và bấm lại, mà mỗi lần bấm là một mã lần bấm mới nên server
     sẽ tính thành hai thao tác thật — đúng thứ cơ chế chống bấm trùng không cứu được. */
  function pendingMark() {
    return '<div class="pk-pending">⏳ Đã bấm, đang chờ có sóng để gửi lên.</div>';
  }

  // ------------------------------------------------------------------
  // Bước 1 — chọn chuyến
  // ------------------------------------------------------------------
  /** Vẽ danh sách chuyến của một ngày. runs rỗng thì nói rõ là ngày đó không có chuyến. */
  HP.renderRunList = function (runs) {
    var box = HP.$("pk-run-list");
    if (!runs || !runs.length) {
      box.innerHTML = '<div class="pk-empty">Ngày này bạn không có chuyến nào. ' +
        "Chọn ngày khác, hoặc hỏi người điều phối.</div>";
      return;
    }
    box.innerHTML = runs.map(function (run) {
      var facts = [run.date, run.stop_count + " điểm", run.line_count + " đơn"];
      if (run.warehouse_name) {
        facts.push(run.warehouse_name);
      }
      /* Ca đứng riêng và to hơn phần còn lại: khi một ngày có chuyến sáng và chuyến chiều,
         đây là thứ duy nhất phân biệt được hai thẻ chỉ khác nhau con số cuối mã chuyến. */
      var session = run.session_label
        ? '<span class="pk-runcard-session">' + HP.esc(run.session_label) + "</span>"
        : "";
      return '<button class="pk-runcard" type="button" data-action="open-run" ' +
        'data-run-id="' + run.id + '">' +
        '<span class="pk-runcard-head">' + session +
        "<strong>" + HP.esc(run.name) + "</strong>" +
        badge(HP.LABEL.RUN_BADGE, run.state) + "</span>" +
        '<span class="pk-runcard-meta">' + HP.esc(facts.join(" · ")) + "</span>" +
        "</button>";
    }).join("");
  };

  // ------------------------------------------------------------------
  // Bước 2 — xuất phát
  // ------------------------------------------------------------------
  function renderDepart(run, queued) {
    var rows = (run.stops || []).map(function (stop, index) {
      return '<li><strong>' + (index + 1) + ". " + HP.esc(stop.point_name) + "</strong>" +
        '<span class="pk-preview-meta">' + HP.esc(stop.address || "") + "</span>" +
        '<span class="pk-preview-meta">' +
        HP.esc((stop.lines || []).map(function (line) {
          return line.po_name;
        }).join(", ")) + "</span></li>";
    }).join("");

    var html = '<div class="pk-card">' +
      "<h3>Chuyến sắp đi</h3>" +
      '<div class="pk-preview-facts">' +
      HP.esc(run.stop_count + " điểm · " + run.line_count + " đơn" +
        (run.warehouse_name ? " · xuất phát từ " + run.warehouse_name : "")) +
      "</div>" +
      (rows ? '<ol class="pk-preview">' + rows + "</ol>"
        : '<div class="pk-empty">Chuyến chưa có điểm nào.</div>') +
      "</div>";

    html += queued.runs[run.id] ? pendingMark()
      : '<button class="pk-btn pk-btn-primary pk-btn-block" data-action="depart" ' +
        'type="button">Xuất phát</button>';
    HP.$("pk-depart-summary").innerHTML = html;
  }

  // ------------------------------------------------------------------
  // Bước 3 — đi từng điểm
  // ------------------------------------------------------------------
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

  /**
   * Một thẻ điểm dừng — dùng cho CẢ hai chỗ: đầu tấm trượt (điểm đang làm) và danh sách các
   * điểm còn lại. Một hàm cho cả hai để không có hai bản đánh dấu lệch nhau, vốn là thứ đã
   * làm điểm đang làm trông như nằm ở cấp khác so với các điểm sau.
   *
   * variant "head": thẻ phẳng, không viền, không bóng — nó đã nằm trong khung tấm trượt.
   */
  function renderStop(stop, index, queued, variant) {
    var classes = ["pk-stop", "pk-stop-" + stop.state];
    if (variant === "head") {
      classes.push("pk-stop-flat");
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

    /* Mỗi thẻ có đủ nút của chính nó. Không còn phải bỏ nút để tránh trùng, vì điểm đang
       làm chỉ xuất hiện MỘT chỗ — ở đầu tấm trượt. */
    var buttons = [];
    if (stop.state === "pending") {
      buttons.push('<button class="pk-btn pk-btn-primary pk-btn-wide" data-action="arrive" ' +
        'data-stop-id="' + stop.id + '" type="button">Đã tới</button>');
      buttons.push('<button class="pk-btn pk-btn-ghost" data-action="skip" data-stop-id="' +
        stop.id + '" type="button">Bỏ qua</button>');
    } else if (stop.state === "arrived") {
      buttons.push('<button class="pk-btn pk-btn-green pk-btn-wide" data-action="stop-done" ' +
        'data-stop-id="' + stop.id + '" type="button">Đã nhận xong</button>');
      buttons.push('<button class="pk-btn pk-btn-ghost" data-action="skip" data-stop-id="' +
        stop.id + '" type="button">Bỏ qua</button>');
    }
    if (buttons.length) {
      html += '<div class="pk-stop-actions">' + buttons.join("") + "</div>";
    }
    return html + "</section>";
  }

  /**
   * Lối kết thúc SỚM, nằm cuối danh sách điểm.
   * Khi còn điểm chưa xong thì đây chỉ là một dòng chữ nhỏ có hỏi lại — không phải nút to
   * đặt cạnh nút chính để bấm nhầm. Khi đã đi hết điểm, nút kết thúc chuyển lên đầu tấm
   * trượt (xem renderSheetHead) nên chỗ này để trống, tránh hai nút làm cùng một việc.
   */
  function renderFinish(run, queued) {
    var box = HP.$("pk-finish");
    var left = run.stop_count - run.done_stop_count;
    if (queued.runs[run.id] || left <= 0) {
      box.innerHTML = "";
      return;
    }
    box.innerHTML = '<div class="pk-finish-note">Còn ' + left + " điểm chưa xong.</div>" +
      '<button class="pk-linkbtn" data-action="finish" type="button">Kết thúc sớm</button>';
  }

  /** Nút kết thúc chuyến, dùng ở đầu tấm trượt khi mọi điểm đã xong. */
  function finishButton() {
    var label = HP.S.requireReturn ? "Đã về kho — kết thúc chuyến" : "Kết thúc chuyến";
    return '<button class="pk-btn pk-btn-green pk-btn-block" data-action="finish" ' +
      'type="button">' + label + "</button>";
  }

  /**
   * Đầu tấm trượt — phần duy nhất nhìn thấy khi tấm trượt đang thu gọn.
   *
   * Đây là THẺ ĐẦY ĐỦ của điểm đang làm, dựng bằng đúng ``renderStop`` như các điểm khác.
   * Trước đây phần đầu chỉ có tên và một nút, còn thẻ của điểm đó vẫn nằm trong danh sách —
   * thành ra điểm đang làm bị xé làm hai chỗ và trông như ở cấp khác với các điểm sau.
   * Giờ nó chỉ xuất hiện MỘT chỗ, và danh sách bên dưới chỉ còn các điểm còn lại.
   */
  function renderSheetHead(run, queued, current) {
    var head = HP.$("pk-sheet-head");
    var html = '<div class="pk-sheet-progress">' + HP.esc([
      run.done_stop_count + "/" + run.stop_count + " điểm",
      "đi " + (HP.duration(run.total_travel_minutes) || "0'"),
      "nhận " + (HP.duration(run.total_service_minutes) || "0'"),
      run.received_line_count + "/" + run.line_count + " đơn",
    ].join(" · ")) + "</div>";

    if (!current) {
      head.innerHTML = html +
        (queued.runs[run.id] ? pendingMark()
          : '<div class="pk-finish-note">Đã đi hết các điểm.</div>' + finishButton());
      return;
    }

    var index = 0;
    run.stops.forEach(function (stop, position) {
      if (stop.id === current.id) {
        index = position + 1;
      }
    });
    head.innerHTML = html + renderStop(current, index - 1, queued, "head");
  }

  // ------------------------------------------------------------------
  // Bước 4 — đã xong
  // ------------------------------------------------------------------
  function renderDone(run) {
    HP.$("pk-done-summary").innerHTML = '<div class="pk-card pk-card-done">' +
      "<h3>Chuyến đã kết thúc</h3>" +
      '<div class="pk-done-grid">' +
      statTile("Di chuyển", HP.duration(run.total_travel_minutes) || "0'") +
      statTile("Nhận hàng", HP.duration(run.total_service_minutes) || "0'") +
      statTile("Cả chuyến", HP.duration(run.total_minutes) || "0'") +
      statTile("Đơn nhận được", run.received_line_count + "/" + run.line_count) +
      "</div></div>" +
      '<button class="pk-btn pk-btn-ghost pk-btn-block" data-action="pick" type="button">' +
      "Về danh sách chuyến</button>";
  }

  function statTile(label, value) {
    return '<div class="pk-tile"><span class="pk-tile-value">' + HP.esc(value) + "</span>" +
      '<span class="pk-tile-label">' + HP.esc(label) + "</span></div>";
  }

  // ------------------------------------------------------------------
  // Đầu trang và chân trang
  // ------------------------------------------------------------------
  function renderHeader(run, step) {
    var title = HP.$("pk-run-name");
    var meta = HP.$("pk-run-meta");
    if (step === "pick" || !run) {
      title.textContent = "Chọn chuyến đi nhận";
      meta.textContent = "";
      return;
    }
    title.textContent = run.name;
    var parts = [run.date];
    if (run.session_label) {
      parts.push("ca " + run.session_label.toLowerCase());
    }
    parts.push(HP.LABEL.RUN[run.state] || run.state);
    if (run.depart_at) {
      parts.push(run.done_stop_count + "/" + run.stop_count + " điểm");
    }
    if (run.vehicle_note) {
      parts.push(run.vehicle_note);
    }
    meta.textContent = parts.join(" · ");
  }

  /** Vẽ lại toàn bộ trang. run = null nghĩa là chưa chọn chuyến nào. */
  HP.render = function (run) {
    /* Đổi sang chuyến khác thì cho bản đồ căn khung lại từ đầu. */
    if (run && HP.S.run && HP.S.run.id !== run.id) {
      HP.resetMapView();
    }
    HP.S.run = run;
    var step = HP.stepOf(run, HP.S.forcePick);
    var queued = HP.queuedKeys();

    renderSteps(step);
    renderHeader(run, step);
    showScreen(step);

    if (step === "depart") {
      renderDepart(run, queued);
      return;
    }
    if (step === "done") {
      renderDone(run);
      return;
    }
    if (step !== "run") {
      return;
    }

    /* Điểm đang làm nằm ở đầu tấm trượt, nên danh sách bên dưới BỎ nó ra. Có nó ở cả hai
       chỗ là nguồn của cảm giác "điểm 1 không cùng cấp với điểm 2". */
    var current = HP.nextStop(run.stops);
    var rest = run.stops.filter(function (stop) {
      return !current || stop.id !== current.id;
    });

    var container = HP.$("pk-stops");
    if (!run.stops.length) {
      container.innerHTML = '<div class="pk-empty">Chuyến chưa có điểm nào.</div>';
    } else if (!rest.length) {
      container.innerHTML = '<div class="pk-empty">Không còn điểm nào khác.</div>';
    } else {
      container.innerHTML = '<div class="pk-list-title">Các điểm khác (' + rest.length +
        ")</div>" + rest.map(function (stop) {
          /* Giữ SỐ THỨ TỰ THẬT trong chuyến, không đánh số lại theo danh sách đã lọc — số
             trên thẻ phải khớp với số trên ghim bản đồ. */
          var position = 0;
          run.stops.forEach(function (item, at) {
            if (item.id === stop.id) {
              position = at;
            }
          });
          return renderStop(stop, position, queued, "list");
        }).join("");
    }

    renderSheetHead(run, queued, current);
    renderFinish(run, queued);
    HP.renderMap(run);
    /* Vẽ lại xong thì đưa thân về đầu: đang cuộn giữa danh sách mà nội dung đổi thì thẻ
       trên cùng bị cắt mất phần đầu, trông như thẻ lỗi. */
    HP.$("pk-sheet-body").scrollTop = 0;
    /* Nấc thu gọn đo theo chiều cao phần đầu, mà phần đầu vừa đổi nội dung. */
    HP.sheet.refresh();
  };
})(window.HlvPickup);
