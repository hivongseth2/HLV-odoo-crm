/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { jsonrpc } from "@web/core/network/rpc_service";
import { _t } from "@web/core/l10n/translation";

const ChatbotWidget = publicWidget.Widget.extend({
    template: 'website_public_inventory_18.chatbot_widget',
    events: {
        'click .chatbot-toggle': '_onToggleChatbot',
        'click .chatbot-close': '_onCloseChatbot',
        'click .chatbot-send': '_onSendMessage',
        'keypress .chatbot-input': '_onKeyPress',
        'click .chatbot-minimize': '_onMinimizeChatbot',
    },

    init: function (parent, options) {
        this._super.apply(this, arguments);
        this.isOpen = false;
        this.isMinimized = false;
        this.messages = [];
        this.isLoading = false;
    },

    start: function () {
        var self = this;
        return this._super.apply(this, arguments).then(function () {
            self._checkChatbotStatus();
            self._initializeChatbot();
        });
    },

    _checkChatbotStatus: function () {
        var self = this;
        return jsonrpc('/chatbot/status', {}).then(function (result) {
            if (!result.enabled || !result.configured) {
                self.$el.hide();
            } else {
                self.$el.show();
            }
        }).catch(function () {
            self.$el.hide();
        });
    },

    _initializeChatbot: function () {
        this._addMessage('bot', 'Xin chào! Tôi có thể giúp bạn tìm kiếm thông tin sản phẩm và tồn kho. Hãy cho tôi biết bạn đang tìm gì?');
    },

    _onToggleChatbot: function (ev) {
        ev.preventDefault();
        if (this.isOpen) {
            this._closeChatbot();
        } else {
            this._openChatbot();
        }
    },

    _onCloseChatbot: function (ev) {
        ev.preventDefault();
        this._closeChatbot();
    },

    _onMinimizeChatbot: function (ev) {
        ev.preventDefault();
        this.isMinimized = !this.isMinimized;
        this.$('.chatbot-body').toggle(!this.isMinimized);
        this.$('.chatbot-minimize i').toggleClass('fa-minus fa-plus');
    },

    _openChatbot: function () {
        this.isOpen = true;
        this.isMinimized = false;
        this.$('.chatbot-container').addClass('chatbot-open');
        this.$('.chatbot-toggle').hide();
        this.$('.chatbot-input').focus();
    },

    _closeChatbot: function () {
        this.isOpen = false;
        this.isMinimized = false;
        this.$('.chatbot-container').removeClass('chatbot-open');
        this.$('.chatbot-toggle').show();
    },

    _onKeyPress: function (ev) {
        if (ev.which === 13) { // Enter key
            ev.preventDefault();
            this._onSendMessage();
        }
    },

    _onSendMessage: function () {
        if (this.isLoading) return;

        var message = this.$('.chatbot-input').val().trim();
        if (!message) return;

        this._addMessage('user', message);
        this.$('.chatbot-input').val('');
        this._sendMessageToBot(message);
    },

    _addMessage: function (sender, text, data) {
        var messageHtml = '';
        var timestamp = new Date().toLocaleTimeString('vi-VN', {
            hour: '2-digit',
            minute: '2-digit'
        });

        if (sender === 'user') {
            messageHtml = `
                    <div class="chatbot-message user-message">
                        <div class="message-content">${this._escapeHtml(text)}</div>
                        <div class="message-time">${timestamp}</div>
                    </div>
                `;
        } else {
            messageHtml = `
                    <div class="chatbot-message bot-message">
                        <div class="message-content">${this._formatBotMessage(text, data)}</div>
                        <div class="message-time">${timestamp}</div>
                    </div>
                `;
        }

        this.$('.chatbot-messages').append(messageHtml);
        this._scrollToBottom();
    },

    _formatBotMessage: function (text, data) {
        var html = this._escapeHtml(text).replace(/\n/g, '<br>');

        // Add inventory results if available
        if (data && data.inventory_results && data.inventory_results.length > 0) {
            html += '<div class="inventory-results mt-2">';
            html += '<strong>Sản phẩm trong kho:</strong>';
            data.inventory_results.forEach(function (item) {
                html += `
                        <div class="product-item border rounded p-2 mt-1">
                            <div class="product-name font-weight-bold">${item.name}</div>
                            ${item.default_code ? `<div class="product-code text-muted">Mã: ${item.default_code}</div>` : ''}
                            <div class="product-stock">Tồn kho: <span class="badge badge-success">${item.qty_available} ${item.uom}</span></div>
                            <div class="product-price">Giá: <span class="text-primary">${item.list_price.toLocaleString('vi-VN')} VND</span></div>
                        </div>
                    `;
            });
            html += '</div>';
        }

        // Add web results if available
        if (data && data.web_results && data.web_results.length > 0) {
            html += '<div class="web-results mt-2">';
            html += '<strong>Kết quả tìm kiếm web:</strong>';
            data.web_results.forEach(function (item) {
                html += `
                        <div class="web-item border rounded p-2 mt-1">
                            <div class="web-title font-weight-bold">
                                <a href="${item.link}" target="_blank">${item.title}</a>
                            </div>
                            <div class="web-price text-success">${item.price}</div>
                            <div class="web-description text-muted">${item.description}</div>
                        </div>
                    `;
            });
            html += '</div>';
        }

        return html;
    },

    _sendMessageToBot: function (message) {
        var self = this;
        this.isLoading = true;
        this._showTypingIndicator();

        jsonrpc('/chatbot/message', {
            message: message
        }).then(function (result) {
            self._hideTypingIndicator();
            self.isLoading = false;

            if (result.success) {
                self._addMessage('bot', result.response, result);
            } else {
                self._addMessage('bot', 'Xin lỗi, đã có lỗi xảy ra: ' + (result.error || 'Unknown error'));
            }
        }).catch(function (error) {
            self._hideTypingIndicator();
            self.isLoading = false;
            self._addMessage('bot', 'Xin lỗi, không thể kết nối đến server. Vui lòng thử lại sau.');
            console.error('Chatbot error:', error);
        });
    },

    _showTypingIndicator: function () {
        var typingHtml = `
                <div class="chatbot-message bot-message typing-indicator">
                    <div class="message-content">
                        <div class="typing-dots">
                            <span></span>
                            <span></span>
                            <span></span>
                        </div>
                    </div>
                </div>
            `;
        this.$('.chatbot-messages').append(typingHtml);
        this._scrollToBottom();
    },

    _hideTypingIndicator: function () {
        this.$('.typing-indicator').remove();
    },
    _scrollToBottom() {
        const el = this._messagesEl()[0];
        if (!el) return;
        el.scrollTop = el.scrollHeight;
    },

    _escapeHtml: function (text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },
});

// Auto-initialize chatbot on pages with inventory
publicWidget.registry.chatbot = publicWidget.Widget.extend({
    selector: 'body',

    start: function () {
        var self = this;
        return this._super.apply(this, arguments).then(function () {
            // Only show chatbot on inventory pages
            if (window.location.pathname.includes('/search_stock') ||
                window.location.pathname.includes('/inventory')) {
                self._initChatbot();
            }
        });
    },

    _initChatbot: function () {
        var chatbot = new ChatbotWidget(this);
        chatbot.appendTo(this.$el);
    },
});

export default ChatbotWidget;