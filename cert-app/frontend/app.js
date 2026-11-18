// Main app (shown after login). Helpers like $, api and showMessage live in common.js.

const ICON_COPY = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
const ICON_EMPTY = `<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9h10M7 13h6"/></svg>`;
const ICON_CHECK = `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>`;
const ICON_X = `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>`;
const ICON_MAIL = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/></svg>`;
const ICON_QUESTION =`<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01"/></svg>`;

// ---------- Small helpers ----------
function initials(name) {
  return String(name || "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("");
}

function formatDate(isoDate) {
  if (!isoDate) return "";
  const d = new Date(`${isoDate}T00:00:00`);
  if (Number.isNaN(d.getTime())) return isoDate;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function formatDateTime(isoDateTime) {
  const d = new Date(isoDateTime);
  if (Number.isNaN(d.getTime())) return isoDateTime;
  return d.toLocaleString("en-GB", {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

// Today's date in the user's time zone, as YYYY-MM-DD.
function todayLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 10);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast(`Copied ${text}`);
  } catch (_) {
    toast("Couldn't copy. Select the ID and copy it by hand.", "error");
  }
}

function confirmDialog({ title, body, confirmLabel }) {
  const dialog = $("#confirm-dialog");
  if (typeof dialog.showModal !== "function") return Promise.resolve(window.confirm(body));
  $("#confirm-title").textContent = title;
  $("#confirm-body").textContent = body;
  $("#confirm-ok").textContent = confirmLabel;
  dialog.returnValue = "";
  dialog.showModal();
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true });
  });
}

// ---------- Session ----------
function goToLogin() {
  const here = window.location.pathname + window.location.hash;
  window.location.href = `/login?next=${encodeURIComponent(here)}`;
}

// Like api(), but sends the user to the login page if their session has ended.
async function request(path, options) {
  const res = await api(path, options);
  if (res.status === 401) goToLogin();
  return res;
}

async function loadUser() {
  const { ok, body } = await request("/api/auth/me");
  if (!ok) return false;
  const user = body.data;
  $("#user-name").textContent = user.name;
  $("#user-email").textContent = user.email;
  $("#user-avatar").textContent = initials(user.name);
  return true;
}

$("#logout-btn").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" });
  window.location.href = "/login?signed_out=1";
});

// ---------- Tabs ----------
const TABS = ["certificates", "issue", "verify", "email"];

function showTab(name) {
  const tab = TABS.includes(name) ? name : "certificates";
  $$(".tab").forEach((btn) => {
    const active = btn.dataset.tab === tab;
    btn.classList.toggle("active", active);
    if (active) btn.setAttribute("aria-current", "page");
    else btn.removeAttribute("aria-current");
  });
  $$(".panel").forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${tab}`));
  history.replaceState(null, "", `#${tab}`);
  if (tab === "certificates") refreshList();
  if (tab === "verify") $("#verify-form").cert_id.focus();
}

$$(".tab").forEach((btn) => btn.addEventListener("click", () => showTab(btn.dataset.tab)));
window.addEventListener("hashchange", () => showTab(window.location.hash.slice(1)));

// Buttons anywhere on the page: data-goto="<tab>" switches tab, data-copy="<text>" copies.
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-goto], [data-copy]");
  if (!btn) return;
  if (btn.dataset.goto) showTab(btn.dataset.goto);
  if (btn.dataset.copy) copyText(btn.dataset.copy);
});

// ---------- 1. Certificates list ----------
const listState = { page: 1, limit: 10, pages: 1, search: "", status: "" };

function refreshList() {
  loadCertificates();
  loadStats();
}

async function loadStats() {
  const count = async (status) => {
    const params = new URLSearchParams({ limit: 1 });
    if (status) params.set("status", status);
    const { ok, body } = await request(`/api/certificates?${params}`);
    return ok ? body.pagination.total : "–";
  };
  const [total, active, revoked] = await Promise.all([count(""), count("active"), count("revoked")]);
  $("#stat-total").textContent = total;
  $("#stat-active").textContent = active;
  $("#stat-revoked").textContent = revoked;
}

