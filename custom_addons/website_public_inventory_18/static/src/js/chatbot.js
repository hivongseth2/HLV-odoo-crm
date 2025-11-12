/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { escape } from "@web/core/utils/strings";

const ChatbotWidget = publicWidget.Widget.extend({
    selector: ".chatbot-widget",

    events: {
        "click .chatbot-toggle": "_onToggleChatbot",
        "click .chatbot-send": "_onSendMessage",
        "keypress .chatbot-input": "_onKeyPress",
        "click .chatbot-close": "_onCloseChatbot",
        "click .chatbot-minimize": "_onMinimize",
        "click .btn-ghost": "_onAskMore",
    },
    _scrollToBottom() {
        const box = this.$(".chatbot-messages")[0];
        if (!box) return;
        box.scrollTop = box.scrollHeight;
    },

    start() {
        this._super(...arguments);
        this._initializeChatbot();

        const target = this._messagesEl()[0];
        if (target && !this._mo) {
            this._mo = new MutationObserver(() => this._scrollToBottom());
            this._mo.observe(target, { childList: true, subtree: true });
        }
    },


    _initializeChatbot() {
        this.isOpen = false;
        this.isLoading = false;
        this._checkChatbotStatus();
    },

    _checkChatbotStatus() {
        const self = this;
        $.ajax({
            url: "/chatbot/status",
            type: "GET",
            dataType: "json",
            success(result) {
                if (result.enabled) self.$el.show();
                else self.$el.hide();
            },
            error(err) {
                console.error("Error checking chatbot status:", err);
                self.$el.show(); // dev: vẫn show để test
            },
        });
    },

    _onToggleChatbot(ev) {
        ev.preventDefault();
        this.isOpen ? this._closeChatbot() : this._openChatbot();
    },
    _onAskMore(ev) {
        const code = $(ev.currentTarget).data("code");
        if (!code) return;
        const msg = `Cho mình xem thêm thông tin về ${code}`;
        this._addUserText(msg);
        this.$(".chatbot-input").val(msg);
        this._sendMessage();
    },
    _openChatbot() {
        this.isOpen = true;
        this.$(".chatbot-container").addClass("chatbot-open");
        this.$(".chatbot-input").focus();

        if (this.$(".chatbot-messages .chatbot-message").length === 0) {
            // Lời chào thân thiện, ngắn gọn
            this._addBotText(
                "Chào bạn 👋 Mình là trợ lý bán hàng. Bạn có thể hỏi mã/ tên sản phẩm và kho (ví dụ: “39-055 Tân Sơn Nhì còn mấy cái?”)."
            );
        }
    },

    _closeChatbot() {
        this.isOpen = false;
        this.$(".chatbot-container").removeClass("chatbot-open");
    },

    _onCloseChatbot(ev) {
        ev.preventDefault();
        this._closeChatbot();
    },

    _onMinimize(ev) {
        ev.preventDefault();
        this.$(".chatbot-container").toggleClass("chatbot-minimized");
    },

    _onKeyPress(ev) {
        if (ev.which === 13 && !ev.shiftKey) {
            ev.preventDefault();
            this._sendMessage();
        }
    },

    _onSendMessage(ev) {
        ev?.preventDefault?.();
        this._sendMessage();
    },
    _sendMessage() {
        if (this.isLoading) return;

        const input = this.$(".chatbot-input");
        // normalize: gộp khoảng trắng
        const message = (input.val() || "").replace(/\s+/g, " ").trim();
        if (!message) return;

        this._addUserText(message);
        input.val("");
        this._setLoading(true);

        const self = this;
        $.ajax({
            url: "/chatbot/message",
            type: "POST",
            dataType: "json",
            data: { message, csrf_token: odoo.csrf_token },
            success(result) {
                self._setLoading(false);
                if (!result || !result.success) {
                    self._addBotText("Xin lỗi, đã có lỗi xảy ra. Bạn thử lại giúp mình nhé.");
                    return;
                }

                // 1) text “thân thiện”
                if (result.response) {
                    self._addBotText(result.response);
                }
                // 2) card sản phẩm
                const products = Array.isArray(result.inventory_results) ? result.inventory_results : [];
                if (products.length) self._addProductList(products);
                // 3) web tham khảo
                const web = Array.isArray(result.web_results) ? result.web_results : [];
                if (web.length) self._addWebList(web);
            },
            error(err) {
                self._setLoading(false);
                console.error("Chatbot error:", err);
                self._addBotText("Xin lỗi, không thể kết nối đến server. Bạn thử lại sau nhé.");
            },
        });
    },


    // ========== Render helpers ==========

    _messagesEl() {
        return this.$(".chatbot-messages");
    },

    _addMessageHtml(html, type /* 'user' | 'bot' */) {
        const sideClass = type === "user" ? "user-message" : "bot-message";
        // Dùng DOM thay vì string để chắc chắn style apply
        const $msg = $(document.createElement("div"))
            .addClass(`chatbot-message ${sideClass}`)
            .append(
                $("<div>").addClass("message-content").html(html),  // HTML render ngay
                $("<div>").addClass("message-time").text(new Date().toLocaleTimeString())
            );

        const $wrap = this._messagesEl().append($msg);

        // Force reflow + scroll
        // requestAnimationFrame(() => this._scrollToBottom());
        requestAnimationFrame(() => this._scrollToBottom && this._scrollToBottom());

        // Sau khi ảnh load xong (card sản phẩm), scroll lại
        $msg.find("img").on("load", () => this._scrollToBottom());
    },


    _addUserText(text) {
        this._addMessageHtml(escape(text), "user");
    },
    _addBotText(text) {
        // Convert Markdown cơ bản → HTML, sau đó xuống dòng
        const html = (text || "")
            .replace(/&/g, "&amp;")                // chống XSS nhẹ cho &, <, >
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")   // **đậm**
            .replace(/_(.+?)_/g, "<i>$1</i>")         // _nghiêng_
            .replace(/`(.+?)`/g, "<code>$1</code>")   // `code`
            .replace(/\n/g, "<br/>");                 // xuống dòng
        this._addMessageHtml(html, "bot");
    },


    _addProductList(products) {
        // Danh sách card sản phẩm
        const cardsHtml = products
            .map((p) => this._renderProductCard(p))
            .join("");
        const container = `
      <div class="product-list">
        ${cardsHtml}
      </div>
    `;
        this._addMessageHtml(container, "bot");
    },

    _renderProductCard(p) {
        // Ảnh sản phẩm: ưu tiên ảnh product.product
        const imgUrl = `/web/image/product.product/${p.id}/image_128`;// fallback đủ nhanh; muốn nét hơn dùng image_512
        const code = escape(p.default_code || "");
        const name = escape(p.name || "");
        const uom = escape(p.uom || "");
        const price = Number(p.list_price || 0);
        const tmPrice = Number(p.commercial_price || 0);
        const byWh = p.by_warehouse || {};
        const whChips = Object.keys(byWh)
            .map((wh) => {
                const qty = byWh[wh];
                return `<span class="chip chip-warehouse">${escape(wh)}: ${qty}</span>`;
            })
            .join(" ");

        // Nhãn “Còn hàng / Sắp hết / Hết hàng”
        const total = Number(p.qty_available || 0);
        let stockLabel = `<span class="stock-badge badge-out">Hết hàng</span>`;
        if (total > 10) stockLabel = `<span class="stock-badge badge-in">Còn nhiều</span>`;
        else if (total > 0) stockLabel = `<span class="stock-badge badge-low">Sắp hết</span>`;

        return `
      <div class="product-card">
        <div class="pc-left">
          <img class="pc-image" src="${imgUrl}" alt="${name}" onerror="this.src='https://via.placeholder.com/96?text=No+Image';"/>
        </div>
        <div class="pc-right">
          <div class="pc-name">${name}</div>
          <div class="pc-code">Mã: <strong>${code || "—"}</strong></div>
          <div class="pc-stockline">
            ${stockLabel}
            <span class="pc-uom">Tổng tồn: ${total} ${uom}</span>
          </div>
          <div class="pc-wh">${whChips}</div>
          <div class="pc-price">
            <span class="price-retail">${price.toLocaleString()} VND</span>
            ${tmPrice && tmPrice !== price
                ? `<span class="price-commercial">TM: ${tmPrice.toLocaleString()} VND</span>`
                : ""
            }
          </div>
          <div class="pc-actions">
            <button class="btn-ghost" data-code="${code}">Hỏi thêm</button>
            <button class="btn-primary" data-code="${code}">Đặt mua</button>
          </div>
        </div>
      </div>
    `;
    },

    _addWebList(items) {
        const html = items
            .map(
                (w) => `
        <div class="web-item">
          <div class="web-title"><a href="${escape(w.link)}" target="_blank" rel="noopener">${escape(
                    w.title || "Kết quả"
                )}</a></div>
          <div class="web-price">${escape(w.price || "")}</div>
          <div class="web-description">${escape(w.description || "")}</div>
        </div>`
            )
            .join("");
        this._addMessageHtml(`<div class="web-results">${html}</div>`, "bot");
    },

    _setLoading(loading) {
        this.isLoading = loading;
        const sendBtn = this.$(".chatbot-send");
        const input = this.$(".chatbot-input");

        if (loading) {
            sendBtn.prop("disabled", true).text("...");
            input.prop("disabled", true);

            const dots = `
    <div class="chatbot-message bot-message typing-indicator">
      <div class="message-content">
        <div class="typing-dots"><span></span><span></span><span></span></div>
      </div>
      <div class="message-time">${new Date().toLocaleTimeString()}</div>
    </div>`;
            const $wrap = this._messagesEl().append(dots);
            this._scrollToBottom();
        } else {
            sendBtn.prop("disabled", false).text("Gửi");
            input.prop("disabled", false);
            this.$(".typing-indicator").last().remove();
        }

    },
});

publicWidget.registry.chatbot = ChatbotWidget;
export default ChatbotWidget;
