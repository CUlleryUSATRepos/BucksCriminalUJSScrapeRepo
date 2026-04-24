const CSV_URL = "./data/ujs_criminal_bucks.csv";

const state = {
  rawRows: [],
  filteredRows: [],
  sortKey: "FilingDate",
  sortDirection: "desc",
};

const elements = {
  rowsShown: document.getElementById("rowsShown"),
  uniqueDockets: document.getElementById("uniqueDockets"),
  latestFilingDate: document.getElementById("latestFilingDate"),
  lastUpdated: document.getElementById("lastUpdated"),
  tableStatus: document.getElementById("tableStatus"),
  tableBody: document.getElementById("tableBody"),
  searchInput: document.getElementById("searchInput"),
  eventTypeFilter: document.getElementById("eventTypeFilter"),
  filingDateFilter: document.getElementById("filingDateFilter"),
  resetFilters: document.getElementById("resetFilters"),
  sortButtons: document.querySelectorAll(".sort-btn"),
  themeToggle: document.querySelector("[data-theme-toggle]"),
};

function setupThemeToggle() {
  const root = document.documentElement;
  let theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  root.setAttribute("data-theme", theme);

  elements.themeToggle?.addEventListener("click", () => {
    theme = theme === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", theme);
  });
}

function cleanValue(value) {
  return (value ?? "").toString().trim();
}

function parseUsDate(value) {
  const raw = cleanValue(value);
  if (!raw) return null;

  const [datePart, timePart = ""] = raw.split(" ");
  const [month, day, year] = datePart.split("/").map(Number);
  if (!month || !day || !year) return null;

  let hours = 0;
  let minutes = 0;

  if (timePart) {
    const timeMatch = raw.match(/(\d{1,2}):(\d{2})\s*(AM|PM)/i);
    if (timeMatch) {
      hours = Number(timeMatch[1]);
      minutes = Number(timeMatch[2]);
      const meridiem = timeMatch[3].toUpperCase();

      if (meridiem === "PM" && hours !== 12) hours += 12;
      if (meridiem === "AM" && hours === 12) hours = 0;
    }
  }

  return new Date(year, month - 1, day, hours, minutes);
}

function formatDate(value, includeTime = false) {
  const date = parseUsDate(value);
  if (!date) return "—";

  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    ...(includeTime ? { hour: "numeric", minute: "2-digit" } : {}),
  }).format(date);
}

