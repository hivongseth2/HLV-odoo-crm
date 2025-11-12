/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

const AISalesWidget = publicWidget.Widget.extend({
    template: 'ai_sales_support_18.ai_sales_widget',
    events: {
        'click .ai-sales-toggle-btn': '_onToggleWidget',
        'click .ai-sales-send': '_onSendMessage',
        'keypress .ai-sales-input': '_onKeyPress',
        'click .ai-sales-close': '_onCloseWidget',
    },

    start: function () {
        this._super.apply(this, arguments);
        this._initializeWidget();
    },

    _initializeWidget: function () {
        this.isOpen = false;
        this.isLoading = false;
        this._checkAIStatus();
    },

    _checkAIStatus: function () {
        const self = this;
        $.ajax({
            url: '/ai_sales/status',
            type: 'POST',
            dataType: 'json',
            contentType: 'application/json',
            data: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                params: {}
            }),
            success: function (result) {
                if (result.result && result.result.enabled) {
                    self.$el.show();
                } else {
                    self.$el.hide();
                }
            },
            error: function (error) {
                console.error('Error checking AI status:', error);
                self.$el.hide();
            }
        });
    },

    _onToggleWidget: function (ev) {
        ev.preventDefault();
        if (this.isOpen) {
            this._closeWidget();
        } else {
            this._openWidget();
        }
    },

    _openWidget: function () {
        this.isOpen = true;
        this.$('.ai-sales-container').addClass('ai-sales-open');
        this.$('.ai-sales-input').focus();
        
        // Add welcome message if chat is empty
        if (this.$('.ai-sales-messages .ai-sales-message').length === 0) {
            this._addMessage('Xin chào! Tôi là AI Sales Assistant. Tôi có thể giúp bạn xử lý yêu cầu bán hàng, kiểm tra tồn kho và tạo báo giá. Bạn cần hỗ trợ gì?', 'bot');
        }
    },

    _closeWidget: function () {
        this.isOpen = false;
        this.$('.ai-sales-container').removeClass('ai-sales-open');
    },

    _onCloseWidget: function (ev) {
        ev.preventDefault();
        this._closeWidget();
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

        const input = this.$('.ai-sales-input');
        const message = input.val().trim();
        
        if (!message) return;

        // Add user message to chat
        this._addMessage(message, 'user');
        input.val('');

        // Show loading
        this._setLoading(true);

        // Send to backend
        const self = this;
        $.ajax({
            url: '/ai_sales/inquiry',
            type: 'POST',
            dataType: 'json',
            contentType: 'application/json',
            data: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                params: {
                    inquiry_text: message
                }
            }),
            success: function (result) {
                self._setLoading(false);
                if (result.result && result.result.success) {
                    self._addMessage(result.result.response, 'bot');
                    
                    // Add inquiry details if available
                    if (result.result.inquiry_id) {
                        const detailsHtml = `
                            <div class="ai-sales-inquiry-details mt-2">
                                <small class="text-muted">
                                    <strong>Mã yêu cầu:</strong> ${result.result.inquiry_id}<br/>
                                    <strong>Trạng thái:</strong> ${result.result.state}
                                </small>
                            </div>
                        `;
                        self.$('.ai-sales-messages .ai-sales-message').last()
                            .find('.ai-sales-message-content').append(detailsHtml);
                    }
                } else {
                    const errorMsg = result.result ? result.result.message : 'Đã có lỗi xảy ra khi xử lý yêu cầu.';
                    self._addMessage(errorMsg, 'error');
                }
            },
            error: function (error) {
                self._setLoading(false);
                console.error('AI Sales error:', error);
                self._addMessage('Xin lỗi, không thể kết nối đến server. Vui lòng thử lại sau.', 'error');
            }
        });
    },

    _addMessage: function (text, type) {
        const messagesContainer = this.$('.ai-sales-messages');
        const messageHtml = `
            <div class="ai-sales-message ${type}">
                <div class="ai-sales-message-content">${text}</div>
                <div class="ai-sales-message-time">${new Date().toLocaleTimeString()}</div>
            </div>
        `;
        messagesContainer.append(messageHtml);
        messagesContainer.scrollTop(messagesContainer[0].scrollHeight);
    },

    _setLoading: function (loading) {
        this.isLoading = loading;
        const sendBtn = this.$('.ai-sales-send');
        const input = this.$('.ai-sales-input');
        
        if (loading) {
            sendBtn.prop('disabled', true);
            sendBtn.find('i').removeClass('fa-paper-plane').addClass('fa-spinner fa-spin');
            input.prop('disabled', true);
            this._addMessage('Đang xử lý yêu cầu...', 'loading');
        } else {
            sendBtn.prop('disabled', false);
            sendBtn.find('i').removeClass('fa-spinner fa-spin').addClass('fa-paper-plane');
            input.prop('disabled', false);
            // Remove loading message
            this.$('.ai-sales-message.loading').last().remove();
        }
    },
});

