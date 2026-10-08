/* Trang /huong-dan: bấm một hướng dẫn trên cây thì mở trong khung xem bên phải (máy tính),
   ?g=<slug> nhớ hướng dẫn đang mở để F5 / gửi link vẫn đúng chỗ; ô tìm lọc cây theo tên.
   Điện thoại (khung xem bị ẩn) để link đi bình thường — mở cả trang. */
(function () {
  "use strict";

  var view = document.getElementById("guide-view");
  var tree = document.querySelector(".tree");
  if (!view || !tree) {
    return;
  }
  var wide = window.matchMedia("(min-width: 821px)");
  var title = document.getElementById("guide-view-title");
  var full = document.getElementById("guide-view-full");

  /** Chữ thường, bỏ dấu tiếng Việt — để gõ "hoi gia" vẫn ra "Hỏi giá". */
  function plain(text) {
    return text.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase();
  }

  function show(link, remember) {
    tree.querySelectorAll(".leaf.is-active").forEach(function (el) { el.classList.remove("is-active"); });
    link.classList.add("is-active");
    view.src = link.getAttribute("href") + "?embed=1";
    title.textContent = link.dataset.name;
    full.href = link.getAttribute("href");
    if (remember) {
      history.replaceState(null, "", "?g=" + encodeURIComponent(link.dataset.slug));
    }
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

  var wanted = new URLSearchParams(location.search).get("g");
  var start = (wanted && tree.querySelector('.leaf[data-slug="' + CSS.escape(wanted) + '"]')) || tree.querySelector(".leaf");
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
})();