function certificateRow(c) {
  const id = escapeHtml(c.cert_id);
  const revokeButton = c.status === "active"
    ? `<button class="btn btn-danger-soft btn-sm" data-revoke="${id}"
         data-name="${escapeHtml(c.recipient_name)}" data-course="${escapeHtml(c.course_name)}">Revoke</button>`
    : "";
  return `
    <tr>
      <td>
        <span class="id-cell">
          <span class="mono">${id}</span>
          <button class="icon-btn" data-copy="${id}" title="Copy ID" aria-label="Copy ${id}">${ICON_COPY}</button>
        </span>
      </td>
      <td>
        <div class="person">
          <span class="avatar sm" aria-hidden="true">${escapeHtml(initials(c.recipient_name))}</span>
          <div>
            <div class="strong">${escapeHtml(c.recipient_name)}</div>
            <div class="sub">${escapeHtml(c.recipient_email)}</div>
          </div>
        </div>
      </td>
      <td>${escapeHtml(c.course_name)}</td>
      <td class="nowrap">${escapeHtml(formatDate(c.issue_date))}</td>
      <td><span class="badge ${c.status === "active" ? "active" : "revoked"}">${escapeHtml(c.status)}</span></td>
      <td class="actions-col">${revokeButton}</td>
    </tr>`;
}

async function loadCertificates() {
  const params = new URLSearchParams({ page: listState.page, limit: listState.limit });
  if (listState.search) params.set("search", listState.search);
  if (listState.status) params.set("status", listState.status);

  const rows = $("#cert-rows");
  const msg = $("#list-message");
  rows.classList.add("is-loading");
  const { ok, body } = await request(`/api/certificates?${params}`);
  rows.classList.remove("is-loading");

  if (!ok) {
    rows.innerHTML = "";
    showMessage(msg, body?.error?.message || "Could not load certificates.", "error");
    return;
  }
  hideMessage(msg);

  const certs = body.data;
  const { total } = body.pagination;
  listState.pages = body.pagination.pages || 1;

  if (certs.length === 0) {
    const filtered = listState.search || listState.status;
    rows.innerHTML = `
      <tr><td colspan="6">
        <div class="empty">
          ${ICON_EMPTY}
          <strong>No certificates found</strong>
          <span>${filtered ? "Try a different search or filter." : "Issue your first certificate and it will show up here."}</span>
        </div>
      </td></tr>`;
  } else {
    rows.innerHTML = certs.map(certificateRow).join("");
  }

  const from = total ? (listState.page - 1) * listState.limit + 1 : 0;
  const to = Math.min(listState.page * listState.limit, total);
  $("#page-info").textContent = total ? `Showing ${from}–${to} of ${total}` : "No results";
  $("#prev-page").disabled = listState.page <= 1;
  $("#next-page").disabled = listState.page >= listState.pages;
}

$("#cert-rows").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-revoke]");
  if (!btn) return;
  const certId = btn.dataset.revoke;

  const confirmed = await confirmDialog({
    title: "Revoke this certificate?",
    // \u2011 is a non-breaking hyphen, so the ID never wraps onto two lines.
    body: `${btn.dataset.name}'s "${btn.dataset.course}" certificate (${certId.replace("-", "\u2011")}) will stop being valid. ` +
      "Anyone who verifies it will see that it was revoked. This can't be undone.",
    confirmLabel: "Revoke certificate",
  });
  if (!confirmed) return;

  setLoading(btn, true);
  const { ok, body } = await request(`/api/certificates/${encodeURIComponent(certId)}/revoke`, {
    method: "PATCH",
  });
  if (ok) {
    toast(`Certificate ${certId} revoked.`);
    refreshList();
  } else {
    setLoading(btn, false);
    showMessage($("#list-message"), body?.error?.message || "Could not revoke certificate.", "error");
  }
});

let searchTimer;
$("#search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    listState.search = e.target.value.trim();
    listState.page = 1;
    loadCertificates();
  }, 300);
});

$("#status-filter").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-status]");
  if (!btn) return;
  $$("#status-filter button").forEach((b) => {
    b.classList.toggle("active", b === btn);
    b.setAttribute("aria-pressed", String(b === btn));
  });
  listState.status = btn.dataset.status;
  listState.page = 1;
  loadCertificates();
});

$("#prev-page").addEventListener("click", () => {
  if (listState.page > 1) { listState.page--; loadCertificates(); }
});
$("#next-page").addEventListener("click", () => {
  if (listState.page < listState.pages) { listState.page++; loadCertificates(); }
});

