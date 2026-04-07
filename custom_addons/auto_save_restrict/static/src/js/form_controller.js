/** @odoo-module */
import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { SettingsConfirmationDialog } from "@web/webclient/settings_form_view/settings_confirmation_dialog";
import { onMounted, onWillUnmount } from "@odoo/owl";

patch(FormController.prototype, {
/* Patch FormController to restrict auto save in form views */
   setup(){
      super.setup(...arguments);
      this._hasPendingInput = false;
      onMounted(() => {
          this.__onFormInput = (ev) => {
              if (this.rootRef?.el?.contains(ev.target)) {
                  this._hasPendingInput = true;
              }
          };
          document.addEventListener('input', this.__onFormInput, true);
      });
      onWillUnmount(() => {
          document.removeEventListener('input', this.__onFormInput, true);
      });
   },

   async save(...args) {
       this._hasPendingInput = false;
       return super.save(...args);
   },

   async beforeLeave() {
        const dirty = await this.model.root.isDirty();
        if (dirty || this._hasPendingInput) {
            return this._confirmSave();
        }
    },

   beforeUnload(ev) {
        if (this.model.root.dirty || this._hasPendingInput) {
            ev.preventDefault();
            ev.returnValue = '';
        }
    },

   beforeVisibilityChange() {
        // Override: do NOT auto-save when tab loses focus / visibility changes.
        // Original Odoo behavior calls this.model.root.save() here,
        // which saves without user confirmation.
    },

   async _confirmSave() {
        let _continue = true;
        await new Promise((resolve) => {
            this.dialogService.add(SettingsConfirmationDialog, {
                body: _t("Would you like to save your changes?"),
                confirm: async () => {
                    await this.save();
                    _continue = true;
                    resolve();
                },
                cancel: async () => {
                    await this.model.root.discard();
                    await this.model.root.save();
                    _continue = true;
                    resolve();
                },
                stayHere: () => {
                    _continue = false;
                    resolve();
                },
            });
        });
        return _continue;
    }
});