function formatTimestamp(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "Unavailable";

  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function compareValues(a, b, key, direction) {
  const multiplier = direction === "asc" ? 1 : -1;

  if (key === "FilingDate" || key === "EventDate") {
    const aDate = parseUsDate(a[key]);
    const bDate = parseUsDate(b[key]);
    const aTime = aDate ? aDate.getTime() : -Infinity;
    const bTime = bDate ? bDate.getTime() : -Infinity;
    return (aTime - bTime) * multiplier;
  }

  const aValue = cleanValue(a[key]).toLowerCase();
  const bValue = cleanValue(b[key]).toLowerCase();
  return aValue.localeCompare(bValue) * multiplier;
}

function populateFilters(rows) {
  const eventTypes = [...new Set(rows.map(row => cleanValue(row.EventType)).filter(Boolean))].sort();
  const filingDates = [...new Set(rows.map(row => cleanValue(row.FilingDate)).filter(Boolean))]
    .sort((a, b) => {
      const aTime = parseUsDate(a)?.getTime() ?? 0;
      const bTime = parseUsDate(b)?.getTime() ?? 0;
      return bTime - aTime;
    });

  elements.eventTypeFilter.innerHTML =
    `<option value="">All event types</option>` +
    eventTypes.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");

  elements.filingDateFilter.innerHTML =
    `<option value="">All filing dates</option>` +
    filingDates.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
}

function applyFilters() {
  const query = cleanValue(elements.searchInput.value).toLowerCase();
  const eventType = cleanValue(elements.eventTypeFilter.value);
  const filingDate = cleanValue(elements.filingDateFilter.value);

  const filtered = state.rawRows.filter(row => {
    const matchesSearch =
      !query ||
      [
        row.DocketNumber,
        row.CaseCaption,
        row.EventType,
        row.EventLocation,
        row.ComplaintNumber,
        row.IncidentNumber,
      ]
        .map(cleanValue)
        .join(" ")
        .toLowerCase()
        .includes(query);

    const matchesEventType = !eventType || cleanValue(row.EventType) === eventType;
    const matchesFilingDate = !filingDate || cleanValue(row.FilingDate) === filingDate;

    return matchesSearch && matchesEventType && matchesFilingDate;
  });

  filtered.sort((a, b) => compareValues(a, b, state.sortKey, state.sortDirection));
  state.filteredRows = filtered;

  updateSummary(filtered);
  renderTable(filtered);
}

function updateSummary(rows) {
  const uniqueDockets = new Set(rows.map(row => cleanValue(row.DocketNumber)).filter(Boolean)).size;

  const latestFiling = rows
    .map(row => parseUsDate(row.FilingDate))
    .filter(Boolean)
    .sort((a, b) => b - a)[0];

  elements.rowsShown.textContent = rows.length.toLocaleString("en-US");
  elements.uniqueDockets.textContent = uniqueDockets.toLocaleString("en-US");
  elements.latestFilingDate.textContent = latestFiling ? formatTimestamp(latestFiling).split(",")[0] : "—";
  elements.tableStatus.textContent = `${rows.length.toLocaleString("en-US")} rows shown`;
}

function renderTable(rows) {
  if (!rows.length) {
    elements.tableBody.innerHTML = `
      <tr>
        <td colspan="7" class="empty-cell">No rows match the current filters.</td>
      </tr>
    `;
    return;
  }

  elements.tableBody.innerHTML = rows
    .map(
      row => `
        <tr>
          <td class="mono">${escapeHtml(formatDate(row.FilingDate))}</td>
          <td class="mono">${escapeHtml(formatDate(row.EventDate, true))}</td>
          <td class="mono">${escapeHtml(cleanValue(row.DocketNumber) || "—")}</td>
          <td class="caption-cell">
            <p class="caption-main">${escapeHtml(cleanValue(row.CaseCaption) || "—")}</p>
            <p class="caption-sub">${escapeHtml(cleanValue(row.CaseStatus) || "")}</p>
          </td>
          <td>${escapeHtml(cleanValue(row.EventType) || "—")}</td>
          <td>${escapeHtml(cleanValue(row.EventLocation) || "—")}</td>
          <td>
            <div class="links-cell">
              ${renderLink(row.DocketSheetURL, "Docket")}
              ${renderLink(row.CourtSummaryURL, "Summary")}
            </div>
          </td>
        </tr>
      `
    )
    .join("");
}

function renderLink(url, label) {
  const safeUrl = cleanValue(url);
  if (!safeUrl) return `<span class="caption-sub">—</span>`;

  return `<a class="table-link" href="${escapeAttribute(safeUrl)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
}

function escapeHtml(value) {
  return cleanValue(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttribute(value) {
  return escapeHtml(value);
}

async function setLastUpdated() {
  try {
    const response = await fetch(CSV_URL, { method: "GET", cache: "no-store" });
    const lastModified = response.headers.get("Last-Modified");

    if (lastModified) {
      elements.lastUpdated.textContent = formatTimestamp(lastModified);
      return;
    }
  } catch (error) {
    console.warn("Could not read Last-Modified header:", error);
  }

  if (document.lastModified) {
    elements.lastUpdated.textContent = formatTimestamp(document.lastModified);
  } else {
    elements.lastUpdated.textContent = "Unavailable";
  }
}

async function loadData() {
  elements.tableStatus.textContent = "Loading data…";

  try {
    await setLastUpdated();

    const response = await fetch(CSV_URL, { cache: "no-store" });
    const csvText = await response.text();

    const parsed = Papa.parse(csvText, {
      header: true,
      skipEmptyLines: true,
    });

    state.rawRows = parsed.data.filter(row => cleanValue(row.DocketNumber));
    populateFilters(state.rawRows);
    applyFilters();
  } catch (error) {
    console.error(error);
    elements.tableStatus.textContent = "Could not load dashboard data.";
    elements.tableBody.innerHTML = `
      <tr>
        <td colspan="7" class="empty-cell">There was an error loading the CSV.</td>
      </tr>
    `;
    elements.lastUpdated.textContent = "Unavailable";
  }
}

function bindEvents() {
  elements.searchInput.addEventListener("input", applyFilters);
  elements.eventTypeFilter.addEventListener("change", applyFilters);
  elements.filingDateFilter.addEventListener("change", applyFilters);

  elements.resetFilters.addEventListener("click", () => {
    elements.searchInput.value = "";
    elements.eventTypeFilter.value = "";
    elements.filingDateFilter.value = "";
    state.sortKey = "FilingDate";
    state.sortDirection = "desc";
    applyFilters();
  });

  elements.sortButtons.forEach(button => {
    button.addEventListener("click", () => {
      const nextKey = button.dataset.sort;
      if (state.sortKey === nextKey) {
        state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = nextKey;
        state.sortDirection = nextKey === "DocketNumber" ? "asc" : "desc";
      }
      applyFilters();
    });
  });
}

setupThemeToggle();
bindEvents();
loadData();