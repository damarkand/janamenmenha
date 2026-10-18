export const DASH = "—";

export function val(value) {
  return value === null || value === undefined || value === "" ? DASH : String(value);
}

export function initials(fullName) {
  const parts = String(fullName || "").trim().split(/\s+/).filter(Boolean);
  return parts.length
    ? parts.slice(0, 2).map(p => Array.from(p)[0]).join("").toUpperCase()
    : DASH;
}

export function formatDate(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value ?? ""));
  return m ? `${m[3]}.${m[2]}.${m[1]}` : val(value);
}

export function formatMoney(value) {
  if (value === null || value === undefined || value === "") return DASH;
  const n = Number(value);
  return Number.isFinite(n)
    ? new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(n)
    : String(value);
}

export function fillFields(root, data) {
  root.querySelectorAll("[data-field]").forEach(el => {
    const key = el.dataset.field;
    if (key in data) el.textContent = data[key];
  });
}

const DEV_PORTS = ["3000", "5173", "5500", "5501", "8080"];
export const API_BASE_URL = location.protocol === "file:" || DEV_PORTS.includes(location.port)
  ? "http://localhost:8000/api/v1"
  : `${location.origin}/api/v1`;

export async function apiFetch(path, options = {}) {
  const accessToken = sessionStorage.getItem("access_token");

  if (!accessToken) {
    throw new Error("Сессия завершена. Войдите в систему повторно.");
  }

  let response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${accessToken}`,
        ...options.headers
      }
    });
  } catch {
    throw new Error("Не удалось подключиться к серверу. Проверьте соединение.");
  }

  if (response.status === 401) {
    sessionStorage.removeItem("access_token");
    sessionStorage.removeItem("refresh_token");
    sessionStorage.removeItem("user");

    window.location.replace("index.html");
    throw new Error("Необходимо авторизоваться повторно.");
  }

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const detail = Array.isArray(data?.detail)
  ? data.detail.map(entry => entry.msg).filter(Boolean).join("; ")
  : typeof data?.detail === "string" ? data.detail : data?.message;
    throw new Error(detail || `Сервер вернул ошибку HTTP ${response.status}.`);
  }

  return data;
}

export function formatDateTime(value) {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return DASH;

  const pad = n => String(n).padStart(2, "0");

  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()}, ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function formatRelativeTime(value) {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return DASH;

  const minutes = Math.floor((Date.now() - date.getTime()) / 60000);

  if (minutes < 1) return "только что";
  if (minutes < 60) return `${minutes} мин назад`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ч назад`;

  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} дн назад`;

  return formatDateTime(value);
}

export function setUnreadCount(count, user = null) {
  const unread = Math.max(0, Number(count) || 0);
  const badge = document.getElementById("hr-notification-count");

  if (badge) {
    badge.textContent = unread > 99 ? "99+" : String(unread);
    badge.hidden = unread <= 0;
  }

  if (user) user.unread_notifications = unread;

  try {
    const stored = JSON.parse(sessionStorage.getItem("user") || "null");

    if (stored) {
      stored.unread_notifications = unread;
      sessionStorage.setItem("user", JSON.stringify(stored));
    }
  } catch {
    // Кэш не критичен
  }
}