import {
  apiFetch,
  formatDateTime,
  formatRelativeTime,
  setUnreadCount
} from "../utils.js";

const ICONS = {
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h8"/>',
  book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21z"/><path d="M4 5.5v13A2.5 2.5 0 0 1 6.5 16H20M8 7h7"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/>'
};

const EMPTY_TEXTS = {
  all: {
    title: "Уведомлений пока нет",
    description: "Новые события и сообщения появятся здесь."
  },
  unread: {
    title: "Нет непрочитанных уведомлений",
    description: "Вы прочитали всё, что пришло."
  }
};

function getIcon(type) {
  const value = String(type || "");

  if (value.startsWith("request")) return ICONS.file;
  if (value.startsWith("course") || value.startsWith("learning")) return ICONS.book;

  return ICONS.bell;
}

function navigateByLink(link) {
  if (!link) return;

  const pageId = String(link).replace(/^[#/]+/, "").split(/[/?#]/)[0];

  if (!pageId || pageId === "notifications") return;

  document.querySelector(`.hr-app [data-page="${CSS.escape(pageId)}"]`)?.click();
}

export function init(root, user) {
  const list = root.querySelector("#notifications-list");
  const state = root.querySelector("#notifications-state");
  const message = root.querySelector("#notifications-message");
  const readAllButton = root.querySelector("#notifications-read-all");
  const tabCount = root.querySelector("#notifications-tab-count");
  const tabs = root.querySelectorAll(".hr-tab");

  const itemTemplate = root.querySelector("#notification-template");
  const loadingTemplate = root.querySelector("#notifications-loading-template");
  const emptyTemplate = root.querySelector("#notifications-empty-template");
  const errorTemplate = root.querySelector("#notifications-error-template");

  if (!list || !state || !message || !readAllButton || !tabCount || !itemTemplate) return;

  let filter = "all";
  let items = [];
  let unreadCount = 0;
  let loadToken = 0;
  let readAllPending = false;
  const pendingIds = new Set();

  /* Состояния */

  function showMessage(text) {
    message.textContent = text;
    message.hidden = false;
  }

  function hideMessage() {
    message.hidden = true;
  }

  function clearState() {
    state.replaceChildren();
  }

  function showLoading() {
    state.replaceChildren(loadingTemplate.content.cloneNode(true));
  }

  function showEmpty() {
    const node = emptyTemplate.content.cloneNode(true);
    const texts = EMPTY_TEXTS[filter];

    node.querySelector(".hr-empty-title").textContent = texts.title;
    node.querySelector(".hr-empty-description").textContent = texts.description;

    state.replaceChildren(node);
  }

  function showLoadError(text) {
    const node = errorTemplate.content.cloneNode(true);

    node.querySelector(".hr-empty-description").textContent = text;
    node.querySelector(".hr-retry-button").addEventListener("click", loadNotifications);

    state.replaceChildren(node);
  }

  /* Отрисовка */

  function syncUnread() {
    setUnreadCount(unreadCount, user);

    tabCount.textContent = unreadCount > 99 ? "99+" : String(unreadCount);
    tabCount.hidden = unreadCount <= 0;

    readAllButton.disabled = unreadCount <= 0 || readAllPending;
  }

  function createItem(notification) {
    const node = itemTemplate.content.cloneNode(true);
    const article = node.querySelector(".hr-notification-item");

    article.dataset.id = String(notification.id);
    article.classList.toggle("is-unread", !notification.read);

    node.querySelector(".hr-notification-icon").innerHTML = `
      <svg viewBox="0 0 24 24" aria-hidden="true">${getIcon(notification.type)}</svg>
    `;

    node.querySelector(".hr-notification-title-text").textContent = notification.title || "Уведомление";
    node.querySelector(".hr-notification-dot").hidden = Boolean(notification.read);
    node.querySelector(".hr-notification-read").hidden = Boolean(notification.read);

    const text = node.querySelector(".hr-notification-message");
    text.textContent = notification.message || "";
    text.hidden = !notification.message;

    const time = node.querySelector(".hr-notification-time");
    time.textContent = formatRelativeTime(notification.created_at);
    time.title = formatDateTime(notification.created_at);

    return node;
  }

  function render() {
    const visible = filter === "unread" ? items.filter(item => !item.read) : items;

    list.replaceChildren(...visible.map(createItem));

    if (visible.length) {
      clearState();
    } else {
      showEmpty();
    }

    syncUnread();
  }

  /* API */

  async function loadNotifications() {
    const token = ++loadToken;

    hideMessage();
    list.replaceChildren();
    showLoading();

    try {
      const data = await apiFetch(`/notifications?unread_only=${filter === "unread"}`);

      if (token !== loadToken || !root.isConnected) return;

      items = Array.isArray(data) ? data : [];
      unreadCount = filter === "unread"
        ? items.length
        : items.filter(item => !item.read).length;

      render();
    } catch (error) {
      if (token !== loadToken || !root.isConnected) return;

      console.error("Ошибка загрузки уведомлений:", error);
      showLoadError(error.message || "Проверьте соединение с сервером.");
    }
  }

  async function markRead(id) {
    const item = items.find(entry => String(entry.id) === id);

    if (!item || item.read || pendingIds.has(id)) return;

    pendingIds.add(id);
    hideMessage();

    try {
      await apiFetch(`/notifications/${encodeURIComponent(id)}/read`, { method: "POST" });

      item.read = true;
      unreadCount = Math.max(0, unreadCount - 1);

      if (root.isConnected) render();
    } catch (error) {
      console.error("Ошибка отметки уведомления:", error);
      showMessage(error.message || "Не удалось отметить уведомление прочитанным.");
      throw error;
    } finally {
      pendingIds.delete(id);
    }
  }

  async function markAllRead() {
    if (readAllPending || unreadCount <= 0) return;

    readAllPending = true;
    readAllButton.disabled = true;
    hideMessage();

    try {
      await apiFetch("/notifications/read-all", { method: "POST" });

      items.forEach(item => {
        item.read = true;
      });
      unreadCount = 0;
    } catch (error) {
      console.error("Ошибка отметки всех уведомлений:", error);
      showMessage(error.message || "Не удалось отметить уведомления прочитанными.");
    } finally {
      readAllPending = false;

      if (root.isConnected) render();
    }
  }

  async function openNotification(id) {
    const item = items.find(entry => String(entry.id) === id);

    if (!item) return;

    try {
      await markRead(id);
    } catch {
    }

    navigateByLink(item.link);
  }

  /* События */

  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      if (tab.dataset.filter === filter) return;

      filter = tab.dataset.filter;

      tabs.forEach(entry => {
        const active = entry === tab;
        entry.classList.toggle("is-active", active);
        entry.setAttribute("aria-selected", String(active));
      });

      loadNotifications();
    });
  });

  readAllButton.addEventListener("click", markAllRead);

  list.addEventListener("click", event => {
    const button = event.target.closest("[data-action]");
    const article = event.target.closest(".hr-notification-item");

    if (!button || !article) return;

    const id = article.dataset.id;

    if (button.dataset.action === "read") {
      markRead(id).catch(() => {});
    } else if (button.dataset.action === "open") {
      openNotification(id);
    }
  });

  loadNotifications();
}