/* Trang /huong-dan: bấm một hướng dẫn trên cây thì mở trong khung xem bên phải (máy tính),
   ?g=<slug> nhớ hướng dẫn đang mở để F5 / gửi link vẫn đúng chỗ; ô tìm lọc cây theo tên.
   Điện thoại (khung xem bị ẩn) để link đi bình thường — mở cả trang.
   Khai HlvGuide.viewer cho ngăn Ticket (trang một hướng dẫn khai bản riêng: guide_viewer_single.js),
   sự kiện "hlv:guide-shown" trên document mỗi khi đổi hướng dẫn. */
(function (ns) {
  "use strict";

  var view = document.getElementById("guide-view");
  var tree = document.querySelector(".tree");
  var wide = window.matchMedia("(min-width: 821px)");
  var title = document.getElementById("guide-view-title");
  var full = document.getElementById("guide-view-full");
  var plain = ns.text.plain;

  function guideOf(link) {
    return { id: Number(link.dataset.id), slug: link.dataset.slug, name: link.dataset.name, url: link.getAttribute("href") };
  }

  function leafOf(slug) {
    return tree && slug ? tree.querySelector('.leaf[data-slug="' + CSS.escape(slug) + '"]') : null;
  }

  function show(link, remember) {
    tree.querySelectorAll(".leaf.is-active").forEach(function (el) { el.classList.remove("is-active"); });
    link.classList.add("is-active");
    view.src = link.getAttribute("href") + "?embed=1";
    title.textContent = link.dataset.name;
    full.href = link.getAttribute("href");
    if (remember) {
      var params = new URLSearchParams(location.search);
      params.set("g", link.dataset.slug);
      history.replaceState(null, "", "?" + params.toString());
    }
    ns.viewer.current = guideOf(link);
    document.dispatchEvent(new CustomEvent("hlv:guide-shown", { detail: ns.viewer.current }));
  }

  ns.viewer = {
    single: false,
    current: null,
    /** Mở được hướng dẫn khác ngay trong trang (máy tính, có khung xem) hay phải chuyển trang. */
    canShowInline: function () { return !!view && wide.matches; },
    /**
     * Mở hướng dẫn slug trong khung xem → true. Không mở tại chỗ được (điện thoại, không thấy trên
     * cây) → chuyển sang trang của hướng dẫn đó, kèm ?t=ticketId để mở luôn ticket, trả false.
     */
    show: function (slug, ticketId) {
      var link = leafOf(slug);
      if (!link || !ns.viewer.canShowInline()) {
        location.href = "/huong-dan/" + encodeURIComponent(slug) + "/" + (ticketId ? "?t=" + ticketId : "");
        return false;
      }
      if (!ns.viewer.current || ns.viewer.current.slug !== slug) {
        show(link, true);
      }
      return true;
    },
    /** Mọi hướng dẫn trên cây (đã lọc theo quyền xem) để chọn khi tạo ticket. */
    guides: function () {
      return tree ? Array.prototype.map.call(tree.querySelectorAll(".leaf"), guideOf) : [];
    },
  };

  if (!view || !tree) {
    return;
  }

  tree.addEventListener("click", function (event) {
    var link = event.target.closest(".leaf");
    // Ctrl/Shift/Cmd + bấm: để trình duyệt mở tab mới như link thường.
    if (!link || !wide.matches || event.ctrlKey || event.metaKey || event.shiftKey) {
      return;
    }
    event.preventDefault();
    show(link, true);
  });

  var start = leafOf(new URLSearchParams(location.search).get("g")) || tree.querySelector(".leaf");
  if (start && wide.matches) {
    show(start, false);
  }

  var search = document.getElementById("guide-search");
  if (search) {
    search.addEventListener("input", function () {
      var query = plain(search.value.trim());
      tree.querySelectorAll(".leaf").forEach(function (link) {
        link.hidden = !!query && plain(link.textContent + " " + (link.title || "")).indexOf(query) < 0;
      });
      tree.querySelectorAll("details.folder").forEach(function (folder) {
        folder.hidden = !!query && !folder.querySelector(".leaf:not([hidden])");
        if (query) {
          folder.open = true;
        }
      });
    });
  }
})(window.HlvGuide = window.HlvGuide || {});
