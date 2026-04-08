/** @odoo-module */
import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { onMounted, onWillUnmount } from "@odoo/owl";

patch(FormController.prototype, {

    setup() {
        super.setup(...arguments);
        this._formInDialog = false;
        this._leaveDecisionMade = false;
        this._userTyping = false;

        onMounted(() => {
            this._formInDialog = !!this.rootRef?.el?.closest(".o_dialog");

            if (!this._formInDialog) {
                // Track real user input inside form sheet
                this.__onUserInput = (ev) => {
                    if (!ev.isTrusted) return;
                    const sheet = this.rootRef?.el?.querySelector(".o_form_sheet, .o_form_sheet_bg");
                    if (sheet && sheet.contains(ev.target)) {
                        this._userTyping = true;
                    }
                };
                document.addEventListener("input", this.__onUserInput, true);

                // Watch for Odoo removing o_form_dirty (native save/discard)
                // When that happens, clear _userTyping too
                const formEl = this.rootRef?.el;
                if (formEl) {
                    this.__classObserver = new MutationObserver((mutations) => {
                        for (const m of mutations) {
                            if (m.attributeName === "class") {
                                if (!formEl.classList.contains("o_form_dirty")) {
                                    this._userTyping = false;
                                }
                            }
                        }
                    });
                    this.__classObserver.observe(formEl, { attributes: true, attributeFilter: ["class"] });
                }
            }
        });

        onWillUnmount(() => {
            if (this.__onUserInput) {
                document.removeEventListener("input", this.__onUserInput, true);
            }
            if (this.__classObserver) {
                this.__classObserver.disconnect();
            }
        });
    },

    async save(...args) {
        this._userTyping = false;
        return super.save(...args);
    },

    async beforeLeave() {
        if (this._formInDialog) {
            return;
        }
        if (this._leaveDecisionMade) {
            this._leaveDecisionMade = false;
            return;
        }
        const dirty = await this.model.root.isDirty();
        if (dirty) {
            return this._confirmSave();
        }
    },

    beforeUnload(ev) {
        if (this._formInDialog) {
            return;
        }
        const formEl = this.rootRef?.el;
        const cssDirty = formEl && formEl.classList.contains("o_form_dirty");
        if (cssDirty || this._userTyping) {
            ev.preventDefault();
            ev.returnValue = "";
        }
    },

    beforeVisibilityChange() {
        // do NOT auto-save when tab loses focus
    },

    async _confirmSave() {
        let _continue = true;
        await new Promise((resolve) => {
            let handled = false;
            this.dialogService.add(
                ConfirmationDialog,
                {
                    title: _t("Thay \u0111\u1ed5i ch\u01b0a \u0111\u01b0\u1ee3c l\u01b0u"),
                    body: _t("B\u1ea1n c\u00f3 mu\u1ed1n l\u01b0u c\u00e1c thay \u0111\u1ed5i c\u1ee7a m\u00ecnh kh\u00f4ng?"),
                    confirmLabel: _t("L\u01b0u"),
                    confirm: async () => {
                        handled = true;
                        this._leaveDecisionMade = true;
                        this._userTyping = false;
                        await this.save();
                        _continue = true;
                        resolve();
                    },
                    cancelLabel: _t("Hu\u1ef7 b\u1ecf"),
                    cancel: async () => {
                        handled = true;
                        this._leaveDecisionMade = true;
                        this._userTyping = false;
                        await this.model.root.discard();
                        _continue = true;
                        resolve();
                    },
                },
                {
                    onClose: () => {
                        if (!handled) {
                            _continue = false;
                            resolve();
                        }
                    },
                }
            );
        });
        return _continue;
    },
});
