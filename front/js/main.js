import { API_BASE_URL, initials, fillFields } from "./utils.js";

const HR_API_BASE_URL = API_BASE_URL;

const HR_ICONS = {
  user: '<circle cx="12" cy="8" r="4"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h8"/>',
  book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21z"/><path d="M4 5.5v13A2.5 2.5 0 0 1 6.5 16H20M8 7h7"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/>',
  sparkles: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  home: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/>',
  check: '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="m8 12 3 3 5-6"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18M8 15h2M12 15h2"/>',
  team: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20v-1.5A5.5 5.5 0 0 1 8 13h2a5.5 5.5 0 0 1 5.5 5.5V20"/><circle cx="17" cy="9" r="2.5"/><path d="M17 14a4.5 4.5 0 0 1 4.5 4.5V20"/>',
};

const PAGES = {
  home:          { label: "Главная",      icon: "home",     file: "pages/home.html",          module: "./pages/home.js",          nav: true },
  tasks:         { label: "Задачи",       icon: "check",    file: "pages/tasks.html",         module: "./pages/tasks.js",         nav: true },
  schedule:      { label: "График",       icon: "calendar", file: "pages/schedule.html",      module: "./pages/schedule.js",      nav: true },
  requests:      { label: "Заявки",       icon: "file",     file: "pages/requests.html",      module: "./pages/requests.js",      nav: true },
  learning:      { label: "Обучение",     icon: "book",     file: "pages/learning.html",      module: "./pages/learning.js",      nav: true },
  assistant:     { label: "Ирби", icon: "sparkles", file: "pages/assistant.html",     module: "./pages/assistant.js",     nav: true },
  team:          { label: "Команда",      icon: "team",     file: "pages/team.html",          module: "./pages/team.js",          nav: true, roles: ["manager", "hr"] },
  profile:       { label: "Мой профиль",  icon: "user",     file: "pages/profile.html",       module: "./pages/profile.js",       nav: true },
  notifications: { label: "Уведомления",  icon: "bell",     file: "pages/notifications.html", module: "./pages/notifications.js", nav: false },
};

const DEFAULT_PAGE = "home";

let hrCurrentUser = null;
let hrCurrentPage = DEFAULT_PAGE;
let hrRenderToken = 0;
const hrHtmlCache = new Map();

/* Helpers */

function hrEscape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function hrIcon(name) {
  const path = HR_ICONS[name] || HR_ICONS.file;
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
}

function hrGetAppRoot() {
  return document.querySelector(".hr-app");
}

function hrGetContent() {
  return document.getElementById("hr-page-content");
}

/* Состояния контента */

function hrSetLoading() {
  const content = hrGetContent();
  if (!content) return;

  content.innerHTML = `
    <div class="hr-page-loading">
      <span class="hr-spinner"></span>
      <span>Загружаем данные...</span>
    </div>
  `;
}

function hrSetError(message, onRetry) {
  const content = hrGetContent();
  if (!content) return;

  content.innerHTML = `
    <div class="hr-empty-state">
      <div class="hr-empty-icon">${hrIcon("file")}</div>
      <h2 class="hr-empty-title">Не удалось загрузить данные</h2>
      <p class="hr-empty-description">${hrEscape(message)}</p>
      <button class="hr-retry-button" id="hr-retry-button">Повторить</button>
    </div>
  `;

  document.getElementById("hr-retry-button")?.addEventListener("click", onRetry);
}

/* API */

async function hrFetchCurrentUser() {
  const accessToken = sessionStorage.getItem("access_token");

  if (!accessToken) {
    throw new Error("Сессия завершена. Войдите в систему повторно.");
  }

  const response = await fetch(`${HR_API_BASE_URL}/auth/me`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/json"
    }
  });

  if (response.status === 401) {
    sessionStorage.removeItem("access_token");
    sessionStorage.removeItem("refresh_token");
    sessionStorage.removeItem("user");

    window.location.replace("index.html");
    throw new Error("Необходимо авторизоваться повторно.");
  }

  if (!response.ok) {
    throw new Error(`Сервер вернул ошибку HTTP ${response.status}.`);
  }

  const user = await response.json();
  sessionStorage.setItem("user", JSON.stringify(user));
  return user;
}

/* Сайдбар */

function hrRenderNavigation() {
  const navigation = document.getElementById("hr-navigation");
  if (!navigation) return;

  navigation.innerHTML = Object.entries(PAGES)
    .filter(([, page]) => page.nav && (!page.roles || page.roles.includes(hrCurrentUser?.role)))
    .map(([id, page]) => `
      <button type="button" class="hr-nav-item" data-page="${hrEscape(id)}">
        <span class="hr-nav-icon">${hrIcon(page.icon)}</span>
        <span class="hr-nav-text">${hrEscape(page.label)}</span>
      </button>
    `)
    .join("");
}

