/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

const ChatbotWidget = publicWidget.Widget.extend({
    // 👉 BẮT BUỘC: selector để auto-mount
    selector: '.chatbot-widget',

    // (tuỳ chọn) không cần 'template' nếu đã render bằng t-call trong XML
    // template: 'website_public_inventory_18.chatbot_widget',

    events: {
        'click .chatbot-toggle': '_onToggleChatbot',
        'click .chatbot-send': '_onSendMessage',
        'keypress .chatbot-input': '_onKeyPress',
        'click .chatbot-close': '_onCloseChatbot',
        // nếu muốn xài nút minimize thì thêm handler:
        'click .chatbot-minimize': '_onMinimize',
    },

    start() {
        this._super(...arguments);
        this._initializeChatbot();
    },

    _initializeChatbot() {
        this.isOpen = false;
        this.isLoading = false;
        this._checkChatbotStatus();
    },

    _checkChatbotStatus() {
        const self = this;
        $.ajax({
            url: '/chatbot/status',
            type: 'GET',
            dataType: 'json',
            success(result) {
                if (result.enabled) self.$el.show();
                else self.$el.hide();
            },
            error(err) {
                console.error('Error checking chatbot status:', err);
                // tuỳ bạn: ẩn khi lỗi hay vẫn hiển thị để test local
                self.$el.show(); // 👈 trong lúc dev nên để show để test giao diện
            }
        });
    },

    _onToggleChatbot(ev) {
        ev.preventDefault();
        this.isOpen ? this._closeChatbot() : this._openChatbot();
    },

    _openChatbot() {
        this.isOpen = true;
        this.$('.chatbot-container').addClass('chatbot-open');
        this.$('.chatbot-input').focus();

        if (this.$('.chatbot-messages .message').length === 0) {
            this._addMessage(
                'Xin chào! Tôi có thể giúp bạn tìm kiếm sản phẩm và kiểm tra tồn kho. Bạn cần hỗ trợ gì?',
                'bot'
            );
        }
    },

    _closeChatbot() {
        this.isOpen = false;
        this.$('.chatbot-container').removeClass('chatbot-open');
    },

    _onCloseChatbot(ev) {
        ev.preventDefault();
        this._closeChatbot();
    },

    _onMinimize(ev) {
        ev.preventDefault();
        this.$('.chatbot-container').toggleClass('chatbot-minimized');
    },

    _onKeyPress(ev) {
        if (ev.which === 13 && !ev.shiftKey) {
            ev.preventDefault();
            this._sendMessage();
        }
    },

    _onSendMessage(ev) {
        ev.preventDefault();
        this._sendMessage();
    },

    _sendMessage() {
        if (this.isLoading) return;

        const input = this.$('.chatbot-input');
        const message = (input.val() || '').trim();
        if (!message) return;

        this._addMessage(message, 'user');
        input.val('');
        this._setLoading(true);

        const self = this;
        $.ajax({
            url: '/chatbot/message',
            type: 'POST',
            dataType: 'json',
            data: {
                message: message,
                csrf_token: odoo.csrf_token
            },
            success(result) {
                self._setLoading(false);
                if (result.success) self._addMessage(result.response, 'bot');
                else self._addMessage('Xin lỗi, đã có lỗi xảy ra. Vui lòng thử lại sau.', 'bot error');
            },
            error(err) {
                self._setLoading(false);
                console.error('Chatbot error:', err);
                self._addMessage('Xin lỗi, không thể kết nối đến server. Vui lòng thử lại sau.', 'bot error');
            }
        });
    },

    _addMessage(text, type) {
        const messagesContainer = this.$('.chatbot-messages');
        const messageHtml = `
            <div class="message ${type}${type.includes('loading') ? ' loading' : ''}">
                <div class="message-content">${_.escape(text)}</div>
                <div class="message-time">${new Date().toLocaleTimeString()}</div>
            </div>`;
        messagesContainer.append(messageHtml);
        messagesContainer.scrollTop(messagesContainer[0].scrollHeight);
    },

    _setLoading(loading) {
        this.isLoading = loading;
        const sendBtn = this.$('.chatbot-send');
        const input = this.$('.chatbot-input');

        if (loading) {
            sendBtn.prop('disabled', true).text('...');
            input.prop('disabled', true);
            this._addMessage('Đang xử lý...', 'bot loading');
        } else {
            sendBtn.prop('disabled', false).text('Gửi');
            input.prop('disabled', false);
            this.$('.message.loading').last().remove();
        }
    },
});

publicWidget.registry.chatbot = ChatbotWidget;
export default ChatbotWidget;
