/* Three receiver menus and their saved visibility checkboxes.
 * Use ordinary DOM nodes/textContent so receiver or owner labels are text,
 * never executable markup. All hardware actions go through HA select actions.
 */
class OnkyoChoiceCard extends HTMLElement {
  setConfig(config) {
    if (!Array.isArray(config.entities) || !config.entities.length) {
      throw new Error("Provide the Network Services, Input Selection and Listening Modes entities");
    }
    this.config = config;
    if (!this.shadowRoot) this.attachShadow({mode: "open"});
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
    this.render();
  }

  getCardSize() { return 5; }

  render() {
    if (!this.config || !this._hass) return;
    // Do not rebuild a focused/open menu on unrelated HA state changes.
    const states = this.config.entities.map(item => this._hass.states[item.entity]);
    const signature = JSON.stringify(states.map(state => state && [state.state, state.attributes]));
    if (signature === this.signature) return;
    this.signature = signature;
    const opened = new Set([...this.shadowRoot.querySelectorAll("details[open]")].map(node => node.dataset.entity));
    this.shadowRoot.replaceChildren();
    const style = document.createElement("style");
    style.textContent = `
      ha-card { padding:20px; color:var(--primary-text-color); }
      h2 { font-size:20px; font-weight:500; margin:0 0 16px; }
      .group { margin:0 0 20px; } .group:last-child { margin-bottom:0; }
      label.caption { display:block; font-weight:500; margin-bottom:6px; }
      select { box-sizing:border-box; width:100%; padding:12px; border-radius:6px;
        border:1px solid var(--divider-color); color:var(--primary-text-color);
        background:var(--card-background-color); font:inherit; }
      details { margin-top:10px; } summary { cursor:pointer; color:var(--primary-color); padding:6px 0; }
      .checks { max-height:250px; overflow:auto; padding:4px; }
      .check { display:flex; align-items:center; gap:9px; padding:7px 0; }
      input { width:18px; height:18px; accent-color:var(--primary-color); }
      .note { font-size:12px; color:var(--secondary-text-color); margin-top:8px; }
      .error { color:var(--error-color); white-space:pre-wrap; }
    `;
    this.shadowRoot.append(style);
    const card = document.createElement("ha-card");
    const title = document.createElement("h2");
    title.textContent = this.config.title || "Receiver Menus";
    card.append(title);
    this.config.entities.forEach((item, index) => {
      const group = document.createElement("div"); group.className = "group";
      const label = document.createElement("label"); label.className = "caption";
      label.textContent = item.name; label.htmlFor = `choice-${index}`;
      group.append(label);
      const state = states[index];
      if (!state) { const missing = document.createElement("p"); missing.textContent = "Entity unavailable"; group.append(missing); card.append(group); return; }
      const attr = state.attributes;
      const choices = attr.all_choices || {};
      const shown = new Set(attr.shown_choices || []);
      const select = document.createElement("select"); select.id = `choice-${index}`;
      select.disabled = state.state === "unavailable";
      const visible = Object.entries(choices).filter(([key]) => shown.has(key));
      // A hidden current choice remains readable without exposing it as a
      // selectable item. This never changes the receiver's current setting.
      if (!visible.some(([,name]) => name === state.state)) {
        const current = document.createElement("option"); current.value = "";
        current.textContent = ["unknown", "unavailable"].includes(state.state)
          ? "Choose…" : `${state.state} (hidden)`;
        current.disabled = true; current.selected = true; select.append(current);
      }
      visible.forEach(([,name]) => { const option = document.createElement("option");
        option.value = name; option.textContent = name; option.selected = name === state.state; select.append(option); });
      const error = document.createElement("p"); error.className = "error"; error.setAttribute("role", "alert");
      select.addEventListener("change", async () => {
        select.disabled = true;
        try { await this._hass.callService("select", "select_option", {entity_id:item.entity, option:select.value}); }
        catch (err) { error.textContent = err.message || String(err); }
        finally { select.disabled = false; }
      });
      group.append(select);
      const details = document.createElement("details"); details.dataset.entity = item.entity; details.open = opened.has(item.entity);
      const summary = document.createElement("summary"); summary.textContent = `Show ${item.name}`;
      details.append(summary);
      const checks = document.createElement("div"); checks.className = "checks";
      Object.entries(choices).forEach(([key,name]) => {
        const row = document.createElement("label"); row.className = "check";
        const box = document.createElement("input"); box.type = "checkbox"; box.checked = shown.has(key); box.value = key;
        box.addEventListener("change", async () => {
          const selected = [...checks.querySelectorAll("input:checked")].map(node => node.value);
          const boxes = [...checks.querySelectorAll("input")]; boxes.forEach(node => node.disabled = true);
          try { await this._hass.callService("onkyo_extended", "set_visibility", {
            entry_id:attr.config_entry_id, category:attr.visibility_category, choices:selected}); }
          catch (err) { box.checked = !box.checked; error.textContent = err.message || String(err); }
          finally { boxes.forEach(node => node.disabled = false); }
        });
        const text = document.createElement("span"); text.textContent = name; row.append(box,text); checks.append(row);
      });
      details.append(checks);
      const note = document.createElement("p"); note.className = "note";
      note.textContent = "Hidden choices remain available to scenes and scripts.";
      details.append(note); group.append(details,error); card.append(group);
    });
    this.shadowRoot.append(card);
  }
}
if (!customElements.get("onkyo-choice-card")) customElements.define("onkyo-choice-card", OnkyoChoiceCard);
window.customCards = window.customCards || [];
if (!window.customCards.some(card => card.type === "onkyo-choice-card")) {
  window.customCards.push({type:"onkyo-choice-card", name:"Onkyo Receiver Menus", description:"Inputs, network services, listening modes and saved visibility lists"});
}
