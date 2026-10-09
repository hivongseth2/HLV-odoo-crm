/* Ngăn hỏi đáp / yêu cầu sửa: danh sách ticket, chi tiết kèm thảo luận, form tạo mới
   (guide_ticket_form.js). Nằm bên trái /huong-dan (tab cạnh cây thư mục) và bên phải trang một
   hướng dẫn (bật / tắt bằng nút trên thanh). Đoạn trích của ticket được tô trên hướng dẫn; mở
   ticket là khung xem nhảy tới đoạn đó. ?t=<id> trên link mở thẳng một ticket. */
(function (ns) {
  "use strict";

  var h = ns.core.h;
  var text = ns.text;
  var viewer = ns.viewer;
  var quote = ns.quote;
  var pane = document.getElementById("side-tickets");
  var treePane = document.getElementById("side-tree");
  var toggle = document.getElementById("side-toggle");
  var layout = document.querySelector(".layout");
  var badge = document.getElementById("ticket-badge");
  var guideChip = document.getElementById("guide-tickets");
  var askButton = document.getElementById("guide-ask");
  if (!pane || !viewer) {
    return;
  }

  var KINDS = { question: "Câu hỏi", request: "Yêu cầu sửa" };
  var STATES = { open: "Chưa xử lý", done: "Đã xử lý" };
  var FILTERS = [["open", "Chưa xử lý"], ["done", "Đã xử lý"], ["all", "Tất cả"]];
  var SCOPES = [["all", "Mọi hướng dẫn"], ["guide", viewer.single ? "Hướng dẫn này" : "Hướng dẫn đang mở"], ["mine", "Ticket của tôi"]];
  var PICK_NEW = "Hỏi / yêu cầu sửa đoạn này";
  var PICK_ADD = "Thêm đoạn này vào ticket";
  var ui = {
    tickets: [], filter: "open", scope: viewer.single ? "guide" : "all", query: "",
    view: "list", openId: null, newForm: null,
  };
  var pendingReveal = null; // {id, index} chờ khung xem tải xong mới cuộn được

  // ------------------------------------------------------------------ chung

  /** "tree" / "tickets" ở /huong-dan; ở trang một hướng dẫn "tickets" là mở ngăn, null là đóng. */
  function setTab(name) {
    document.querySelectorAll(".side-tab").forEach(function (tab) {
      tab.setAttribute("aria-selected", String(tab.dataset.tab === name));
    });
    if (treePane) {
      treePane.hidden = name !== "tree";
    }
    pane.hidden = name !== "tickets";
    layout.classList.toggle("is-tickets", name === "tickets");
    if (toggle) {
      toggle.setAttribute("aria-expanded", String(name === "tickets"));
    }
  }

  function setView(name) {
    ui.view = name;
    quote.setPickLabel(name === "new" ? PICK_ADD : PICK_NEW);
    if (name !== "new") {
      ui.newForm = null;
    }
    if (name !== "detail") {
      ui.openId = null;
    }
  }

  function rememberTicket(id) {
    var params = new URLSearchParams(location.search);
    if (id) {
      params.set("t", id);
    } else {
      params.delete("t");
    }
    var query = params.toString();
    history.replaceState(null, "", location.pathname + (query ? "?" + query : ""));
  }

  function when(dateText) {
    var date = text.parseServerDate(dateText);
    return h("time", { title: date ? date.toLocaleString("vi-VN") : null, text: text.timeAgo(date, new Date()) });
  }

  function kindBadge(kind) {
    return h("span", { class: "tk-kind tk-kind-" + kind, text: KINDS[kind] || kind });
  }

  function stateBadge(state) {
    return h("span", { class: "tk-state tk-state-" + state, text: STATES[state] || state });
  }

  function backButton() {
    return h("button", { type: "button", class: "tk-back", text: "← Danh sách", onclick: openList });
  }

  function load() {
    return ns.core.rpc("/list").then(function (tickets) {
      ui.tickets = tickets;
      refreshCounts();
      markCurrentGuide();
      if (ui.view === "list") {
        renderItems();
      }
    }, function (err) {
      if (ui.view === "list") {
        pane.textContent = "";
        pane.appendChild(h("div", { class: "tk-empty", text: "Không tải được ticket: " + err.message }));
      }
    });
  }

  function isCurrentGuide(ticket) {
    return !!(ticket.guide && viewer.current && ticket.guide.id === viewer.current.id);
  }

  function countOpen(tickets) {
    return tickets.filter(function (t) { return t.state === "open"; }).length;
  }

  function refreshCounts() {
    var here = ui.tickets.filter(isCurrentGuide);
    // Trang một hướng dẫn: số trên nút là ticket của chính hướng dẫn đó.
    var open = countOpen(viewer.single ? here : ui.tickets);
    badge.textContent = open;
    badge.hidden = !open;
    if (guideChip) {
      var openHere = countOpen(here);
      guideChip.textContent = here.length + " ticket" + (openHere ? " · " + openHere + " chưa xử lý" : "");
      guideChip.hidden = !here.length;
    }
  }

  function markCurrentGuide() {
    quote.mark(ui.tickets.filter(isCurrentGuide));
    flagMissingQuotes();
  }

  /**
   * Làm mờ đoạn trích (trong chi tiết ticket đang mở) không còn tìm thấy trên bản hướng dẫn hiện
   * tại — thường do hướng dẫn đã tải bản mới sửa / xoá đoạn đó. Chỉ xét khi khung xem đang hiện
   * đúng hướng dẫn của ticket.
   */
  function flagMissingQuotes() {
    pane.querySelectorAll(".tk-quote[data-index]").forEach(function (el) {
      var found = quote.hasMark(el.dataset.guideUrl, Number(el.dataset.ticket), Number(el.dataset.index));
      el.classList.toggle("is-missing", found === false);
      el.title = found === false
        ? "Không còn tìm thấy đoạn này trong bản hướng dẫn hiện tại"
        : "Bấm để xem chỗ này trong hướng dẫn";
    });
  }

  /** Cuộn khung xem tới đoạn trích thứ index của ticket; ticket của hướng dẫn khác thì mở hướng dẫn đó trước. */
  function showInGuide(ticket, index) {
    if (!ticket.guide) {
      return;
    }
    var target = { id: ticket.id, index: index || 0 };
    if (isCurrentGuide(ticket)) {
      if (!quote.reveal(target.id, target.index)) {
        pendingReveal = target; // khung xem chưa tải xong
      }
    } else if (viewer.show(ticket.guide.slug, ticket.id)) {
      pendingReveal = target;
    }
  }

  // ------------------------------------------------------------------ danh sách

  function visibleTickets() {
    var query = text.plain(ui.query.trim());
    return ui.tickets.filter(function (t) {
      if (ui.filter !== "all" && t.state !== ui.filter) {
        return false;
      }
      if (ui.scope === "mine" && !t.mine) {
        return false;
      }
      if (ui.scope === "guide" && !isCurrentGuide(t)) {
        return false;
      }
      return !query || text.plain([t.name, t.quotes.join(" "), t.author, t.guide ? t.guide.name : ""].join(" ")).indexOf(query) >= 0;
    });
  }

  function ticketItem(t) {
    var more = t.quotes.length - 1;
    return h("button", { type: "button", class: "tk-item is-" + t.state, onclick: function () { openDetail(t.id); } }, [
      h("div", { class: "tk-item-head" }, [kindBadge(t.kind), h("span", { class: "tk-title", text: t.name })]),
      t.quotes.length ? h("div", { class: "tk-quote", text: t.quotes[0] }) : null,
      more > 0 ? h("div", { class: "tk-more", text: "và " + more + " chỗ khác" }) : null,
      h("div", { class: "tk-meta" }, [
        viewer.single ? null : h("span", { text: t.guide ? t.guide.name : "Chung" }),
        h("span", { text: t.author }),
        when(t.last_message_on),
        h("span", { text: t.message_count + " tin" }),
      ]),
    ]);
  }

  function renderItems() {
    var list = document.getElementById("tk-list");
    if (!list) {
      return;
    }
    list.textContent = "";
    var tickets = visibleTickets();
    tickets.forEach(function (t) { list.appendChild(ticketItem(t)); });
    if (!tickets.length) {
      list.appendChild(h("div", { class: "tk-empty", text: ui.tickets.length ? "Không có ticket nào khớp bộ lọc." : "Chưa có ticket nào." }));
    }
    document.querySelectorAll(".tk-filter").forEach(function (chip) {
      chip.setAttribute("aria-pressed", String(chip.dataset.filter === ui.filter));
    });
  }

  function openList() {
    setView("list");
    rememberTicket(null);
    var openCount = countOpen(ui.tickets);
    pane.textContent = "";
    pane.appendChild(h("div", { class: "tk-toolbar" }, [
      h("button", { type: "button", class: "btn btn-primary", text: "+ Ticket mới", onclick: function () { openNew({}); } }),
      h("input", {
        type: "search", class: "tk-search", placeholder: "Tìm ticket…", "aria-label": "Tìm ticket", value: ui.query,
        oninput: function (event) { ui.query = event.target.value; renderItems(); },
      }),
    ]));
    pane.appendChild(h("div", { class: "tk-filters" }, FILTERS.map(function (f) {
      return h("button", {
        type: "button", class: "tk-filter", "data-filter": f[0],
        text: f[1] + (f[0] === "open" && openCount ? " (" + openCount + ")" : ""),
        onclick: function () { ui.filter = f[0]; renderItems(); },
      });
    }).concat([
      h("select", {
        class: "tk-scope", "aria-label": "Phạm vi",
        onchange: function (event) { ui.scope = event.target.value; renderItems(); },
      }, SCOPES.map(function (s) {
        return h("option", { value: s[0], selected: s[0] === ui.scope, text: s[1] });
      })),
    ])));
    pane.appendChild(h("div", { id: "tk-list", class: "tk-list" }));
    renderItems();
  }

  // ------------------------------------------------------------------ chi tiết

  function attachmentItem(att) {
    if (att.mimetype.indexOf("image/") === 0) {
      return h("a", { class: "att-image", href: att.url, target: "_blank", rel: "noopener", title: att.name }, [
        h("img", { src: att.url, alt: att.name, loading: "lazy" }),
      ]);
    }
    if (att.mimetype.indexOf("video/") === 0) {
      return h("video", { class: "att-video", src: att.url, controls: true, preload: "metadata", title: att.name });
    }
    if (att.mimetype.indexOf("audio/") === 0) {
      return h("audio", { class: "att-audio", src: att.url, controls: true, preload: "none", title: att.name });
    }
    return h("a", { class: "att-file", href: att.url + "?download=true", title: "Tải về" }, [
      h("span", { class: "att-ext", text: text.fileLabel(att.name) }),
      h("span", { class: "att-name", text: att.name }),
      h("small", { text: text.formatSize(att.size) }),
    ]);
  }

  function messageItem(msg) {
    var body = h("div", { class: "msg-body" });
    body.innerHTML = msg.body; // Html đã được Odoo lọc khi lưu tin (mail.message.body)
    return h("div", { class: "msg" + (msg.mine ? " is-mine" : "") }, [
      msg.avatar ? h("img", { class: "msg-avatar", src: msg.avatar, alt: "" }) : h("span", { class: "msg-avatar" }),
      h("div", { class: "msg-main" }, [
        h("div", { class: "msg-head" }, [h("b", { text: msg.author }), when(msg.date)]),
        body,
        msg.attachments.length ? h("div", { class: "msg-atts" }, msg.attachments.map(attachmentItem)) : null,
      ]),
    ]);
  }

  function replyActions(t) {
    var send = { label: "Gửi", primary: true };
    if (!t.can_set_state) {
      return [send];
    }
    return t.state === "open"
      ? [{ label: "Đánh dấu đã xử lý", fields: { state: "done" }, setsState: true }, send]
      : [{ label: "Mở lại", fields: { state: "open" }, setsState: true }, send];
  }

  function quoteList(t) {
    var linked = !!t.guide;
    return h("div", { class: "tk-quotes" }, t.quotes.map(function (q, index) {
      return h("blockquote", {
        class: "tk-quote tk-quote-full" + (linked ? " is-link" : ""),
        "data-ticket": linked ? t.id : null,
        "data-index": linked ? index : null,
        "data-guide-url": linked ? "/huong-dan/" + t.guide.slug + "/" : null,
        text: q,
        onclick: linked ? function () { showInGuide(t, index); } : null,
      });
    }));
  }

  function versionNote(t) {
    if (!t.guide_changed) {
      return null;
    }
    var day = function (value) { return text.formatDate(text.parseServerDate(value)); };
    return h("div", {
      class: "tk-note",
      text: "Hỏi trên bản hướng dẫn ngày " + day(t.guide_version_asked) + ". Hướng dẫn đã tải bản mới ngày "
        + day(t.guide_version_now) + ", đoạn trích có thể không còn.",
    });
  }

  function renderDetail(t) {
    pane.textContent = "";
    var reply = ns.composer({
      placeholder: "Trả lời, bổ sung… (Ctrl+V để dán ảnh, Ctrl+Enter để gửi)",
      actions: replyActions(t),
      allowEmpty: function (action) { return !!action.setsState; },
      submit: function (fields, files, onProgress) {
        return ns.core.send("/" + t.id + "/reply", fields, files, onProgress).then(function () {
          load();
          return openDetail(t.id, { reveal: false });
        });
      },
    });
    var guideLine = null;
    if (!t.guide) {
      guideLine = h("div", { class: "tk-meta", text: "Ticket chung, không gắn hướng dẫn" });
    } else if (!isCurrentGuide(t) || !viewer.single) {
      guideLine = h("button", {
        type: "button", class: "tk-guide-link", title: "Mở hướng dẫn này",
        text: "Hướng dẫn: " + t.guide.name, onclick: function () { showInGuide(t, 0); },
      });
    }
    pane.appendChild(h("div", { class: "tk-detail" }, [
      backButton(),
      h("h2", { class: "tk-detail-title", text: t.name }),
      h("div", { class: "tk-detail-badges" }, [
        kindBadge(t.kind),
        stateBadge(t.state),
        t.state === "done" && t.done_by ? h("small", { text: "bởi " + t.done_by }) : null,
      ]),
      h("div", { class: "tk-meta" }, [h("span", { text: t.author }), when(t.created_on)]),
      guideLine,
      versionNote(t),
      t.quotes.length ? quoteList(t) : null,
      h("div", { class: "tk-thread" }, t.messages.map(messageItem)),
      reply,
    ]));
    flagMissingQuotes();
  }

  function openDetail(id, options) {
    var first = ui.openId !== id;
    setView("detail");
    ui.openId = id;
    rememberTicket(id);
    if (first) {
      pane.textContent = "";
      pane.appendChild(h("div", { class: "tk-empty", text: "Đang tải…" }));
    }
    return ns.core.rpc("/" + id).then(function (t) {
      if (ui.openId !== id) {
        return; // người dùng đã bấm sang chỗ khác trong lúc chờ
      }
      renderDetail(t);
      if (!first) {
        pane.scrollTop = pane.scrollHeight; // vừa gửi tin: cuộn xuống tin mới nhất
      }
      // Tự nhảy tới đoạn trích khi không phải rời trang (hướng dẫn đang mở, hoặc mở được tại chỗ).
      var reveal = !options || options.reveal !== false;
      if (reveal && t.guide && (isCurrentGuide(t) || viewer.canShowInline())) {
        showInGuide(t, (options && options.index) || 0);
      }
    }, function (err) {
      pane.textContent = "";
      pane.appendChild(backButton());
      pane.appendChild(h("div", { class: "tk-empty", text: err.message }));
    });
  }

  // ------------------------------------------------------------------ tạo mới

  function openNew(preset) {
    if (ui.view === "new" && ui.newForm) {
      ui.newForm.add(preset); // đang soạn dở: thêm đoạn trích, giữ chữ đã gõ
      return;
    }
    setView("new");
    rememberTicket(null);
    ui.newForm = ns.ticketForm({
      guide: preset.guide || viewer.current,
      quote: preset.quote || "",
      onBack: openList,
      onCreated: function (id) {
        // Tải lại danh sách trước để đoạn trích mới đã được tô khi khung xem nhảy tới.
        return load().then(function () { return openDetail(id); });
      },
    });
    pane.textContent = "";
    pane.appendChild(ui.newForm.el);
    ui.newForm.add({}); // đặt con trỏ vào ô nội dung khi form đã nằm trên trang
  }

  // ------------------------------------------------------------------ nối sự kiện

  document.querySelectorAll(".side-tab").forEach(function (tab) {
    tab.addEventListener("click", function () { setTab(tab.dataset.tab); });
  });

  if (toggle) {
    toggle.addEventListener("click", function () { setTab(pane.hidden ? "tickets" : null); });
  }

  quote.onPick(function (picked) {
    setTab("tickets");
    openNew({ guide: viewer.current, quote: picked });
  });

  quote.onOpen(function (id, index) {
    setTab("tickets");
    openDetail(id, { reveal: false, index: index });
  });

  document.addEventListener("hlv:guide-shown", function () {
    refreshCounts();
    if (ui.view === "list" && ui.scope === "guide") {
      renderItems();
    }
  });

  document.addEventListener("hlv:guide-loaded", function () {
    markCurrentGuide();
    if (pendingReveal) {
      quote.reveal(pendingReveal.id, pendingReveal.index);
      pendingReveal = null;
    }
  });

  if (askButton) {
    askButton.addEventListener("click", function () {
      setTab("tickets");
      openNew({ guide: viewer.current });
    });
  }

  if (guideChip) {
    guideChip.addEventListener("click", function () {
      setTab("tickets");
      ui.scope = "guide";
      ui.filter = "all";
      openList();
    });
  }

  // Quay lại tab trình duyệt: tải lại danh sách để thấy ticket / trả lời mới của người khác.
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      load();
    }
  });

  var wanted = Number(new URLSearchParams(location.search).get("t"));
  // Trang một hướng dẫn trên máy tính: mở sẵn ngăn hỏi đáp; điện thoại thì ngăn phủ lên trang
  // nên để người dùng tự bật.
  if (viewer.single && window.matchMedia("(min-width: 821px)").matches) {
    setTab("tickets");
  }
  openList();
  load().then(function () {
    if (wanted) {
      setTab("tickets");
      openDetail(wanted);
    }
  });
})(window.HlvGuide = window.HlvGuide || {});
