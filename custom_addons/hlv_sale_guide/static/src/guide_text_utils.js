/* Hàm thuần dùng chung cho trang /huong-dan: không đụng DOM, không gọi máy chủ.
   Gắn vào window.HlvGuide.text để các file khác dùng (trang không qua asset bundle của Odoo). */
(function (ns) {
  "use strict";

  /** Chữ thường, bỏ dấu tiếng Việt — để gõ "hoi gia" vẫn ra "Hỏi giá". Nhận str, trả str. */
  function plain(text) {
    return text.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase();
  }

  /** Một ký tự → chữ thường, giữ nguyên nếu chữ thường dài hơn một ký tự (VD "İ") để không lệch vị trí. */
  function lowerChar(ch) {
    var low = ch.toLowerCase();
    return low.length === 1 ? low : ch;
  }

  /**
   * Tìm đoạn trích trong nội dung trang, bỏ qua mọi khoảng trắng và hoa/thường.
   *
   * Bỏ hẳn khoảng trắng (không chỉ gộp) vì đoạn bôi đen vắt qua hai đoạn văn cho ra "a\n\nb"
   * trong khi các text node nối lại là "ab" — so kiểu nào cũng phải ra cùng một chuỗi.
   * texts: mảng chuỗi (nội dung các text node theo thứ tự). quote: chuỗi cần tìm.
   * Trả {startNode, startOffset, endNode, endOffset} (chỉ số trong texts, offset trong chuỗi,
   * endOffset là vị trí sau ký tự cuối) cho lần xuất hiện đầu tiên; không thấy / quote rỗng → null.
   */
  function locateQuote(texts, quote) {
    var needle = Array.from(quote || "").filter(function (ch) { return !/\s/.test(ch); }).map(lowerChar).join("");
    if (!needle) {
      return null;
    }
    var hay = [];
    var where = [];
    texts.forEach(function (text, index) {
      for (var offset = 0; offset < text.length; offset++) {
        if (!/\s/.test(text[offset])) {
          hay.push(lowerChar(text[offset]));
          where.push([index, offset]);
        }
      }
    });
    var at = hay.join("").indexOf(needle);
    if (at < 0) {
      return null;
    }
    var first = where[at];
    var last = where[at + needle.length - 1];
    return { startNode: first[0], startOffset: first[1], endNode: last[0], endOffset: last[1] + 1 };
  }

  /** Số byte → "820 B" / "12 KB" / "3.4 MB". Âm / không phải số → "0 B". */
  function formatSize(bytes) {
    bytes = bytes > 0 ? bytes : 0;
    if (bytes < 1024) {
      return bytes + " B";
    }
    if (bytes < 1024 * 1024) {
      return Math.round(bytes / 1024) + " KB";
    }
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  /** Ngày giờ máy chủ gửi xuống ("2026-10-09 07:30:00", giờ UTC) → Date. Rỗng → null. */
  function parseServerDate(text) {
    return text ? new Date(text.replace(" ", "T") + "Z") : null;
  }

  /**
   * Thời điểm → chữ ngắn so với now: "vừa xong", "5 phút trước", "3 giờ trước", "hôm qua",
   * "4 ngày trước", quá một tuần thì "dd/mm/yyyy". date, now: Date. date null → "".
   */
  function timeAgo(date, now) {
    if (!date) {
      return "";
    }
    var seconds = Math.max(0, (now - date) / 1000);
    if (seconds < 60) {
      return "vừa xong";
    }
    if (seconds < 3600) {
      return Math.floor(seconds / 60) + " phút trước";
    }
    if (seconds < 86400) {
      return Math.floor(seconds / 3600) + " giờ trước";
    }
    var days = Math.floor(seconds / 86400);
    if (days < 2) {
      return "hôm qua";
    }
    if (days < 7) {
      return days + " ngày trước";
    }
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    return pad(date.getDate()) + "/" + pad(date.getMonth() + 1) + "/" + date.getFullYear();
  }

  /**
   * Kiểm file đính kèm trước khi gửi (máy chủ vẫn kiểm lại — đây chỉ để báo sớm).
   * sizes: mảng số byte; limits: {max_files, max_file_bytes, max_total_bytes}.
   * Hợp lệ → ""; không → thông điệp cho người dùng.
   */
  function uploadProblem(sizes, limits) {
    if (sizes.length > limits.max_files) {
      return "Mỗi tin đính kèm tối đa " + limits.max_files + " file.";
    }
    if (sizes.some(function (size) { return size > limits.max_file_bytes; })) {
      return "Mỗi file tối đa " + formatSize(limits.max_file_bytes) + ".";
    }
    if (sizes.reduce(function (sum, size) { return sum + size; }, 0) > limits.max_total_bytes) {
      return "Tổng các file đính kèm tối đa " + formatSize(limits.max_total_bytes) + ".";
    }
    return "";
  }

  ns.text = {
    plain: plain,
    locateQuote: locateQuote,
    formatSize: formatSize,
    parseServerDate: parseServerDate,
    timeAgo: timeAgo,
    uploadProblem: uploadProblem,
  };
})(window.HlvGuide = window.HlvGuide || {});
