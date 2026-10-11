/* State dùng chung + những thứ có side effect: DOM, gọi API, tải file.
   Tách khỏi hd_utils.js để phần util giữ được tính thuần. */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  HD.S = {
    config: {},
    // Danh sách
    search: "",
    type: "",
    state: "all",
    page: 1,
    rows: [],
    selected: {},       // {id: true} hợp đồng đang tick để xuất hàng loạt
    exportIds: [],      // id hợp đồng của hộp Xuất / In đang mở
    // Ngăn soạn
    contract: null,     // chi tiết hợp đồng đang mở (null = hợp đồng mới chưa lưu)
    lines: [],          // [{product_name, uom, quantity, price_unit}] đang sửa trên ngăn
    dirty: false,
    // Mẫu
    templates: [],
    template: null,     // chi tiết mẫu đang mở trong trình soạn
  };

  HD.$ = function (id) { return document.getElementById(id); };

  HD.show = function (id, on) {
    HD.$(id).classList.toggle("hd-hidden", !on);
  };

  /**
   * Gọi endpoint JSON-RPC của Odoo. Trả Promise của `result`; lỗi phía server (UserError,
   * AccessError, ValidationError) ném thành Error có message đọc được.
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
      return payload.result;
    });
  };

  HD.api = function (name, params) {
    return HD.rpc("/api/hop-dong/" + name, params);
  };

  var toastTimer = null;
  /** Thông báo ngắn góc dưới; kind = "error" thì nền đỏ và để lâu hơn. */
  HD.toast = function (message, kind) {
    var box = HD.$("hd-toast");
    box.textContent = message;
    box.classList.toggle("is-error", kind === "error");
    box.classList.remove("hd-hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { box.classList.add("hd-hidden"); }, kind === "error" ? 6000 : 2500);
  };

  /** Bắt lỗi của Promise và hiện toast đỏ — dùng cuối mọi chuỗi gọi API. */
  HD.fail = function (err) {
    HD.toast(err && err.message ? err.message : String(err), "error");
  };

  HD.debounce = function (fn, ms) {
    var timer = null;
    return function () {
      var args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(null, args); }, ms);
    };
  };

  /** Uỷ quyền sự kiện: handler(el, event) chạy khi `event` xảy ra trên phần tử khớp selector. */
  HD.on = function (root, eventName, selector, handler) {
    root.addEventListener(eventName, function (event) {
      var el = event.target.closest(selector);
      if (el && root.contains(el)) {
        handler(el, event);
      }
    });
  };

  /** Tên file trong Content-Disposition (ưu tiên filename*=UTF-8''… vì tên có dấu tiếng Việt). */
  function filenameOf(header) {
    var star = /filename\*=UTF-8''([^;]+)/i.exec(header || "");
    if (star) {
      return decodeURIComponent(star[1]);
    }
    var plain = /filename="?([^";]+)"?/i.exec(header || "");
    return plain ? plain[1] : "hop-dong";
  }

  /**
   * Tải file từ route GET bằng fetch thay vì đổi location: server báo lỗi (mẫu thiếu file,
   * không có quyền...) thì hiện toast, không đẩy người dùng sang trang lỗi của Odoo.
   */
  HD.download = function (url) {
    HD.toast("Đang tạo file…");
    return fetch(url, { credentials: "same-origin" }).then(function (response) {
      if (!response.ok) {
        return response.text().then(function (html) {
          var doc = new DOMParser().parseFromString(html, "text/html");
          var message = (doc.querySelector("pre, .alert, h1, title") || {}).textContent || "";
          throw new Error(message.trim() || "Không tải được file (mã " + response.status + ")");
        });
      }
      var name = filenameOf(response.headers.get("Content-Disposition"));
      return response.blob().then(function (blob) {
        var link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = name;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () { URL.revokeObjectURL(link.href); }, 10000);
        HD.toast("Đã tải " + name);
      });
    }).catch(HD.fail);
  };

  HD.exportUrl = function (ids, fmt) {
    return "/hop-dong/xuat?ids=" + ids.join(",") + "&fmt=" + fmt;
  };

  /** Mở/đóng hộp thoại theo id; Esc đóng hộp trên cùng (đăng ký ở hd_app.js). */
  HD.openModal = function (id) { HD.show(id, true); };
  HD.closeModal = function (id) { HD.show(id, false); };

  /** Nối ô tìm + danh sách thả xuống: gõ -> fetchItems(term) -> vẽ renderItem -> onPick(item). */
  HD.bindPicker = function (input, list, fetchItems, renderItem, onPick) {
    var items = [];
    var run = HD.debounce(function () {
      var term = input.value.trim();
      fetchItems(term).then(function (result) {
        items = result;
        list.innerHTML = items.length
          ? items.map(function (item, index) {
            return '<button type="button" class="hd-dropdown-item" data-index="' + index + '">' +
              renderItem(item) + "</button>";
          }).join("")
          : '<div class="hd-dropdown-empty">Không tìm thấy</div>';
        list.classList.remove("hd-hidden");
      }).catch(HD.fail);
    }, 250);
    input.addEventListener("input", run);
    input.addEventListener("focus", run);
    input.addEventListener("blur", function () {
      setTimeout(function () { list.classList.add("hd-hidden"); }, 150);
    });
    HD.on(list, "mousedown", ".hd-dropdown-item", function (el, event) {
      event.preventDefault();
      onPick(items[+el.dataset.index]);
      list.classList.add("hd-hidden");
    });
  };

  /** Đọc file người dùng chọn thành base64 (không có tiền tố data:). */
  HD.readFileBase64 = function (file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(String(reader.result).split(",")[1] || ""); };
      reader.onerror = function () { reject(new Error("Không đọc được file")); };
      reader.readAsDataURL(file);
    });
  };

  HD.typeOptions = function (selected, withAll) {
    var options = withAll ? '<option value="">Tất cả loại</option>' : "";
    return options + (HD.S.config.types || []).map(function (t) {
      return '<option value="' + t[0] + '"' + (t[0] === selected ? " selected" : "") + ">" + HD.esc(t[1]) + "</option>";
    }).join("");
  };
})(window.HlvContract);