// ---------- 2. Issue form ----------
const issueForm = $("#issue-form");
const issueMessage = $("#issue-message");
const bulkUploadForm = $("#bulk-upload-form");
const bulkMessage = $("#bulk-message");
const bulkPreview = $("#bulk-preview");
const bulkState = { jobId: null, preview: null, timer: null };

function setIssueMode(mode) {
  const single = mode === "single";
  $("#single-issue-pane").classList.toggle("hidden", !single);
  $("#bulk-issue-pane").classList.toggle("hidden", single);
  $$("[data-issue-mode]").forEach((btn) => btn.classList.toggle("active", btn.dataset.issueMode === mode));
}

$$("[data-issue-mode]").forEach((btn) => {
  btn.addEventListener("click", () => setIssueMode(btn.dataset.issueMode));
});

function persistBulkJob(jobId) {
  if (jobId) localStorage.setItem("certdesk-bulk-job", jobId);
  else localStorage.removeItem("certdesk-bulk-job");
}

function clearBulkPreview() {
  bulkState.jobId = null;
  bulkState.preview = null;
  persistBulkJob(null);
  bulkPreview.classList.add("hidden");
  $("#bulk-summary").innerHTML = "";
  $("#bulk-rows").innerHTML = "";
  hideMessage(bulkMessage);
}

function renderBulkSummary(summary = {}) {
  const total = Number(summary.total || 0);
  const ready = Number(summary.ready || 0);
  const errors = Number(summary.errors || 0);
  $("#bulk-summary").innerHTML = `
    <span class="summary-pill"><strong>${total}</strong> total</span>
    <span class="summary-pill ok"><strong>${ready}</strong> ready</span>
    <span class="summary-pill bad"><strong>${errors}</strong> errors</span>
  `;
}

function renderBulkPreview(rows = [], summary = {}) {
  renderBulkSummary(summary);
  if (!rows.length) {
    $("#bulk-rows").innerHTML = `<tr><td colspan="6"><div class="empty">No rows to show.</div></td></tr>`;
    return;
  }
  $("#bulk-rows").innerHTML = rows.map((row) => {
    const statusClass = row.status === "ready" ? "ready" : row.status === "error" ? "bad" : "warn";
    const safeEmail = escapeHtml(row.recipient_email || "");
    return `
      <tr>
        <td>${escapeHtml(row.row_number)}</td>
        <td>${escapeHtml(row.recipient_name || "")}</td>
        <td class="mono">${safeEmail}</td>
        <td>${escapeHtml(row.course_name || "")}</td>
        <td>${escapeHtml(row.issue_date || "")}</td>
        <td><span class="bulk-status ${statusClass}">${escapeHtml(row.status)}</span>${row.error ? `<div class="bulk-error">${escapeHtml(row.error)}</div>` : ""}</td>
      </tr>`;
  }).join("");
  bulkPreview.classList.remove("hidden");
}

function showBulkJobStatus(job) {
  const banner = $("#bulk-progress-banner");
  if (!job) {
    banner.classList.add("hidden");
    return;
  }
  const progress = job.summary || {};
  const done = Number(progress.issued || 0) + Number(progress.failed || 0);
  const total = Number(progress.total || 0) || 1;
  const title = job.status === "completed" ? `Bulk issue complete: ${done} of ${total} rows finished.` : `Bulk issue: ${done} of ${total}`;
  banner.innerHTML = `
    <strong>${escapeHtml(title)}</strong>
    ${job.status === "completed" ? `<a href="/api/bulk-issues/${encodeURIComponent(job.job_id)}/results.csv" target="_blank" rel="noreferrer">Download CSV</a>` : ""}
  `;
  banner.classList.remove("hidden");
}

function stopBulkPolling() {
  if (bulkState.timer) {
    clearInterval(bulkState.timer);
    bulkState.timer = null;
  }
}

async function pollBulkJob(jobId) {
  if (!jobId) return;
  const { ok, body } = await request(`/api/bulk-issues/${encodeURIComponent(jobId)}`);
  if (!ok) return;

  const job = body.job;
  showBulkJobStatus(job);

  if (job.status === "pending" || job.status === "processing") {
    stopBulkPolling();
    bulkState.timer = setInterval(async () => {
      await pollBulkJob(jobId);
    }, 2000);
    return;
  }

  stopBulkPolling();
  if (job.status === "completed" || job.status === "failed") {
    const summary = job.summary || {};
    showMessage(bulkMessage, `Bulk issue ${job.status === "completed" ? "finished" : "stopped"}. ${summary.issued || 0} issued, ${summary.failed || 0} failed.`, job.status === "completed" ? "success" : "error");
  }
}

