// Keep native keyboard-accessible selection lists while filtering their options.
(function () {
    function setupPicker(searchId, selectId, statusId, noun) {
        const search = document.getElementById(searchId);
        const select = document.getElementById(selectId);
        const status = document.getElementById(statusId);
        if (!search || !select || !status) return;

        const placeholder = select.options[0];
        const options = Array.from(select.options).slice(1);
        let selectedValue = select.value;
        select.addEventListener('change', () => {
            selectedValue = select.value;
        });
        search.addEventListener('input', () => {
            const query = search.value.trim().toLocaleLowerCase();
            const matches = options.filter(option =>
                option.textContent.toLocaleLowerCase().includes(query)
            );
            select.replaceChildren(placeholder, ...matches);
            // Never silently select the first match as the search changes.
            select.value = matches.some(option => option.value === selectedValue)
                ? selectedValue : '';
            status.textContent = matches.length
                ? `${matches.length} ${noun}${matches.length === 1 ? '' : 's'}`
                : `No ${noun}s found.`;
        });
    }

    setupPicker('teacherSearch', 'teacherSelect', 'teacherSearchStatus', 'teacher');
    setupPicker('studentSearch', 'studentToAdd', 'studentSearchStatus', 'student');
})();
