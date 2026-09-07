"use strict";

/**
 * Admin dashboard SPA.
 * Auth: the ADMIN_API_TOKEN is kept in sessionStorage and sent as X-Admin-Token.
 */

const TOKEN_KEY = "admin_token";

const els = {
  loginView: document.getElementById("login-view"),
  dashboardView: document.getElementById("dashboard-view"),
  loginForm: document.getElementById("login-form"),
  tokenInput: document.getElementById("token-input"),
  loginError: document.getElementById("login-error"),
  logoutBtn: document.getElementById("logout-btn"),
  refreshBtn: document.getElementById("refresh-btn"),
  toast: document.getElementById("toast"),
};

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------

async function api(path, options = {}) {
  const token = sessionStorage.getItem(TOKEN_KEY) || "";
  const response = await fetch(path, {
    ...options,
    headers: { "X-Admin-Token": token, ...(options.headers || {}) },
  });
  if (response.status === 401 || response.status === 503) {
    showLogin();
    throw new Error("unauthorized");
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// View switching
// ---------------------------------------------------------------------------

function showLogin() {
  els.loginView.hidden = false;
  els.dashboardView.hidden = true;
  els.logoutBtn.hidden = true;
}

function showDashboard() {
  els.loginView.hidden = true;
  els.dashboardView.hidden = false;
  els.logoutBtn.hidden = false;
}

function toast(message, isError = false) {
  els.toast.textContent = message;
  els.toast.style.background = isError ? "#dc2626" : "#111827";
  els.toast.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => (els.toast.hidden = true), 3000);
}

// ---------------------------------------------------------------------------
// Rendering helpers
// ---------------------------------------------------------------------------

const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch])
  );

const fmtDateTime = (iso) =>
  new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

const badge = (status) =>
  `<span class="badge badge-${escapeHtml(status)}">${escapeHtml(status)}</span>`;

function renderRows(tbodyId, emptyId, rows) {
  const body = document.getElementById(tbodyId);
  const empty = document.getElementById(emptyId);
  body.innerHTML = rows.join("");
  empty.hidden = rows.length > 0;
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadStats() {
  const stats = await api("/api/admin/stats");
  document.getElementById("stat-upcoming").textContent = stats.upcoming_bookings;
  document.getElementById("stat-today").textContent = stats.next_24h_bookings;
  document.getElementById("stat-customers").textContent = stats.total_customers;
  document.getElementById("stat-callbacks").textContent = stats.pending_callbacks;
}

async function loadBookings() {
  const bookings = await api("/api/admin/bookings");
  renderRows(
    "bookings-body",
    "bookings-empty",
    bookings.map(
      (b) => `<tr>
        <td>${fmtDateTime(b.start_time)}</td>
        <td>${escapeHtml(b.customer_name) || "—"}</td>
        <td>${escapeHtml(b.customer_phone)}</td>
        <td>${escapeHtml(b.customer_email) || "—"}</td>
        <td>${badge(b.status)}</td>
        <td>${b.reminder_sent ? "✓ sent" : "—"}</td>
        <td>${
          b.status === "confirmed"
            ? `<button class="btn btn-danger small" data-cancel-booking="${b.id}">Cancel</button>`
            : ""
        }</td>
      </tr>`
    )
  );
}

async function loadCallbacks() {
  const callbacks = await api("/api/admin/callbacks");
  renderRows(
    "callbacks-body",
    "callbacks-empty",
    callbacks.map(
      (cb) => `<tr>
        <td>${fmtDateTime(cb.created_at)}</td>
        <td>${escapeHtml(cb.customer_name) || "—"}</td>
        <td>${escapeHtml(cb.customer_phone)}</td>
        <td>${escapeHtml(cb.reason) || "—"}</td>
        <td>${badge(cb.status)}</td>
        <td>${
          cb.status === "pending"
            ? `<button class="btn btn-success small" data-complete-callback="${cb.id}">Mark done</button>`
            : ""
        }</td>
      </tr>`
    )
  );
}

async function loadCustomers() {
  const customers = await api("/api/admin/customers");
  renderRows(
    "customers-body",
    "customers-empty",
    customers.map(
      (c) => `<tr>
        <td>${escapeHtml(c.name) || "—"}</td>
        <td>${escapeHtml(c.phone)}</td>
        <td>${escapeHtml(c.email) || "—"}</td>
        <td>${c.bookings}</td>
        <td>${fmtDateTime(c.created_at)}</td>
      </tr>`
    )
  );
}

async function loadAll() {
  try {
    await Promise.all([loadStats(), loadBookings(), loadCallbacks(), loadCustomers()]);
    showDashboard();
  } catch (err) {
    if (err.message !== "unauthorized") toast(err.message, true);
  }
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

els.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  sessionStorage.setItem(TOKEN_KEY, els.tokenInput.value.trim());
  els.loginError.hidden = true;
  try {
    await loadAll();
  } catch {
    els.loginError.hidden = false;
  }
});

els.logoutBtn.addEventListener("click", () => {
  sessionStorage.removeItem(TOKEN_KEY);
  showLogin();
});

els.refreshBtn.addEventListener("click", loadAll);

document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    document.querySelectorAll(".tab-panel").forEach((panel) => (panel.hidden = true));
    document.getElementById(`tab-${tab.dataset.tab}`).hidden = false;
  })
);

document.addEventListener("click", async (event) => {
  const cancelId = event.target.dataset?.cancelBooking;
  const completeId = event.target.dataset?.completeCallback;
  try {
    if (cancelId && confirm("Cancel this booking? The customer will be emailed.")) {
      await api(`/api/admin/bookings/${cancelId}/cancel`, { method: "POST" });
      toast("Booking cancelled");
      await loadAll();
    } else if (completeId) {
      await api(`/api/admin/callbacks/${completeId}/complete`, { method: "POST" });
      toast("Callback marked as done");
      await loadAll();
    }
  } catch (err) {
    if (err.message !== "unauthorized") toast(err.message, true);
  }
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

if (sessionStorage.getItem(TOKEN_KEY)) {
  loadAll();
} else {
  showLogin();
}
