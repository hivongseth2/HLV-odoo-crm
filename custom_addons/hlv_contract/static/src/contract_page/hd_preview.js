/* Khung xem trước trực tiếp: tờ hợp đồng thu nhỏ đặt cạnh chỗ nhập liệu (ngăn soạn, bảng dữ
   liệu). Server trả HTML có <span class="hd-pv" data-pv="Ten_Bien"> ở chỗ từng biến nhập:
   tô vàng = đã điền, khung đứt = còn trống. Bấm chỗ đó -> nhảy tới ô nhập; đứng ở ô nhập nào
   thì chỗ của nó trên tờ hợp đồng sáng lên. */
window.HlvContract = window.HlvContract || {};

(function (HD) {
  "use strict";

  var PAPER_WIDTH = 820;   // ~ khổ A4 + lề trong, để tính tỉ lệ thu nhỏ
  var STORAGE_KEY = "hlv_contract.preview";

  /** Bật/tắt khung xem trước, nhớ theo trình duyệt. Mặc định bật khi màn hình đủ rộng. */
  HD.previewEnabled = function (value) {
    try {
      if (value !== undefined) {
        window.localStorage.setItem(STORAGE_KEY, value ? "1" : "0");
        return value;
      }
      var saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved !== null) {
        return saved === "1";
      }
    } catch (err) {
      // trình duyệt chặn localStorage (chế độ riêng tư): dùng mặc định
    }
    return window.innerWidth >= 1100;
  };

  /**
   * Gắn khung xem trước vào aside. opts.onPick(name): bấm vào chỗ biến trên tờ hợp đồng.
   * opts.title: dòng giải thích trên đầu khung.
   * Trả {setHtml(html), highlight(name), setStatus(text)}.
   */
  HD.mountLivePreview = function (aside, opts) {
    aside.innerHTML =
      '<div class="hd-pv-head"><div><b>Xem trước</b> <span class="hd-pv-status"></span></div>' +
      '<div class="hd-pv-legend"><span class="hd-pv">đã điền</span> <span class="hd-pv is-empty">còn trống</span> — ' +
      HD.esc(opts.title || "bấm vào để tới ô nhập") + "</div></div>" +
      '<div class="hd-pv-scroll"><article class="hd-paper hd-pv-paper"><p class="hd-muted">Đang tải…</p></article></div>';
    var scroller = aside.querySelector(".hd-pv-scroll");
    var paper = aside.querySelector(".hd-pv-paper");
    var status = aside.querySelector(".hd-pv-status");
    var focused = null;

    function fit() {
      var width = scroller.clientWidth - 24;
      paper.style.zoom = width > 0 ? Math.min(1, Math.max(0.35, width / PAPER_WIDTH)) : 1;
    }

    function highlight(name) {
      focused = name;
      paper.querySelectorAll(".hd-pv.is-focus").forEach(function (el) { el.classList.remove("is-focus"); });
      if (!name) {
        return;
      }
      var spans = paper.querySelectorAll('[data-pv="' + name + '"]');
      spans.forEach(function (el) { el.classList.add("is-focus"); });
      if (spans.length) {
        // Cuộn riêng khung xem trước (scrollIntoView sẽ cuộn cả ngăn soạn đang gõ)
        var delta = spans[0].getBoundingClientRect().top - scroller.getBoundingClientRect().top;
        scroller.scrollTo({ top: scroller.scrollTop + delta - scroller.clientHeight / 3, behavior: "smooth" });
      }
    }

    paper.addEventListener("click", function (event) {
      var span = event.target.closest("[data-pv]");
      if (span && opts.onPick) {
        opts.onPick(span.dataset.pv);
      }
    });
    // Theo dõi chính khung (không gắn vào window): ngăn soạn vẽ lại liên tục, gắn vào window
    // thì mỗi lần vẽ lại để thừa một listener
    if (window.ResizeObserver) {
      new ResizeObserver(fit).observe(scroller);
    }
    fit();

    return {
      setHtml: function (html) {
        var top = scroller.scrollTop;
        paper.innerHTML = html;
        fit();
        scroller.scrollTop = top;   // giữ chỗ đang xem khi cập nhật lúc gõ
        if (focused) {
          paper.querySelectorAll('[data-pv="' + focused + '"]').forEach(function (el) { el.classList.add("is-focus"); });
        }
      },
      highlight: highlight,
      setStatus: function (text) { status.textContent = text || ""; },
    };
  };
})(window.HlvContract);
