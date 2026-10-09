/* Lõi cho ngăn Ticket: dựng phần tử DOM, gọi API /huong-dan-ticket, cấu hình trang.
   Trang /huong-dan không qua asset bundle của Odoo nên tự làm mấy việc nhỏ này bằng JS thường. */
(function (ns) {
  "use strict";

  var ROUTE = "/huong-dan-ticket";
  var data = document.body.dataset;

  /**
   * h("div", {class: "x", text: "chữ", onclick: fn, title: "…"}, [con…]) → phần tử.
   * Giá trị null / undefined / false bị bỏ qua (cả thuộc tính lẫn con); con là chuỗi thành text
   * node — không bao giờ gán innerHTML ở đây.
   */
  function h(tag, attrs, children) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      var value = attrs[key];
      if (value === null || value === undefined || value === false) {
        return;
      }
      if (key === "class") {
        el.className = value;
      } else if (key === "text") {
        el.textContent = value;
      } else if (key.slice(0, 2) === "on") {
        el.addEventListener(key.slice(2), value);
      } else {
        el.setAttribute(key, value === true ? "" : value);
      }
    });
    [].concat(children || []).forEach(function (child) {
      if (child !== null && child !== undefined && child !== false) {
        el.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
      }
    });
    return el;
  }

  /** Gọi route JSON-RPC của Odoo, trả Promise kết quả; lỗi máy chủ → Error có thông điệp. */
  function rpc(path, params) {
    return fetch(ROUTE + path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: params || {} }),
    }).then(function (resp) {
      return resp.json();
    }).then(function (reply) {
      if (reply.error) {
        throw new Error((reply.error.data && reply.error.data.message) || reply.error.message);
      }
      return reply.result;
    });
  }

  /**
   * POST multipart kèm file (tạo / trả lời ticket). fields: {tên: giá trị}, bỏ qua null;
   * files: mảng File; onProgress(tỉ lệ 0..1) khi đang tải lên. Dùng XHR thay fetch để có tiến độ
   * — video vài chục MB mất một lúc. Trả Promise JSON; lỗi → Error có thông điệp.
   */
  function send(path, fields, files, onProgress) {
    return new Promise(function (resolve, reject) {
      var form = new FormData();
      form.append("csrf_token", data.csrf);
      Object.keys(fields).forEach(function (key) {
        if (fields[key] !== null && fields[key] !== undefined) {
          form.append(key, fields[key]);
        }
      });
      files.forEach(function (file) { form.append("files", file, file.name); });
      var xhr = new XMLHttpRequest();
      xhr.open("POST", ROUTE + path);
      xhr.responseType = "json";
      if (onProgress) {
        xhr.upload.onprogress = function (event) {
          if (event.lengthComputable) {
            onProgress(event.loaded / event.total);
          }
        };
      }
      xhr.onload = function () {
        var reply = xhr.response;
        if (xhr.status === 200 && reply && !reply.error) {
          resolve(reply);
        } else {
          // 400 không kèm JSON thường là phiên đăng nhập hết hạn (csrf_token cũ).
          reject(new Error((reply && reply.error) || "Gửi không được (mã " + xhr.status + "). Tải lại trang rồi thử lại."));
        }
      };
      xhr.onerror = function () { reject(new Error("Mất kết nối, chưa gửi được.")); };
      xhr.send(form);
    });
  }

  ns.core = {
    h: h,
    rpc: rpc,
    send: send,
    limits: JSON.parse(data.limits || "{}"),
  };
})(window.HlvGuide = window.HlvGuide || {});
