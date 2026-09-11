/** @odoo-module **/
// Purpose: Delivery planner mixin for overview drawer messages, attachments, and package modal helpers.

import { markup } from "@odoo/owl";

export class DeliveryPlannerDrawerMessagesMixin {
    openOverviewDrawer(so) {
        this.state.selectedOrder = so;
        this.state.isDrawerOpen = true;
        this.state.drawerMessages = [];
        this.state.drawerMessageText = '';
        this.state.drawerMessageFiles = [];
        this.state.drawerMentionSuggestions = [];
        this.state.drawerMentionActiveIndex = 0;
        this.loadDrawerMessages(so.id);
        this.loadDrawerMentionAliases();
    }

    async loadDrawerMessages(orderId) {
        this.state.drawerMessagesLoading = true;
        try {
            const result = await this.orm.call(
                'hlv.delivery.planner.service', 'get_order_messages',
                [orderId]
            );
            this.state.drawerMessages = (result || []).map(msg => {
                if (msg.body) {
                    msg.body = markup(msg.body);
                }
                return msg;
            });
        } catch (e) {
            console.error('loadDrawerMessages error', e);
            this.state.drawerMessages = [];
        }
        this.state.drawerMessagesLoading = false;
    }

    sendDrawerMessage() {
        const body = (this.state.drawerMessageText || '').trim();
        const files = [...this.state.drawerMessageFiles];
        const attachments = files.map((file) => ({
            name: file.name,
            mimetype: file.mimetype,
            datas: file.datas,
        }));
        if ((!body && !attachments.length) || !this.state.selectedOrder) return;

        if (!this._drawerMessageQueue) this._drawerMessageQueue = [];
        this._drawerMessageQueue.push({
            orderId: this.state.selectedOrder.id,
            body,
            files,
            attachments,
        });

        // Chỉ xóa payload vừa đưa vào queue. Người dùng có thể nhập và gửi
        // tin tiếp theo trong khi RPC trước vẫn đang chạy.
        this.state.drawerMessageText = '';
        this.state.drawerMessageFiles = [];
        this.state.drawerMentionSuggestions = [];
        void this._processDrawerMessageQueue();
    }

    async _processDrawerMessageQueue() {
        if (this._drawerMessageQueueRunning || !this._drawerMessageQueue?.length) return;

        this._drawerMessageQueueRunning = true;
        this.state.drawerMessageSending = true;
        const successfulOrderIds = new Set();
        const failedItems = [];

        try {
            while (this._drawerMessageQueue.length) {
                const item = this._drawerMessageQueue.shift();
                try {
                    await this.orm.call(
                        'hlv.delivery.planner.service', 'post_order_message',
                        [item.orderId, item.body, item.attachments]
                    );
                    successfulOrderIds.add(item.orderId);
                } catch (e) {
                    failedItems.push(item);
                    console.error('sendDrawerMessage error', e);
                    this.notification.add('Không gửi được tin nhắn. Nội dung đã được giữ lại.', { type: 'danger' });
                }
            }

            const currentOrderId = this.state.selectedOrder?.id;
            const currentFailures = failedItems.filter((item) => item.orderId === currentOrderId);
            if (currentFailures.length) {
                const failedBodies = currentFailures.map((item) => item.body).filter(Boolean);
                const currentBody = this.state.drawerMessageText || '';
                this.state.drawerMessageText = [...failedBodies, currentBody].filter(Boolean).join('\n');
                this.state.drawerMessageFiles = [
                    ...currentFailures.flatMap((item) => item.files),
                    ...this.state.drawerMessageFiles,
                ];
            }
            if (currentOrderId && successfulOrderIds.has(currentOrderId)) {
                await this.loadDrawerMessages(currentOrderId);
            }
        } finally {
            this.state.drawerMessageSending = false;
            this._drawerMessageQueueRunning = false;
            if (this._drawerMessageQueue?.length) void this._processDrawerMessageQueue();
        }
    }