const bulkFileInput = $("#bulk-file");
const bulkFileName = $("#bulk-file-name");

bulkFileInput.addEventListener("change", () => {
  const file = bulkFileInput.files?.[0];
  bulkFileName.textContent = file ? `Selected: ${file.name}` : "or drag it here. Up to 500 rows and 1 MB.";
  if (file) {
    bulkUploadForm.requestSubmit();
  }
});

bulkUploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  hideMessage(bulkMessage);
  const file = bulkFileInput.files?.[0];
  if (!file) {
    showMessage(bulkMessage, "Choose a CSV file before checking it.", "error");
    return;
  }
  const formData = new FormData();
  formData.append("file", file);
  const button = bulkUploadForm.querySelector('button[type="submit"]');
  setLoading(button, true);

  const { ok, body } = await request("/api/bulk-issues", {
    method: "POST",
    body: formData,
    headers: {},
  });
  setLoading(button, false);

  if (!ok) {
    showMessage(bulkMessage, body?.error?.message || "The CSV could not be checked.", "error");
    clearBulkPreview();
    return;
  }

  bulkState.jobId = body.job_id;
  bulkState.preview = body;
  persistBulkJob(body.job_id);
  renderBulkPreview(body.rows, body.summary);
  showMessage(bulkMessage, `${body.summary.ready} row(s) are ready to issue. ${body.summary.errors} row(s) need attention.`, "info");
  showBulkJobStatus({ job_id: body.job_id, status: "pending", summary: body.summary });
});

$("#bulk-cancel").addEventListener("click", () => {
  clearBulkPreview();
  $("#bulk-file").value = "";
  showMessage(bulkMessage, "The upload was cancelled. You can check another CSV anytime.", "info");
});

$("#bulk-approve").addEventListener("click", async () => {
  if (!bulkState.jobId) return;
  const hasEmail = Boolean(emailSettings);
  if (!hasEmail) {
    showMessage(bulkMessage, "Email isn't connected, so the certificate rows will still be issued without sending any email notifications.", "warn");
  }
  const { ok, body } = await request(`/api/bulk-issues/${encodeURIComponent(bulkState.jobId)}/approve`, {
    method: "POST",
  });
  if (!ok) {
    showMessage(bulkMessage, body?.error?.message || "The bulk issue could not be approved.", "error");
    return;
  }

  persistBulkJob(bulkState.jobId);
  showMessage(bulkMessage, "Bulk issue started in the background. You can keep working while it completes.", "success");
  await pollBulkJob(bulkState.jobId);
});

async function restoreBulkProgress() {
  const savedJobId = localStorage.getItem("certdesk-bulk-job");
  if (!savedJobId) return;
  bulkState.jobId = savedJobId;
  const { ok, body } = await request(`/api/bulk-issues/${encodeURIComponent(savedJobId)}`);
  if (!ok) {
    persistBulkJob(null);
    bulkState.jobId = null;
    return;
  }
  const job = body.job;
  bulkState.preview = job;
  if (job.rows && job.rows.length) {
    renderBulkPreview(job.rows, job.summary);
  }
  showBulkJobStatus(job);
  if (job.status === "pending" || job.status === "processing") {
    pollBulkJob(savedJobId);
  }
}

function setPreviewText(el, value, placeholder) {
  el.textContent = value || placeholder;
  el.classList.toggle("is-placeholder", !value);
}

// Draw the preview from the form, or from an issued certificate.
function updatePreview(cert = null) {
  const values = cert || {
    recipient_name: issueForm.recipient_name.value.trim(),
    course_name: issueForm.course_name.value.trim(),
    issue_date: issueForm.issue_date.value,
  };
  setPreviewText($("#pv-name"), values.recipient_name, "Recipient name");
  setPreviewText($("#pv-course"), values.course_name, "Course name");
  setPreviewText($("#pv-date"), formatDate(values.issue_date), "–");
  $("#pv-id").textContent = cert ? cert.cert_id : "CERT-········";
  $("#cert-preview").classList.toggle("issued", Boolean(cert));
  $("#preview-note").textContent = cert
    ? "Issued. Share this ID so anyone can verify the certificate."
    : "Preview. The certificate ID is created when you issue it.";
}

