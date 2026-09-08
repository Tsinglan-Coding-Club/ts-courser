// Keep a native keyboard-accessible selection list while filtering by name.
(function () {
    const search = document.getElementById('teacherSearch');
    const select = document.getElementById('teacherSelect');
    const status = document.getElementById('teacherSearchStatus');
    if (!search || !select || !status) return;

    const placeholder = select.options[0];
    const teachers = Array.from(select.options).slice(1);
    let selectedUsername = select.value;
    select.addEventListener('change', () => {
        selectedUsername = select.value;
    });
    search.addEventListener('input', () => {
        const query = search.value.trim().toLocaleLowerCase();
        const matches = teachers.filter(option =>
            option.textContent.toLocaleLowerCase().includes(query)
        );
        select.replaceChildren(placeholder, ...matches);
        // Never silently select the first match as the search changes.
        select.value = matches.some(option => option.value === selectedUsername)
            ? selectedUsername : '';
        status.textContent = matches.length ? matches.length + ' teachers' : 'No teachers found.';
    });
})();
