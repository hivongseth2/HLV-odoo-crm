/** @odoo-module ignore */
/* Bản đồ Google cho bước "Đi nhận" — chiếm trọn màn hình, tấm trượt nằm đè lên.

   Trang phải chạy được KHÔNG CÓ bản đồ: chưa khai key, hết quota, hay mạng chặn
   maps.googleapis.com đều không được làm hỏng việc bấm mốc thời gian. Nhưng khi không vẽ
   được thì phải NÓI RÕ vì sao, chứ ẩn đi im lặng thì người dùng không biết là chưa làm hay
   là thiếu cấu hình. */
window.HlvPickup = window.HlvPickup || {};

(function (HP) {
  "use strict";

  var map = null;
  var markers = [];
  var routeLine = null;
  var meMarker = null;
  var loading = null;
  var fitted = false;

  var COLOR = {
    done: "#9aa0a6",
    next: "#1a73e8",
    pending: "#c5221f",
    origin: "#137333",
  };

  function apiKey() {
    var node = HP.$("pk-maps-config");
    return (node && node.dataset.mapsKey) || "";
  }

  /** Nạp thư viện Google Maps đúng một lần. Trả promise resolve true/false (được/không được). */
  function loadLibrary() {
    if (loading) {
      return loading;
    }
    var key = apiKey();
    if (!key) {
      loading = Promise.resolve(false);
      return loading;
    }
    loading = new Promise(function (resolve) {
      var script = document.createElement("script");
      /* geometry: cần để giải mã đường đi Google trả về dạng polyline nén. */
      script.src = "https://maps.googleapis.com/maps/api/js?libraries=geometry&key=" +
        encodeURIComponent(key);
      script.async = true;
      script.onload = function () {
        resolve(!!(window.google && window.google.maps));
      };
      script.onerror = function () {
        resolve(false);
      };
      document.head.appendChild(script);
    });
    return loading;
  }

  function note(message) {
    var box = HP.$("pk-map-note");
    box.classList.toggle("pk-hidden", !message);
    box.textContent = message || "";
  }

  function clearMarkers() {
    markers.forEach(function (marker) {
      marker.setMap(null);
    });
    markers = [];
  }

  /** Ghim hình giọt nước, tô màu theo trạng thái điểm. */
  function pin(gmaps, color) {
    return {
      path: "M 0,0 C -2,-19 -11,-22 -11,-30 A 11,11 0 1,1 11,-30 C 11,-22 2,-19 0,0 z",
      fillColor: color,
      fillOpacity: 1,
      strokeColor: "#ffffff",
      strokeWeight: 1.5,
      scale: 1,
      labelOrigin: new gmaps.Point(0, -30),
    };
  }

  function colorOf(stop, nextId) {
    if (stop.state === "done" || stop.state === "skipped" || stop.state === "failed") {
      return COLOR.done;
    }
    return stop.id === nextId ? COLOR.next : COLOR.pending;
  }

  function drawRoute(gmaps, encoded) {
    if (routeLine) {
      routeLine.setMap(null);
      routeLine = null;
    }
    if (!encoded || !gmaps.geometry) {
      return;
    }
    routeLine = new gmaps.Polyline({
      path: gmaps.geometry.encoding.decodePath(encoded),
      map: map,
      strokeColor: COLOR.next,
      strokeOpacity: 0.75,
      strokeWeight: 5,
    });
  }

  /**
   * Vẽ lại bản đồ theo dữ liệu chuyến.
   * Điểm thiếu toạ độ bị bỏ qua — vẽ được điểm nào hay điểm đó, còn hơn là bỏ cả bản đồ vì
   * một điểm chưa duyệt toạ độ; số điểm vắng mặt được báo ngay trên bản đồ.
   */
  HP.renderMap = function (run) {
    var box = HP.$("pk-map");
    if (!box || !run) {
      return;
    }
    var stops = run.stops || [];
    var points = stops.filter(function (stop) {
      return stop.lat && stop.lng;
    });

    /* Chuyến rỗng thì không nói gì: chưa có điểm nào là chuyện của người xếp chuyến. */
    if (!stops.length) {
      note("");
      return;
    }
    /* Thiếu key là gốc rễ: không có key thì vừa không vẽ được bản đồ, vừa không tra được
       toạ độ. Báo cái này trước, báo chuyện toạ độ sau. */
    if (!apiKey()) {
      note("Chưa khai API key Google Maps (trình duyệt). Quản trị vào Cài đặt → Đi nhận hàng.");
      return;
    }
    if (!points.length) {
      note(stops.length + " điểm chưa có toạ độ nên chưa vẽ được bản đồ. " +
        "Quản lý vào Đi nhận hàng → Điểm nhận hàng để tra và duyệt toạ độ.");
      return;
    }

    loadLibrary().then(function (ready) {
      if (!ready) {
        note("Không tải được Google Maps. Kiểm tra mạng, hoặc key bị khoá sai HTTP referrer.");
        return;
      }
      var missing = stops.length - points.length;
      note(missing ? missing + " điểm chưa có toạ độ nên không hiện trên bản đồ." : "");

      var gmaps = window.google.maps;
      if (!map) {
        map = new gmaps.Map(box, {
          zoom: 12,
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: false,
          /* Nút zoom của Google bị tấm trượt che mất, và trên điện thoại người ta chụm ngón
             tay chứ không bấm nút. */
          zoomControl: false,
          gestureHandling: "greedy",
        });
      }
      clearMarkers();

      var next = HP.nextStop(stops);
      var nextId = next ? next.id : 0;
      var bounds = new gmaps.LatLngBounds();

      if (run.origin && run.origin.lat) {
        var start = new gmaps.LatLng(run.origin.lat, run.origin.lng);
        markers.push(new gmaps.Marker({
          position: start, map: map, title: "Kho xuất phát",
          icon: pin(gmaps, COLOR.origin),
          label: { text: "K", color: "#fff", fontSize: "12px", fontWeight: "600" },
        }));
        bounds.extend(start);
      }

      stops.forEach(function (stop, index) {
        if (!stop.lat || !stop.lng) {
          return;
        }
        var position = new gmaps.LatLng(stop.lat, stop.lng);
        var marker = new gmaps.Marker({
          position: position,
          map: map,
          title: stop.point_name,
          icon: pin(gmaps, colorOf(stop, nextId)),
          label: {
            text: String(index + 1), color: "#fff", fontSize: "12px", fontWeight: "600",
          },
          zIndex: stop.id === nextId ? 10 : 1,
        });
        marker.addListener("click", function () {
          HP.sheet.focusStop(stop.id);
        });
        markers.push(marker);
        bounds.extend(position);
      });

      drawRoute(gmaps, run.route_polyline);

      /* Chỉ căn khung MỘT LẦN cho mỗi chuyến: sau mỗi lần bấm nút, màn hình được vẽ lại —
         tự kéo bản đồ về khung tổng thể mỗi lần như vậy sẽ huỷ chỗ người dùng vừa phóng to. */
      if (!fitted) {
        map.fitBounds(bounds, 60);
        fitted = true;
      }
    });
  };

  /** Quên khung đã căn — gọi khi đổi sang chuyến khác. */
  HP.resetMapView = function () {
    fitted = false;
  };

  /**
   * Đưa bản đồ về vị trí hiện tại và ghim lại.
   * Không lấy được vị trí thì báo lên khối ghi chú chứ không im lặng.
   */
  HP.centerOnMe = function () {
    if (!map) {
      return Promise.resolve(false);
    }
    return HP.currentPosition().then(function (gps) {
      if (!gps) {
        note("Không lấy được vị trí. Bật định vị cho trình duyệt rồi thử lại.");
        return false;
      }
      var gmaps = window.google.maps;
      var here = new gmaps.LatLng(gps.lat, gps.lng);
      if (!meMarker) {
        meMarker = new gmaps.Marker({
          map: map,
          title: "Tôi đang ở đây",
          icon: {
            path: gmaps.SymbolPath.CIRCLE,
            scale: 7,
            fillColor: COLOR.next,
            fillOpacity: 1,
            strokeColor: "#ffffff",
            strokeWeight: 3,
          },
          zIndex: 20,
        });
      }
      meMarker.setPosition(here);
      map.panTo(here);
      map.setZoom(15);
      return true;
    });
  };
})(window.HlvPickup);