function resetIssueForm() {
  issueForm.reset();
  issueForm.issue_date.max = todayLocal();
  issueForm.issue_date.value = todayLocal();
  clearFieldErrors(issueForm);
}

issueForm.addEventListener("input", () => updatePreview());

$("#issue-clear").addEventListener("click", () => {
  resetIssueForm();
  hideMessage(issueMessage);
  updatePreview();
});

issueForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearFieldErrors(issueForm);
  hideMessage(issueMessage);

  const payload = {
    recipient_name: issueForm.recipient_name.value.trim(),
    recipient_email: issueForm.recipient_email.value.trim(),
    course_name: issueForm.course_name.value.trim(),
    issue_date: issueForm.issue_date.value,
  };

  // Read this before the form is reset below.
  const wantsEmail = Boolean($("#send-email")?.checked);

  const button = issueForm.querySelector('button[type="submit"]');
  setLoading(button, true);
  const { ok, body } = await request("/api/certificates", {
    method: "POST",
    body: JSON.stringify(payload),
  });

  if (!ok) {
    setLoading(button, false);
    showFieldErrors(issueForm, body?.error?.details);
    showMessage(issueMessage, body?.error?.message || "Something went wrong.", "error");
    return;
  }

  const cert = body.data;
  const emailResult = await emailCertificate(cert, wantsEmail);
  setLoading(button, false);

  const id = escapeHtml(cert.cert_id);
  resetIssueForm();
  updatePreview(cert);
  issueMessage.className = "alert success";
  issueMessage.innerHTML = `
    <span><strong>Certificate issued.</strong> ID <span class="mono">${id}</span></span>
    <span class="alert-actions">
      <button type="button" class="link-btn" data-copy="${id}">Copy ID</button>
      <button type="button" class="link-btn" data-goto="certificates">View all</button>
    </span>
    <span class="alert-note ${emailResult.type}">${ICON_MAIL}<span>${escapeHtml(emailResult.text)}</span></span>`;
});

// After a certificate is issued: email it to the recipient, if email is set up.
async function emailCertificate(cert, wantsEmail) {
  if (!emailSettings) {
    return { type: "warn", text: "No email was sent, because email isn't set up." };
  }
  if (!wantsEmail) {
    return { type: "muted", text: "No email was sent (you turned it off)." };
  }
  const { ok, body } = await request(
    `/api/certificates/${encodeURIComponent(cert.cert_id)}/send-email`,
    { method: "POST" },
  );
  if (ok) {
    return { type: "sent", text: `Emailed to ${body.data.sent_to} from ${body.data.sent_from}.` };
  }
  return {
    type: "error",
    text: `The certificate was issued, but the email could not be sent: ${body?.error?.message || "unknown error"}`,
  };
}

// ---------- 4. Email setup ----------
// emailSettings is null when email isn't set up (or the server can't tell us).
let emailSettings = null;
let emailLoadError = "";
const emailForm = $("#email-form");
const emailMessage = $("#email-message");
const GMAIL_DEFAULTS = { smtp_host: "smtp.gmail.com", smtp_port: 587 };

function senderLabel(settings) {
  return settings.from_name ? `${settings.from_name} <${settings.email}>` : settings.email;
}

async function loadEmailSettings() {
  const { ok, status, body } = await request("/api/email-settings");
  emailSettings = ok ? body?.data || null : null;
  emailLoadError = ok || status === 401 ? "" : body?.error?.message || "Could not load email settings.";
  renderEmail();
}

function renderEmail() {
  renderEmailStatus();
  renderDelivery();
  const dot = $("#email-dot");
  dot.className = `tab-dot ${emailSettings ? "on" : "off"}`;
  dot.title = emailSettings ? "Email connected" : "Email not set up";
}

