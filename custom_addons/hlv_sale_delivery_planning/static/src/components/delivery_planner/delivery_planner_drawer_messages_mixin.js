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
        this.loadDrawerMentionAliases();
        this.loadDrawerMessages(so.id);
    }

    async loadDrawerMentionAliases() {
        if (this.state.drawerMentionAliases && this.state.drawerMentionAliases.length) {
            return;
        }
        try {
            const aliases = await this.orm.call(
                'hlv.delivery.planner.service', 'get_sale_plan_mention_aliases', []
            );
            this.state.drawerMentionAliases = aliases || [];
        } catch (e) {
            console.warn('loadDrawerMentionAliases failed', e);
            this.state.drawerMentionAliases = [];
        }
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

    async sendDrawerMessage() {
        const body = (this.state.drawerMessageText || '').trim();
        const attachments = this.state.drawerMessageFiles.map((file) => ({
            name: file.name,
            mimetype: file.mimetype,
            datas: file.datas,
        }));
        if ((!body && !attachments.length) || !this.state.selectedOrder || this.state.drawerMessageSending) return;

        try {
            this.state.drawerMessageSending = true;
            await this.orm.call(
                'hlv.delivery.planner.service', 'post_order_message',
                [this.state.selectedOrder.id, body, attachments]
            );
            this.state.drawerMessageText = '';
            this.state.drawerMessageFiles = [];
            this.state.drawerMentionSuggestions = [];
            await this.loadDrawerMessages(this.state.selectedOrder.id);
        } catch (e) {
            console.error('sendDrawerMessage error', e);
        } finally {
            this.state.drawerMessageSending = false;
        }
    }

    onDrawerMessageInput(ev) {
        this.state.drawerMessageText = ev.target.value;
        this.updateDrawerMentionSuggestions(ev.target);
    }

    _normalizeMentionAlias(value) {
        return String(value || '').trim().toLowerCase().replace(/^@+/, '').replace(/\s+/g, '');
    }

    _currentMentionQuery(input) {
        const value = input ? input.value || '' : this.state.drawerMessageText || '';
        const pos = input && typeof input.selectionStart === 'number' ? input.selectionStart : value.length;
        const before = value.slice(0, pos);
        const match = /(^|\s)@([A-Za-z0-9_.-]*)$/.exec(before);
        if (!match) return null;
        return { start: pos - match[2].length - 1, term: (match[2] || '').toLowerCase(), pos };
    }

    updateDrawerMentionSuggestions(input) {
        const query = this._currentMentionQuery(input);
        if (!query) {
            this.state.drawerMentionSuggestions = [];
            this.state.drawerMentionActiveIndex = 0;
            return;
        }
        const aliases = this.state.drawerMentionAliases || [];
        const items = aliases.filter((item) => {
            const alias = String(item.alias || '').toLowerCase();
            const user = String(item.user_name || '').toLowerCase();
            return !query.term || alias.startsWith(query.term) || user.includes(query.term);
        }).slice(0, 8);
        this.state.drawerMentionSuggestions = items;
        this.state.drawerMentionActiveIndex = Math.min(this.state.drawerMentionActiveIndex || 0, Math.max(items.length - 1, 0));
    }

    selectDrawerMentionAlias(alias) {
        const input = document.getElementById('drawer-message-textarea');
        const query = this._currentMentionQuery(input);
        if (!query || !alias) return;
        const value = input ? input.value || '' : this.state.drawerMessageText || '';
        const next = `${value.slice(0, query.start)}@${alias} ${value.slice(query.pos)}`;
        this.state.drawerMessageText = next;
        this.state.drawerMentionSuggestions = [];
        setTimeout(() => {
            const nextInput = document.getElementById('drawer-message-textarea');
            if (nextInput) {
                const caret = query.start + alias.length + 2;
                nextInput.focus();
                nextInput.setSelectionRange(caret, caret);
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
                if (item) this.selectDrawerMentionAlias(item.alias);
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
