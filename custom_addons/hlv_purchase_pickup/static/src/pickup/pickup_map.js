/* Bản đồ Google cho trang /pickup.

   Trang phải chạy được KHÔNG CÓ bản đồ: chưa khai key, hết quota, hay mạng chặn
   maps.googleapis.com đều không được làm hỏng việc bấm mốc thời gian. Vì vậy mọi thứ ở đây
   đều tự tắt trong im lặng khi không nạp được, và khối #pk-map chỉ hiện khi thật sự vẽ được. */
window.HlvPickup = window.HlvPickup || {};

(function (HP) {
  "use strict";

  var map = null;
  var markers = [];
  var loading = null;

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
      script.src = "https://maps.googleapis.com/maps/api/js?key=" + encodeURIComponent(key);
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

  function clearMarkers() {
    markers.forEach(function (marker) {
      marker.setMap(null);
    });
    markers = [];
  }

  /**
   * Vẽ lại bản đồ theo dữ liệu chuyến.
   * run: payload từ server. Điểm thiếu toạ độ bị bỏ qua — vẽ được điểm nào hay điểm đó,
   * còn hơn là ẩn cả bản đồ vì một điểm chưa duyệt toạ độ.
   */
  HP.renderMap = function (run) {
    var box = HP.$("pk-map");
    if (!box || !run) {
      return;
    }
    var points = (run.stops || []).filter(function (stop) {
      return stop.lat && stop.lng;
    });
    if (!points.length) {
      box.classList.add("pk-hidden");
      return;
    }

    loadLibrary().then(function (ready) {
      if (!ready) {
        box.classList.add("pk-hidden");
        return;
      }
      box.classList.remove("pk-hidden");
      var gmaps = window.google.maps;
      if (!map) {
        map = new gmaps.Map(box, { zoom: 11, mapTypeControl: false, streetViewControl: false });
      }
      clearMarkers();

      var bounds = new gmaps.LatLngBounds();
      if (run.origin && run.origin.lat) {
        var start = new gmaps.LatLng(run.origin.lat, run.origin.lng);
        markers.push(new gmaps.Marker({ position: start, map: map, label: "K", title: "Kho" }));
        bounds.extend(start);
      }
      points.forEach(function (stop, index) {
        var position = new gmaps.LatLng(stop.lat, stop.lng);
        markers.push(new gmaps.Marker({
          position: position,
          map: map,
          label: String(index + 1),
          title: stop.point_name,
          opacity: stop.state === "done" ? 0.5 : 1,
        }));
        bounds.extend(position);
      });
      map.fitBounds(bounds);
    });
  };
})(window.HlvPickup);