function renderEmailStatus() {
  const box = $("#email-status");
  if (emailSettings) {
    const s = emailSettings;
    const verified = s.verified_at ? ` · verified ${escapeHtml(formatDateTime(s.verified_at))}` : "";
    box.innerHTML = `
      <div class="status-row">
        <span class="status-icon ok">${ICON_CHECK}</span>
        <div class="status-text">
          <h2>Connected</h2>
          <p>Certificates are sent as <strong>${escapeHtml(senderLabel(s))}</strong>
             via <span class="mono">${escapeHtml(s.smtp_host)}:${escapeHtml(s.smtp_port)}</span>${verified}</p>
        </div>
        <div class="status-actions">
          <button type="button" class="btn btn-secondary btn-sm" id="email-test">
            <span class="spinner" aria-hidden="true"></span><span>Send test email</span>
          </button>
          <button type="button" class="btn btn-danger-soft btn-sm" id="email-disconnect">Disconnect</button>
        </div>
      </div>`;
    return;
  }
  box.innerHTML = `
    <div class="status-row">
      <span class="status-icon warn">${ICON_MAIL}</span>
      <div class="status-text">
        <h2>Not connected</h2>
        <p>Certificates are issued <strong>without</strong> an email to the recipient. Connect Gmail below to start sending them.</p>
        ${emailLoadError ? `<p class="status-error">${escapeHtml(emailLoadError)}</p>` : ""}
      </div>
    </div>`;
}

// The box on the Issue form that says whether, and from where, the email goes.
function renderDelivery() {
  const box = $("#delivery");
  if (emailSettings) {
    box.innerHTML = `
      <label class="delivery on">
        <input type="checkbox" id="send-email" checked />
        <span class="delivery-text">
          <strong>Email the certificate to the recipient</strong>
          <span>From <b>${escapeHtml(senderLabel(emailSettings))}</b></span>
        </span>
      </label>`;
    return;
  }
  box.innerHTML = `
    <div class="delivery off">
      <span class="delivery-icon">${ICON_MAIL}</span>
      <span class="delivery-text">
        <strong>Email isn't set up</strong>
        <span>The certificate will be issued, but the recipient won't get an email.</span>
      </span>
      <button type="button" class="btn btn-secondary btn-sm" data-goto="email">Set up email</button>
    </div>`;
}

function fillEmailForm() {
  const s = emailSettings || {};
  emailForm.from_name.value = s.from_name || "";
  emailForm.email.value = s.email || "";
  emailForm.app_password.value = "";
  emailForm.app_password.placeholder = emailSettings
    ? "Enter the app password again to save changes"
    : "xxxx xxxx xxxx xxxx";
  emailForm.smtp_host.value = s.smtp_host || GMAIL_DEFAULTS.smtp_host;
  emailForm.smtp_port.value = s.smtp_port || GMAIL_DEFAULTS.smtp_port;
  clearFieldErrors(emailForm);
  hideMessage(emailMessage);
}

function validateEmailForm(values) {
  const errors = {};
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(values.email)) errors.email = "Enter a valid email address";
  if (!values.app_password) {
    errors.app_password = "Paste the app password from Google";
  } else if (values.smtp_host === GMAIL_DEFAULTS.smtp_host && values.app_password.length !== 16) {
    errors.app_password = "Google app passwords are 16 characters long";
  }
  if (!values.smtp_host) errors.smtp_host = "Enter the SMTP server";
  if (!Number.isInteger(values.smtp_port) || values.smtp_port < 1 || values.smtp_port > 65535) {
    errors.smtp_port = "Enter a port from 1 to 65535";
  }
  return errors;
}

$("#email-defaults").addEventListener("click", () => {
  emailForm.smtp_host.value = GMAIL_DEFAULTS.smtp_host;
  emailForm.smtp_port.value = GMAIL_DEFAULTS.smtp_port;
});

emailForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearFieldErrors(emailForm);
  hideMessage(emailMessage);

  const values = {
    email: emailForm.email.value.trim(),
    app_password: emailForm.app_password.value.replace(/\s+/g, ""),
    smtp_host: emailForm.smtp_host.value.trim().toLowerCase(),
    smtp_port: Number(emailForm.smtp_port.value),
  };
  const fromName = emailForm.from_name.value.trim();
  if (fromName) values.from_name = fromName;

  const errors = validateEmailForm(values);
  if (Object.keys(errors).length) {
    showFieldErrors(emailForm, errors);
    return;
  }

  const button = emailForm.querySelector('button[type="submit"]');
  setLoading(button, true);
  showMessage(emailMessage, `Signing in to ${values.smtp_host} to check your details…`, "info");
  const { ok, body } = await request("/api/email-settings", {
    method: "PUT",
    body: JSON.stringify(values),
  });
  setLoading(button, false);

  if (!ok) {
    showFieldErrors(emailForm, body?.error?.details);
    showMessage(emailMessage, body?.error?.message || "Could not save email settings.", "error");
    return;
  }
  emailSettings = body.data;
  emailLoadError = "";
  renderEmail();
  fillEmailForm();
  toast(`Email connected. Certificates will be sent from ${emailSettings.email}.`);
});

