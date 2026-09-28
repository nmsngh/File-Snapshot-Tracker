// AI assistance disclosure:
// ChatGPT was used as a learning aid for explanation, debugging, and review.
// The author adapted, tested, and verified the final implementation.


document.addEventListener("DOMContentLoaded", () => {
    const searchInput = document.querySelector("#change-search");
    const statusFilter = document.querySelector("#status-filter");
    const rows = document.querySelectorAll("[data-change-row]");
    const result = document.querySelector("#filter-result");

    if (!searchInput || !statusFilter || !rows.length) {
        return;
    }

    function applyFilters() {
        const searchTerm = searchInput.value.toLowerCase().trim();
        const selectedStatus = statusFilter.value;
        let visibleCount = 0;

        rows.forEach((row) => {
            const path = row.dataset.path.toLowerCase();
            const status = row.dataset.status;

            const matchesSearch = path.includes(searchTerm);
            const matchesStatus =
                selectedStatus === "all" || status === selectedStatus;

            const isVisible = matchesSearch && matchesStatus;

            row.hidden = !isVisible;

            if (isVisible) {
                visibleCount += 1;
            }
        });

        result.textContent = `${visibleCount} change(s) shown`;
    }

    searchInput.addEventListener("input", applyFilters);
    statusFilter.addEventListener("change", applyFilters);

    applyFilters();
});