// AI Sales Test Page Widget
const AISalesTestWidget = publicWidget.Widget.extend({
    selector: '#ai-sales-form',
    events: {
        'submit': '_onSubmitForm',
        'click #create-quotation-btn': '_onCreateQuotation',
        'click #refresh-inquiries': '_onRefreshInquiries',
        'click .inquiry-item': '_onViewInquiry',
    },

    start: function () {
        this._super.apply(this, arguments);
        this._loadCustomers();
        this._loadRecentInquiries();
    },

    _loadCustomers: function () {
        // Load customers for the select dropdown
        // This would typically call an endpoint to get customer list
        const customerSelect = this.$('#customer_select');
        customerSelect.append('<option value="1">Demo Customer</option>');
    },

    _loadRecentInquiries: function () {
        const self = this;
        $.ajax({
            url: '/ai_sales/inquiries',
            type: 'POST',
            dataType: 'json',
            contentType: 'application/json',
            data: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                params: {
                    limit: 10
                }
            }),
            success: function (result) {
                if (result.result && result.result.success) {
                    self._renderInquiries(result.result.inquiries);
                } else {
                    self.$('#recent-inquiries').html('<div class="text-muted">No inquiries found</div>');
                }
            },
            error: function (error) {
                console.error('Error loading inquiries:', error);
                self.$('#recent-inquiries').html('<div class="text-danger">Error loading inquiries</div>');
            }
        });
    },

    _renderInquiries: function (inquiries) {
        const container = this.$('#recent-inquiries');
        container.empty();
        
        if (inquiries.length === 0) {
            container.html('<div class="text-muted">No inquiries found</div>');
            return;
        }
        
        inquiries.forEach(function (inquiry) {
            const statusClass = inquiry.state.replace('_', '-');
            const statusText = inquiry.state.replace('_', ' ').toUpperCase();
            const amount = inquiry.total_amount ? `${inquiry.total_amount.toLocaleString()} VND` : 'N/A';
            
            const inquiryHtml = `
                <div class="inquiry-item" data-inquiry-id="${inquiry.id}">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <strong>${inquiry.reference}</strong>
                            <span class="inquiry-status ${statusClass} ms-2">${statusText}</span>
                        </div>
                        <small class="text-muted">${new Date(inquiry.create_date).toLocaleDateString()}</small>
                    </div>
                    <div class="mt-2">
                        <div class="text-truncate">${inquiry.inquiry_text}</div>
                        <div class="mt-1">
                            <small class="text-muted">
                                Amount: <strong>${amount}</strong> | 
                                Duration: ${inquiry.processing_duration || 0} min
                            </small>
                        </div>
                    </div>
                </div>
            `;
            container.append(inquiryHtml);
        });
    },

    _onSubmitForm: function (ev) {
        ev.preventDefault();
        
        const inquiryText = this.$('#inquiry_text').val().trim();
        const customerId = this.$('#customer_select').val();
        
        if (!inquiryText) {
            alert('Please enter your inquiry text');
            return;
        }
        
        this._submitInquiry(inquiryText, customerId);
    },

    _submitInquiry: function (inquiryText, customerId) {
        const self = this;
        const submitBtn = this.$('#submit-btn');
        
        // Show loading state
        submitBtn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin me-2"></i>Processing...');
        this.$('#result-section, #error-section').hide();
        
        $.ajax({
            url: '/ai_sales/inquiry',
            type: 'POST',
            dataType: 'json',
            contentType: 'application/json',
            data: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                params: {
                    inquiry_text: inquiryText,
                    customer_id: customerId || null
                }
            }),
            success: function (result) {
                submitBtn.prop('disabled', false).html('<i class="fa fa-paper-plane me-2"></i>Process Inquiry');
                
                if (result.result && result.result.success) {
                    self._showResult(result.result);
                    self._loadRecentInquiries(); // Refresh the list
                } else {
                    const errorMsg = result.result ? result.result.message : 'Unknown error occurred';
                    self._showError(errorMsg);
                }
            },
            error: function (error) {
                submitBtn.prop('disabled', false).html('<i class="fa fa-paper-plane me-2"></i>Process Inquiry');
                console.error('Error submitting inquiry:', error);
                self._showError('Network error. Please try again.');
            }
        });
    },

    _showResult: function (result) {
        this.$('#ai-response').html(result.response.replace(/\n/g, '<br>'));
        this.$('#inquiry-ref').text(result.inquiry_id || 'N/A');
        this.$('#inquiry-status').text(result.state || 'Unknown').removeClass().addClass('badge inquiry-status ' + (result.state || '').replace('_', '-'));
        this.$('#inquiry-total').text('N/A'); // Will be updated when we get the full details
        this.$('#processing-time').text('Processing...');
        this.$('#inventory-sufficient').text('Checking...');
        
        // Set up buttons
        if (result.inquiry_id) {
            this.$('#view-inquiry-btn').attr('href', `/web#id=${result.inquiry_id}&model=ai.sales.inquiry&view_type=form`);
            this.currentInquiryId = result.inquiry_id;
        }
        
        this.$('#result-section').show();
        this.$('#error-section').hide();
    },

    _showError: function (errorMsg) {
        this.$('#error-message').text(errorMsg);
        this.$('#error-section').show();
        this.$('#result-section').hide();
    },

    _onCreateQuotation: function (ev) {
        ev.preventDefault();
        
        if (!this.currentInquiryId) {
            alert('No inquiry selected');
            return;
        }
        
        const customerId = this.$('#customer_select').val();
        if (!customerId) {
            alert('Please select a customer to create quotation');
            return;
        }
        
        const self = this;
        $.ajax({
            url: '/ai_sales/create_quotation',
            type: 'POST',
            dataType: 'json',
            contentType: 'application/json',
            data: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                params: {
                    inquiry_id: this.currentInquiryId,
                    customer_id: customerId
                }
            }),
            success: function (result) {
                if (result.result && result.result.success) {
                    alert('Quotation created successfully: ' + result.result.quotation_name);
                    window.open(`/web#id=${result.result.quotation_id}&model=sale.order&view_type=form`, '_blank');
                } else {
                    alert('Error creating quotation: ' + (result.result ? result.result.error : 'Unknown error'));
                }
            },
            error: function (error) {
                console.error('Error creating quotation:', error);
                alert('Network error creating quotation');
            }
        });
    },

    _onRefreshInquiries: function (ev) {
        ev.preventDefault();
        this._loadRecentInquiries();
    },

    _onViewInquiry: function (ev) {
        const inquiryId = $(ev.currentTarget).data('inquiry-id');
        if (inquiryId) {
            window.open(`/web#id=${inquiryId}&model=ai.sales.inquiry&view_type=form`, '_blank');
        }
    },
});

// Register widgets
publicWidget.registry.ai_sales_widget = AISalesWidget;
publicWidget.registry.ai_sales_test = AISalesTestWidget;

export { AISalesWidget, AISalesTestWidget };