$("#email-status").addEventListener("click", async (e) => {
  const testBtn = e.target.closest("#email-test");
  const disconnectBtn = e.target.closest("#email-disconnect");

  if (testBtn) {
    setLoading(testBtn, true);
    const { ok, body } = await request("/api/email-settings/test", { method: "POST" });
    setLoading(testBtn, false);
    if (ok) toast(`Test email sent to ${body.data.sent_to}. Check your inbox.`);
    else toast(body?.error?.message || "Could not send the test email.", "error");
  }

  if (disconnectBtn) {
    const confirmed = await confirmDialog({
      title: "Disconnect email?",
      body: "The saved app password will be deleted. New certificates will be issued without an email until you connect again.",
      confirmLabel: "Disconnect",
    });
    if (!confirmed) return;
    const { ok, body } = await request("/api/email-settings", { method: "DELETE" });
    if (!ok) {
      toast(body?.error?.message || "Could not disconnect.", "error");
      return;
    }
    emailSettings = null;
    renderEmail();
    fillEmailForm();
    toast("Email disconnected.");
  }
});

// ---------- 3. Verify ----------
function verifyCard(kind, icon, title, text, details = "") {
  return `
    <div class="card result ${kind}">
      <div class="result-head">
        <span class="result-icon">${icon}</span>
        <div><h2>${title}</h2><p>${text}</p></div>
      </div>
      ${details}
    </div>`;
}

$("#verify-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const certId = form.cert_id.value.trim().toUpperCase();
  const out = $("#verify-result");
  if (!certId) {
    form.cert_id.focus();
    return;
  }
  form.cert_id.value = certId;

  const button = form.querySelector('button[type="submit"]');
  setLoading(button, true);
  const { ok, status, body } = await api(`/api/verify/${encodeURIComponent(certId)}`);
  setLoading(button, false);

  if (status === 404) {
    out.innerHTML = verifyCard(
      "missing", ICON_QUESTION, "No certificate found",
      `We couldn't find a certificate with ID <span class="mono">${escapeHtml(certId)}</span>. Check the ID and try again.`,
    );
    return;
  }
  if (!ok) {
    out.innerHTML = verifyCard(
      "missing", ICON_QUESTION, "Something went wrong",
      escapeHtml(body?.error?.message || "Could not verify certificate."),
    );
    return;
  }

  const details = `
    <dl>
      <dt>Certificate ID</dt><dd class="mono">${escapeHtml(body.cert_id)}</dd>
      <dt>Recipient</dt><dd>${escapeHtml(body.recipient_name)}</dd>
      <dt>Course</dt><dd>${escapeHtml(body.course_name)}</dd>
      <dt>Issued on</dt><dd>${escapeHtml(formatDate(body.issue_date))}</dd>
      ${body.revoked_at ? `<dt>Revoked on</dt><dd>${escapeHtml(formatDateTime(body.revoked_at))}</dd>` : ""}
    </dl>`;

  out.innerHTML = body.valid
    ? verifyCard("valid", ICON_CHECK, "Valid certificate", "This certificate is genuine and active.", details)
    : verifyCard("revoked", ICON_X, "Certificate revoked", "This certificate was issued, but it is no longer valid.", details);
});

// ---------- Start ----------
(async function start() {
  setIssueMode("single");
  resetIssueForm();
  updatePreview();
  renderEmail();
  if (!(await loadUser())) return;
  await loadEmailSettings();
  fillEmailForm();
  await restoreBulkProgress();
  showTab(window.location.hash.slice(1));

  // Re-check the session every minute. This sends the user back to login promptly
  // after inactivity expires, even if they remain on an open tab.
  setInterval(async () => {
    const { ok } = await request("/api/auth/me");
    if (!ok) goToLogin();
  }, 60 * 1000);
})();
