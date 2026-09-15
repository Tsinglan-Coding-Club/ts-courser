(function () {
    const form = document.getElementById('bulk-student-form');
    if (!form) return;
    const rows = document.getElementById('student-rows');
    const template = document.getElementById('empty-student-row');
    const total = document.getElementById('id_students-TOTAL_FORMS');
    const maximum = Number(document.getElementById('id_students-MAX_NUM_FORMS').value);
    const add = document.getElementById('add-student-row');
    const token = document.getElementById('preview-token');
    const create = document.getElementById('create-students');
    const status = document.getElementById('preview-status');

    function invalidatePreview() {
        token.value = '';
        if (create) create.disabled = true;
        rows.querySelectorAll('[data-username]').forEach(cell => { cell.textContent = '—'; });
        status.textContent = 'Preview the names again to see the assigned usernames.';
    }

    function renumber() {
        Array.from(rows.children).forEach((row, index) => {
            row.querySelector('[data-row-number]').textContent = index + 1;
            const input = row.querySelector('input');
            input.name = `students-${index}-display_name`;
            input.id = `id_students-${index}-display_name`;
            input.setAttribute('aria-label', `Student name, row ${index + 1}`);
            row.querySelector('[data-remove-row]').setAttribute('aria-label', `Remove student row ${index + 1}`);
        });
        total.value = rows.children.length;
        add.disabled = rows.children.length >= maximum;
    }

    function newRow() {
        return template.content.firstElementChild.cloneNode(true);
    }

    add.addEventListener('click', () => {
        if (rows.children.length >= maximum) return;
        const row = newRow();
        rows.append(row);
        renumber();
        invalidatePreview();
        row.querySelector('input').focus();
    });

    rows.addEventListener('click', event => {
        const button = event.target.closest('[data-remove-row]');
        if (!button) return;
        if (rows.children.length === 1) {
            rows.querySelector('input').value = '';
        } else {
            button.closest('tr').remove();
        }
        renumber();
        invalidatePreview();
    });

    rows.addEventListener('input', invalidatePreview);
    rows.addEventListener('paste', event => {
        if (!event.target.matches('input')) return;
        const names = event.clipboardData.getData('text').split(/\r\n|\r|\n/)
            .map(name => name.trim()).filter(Boolean);
        if (names.length < 2) return;
        event.preventDefault();
        if (rows.children.length + names.length - 1 > maximum) {
            status.textContent = `A batch can contain at most ${maximum} rows. Remove empty rows or paste fewer names.`;
            return;
        }
        event.target.value = names[0];
        let previous = event.target.closest('tr');
        names.slice(1).forEach(name => {
            const row = newRow();
            row.querySelector('input').value = name;
            previous.after(row);
            previous = row;
        });
        renumber();
        invalidatePreview();
    });

    let submitting = false;
    form.addEventListener('submit', event => {
        if (submitting) {
            event.preventDefault();
            return;
        }
        submitting = true;
        if (event.submitter?.value === 'create') {
            status.textContent = 'Creating student accounts… This may take a little time.';
        }
    });
    window.addEventListener('pageshow', () => { submitting = false; });
    renumber();
})();
