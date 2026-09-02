/** @odoo-module **/
/* Indicador y toggle VISTA OPERATIVA / VISTA ADMINISTRATIVA en la barra superior.
 * Sólo aparece para el grupo Control de Valor Administrativo / Administrador.
 * Encendida = todo el sistema se presenta con el ajuste administrativo. */
import { Component, xml, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { session } from "@web/session";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";

export class CvaLensSystray extends Component {
    static template = xml`
        <button class="o_cva_lens_systray" t-att-class="{ o_cva_on: state.on }"
                t-on-click="toggle" t-att-title="tooltip">
            <span class="o_cva_dot"/>
            <span class="o_cva_label" t-esc="label"/>
        </button>`;
    static props = {};

    setup() {
        this.orm = useService("orm");
        const info = session.cva_lens || {};
        this.state = useState({ on: Boolean(info.on), busy: false });
    }

    get label() {
        return this.state.on ? "VISTA ADMINISTRATIVA" : "VISTA OPERATIVA";
    }

    get tooltip() {
        return this.state.on
            ? "Vista administrativa: los importes llevan el ajuste aplicado. Haz clic para cambiar a la vista operativa."
            : "Vista operativa: importes registrados. Haz clic para cambiar a la vista administrativa.";
    }

    async toggle() {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            await this.orm.call("res.users", "action_cva_toggle_lens", []);
            browser.location.reload();
        } catch (e) {
            this.state.busy = false;
            throw e;
        }
    }
}

const info = session.cva_lens;
if (info && info.available) {
    registry.category("systray").add(
        "sale_admin_value_control.cva_lens",
        { Component: CvaLensSystray },
        { sequence: 1 }
    );
}
