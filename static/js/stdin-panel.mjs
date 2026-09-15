/** A page-local input() prompt. It stays visible beside the student's output. */
export class StdinPanel {
    constructor(container) {
        const document = container.ownerDocument;
        this.form = document.createElement('form');
        this.form.className = 'stdin-panel';
        this.form.hidden = true;

        this.label = document.createElement('label');
        this.label.className = 'stdin-prompt';
        this.promptText = document.createElement('span');
        this.promptText.setAttribute('aria-live', 'polite');
        this.input = document.createElement('input');
        this.input.type = 'text';
        this.input.autocomplete = 'off';
        this.input.spellcheck = false;
        this.input.className = 'stdin-field';
        this.label.append(this.promptText, this.input);

        const actions = document.createElement('div');
        actions.className = 'stdin-actions';
        const submit = document.createElement('button');
        submit.type = 'submit';
        submit.textContent = 'Send';
        const cancel = document.createElement('button');
        cancel.type = 'button';
        cancel.textContent = 'Cancel input';
        cancel.addEventListener('click', () => this.request?.cancel());
        actions.append(submit, cancel);

        const directions = document.createElement('details');
        directions.className = 'stdin-directions';
        const summary = document.createElement('summary');
        summary.textContent = 'W/A/S/D controls';
        const pad = document.createElement('div');
        pad.className = 'stdin-direction-buttons';
        for (const [value, text] of [['w', '↑ W'], ['a', '← A'], ['s', '↓ S'], ['d', '→ D']]) {
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = text;
            button.setAttribute('aria-label', `Send ${value}`);
            button.addEventListener('click', () => this.submit(value));
            pad.append(button);
        }
        directions.append(summary, pad);
        this.error = document.createElement('div');
        this.error.className = 'stdin-error';
        this.error.setAttribute('role', 'alert');
        this.form.append(this.label, actions, directions, this.error);
        this.form.addEventListener('submit', event => {
            event.preventDefault();
            this.submit(this.input.value);
        });
        container.append(this.form);
    }

    show(request) {
        this.request = request;
        this.promptText.textContent = request.prompt || 'Python is waiting for input';
        this.input.value = '';
        this.error.textContent = '';
        this.form.hidden = false;
        this.input.focus();
    }

    submit(value) {
        if (!this.request) return;
        const result = this.request.submit(value);
        if (!result.ok) this.error.textContent = result.error;
    }

    close() {
        this.request = null;
        this.form.hidden = true;
        this.error.textContent = '';
    }
}
