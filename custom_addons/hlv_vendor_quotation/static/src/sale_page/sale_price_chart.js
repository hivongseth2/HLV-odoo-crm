/* Biểu đồ diễn biến giá mua của trang tra giá (/hoi-gia-ncc/tra-gia): một đường màu nhấn qua
   từng lần mua đã nhập kho, trục ngang là ngày đơn hàng. Chấm thấp nhất tô xanh; chỉ ghi nhãn
   giá ở chấm gần nhất và chấm thấp nhất (ghi hết thì rối). Rê chuột / chạm: hiện ngày, giá, NCC
   của lần mua gần con trỏ nhất. SVG thuần — trang không nạp thư viện biểu đồ. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var HEIGHT = 170;
  var PAD = { top: 22, right: 18, bottom: 26, left: 70 };
  var esc = HQ.esc;

  /** "yyyy-mm-dd" → số ms (UTC) để đặt lên trục thời gian. */
  function dayValue(day) {
    var p = day.split("-");
    return Date.UTC(+p[0], +p[1] - 1, +p[2]);
  }

  function plain(value) {
    return new Intl.NumberFormat("vi-VN").format(Math.round(value));
  }

  /** Thang tuyến tính [d0, d1] → [r0, r1]; miền rỗng (d0 = d1) → giữa khoảng. */
  function scale(d0, d1, r0, r1) {
    return function (v) {
      return d1 === d0 ? (r0 + r1) / 2 : r0 + (v - d0) / (d1 - d0) * (r1 - r0);
    };
  }

  function label(x, y, text, anchor, cls) {
    return '<text x="' + x + '" y="' + y + '" text-anchor="' + anchor + '" class="' + cls + '">' + esc(text) + "</text>";
  }

  /** Số lần mua vẽ được (có ngày, có giá) — dưới 2 thì đừng hiện khung biểu đồ: một chấm không là diễn biến. */
  HQ.chartablePrices = function (rows) {
    return rows.filter(function (r) { return r.day && r.price > 0; });
  };

  /**
   * Vẽ vào box (phần tử rỗng, rộng theo khung). rows: lần mua mới nhất trước, mỗi dòng có day,
   * date, price, vendor, order, qty, uom. Dưới 2 lần mua vẽ được thì để trống.
   */
  HQ.drawPriceChart = function (box, rows) {
    var points = HQ.chartablePrices(rows).reverse();
    if (points.length < 2) {
      box.innerHTML = "";
      return;
    }
    var width = Math.max(box.clientWidth, 280);
    var prices = points.map(function (p) { return p.price; });
    var lo = Math.min.apply(null, prices);
    var hi = Math.max.apply(null, prices);
    var room = (hi - lo) * 0.15 || hi * 0.1;
    var x = scale(dayValue(points[0].day), dayValue(points[points.length - 1].day), PAD.left, width - PAD.right);
    var y = scale(lo - room, hi + room, HEIGHT - PAD.bottom, PAD.top);
    var xy = points.map(function (p) { return [x(dayValue(p.day)), y(p.price)]; });
    var latest = points.length - 1;
    var lowest = prices.lastIndexOf(lo);

    var grid = [lo, (lo + hi) / 2, hi].filter(function (v, i, all) { return all.indexOf(v) === i; }).map(function (v) {
      var gy = y(v).toFixed(1);
      return '<line x1="' + PAD.left + '" x2="' + (width - PAD.right) + '" y1="' + gy + '" y2="' + gy + '" class="pl-chart-grid"/>' +
        label(PAD.left - 8, +gy + 4, plain(v), "end", "pl-chart-axis");
    }).join("");
    var axis = label(PAD.left, HEIGHT - 6, points[0].date, "start", "pl-chart-axis") +
      label(width - PAD.right, HEIGHT - 6, points[latest].date, "end", "pl-chart-axis");
    var path = '<path class="pl-chart-line" d="M' + xy.map(function (c) { return c[0].toFixed(1) + "," + c[1].toFixed(1); }).join("L") + '"/>';
    var dots = xy.map(function (c, i) {
      return '<circle cx="' + c[0].toFixed(1) + '" cy="' + c[1].toFixed(1) + '" r="4" class="pl-chart-dot' +
        (points[i].price === lo ? " is-low" : "") + '"/>';
    }).join("");
    var notes = label(xy[latest][0], xy[latest][1] - 9, plain(points[latest].price), "end", "pl-chart-value");
    if (lowest !== latest) {
      notes += label(xy[lowest][0], xy[lowest][1] + 17, "thấp nhất " + plain(lo), lowest === 0 ? "start" : "middle", "pl-chart-value");
    }

    box.innerHTML = '<svg width="' + width + '" height="' + HEIGHT + '" role="img" aria-label="Diễn biến giá mua sau VAT, ' +
      points.length + ' lần mua">' + grid + axis + path + dots + notes +
      '<line class="pl-chart-cross hq-hidden" y1="' + PAD.top + '" y2="' + (HEIGHT - PAD.bottom) + '"/>' +
      '<circle class="pl-chart-focus hq-hidden" r="6"/></svg><div class="pl-chart-tip hq-hidden"></div>';

    var svg = box.querySelector("svg");
    var cross = box.querySelector(".pl-chart-cross");
    var focus = box.querySelector(".pl-chart-focus");
    var tip = box.querySelector(".pl-chart-tip");
    svg.addEventListener("pointermove", function (event) {
      var mx = event.clientX - svg.getBoundingClientRect().left;
      var best = 0;
      xy.forEach(function (c, i) {
        if (Math.abs(c[0] - mx) < Math.abs(xy[best][0] - mx)) {
          best = i;
        }
      });
      var p = points[best];
      var c = xy[best];
      cross.setAttribute("x1", c[0]);
      cross.setAttribute("x2", c[0]);
      focus.setAttribute("cx", c[0]);
      focus.setAttribute("cy", c[1]);
      tip.innerHTML = '<div class="hq-muted hq-small">' + esc(p.date) + " · " + esc(p.order) + "</div><b>" + HQ.money(p.price) +
        "</b>" + (p.uom ? "/" + esc(p.uom) : "") + "<div>" + esc(p.vendor) + '</div><div class="hq-muted hq-small">' +
        HQ.qty(p.qty) + " " + esc(p.uom) + "</div>";
      // Tooltip lật sang trái khi chấm ở nửa phải (khỏi tràn mép khung), xuống dưới khi chấm ở
      // nửa trên (khỏi che chính chấm đang xem).
      tip.style.left = c[0] > width / 2 ? "" : c[0] + 12 + "px";
      tip.style.right = c[0] > width / 2 ? width - c[0] + 12 + "px" : "";
      tip.style.top = c[1] < HEIGHT / 2 ? c[1] + 12 + "px" : "";
      [cross, focus, tip].forEach(function (el) { el.classList.remove("hq-hidden"); });
    });
    svg.addEventListener("pointerleave", function () {
      [cross, focus, tip].forEach(function (el) { el.classList.add("hq-hidden"); });
    });
  };
})(window.HlvQuote);
