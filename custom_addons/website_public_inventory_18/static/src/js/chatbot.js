/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

const ChatbotWidget = publicWidget.Widget.extend({
        template: 'website_public_inventory_18.chatbot_widget',
        events: {
            'click .chatbot-toggle': '_onToggleChatbot',
            'click .chatbot-send': '_onSendMessage',
            'keypress .chatbot-input': '_onKeyPress',
            'click .chatbot-close': '_onCloseChatbot',
        },

        start: function () {
            this._super.apply(this, arguments);
            this._initializeChatbot();
        },

        _initializeChatbot: function () {
            this.isOpen = false;
            this.isLoading = false;
            this._checkChatbotStatus();
        },

        _checkChatbotStatus: function () {
            const self = this;
            $.ajax({
                url: '/chatbot/status',
                type: 'GET',
                dataType: 'json',
                success: function (result) {
                    if (result.enabled) {
                        self.$el.show();
                    } else {
                        self.$el.hide();
                    }
                },
                error: function (error) {
                    console.error('Error checking chatbot status:', error);
                    self.$el.hide();
                }
            });
        },

        _onToggleChatbot: function (ev) {
            ev.preventDefault();
            if (this.isOpen) {
                this._closeChatbot();
            } else {
                this._openChatbot();
            }
        },

        _openChatbot: function () {
            this.isOpen = true;
            this.$('.chatbot-container').addClass('chatbot-open');
            this.$('.chatbot-input').focus();
            
            // Add welcome message if chat is empty
            if (this.$('.chatbot-messages .message').length === 0) {
                this._addMessage('Xin chào! Tôi có thể giúp bạn tìm kiếm sản phẩm và kiểm tra tồn kho. Bạn cần hỗ trợ gì?', 'bot');
            }
        },

        _closeChatbot: function () {
            this.isOpen = false;
            this.$('.chatbot-container').removeClass('chatbot-open');
        },

        _onCloseChatbot: function (ev) {
            ev.preventDefault();
            this._closeChatbot();
        },

        _onKeyPress: function (ev) {
            if (ev.which === 13 && !ev.shiftKey) { // Enter key
                ev.preventDefault();
                this._sendMessage();
            }
        },

        _onSendMessage: function (ev) {
            ev.preventDefault();
            this._sendMessage();
        },

        _sendMessage: function () {
            if (this.isLoading) return;

            const input = this.$('.chatbot-input');
            const message = input.val().trim();
            
            if (!message) return;

            // Add user message to chat
            this._addMessage(message, 'user');
            input.val('');

            // Show loading
            this._setLoading(true);

            // Send to backend using simple AJAX
            const self = this;
            $.ajax({
                url: '/chatbot/message',
                type: 'POST',
                dataType: 'json',
                data: {
                    message: message,
                    csrf_token: odoo.csrf_token
                },
                success: function (result) {
                    self._setLoading(false);
                    if (result.success) {
                        self._addMessage(result.response, 'bot');
                    } else {
                        self._addMessage('Xin lỗi, đã có lỗi xảy ra. Vui lòng thử lại sau.', 'bot error');
                    }
                },
                error: function (error) {
                    self._setLoading(false);
                    console.error('Chatbot error:', error);
                    self._addMessage('Xin lỗi, không thể kết nối đến server. Vui lòng thử lại sau.', 'bot error');
                }
            });
        },

        _addMessage: function (text, type) {
            const messagesContainer = this.$('.chatbot-messages');
            const messageHtml = `
                <div class="message ${type}">
                    <div class="message-content">${text}</div>
                    <div class="message-time">${new Date().toLocaleTimeString()}</div>
                </div>
            `;
            messagesContainer.append(messageHtml);
            messagesContainer.scrollTop(messagesContainer[0].scrollHeight);
        },

        _setLoading: function (loading) {
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
                // Remove loading message
                this.$('.message.loading').last().remove();
            }
        },
    });

publicWidget.registry.chatbot = ChatbotWidget;

export default ChatbotWidget;