function hrUpdateActiveNav() {
  document.querySelectorAll("#hr-navigation .hr-nav-item").forEach(button => {
    const active = button.dataset.page === hrCurrentPage;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
}

function hrRenderSidebarUser() {
  const user = hrCurrentUser;

  const avatar = document.getElementById("hr-sidebar-avatar");
  const name = document.getElementById("hr-sidebar-name");
  const role = document.getElementById("hr-sidebar-role");
  const count = document.getElementById("hr-notification-count");

  if (avatar) avatar.textContent = initials(user?.full_name);
  if (name) name.textContent = user?.full_name || "—";
  if (role) role.textContent = user?.role_label || user?.position || "—";

  if (count) {
    const unread = Number(user?.unread_notifications) || 0;
    count.textContent = unread > 99 ? "99+" : String(unread);
    count.hidden = unread <= 0;
  }
}

/* Роутер */

async function hrLoadPageHtml(file) {
  if (hrHtmlCache.has(file)) {
    return hrHtmlCache.get(file);
  }

  const response = await fetch(file, { cache: "no-cache" });

  if (!response.ok) {
    throw new Error(`Не удалось загрузить ${file}: HTTP ${response.status}`);
  }

  const html = await response.text();
  hrHtmlCache.set(file, html);
  return html;
}

async function hrRenderPage(pageId) {
  const allowed = PAGES[pageId] && (!PAGES[pageId].roles || PAGES[pageId].roles.includes(hrCurrentUser?.role));
  const id = allowed ? pageId : DEFAULT_PAGE;
  const page = PAGES[id];
  const content = hrGetContent();

  if (!content) return;

  const token = ++hrRenderToken;

  hrCurrentPage = id;

  const sectionTitle = document.getElementById("hr-current-section");
  if (sectionTitle) sectionTitle.textContent = page.label;

  hrUpdateActiveNav();
  hrGetAppRoot()?.classList.remove("hr-sidebar-open");

  if (!hrHtmlCache.has(page.file)) {
    hrSetLoading();
  }

  try {
    const html = await hrLoadPageHtml(page.file);
    if (token !== hrRenderToken) return;

    content.innerHTML = html;

    if (page.module) {
      const module = await import(page.module);
      if (token !== hrRenderToken) return;

      await module.init?.(content, hrCurrentUser);
    }
  } catch (error) {
    if (token !== hrRenderToken) return;

    console.error(`Ошибка загрузки страницы "${id}":`, error);
    hrSetError(error.message || "Проверьте соединение с сервером.", () => hrRenderPage(id));
  }
}

/* Выход */

function hrLogout() {
  hrRenderToken++;
  hrCurrentUser = null;
  hrCurrentPage = DEFAULT_PAGE;

  sessionStorage.removeItem("access_token");
  sessionStorage.removeItem("refresh_token");
  sessionStorage.removeItem("user");

  window.showMainPage();
}

/* События */

function hrBindEvents() {
  const root = hrGetAppRoot();

  if (!root || root.dataset.eventsBound === "true") return;
  root.dataset.eventsBound = "true";

  root.addEventListener("click", event => {
    const pageButton = event.target.closest("[data-page]");

    if (pageButton && root.contains(pageButton)) {
      event.preventDefault();
      hrRenderPage(pageButton.dataset.page);
      return;
    }

    if (event.target.closest("#hr-mobile-menu")) {
      root.classList.add("hr-sidebar-open");
    }

    if (
      event.target.closest("#hr-mobile-close") ||
      event.target.closest("#hr-sidebar-overlay")
    ) {
      root.classList.remove("hr-sidebar-open");
    }

    if (event.target.closest("#hr-logout-button")) {
      hrLogout();
      return;
    }
  });

  document.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      root.classList.remove("hr-sidebar-open");
    }
  });
}

/* Вход */

export async function initMain(initialUser = null, forceRefresh = false) {
  if (!hrGetAppRoot()) return;

  hrBindEvents();
  hrRenderNavigation();

  if (initialUser && !forceRefresh) {
    hrCurrentUser = initialUser;
  } else if (!forceRefresh) {
    try {
      hrCurrentUser = JSON.parse(sessionStorage.getItem("user") || "null");
    } catch {
      hrCurrentUser = null;
    }
  }

  hrRenderSidebarUser();
  hrSetLoading();

  try {
    if (!hrCurrentUser || forceRefresh) {
      hrCurrentUser = await hrFetchCurrentUser();
    }

    hrRenderSidebarUser();
    hrRenderNavigation();
    await hrRenderPage(hrCurrentPage);
  } catch (error) {
    console.error("Ошибка загрузки профиля:", error);
    hrSetError(error.message || "Проверьте соединение с сервером.", () => initMain(null, true));
  }
}