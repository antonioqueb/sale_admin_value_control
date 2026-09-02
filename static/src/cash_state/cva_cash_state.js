/** @odoo-module **/
/* Widgets del control administrativo sobre Entradas de Caja.
 *
 * cva_deposit_state: etiqueta de estatus (Pendiente / Parcial / Depositado)
 *   que se cambia con UN clic desde la lista, sin abrir el registro: al
 *   pulsar la etiqueta se despliegan las tres opciones y al elegir una se
 *   guarda de inmediato. En modo solo lectura es una etiqueta normal.
 * cva_m2m_links: pedidos ligados como enlaces que abren la orden de venta
 *   directamente desde la lista.
 *
 * Nombres propios (prefijo cva_) para no chocar con widgets de core/Enterprise. */
import { Component, useState, useRef, useExternalListener } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const STATE_CLASS = {
    pending: "o_cva_dstate_pending",
    partial: "o_cva_dstate_partial",
    deposited: "o_cva_dstate_deposited",
};

export class CvaDepositStateField extends Component {
    static template = "sale_admin_value_control.CvaDepositStateField";
    static props = { ...standardFieldProps };

    setup() {
        this.state = useState({ open: false });
        this.root = useRef("root");
        useExternalListener(window, "click", (ev) => {
            if (this.state.open && this.root.el && !this.root.el.contains(ev.target)) {
                this.state.open = false;
            }
        });
    }

    get options() {
        return this.props.record.fields[this.props.name].selection || [];
    }
    get value() {
        return this.props.record.data[this.props.name];
    }
    get label() {
        const opt = this.options.find((o) => o[0] === this.value);
        return opt ? opt[1] : "";
    }
    stateClass(value) {
        return STATE_CLASS[value] || "";
    }

    toggle(ev) {
        ev.stopPropagation();
        ev.preventDefault();
        if (this.props.readonly) {
            return;
        }
        this.state.open = !this.state.open;
    }

    async select(ev, value) {
        ev.stopPropagation();
        ev.preventDefault();
        this.state.open = false;
        if (value === this.value) {
            return;
        }
        // Guarda de inmediato aunque la fila de la lista no esté en edición
        // (mismo mecanismo que el interruptor boolean_toggle).
        await this.props.record.update({ [this.props.name]: value }, { save: true });
    }
}

registry.category("fields").add("cva_deposit_state", {
    component: CvaDepositStateField,
    supportedTypes: ["selection"],
});

export class CvaM2mLinksField extends Component {
    static template = "sale_admin_value_control.CvaM2mLinksField";
    static props = { ...standardFieldProps };

    setup() {
        this.action = useService("action");
    }

    get records() {
        const list = this.props.record.data[this.props.name];
        return list ? list.records : [];
    }

    open(ev, rec) {
        ev.stopPropagation();
        ev.preventDefault();
        if (!rec.resId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: this.props.record.fields[this.props.name].relation,
            res_id: rec.resId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("fields").add("cva_m2m_links", {
    component: CvaM2mLinksField,
    supportedTypes: ["many2many", "one2many"],
    relatedFields: [{ name: "display_name", type: "char" }],
});