    async loadDrawerMentionAliases() {
        try {
            const result = await this.orm.call(
                'hlv.delivery.planner.service', 'get_sale_plan_mention_aliases', []
            );
            this.state.drawerMentionAliases = result || [];
        } catch (e) {
            console.error('loadDrawerMentionAliases error', e);
            this.state.drawerMentionAliases = [];
        }
    }

    _normalizeMentionAlias(value) {
        return String(value || '').trim().toLowerCase().replace(/^@+/, '');
    }

    _currentMentionQuery(input) {
        if (!input) return null;
        const pos = input.selectionStart || 0;
        const before = String(input.value || '').slice(0, pos);
        const match = /(^|\s)@([^@,;:!?()\[\]{}<>]*)$/.exec(before);
        if (!match) return null;
        return { start: pos - match[2].length - 1, term: this._normalizeMentionAlias(match[2]), pos };
    }

    onDrawerMessageInput(ev) {
        this.state.drawerMessageText = ev.target.value;
        this.updateDrawerMentionSuggestions(ev.target);
    }

    updateDrawerMentionSuggestions(input) {
        const query = this._currentMentionQuery(input);
        if (!query) {
            this.state.drawerMentionSuggestions = [];
            this.state.drawerMentionActiveIndex = 0;
            return;
        }
        const items = (this.state.drawerMentionAliases || []).filter((item) => {
            const alias = this._normalizeMentionAlias(item.alias);
            const displayAlias = this._normalizeMentionAlias(item.display_alias);
            const name = this._normalizeMentionAlias(item.user_name);
            return !query.term || alias.startsWith(query.term) || displayAlias.startsWith(query.term) || name.includes(query.term);
        }).slice(0, 30);
        this.state.drawerMentionSuggestions = items;
        this.state.drawerMentionActiveIndex = Math.min(this.state.drawerMentionActiveIndex || 0, Math.max(items.length - 1, 0));
    }

    selectDrawerMentionAlias(alias) {
        const input = document.querySelector('.hlv-drawer-message-input');
        const query = this._currentMentionQuery(input);
        if (!query) return;
        const value = String(this.state.drawerMessageText || '');
        const next = value.slice(0, query.start) + '@' + alias + ' ' + value.slice(query.pos);
        const nextPos = query.start + alias.length + 2;
        this.state.drawerMessageText = next;
        this.state.drawerMentionSuggestions = [];
        this.state.drawerMentionActiveIndex = 0;
        setTimeout(() => {
            const nextInput = document.querySelector('.hlv-drawer-message-input');
            if (nextInput) {
                nextInput.focus();
                nextInput.setSelectionRange(nextPos, nextPos);
            }
        }, 0);
    }

    onMessageKeydown(ev) {
        const suggestions = this.state.drawerMentionSuggestions || [];
        if (suggestions.length) {
            if (ev.key === 'ArrowDown') {
                ev.preventDefault();
                this.state.drawerMentionActiveIndex = ((this.state.drawerMentionActiveIndex || 0) + 1) % suggestions.length;
                return;
            }
            if (ev.key === 'ArrowUp') {
                ev.preventDefault();
                this.state.drawerMentionActiveIndex = ((this.state.drawerMentionActiveIndex || 0) - 1 + suggestions.length) % suggestions.length;
                return;
            }
            if (ev.key === 'Enter' || ev.key === 'Tab') {
                ev.preventDefault();
                const item = suggestions[this.state.drawerMentionActiveIndex || 0];
                if (item) this.selectDrawerMentionAlias(item.display_alias || item.alias);
                return;
            }
        }
        if (ev.key === 'Enter' && !ev.shiftKey) {
            ev.preventDefault();
            this.sendDrawerMessage();
        }
    }

