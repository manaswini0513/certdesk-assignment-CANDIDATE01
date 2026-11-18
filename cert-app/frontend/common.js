// Shared helpers used by every page (login, sign-up and the main app).

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// Call the JSON API. Never throws: network errors come back as status 0.
let csrfToken = null;

async function ensureCsrfToken() {
  if (csrfToken) return csrfToken;
  try {
    const res = await fetch("/api/auth/csrf-token", { credentials: "same-origin" });
    const body = await res.json();
    csrfToken = body?.data?.csrf_token || null;
  } catch (_) {
    csrfToken = null;
  }
  return csrfToken;
}

async function api(path, options = {}) {
  let res;
  const method = (options.method || "GET").toUpperCase();
  const isFormData = options.body instanceof FormData;
  const headers = isFormData ? {} : { "Content-Type": "application/json" };

  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const token = await ensureCsrfToken();
    if (token) headers["X-CSRF-Token"] = token;
  }

  try {
    res = await fetch(path, {
      ...options,
      headers,
      credentials: "same-origin",
    });
  } catch (_) {
    return {
      ok: false,
      status: 0,
      body: { error: { message: "Can't reach the server. Check that it is running." } },
    };
  }
  let body = null;
  try { body = await res.json(); } catch (_) { /* empty body */ }
  return { ok: res.ok, status: res.status, body };
}

// ---------- Messages ----------
function showMessage(el, text, type) {
  el.textContent = text;
  el.className = `alert ${type}`;
}

function hideMessage(el) {
  el.textContent = "";
  el.className = "alert hidden";
}

function toast(text, type = "success") {
  let stack = $("#toast-stack");
  if (!stack) {
    stack = document.createElement("div");
    stack.id = "toast-stack";
    stack.className = "toast-stack";
    stack.setAttribute("aria-live", "polite");
    document.body.appendChild(stack);
  }
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = text;
  stack.appendChild(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 250);
  }, 3200);
}

// ---------- Forms ----------
function clearFieldErrors(form) {
  form.querySelectorAll(".field-error").forEach((el) => (el.textContent = ""));
  form.querySelectorAll("input").forEach((el) => el.classList.remove("invalid"));
}

function showFieldErrors(form, details) {
  Object.entries(details || {}).forEach(([field, text]) => {
    const slot = form.querySelector(`.field-error[data-for="${field}"]`);
    const input = form.querySelector(`[name="${field}"]`);
    if (slot) slot.textContent = text;
    if (input) input.classList.add("invalid");
  });
  form.querySelector("input.invalid")?.focus();
}

function setLoading(button, loading) {
  button.disabled = loading;
  button.classList.toggle("is-loading", loading);
}

// "Show / Hide" buttons next to password inputs.
$$("[data-toggle-password]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const input = document.getElementById(btn.dataset.togglePassword);
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.textContent = show ? "Hide" : "Show";
    btn.setAttribute("aria-pressed", String(show));
    btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
  });
});
