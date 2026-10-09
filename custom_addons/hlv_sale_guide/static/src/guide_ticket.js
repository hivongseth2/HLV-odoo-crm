/* Ngăn Ticket bên trái trang /huong-dan: danh sách câu hỏi / yêu cầu chỉnh sửa, chi tiết kèm
   thảo luận, form tạo mới. Ticket có đoạn trích thì đoạn đó được tô trên hướng dẫn bên phải;
   mở ticket là khung xem nhảy tới đoạn đó. ?t=<id> trên link mở thẳng một ticket. */
(function (ns) {
  "use strict";

  var h = ns.core.h;
  var text = ns.text;
  var viewer = ns.viewer;
  var quote = ns.quote;
  var pane = document.getElementById("side-tickets");
  var treePane = document.getElementById("side-tree");
  var layout = document.querySelector(".layout");
  var badge = document.getElementById("ticket-badge");
  var guideChip = document.getElementById("guide-tickets");
  var askButton = document.getElementById("guide-ask");
  if (!pane) {
    return;
  }

  var KINDS = { question: "Câu hỏi", request: "Yêu cầu sửa" };
  var STATES = { open: "Chưa xử lý", done: "Đã xử lý" };
  var FILTERS = [["open", "Chưa xử lý"], ["done", "Đã xử lý"], ["all", "Tất cả"]];
  var SCOPES = [["all", "Mọi hướng dẫn"], ["guide", "Hướng dẫn đang mở"], ["mine", "Ticket của tôi"]];
  var ui = { tickets: [], filter: "open", scope: "all", query: "", view: "list", openId: null, newForm: null };
  var pendingReveal = null;

  // ------------------------------------------------------------------ chung

  function setTab(name) {
    document.querySelectorAll(".side-tab").forEach(function (tab) {
      tab.setAttribute("aria-selected", String(tab.dataset.tab === name));
    });
    treePane.hidden = name !== "tree";
    pane.hidden = name !== "tickets";
    layout.classList.toggle("is-tickets", name === "tickets");
  }

  function rememberTicket(id) {
    var params = new URLSearchParams(location.search);
    if (id) {
      params.set("t", id);
    } else {
      params.delete("t");
    }
    history.replaceState(null, "", "?" + params.toString());
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

  function currentGuideTickets() {
    var current = viewer.current;
    return current ? ui.tickets.filter(function (t) { return t.guide && t.guide.id === current.id; }) : [];
  }

  function refreshCounts() {
    var open = ui.tickets.filter(function (t) { return t.state === "open"; }).length;
    badge.textContent = open;
    badge.hidden = !open;
    if (guideChip) {
      var mine = currentGuideTickets();
      var openHere = mine.filter(function (t) { return t.state === "open"; }).length;
      guideChip.textContent = "💬 " + mine.length + (openHere ? " (" + openHere + " chưa xử lý)" : "");
      guideChip.hidden = !mine.length;
    }
  }

  function markCurrentGuide() {
    quote.mark(currentGuideTickets());
  }

  /** Mở hướng dẫn của ticket ở khung xem và cuộn tới đoạn trích (điện thoại: mở trang hướng dẫn). */
  function showInGuide(ticket) {
    if (!ticket.guide) {
      return;
    }
    if (!viewer.available()) {
      window.open("/huong-dan/" + ticket.guide.slug + "/", "_blank", "noopener");
      return;
    }
    var sameGuide = viewer.current && viewer.current.id === ticket.guide.id;
    if (sameGuide) {
      quote.reveal(ticket.id);
    } else if (viewer.show(ticket.guide.slug)) {
      pendingReveal = ticket.id; // khung xem tải xong (hlv:guide-loaded) mới cuộn được
    }
  }

  // ------------------------------------------------------------------ danh sách

  function visibleTickets() {
    var query = text.plain(ui.query.trim());
    var current = viewer.current;
    return ui.tickets.filter(function (t) {
      if (ui.filter !== "all" && t.state !== ui.filter) {
        return false;
      }
      if (ui.scope === "mine" && !t.mine) {
        return false;
      }
      if (ui.scope === "guide" && !(current && t.guide && t.guide.id === current.id)) {
        return false;
      }
      return !query || text.plain([t.name, t.quote, t.author, t.guide ? t.guide.name : ""].join(" ")).indexOf(query) >= 0;
    });
  }

  function ticketItem(t) {
    return h("button", { type: "button", class: "tk-item is-" + t.state, onclick: function () { openDetail(t.id); } }, [
      h("div", { class: "tk-item-head" }, [kindBadge(t.kind), h("span", { class: "tk-title", text: t.name })]),
      t.quote ? h("div", { class: "tk-quote", text: t.quote }) : null,
      h("div", { class: "tk-meta" }, [
        h("span", { text: t.guide ? t.guide.name : "Chung" }),
        h("span", { text: t.author }),
        when(t.last_message_on),
        h("span", { title: "Số tin thảo luận", text: "💬 " + t.message_count }),
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
    ui.view = "list";
    ui.openId = null;
    ui.newForm = null;
    rememberTicket(null);
    var openCount = ui.tickets.filter(function (t) { return t.state === "open"; }).length;
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
      h("span", { text: att.mimetype === "application/pdf" ? "📄" : "📎" }),
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
      ? [{ label: "✔ Đánh dấu đã xử lý", fields: { state: "done" }, setsState: true }, send]
      : [{ label: "↺ Mở lại", fields: { state: "open" }, setsState: true }, send];
  }

  function renderDetail(t) {
    pane.textContent = "";
    var thread = h("div", { class: "tk-thread" }, t.messages.map(messageItem));
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
    pane.appendChild(h("div", { class: "tk-detail" }, [
      h("button", { type: "button", class: "tk-back", text: "← Danh sách ticket", onclick: openList }),
      h("h2", { class: "tk-detail-title", text: t.name }),
      h("div", { class: "tk-detail-badges" }, [
        kindBadge(t.kind),
        stateBadge(t.state),
        t.state === "done" && t.done_by ? h("small", { text: "bởi " + t.done_by }) : null,
      ]),
      h("div", { class: "tk-meta" }, [h("span", { text: t.author }), when(t.created_on)]),
      t.guide ? h("button", {
        type: "button", class: "tk-guide-link", title: "Mở hướng dẫn này bên phải",
        text: "📘 " + t.guide.name, onclick: function () { showInGuide(t); },
      }) : h("div", { class: "tk-meta", text: "Ticket chung, không gắn hướng dẫn" }),
      t.quote ? h("blockquote", {
        class: "tk-quote tk-quote-full" + (t.guide ? " is-link" : ""), title: t.guide ? "Bấm để xem đoạn này trong hướng dẫn" : null,
        text: t.quote, onclick: function () { showInGuide(t); },
      }) : null,
      thread,
      reply,
    ]));
  }

  function openDetail(id, options) {
    var first = ui.openId !== id;
    ui.view = "detail";
    ui.openId = id;
    ui.newForm = null;
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
      // Tự nhảy tới đoạn trích chỉ khi có khung xem; điện thoại thì để người dùng bấm mới mở trang.
      if ((!options || options.reveal !== false) && viewer.available()) {
        showInGuide(t);
      }
    }, function (err) {
      pane.textContent = "";
      pane.appendChild(h("button", { type: "button", class: "tk-back", text: "← Danh sách ticket", onclick: openList }));
      pane.appendChild(h("div", { class: "tk-empty", text: err.message }));
    });
  }

  // ------------------------------------------------------------------ tạo mới

  function openNew(preset) {
    if (ui.view === "new" && ui.newForm) {
      ui.newForm.update(preset); // đang soạn dở: chỉ thay đoạn trích / hướng dẫn, giữ chữ đã gõ
      return;
    }
    ui.view = "new";
    ui.openId = null;
    rememberTicket(null);
    var kind = "question";
    var quoteText = preset.quote || "";
    var guides = viewer.guides();
    var kindButtons = Object.keys(KINDS).map(function (key) {
      return h("button", {
        type: "button", class: "tk-kind-pick", "data-kind": key, "aria-pressed": String(key === kind),
        text: key === "question" ? "❓ Câu hỏi" : "✏️ Yêu cầu chỉnh sửa",
        onclick: function () {
          kind = key;
          kindButtons.forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.kind === key)); });
        },
      });
    });
    var guideSelect = h("select", {
      class: "tk-input", "aria-label": "Hướng dẫn",
      onchange: function () { setQuote(""); }, // đoạn trích thuộc hướng dẫn cũ, không còn đúng
    }, [h("option", { value: "", text: "— Chung, không gắn hướng dẫn —" })].concat(guides.map(function (g) {
      return h("option", { value: g.id, text: g.name });
    })));
    var quoteBox = h("div", { class: "tk-quote-pick" });
    var titleInput = h("input", { class: "tk-input", type: "text", maxlength: 80, placeholder: "Tiêu đề (bỏ trống: lấy dòng đầu nội dung)" });

    function setQuote(value) {
      quoteText = value;
      quoteBox.textContent = "";
      if (value) {
        quoteBox.appendChild(h("blockquote", { class: "tk-quote tk-quote-full", text: value }));
        quoteBox.appendChild(h("button", { type: "button", class: "cmp-remove", title: "Bỏ đoạn trích", text: "×", onclick: function () { setQuote(""); } }));
      } else if (viewer.available()) {
        quoteBox.appendChild(h("div", { class: "tk-tip", text: "Mẹo: bôi đen một đoạn trong hướng dẫn bên phải rồi bấm nút hiện ra để trích đoạn đó vào đây." }));
      }
    }

    function update(next) {
      if (next.guide) {
        guideSelect.value = String(next.guide.id);
      }
      setQuote(next.quote || "");
      form.focus();
    }

    var form = ns.composer({
      placeholder: "Nội dung câu hỏi / yêu cầu… (Ctrl+V để dán ảnh chụp màn hình)",
      extra: h("div", { class: "tk-new-fields" }, [
        h("div", { class: "tk-kind-row" }, kindButtons),
        guideSelect,
        quoteBox,
        titleInput,
      ]),
      actions: [{ label: "Gửi ticket", primary: true }],
      submit: function (fields, files, onProgress) {
        fields.kind = kind;
        fields.guide_id = guideSelect.value;
        fields.title = titleInput.value;
        fields.quote = quoteText;
        return ns.core.send("/new", fields, files, onProgress).then(function (reply) {
          // Tải lại danh sách trước để đoạn trích mới đã được tô khi khung xem nhảy tới.
          return load().then(function () { return openDetail(reply.id); });
        });
      },
    });
    ui.newForm = { update: update };
    pane.textContent = "";
    pane.appendChild(h("div", { class: "tk-detail" }, [
      h("button", { type: "button", class: "tk-back", text: "← Danh sách ticket", onclick: openList }),
      h("h2", { class: "tk-detail-title", text: "Ticket mới" }),
      form,
    ]));
    update({ guide: preset.guide || viewer.current, quote: quoteText });
  }

  // ------------------------------------------------------------------ nối sự kiện

  document.querySelectorAll(".side-tab").forEach(function (tab) {
    tab.addEventListener("click", function () { setTab(tab.dataset.tab); });
  });

  quote.onPick(function (picked) {
    setTab("tickets");
    openNew({ guide: viewer.current, quote: picked });
  });

  quote.onOpen(function (id) {
    setTab("tickets");
    openDetail(id, { reveal: false });
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
      quote.reveal(pendingReveal);
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
  openList();
  load().then(function () {
    if (wanted) {
      setTab("tickets");
      openDetail(wanted);
    }
  });
})(window.HlvGuide = window.HlvGuide || {});