    async onDrawerMessagePaste(ev) {
        const items = ev.clipboardData && ev.clipboardData.items;
        if (!items) return;
        const imageItems = Array.from(items).filter(it => it.type.startsWith('image/'));
        if (!imageItems.length) return;
        ev.preventDefault();
        const maxFileSize = 20 * 1024 * 1024;
        const nextFiles = [...this.state.drawerMessageFiles];
        for (const item of imageItems) {
            const file = item.getAsFile();
            if (!file) continue;
            if (file.size > maxFileSize) {
                this.notification.add('Ảnh dán quá 20MB.', { type: 'warning' });
                continue;
            }
            const extMap = { 'image/png': '.png', 'image/jpeg': '.jpg', 'image/gif': '.gif', 'image/webp': '.webp', 'image/bmp': '.bmp' };
            const ext = extMap[file.type] || '.png';
            const name = `paste_${Date.now()}${ext}`;
            try {
                const datas = await this._readFileAsBase64(file);
                nextFiles.push({
                    uid: `${Date.now()}_${Math.random().toString(36).slice(2)}`,
                    name,
                    mimetype: file.type,
                    size: file.size || 0,
                    datas,
                });
            } catch (e) {
                this.notification.add('Không thể đọc ảnh dán.', { type: 'danger' });
            }
        }
        this.state.drawerMessageFiles = nextFiles;
    }

    triggerDrawerFilePicker() {
        const picker = document.getElementById('drawer-message-file-input');
        if (picker) {
            picker.click();
        }
    }

    async onDrawerFilesSelected(ev) {
        const picker = ev.target;
        const files = Array.from((picker && picker.files) || []);
        if (!files.length) {
            return;
        }

        const allowedExt = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv'];
        const maxFileSize = 20 * 1024 * 1024;
        const nextFiles = [...this.state.drawerMessageFiles];

        for (const file of files) {
            const lowerName = (file.name || '').toLowerCase();
            const ext = lowerName.includes('.') ? lowerName.slice(lowerName.lastIndexOf('.')) : '';
            const isImage = (file.type || '').startsWith('image/');
            const isVideo = (file.type || '').startsWith('video/');
            const isPdf = (file.type || '') === 'application/pdf' || ext === '.pdf';
            const isDoc = allowedExt.includes(ext);

            if (!isImage && !isVideo && !isDoc && !isPdf) {
                this.notification.add(`File ${file.name} không thuộc định dạng hỗ trợ.`, { type: 'warning' });
                continue;
            }
            if (file.size > maxFileSize) {
                this.notification.add(`File ${file.name} vượt quá 20MB.`, { type: 'warning' });
                continue;
            }

            try {
                const datas = await this._readFileAsBase64(file);
                nextFiles.push({
                    uid: `${Date.now()}_${Math.random().toString(36).slice(2)}`,
                    name: file.name,
                    mimetype: file.type || 'application/octet-stream',
                    size: file.size || 0,
                    datas,
                });
            } catch (readErr) {
                this.notification.add(`Không thể đọc file ${file.name}.`, { type: 'danger' });
                console.error('read file error', readErr);
            }
        }

        this.state.drawerMessageFiles = nextFiles;
        picker.value = '';
    }

    _readFileAsBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => {
                const result = String(reader.result || '');
                const commaIndex = result.indexOf(',');
                resolve(commaIndex >= 0 ? result.slice(commaIndex + 1) : result);
            };
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    removeDrawerMessageFile(uid) {
        this.state.drawerMessageFiles = this.state.drawerMessageFiles.filter((f) => f.uid !== uid);
    }

    formatFileSize(size) {
        const value = Number(size || 0);
        if (value >= 1024 * 1024) {
            return `${(value / (1024 * 1024)).toFixed(1)} MB`;
        }
        if (value >= 1024) {
            return `${Math.round(value / 1024)} KB`;
        }
        return `${value} B`;
    }

    isVideoAttachment(att) {
        return !!(att && att.mimetype && att.mimetype.indexOf('video/') === 0);
    }

    closeOverviewDrawer() {
        this.state.isDrawerOpen = false;
    }

    // --- Package Modal Actions
    openPackageDetails(pack) {
        this.state.selectedPackage = pack;
        this.state.isPackageModalOpen = true;
    }

    closePackageDetails() {
        this.state.isPackageModalOpen = false;
        this.state.selectedPackage = null;
    }

    // ── Transfer Modal ────────────────────────────────────────────────────
}
