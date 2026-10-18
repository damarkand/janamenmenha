import {
  DASH,
  apiFetch,
  formatDate,
  formatDateTime,
  formatMoney,
  formatRelativeTime,
  val
} from "../utils.js";

const ICONS = {
  vacation: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18"/>',
  advance: '<rect x="3" y="5" width="18" height="15" rx="2"/><path d="M3 9h18M16 14h2"/>',
  sick_leave: '<path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11z"/><path d="M12 8v6M9 11h6"/>',
  other: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h8"/>'
};

const SCOPE_LABELS = {
  mine: "Мои",
  team: "Подчинённых",
  all: "Все"
};

const STATUS_LABELS = {
  pending: "На рассмотрении",
  approved: "Одобрена",
  rejected: "Отклонена",
  cancelled: "Отменена"
};

const ACTION_LABELS = {
  create: "Заявка создана",
  created: "Заявка создана",
  approve: "Заявка одобрена",
  approved: "Заявка одобрена",
  reject: "Заявка отклонена",
  rejected: "Заявка отклонена",
  cancel: "Заявка отменена",
  cancelled: "Заявка отменена"
};

const DETAIL_LABELS = {
  start_date: "Дата начала",
  end_date: "Дата окончания",
  days: "Количество дней",
  amount: "Сумма",
  reason: "Причина",
  comment: "Комментарий"
};

const EMPTY_TEXTS = {
  mine: {
    title: "Заявок пока нет",
    description: "Создайте заявку на отпуск или аванс, и она появится здесь."
  },
  team: {
    title: "Заявок подчинённых нет",
    description: "Когда сотрудники отправят заявки, вы увидите их здесь."
  },
  all: {
    title: "Заявок нет",
    description: "Под выбранные условия не подошла ни одна заявка."
  }
};

function getScopes(user) {
  const role = `${user?.role ?? ""} ${user?.role_label ?? ""}`.toLowerCase();

  if (/\bhr\b|hr-|кадр/.test(role)) return ["mine", "team", "all"];
  if (/manager|head|lead|руковод|начальник/.test(role)) return ["mine", "team"];

  return ["mine"];
}

function getIcon(type) {
  return ICONS[type] || ICONS.other;
}

function formatDetailValue(key, value) {
  if (value === null || value === undefined || value === "") return DASH;
  if (key === "amount") return formatMoney(value);
  if (typeof value === "boolean") return value ? "Да" : "Нет";
  if (typeof value === "object") return JSON.stringify(value);

  return /^\d{4}-\d{2}-\d{2}$/.test(String(value)) ? formatDate(value) : String(value);
}

function summarize(request) {
  const details = request.details || {};

  if (details.start_date && details.end_date) {
    return `${formatDate(details.start_date)} — ${formatDate(details.end_date)}`;
  }

  if (details.amount !== undefined && details.amount !== null) {
    return `Сумма: ${formatMoney(details.amount)}`;
  }

  return details.comment || details.reason || "";
}

function setStatus(element, request) {
  element.className = `hr-status is-${request.status}`;
  element.textContent = request.status_label || STATUS_LABELS[request.status] || val(request.status);
}

function createInfoCard(label, value) {
  const card = document.createElement("div");
  const labelEl = document.createElement("span");
  const valueEl = document.createElement("span");

  card.className = "hr-info-card";
  labelEl.className = "hr-info-label";
  valueEl.className = "hr-info-value";

  labelEl.textContent = label;
  valueEl.textContent = value;

  card.append(labelEl, valueEl);

  return card;
}

export function init(root, user) {
  user = user || {};

  /* Элементы */

  const scopesEl = root.querySelector("#requests-scopes");
  const statusSelect = root.querySelector("#requests-status");
  const typeSelect = root.querySelector("#requests-type");
  const createButton = root.querySelector("#requests-create");
  const message = root.querySelector("#requests-message");
  const state = root.querySelector("#requests-state");
  const list = root.querySelector("#requests-list");

  const itemTemplate = root.querySelector("#request-template");
  const loadingTemplate = root.querySelector("#requests-loading-template");
  const emptyTemplate = root.querySelector("#requests-empty-template");
  const errorTemplate = root.querySelector("#requests-error-template");

  const createDialog = root.querySelector("#request-create-dialog");
  const form = root.querySelector("#request-form");
  const formMessage = root.querySelector("#request-form-message");
  const submitButton = root.querySelector("#request-submit");
  const typeTabs = createDialog?.querySelectorAll("[data-type]");
  const groups = createDialog?.querySelectorAll("[data-group]");

  const detailsDialog = root.querySelector("#request-details-dialog");
  const detailsTitle = root.querySelector("#request-details-title");
  const detailsStatus = root.querySelector("#details-status");
  const detailsMeta = root.querySelector("#details-meta");
  const detailsFields = root.querySelector("#details-fields");
  const detailsFieldsHeading = root.querySelector("#details-fields-heading");
  const detailsHistory = root.querySelector("#details-history");
  const detailsHistoryHeading = root.querySelector("#details-history-heading");
  const detailsMessage = root.querySelector("#details-message");
  const decisionBox = root.querySelector("#details-decision");
  const decisionComment = root.querySelector("#details-comment");
  const actionButtons = {
    cancel: detailsDialog?.querySelector('[data-action="cancel"]'),
    reject: detailsDialog?.querySelector('[data-action="reject"]'),
    approve: detailsDialog?.querySelector('[data-action="approve"]')
  };

  if (
    !scopesEl || !statusSelect || !typeSelect || !createButton || !message || !state || !list ||
    !itemTemplate || !createDialog || !form || !detailsDialog
  ) {
    return;
  }

  /* Состояние */

  const scopes = getScopes(user);

  let scope = scopes[0];
  let items = [];
  let current = null;
  let loadToken = 0;
  let detailsToken = 0;
  let detailsBusy = false;
  let createType = "vacation";

  const isOwn = request =>
    user.id ? request.requester?.id === user.id : request.requester?.full_name === user.full_name;

  /* Сообщения и состояния */

  function showMessage(text, type = "error") {
    message.className = type === "success" ? "hr-success-message" : "hr-error-message";
    message.textContent = text;
    message.hidden = false;
  }

  function hideMessage() {
    message.hidden = true;
  }

  function showLoading() {
    state.replaceChildren(loadingTemplate.content.cloneNode(true));
  }

  function showEmpty() {
    const node = emptyTemplate.content.cloneNode(true);
    const hasFilters = Boolean(statusSelect.value || typeSelect.value);
    const texts = hasFilters
      ? { title: "Ничего не найдено", description: "Попробуйте изменить фильтры." }
      : EMPTY_TEXTS[scope];

    node.querySelector(".hr-empty-title").textContent = texts.title;
    node.querySelector(".hr-empty-description").textContent = texts.description;

    state.replaceChildren(node);
  }

  function showLoadError(text) {
    const node = errorTemplate.content.cloneNode(true);

    node.querySelector(".hr-empty-description").textContent = text;
    node.querySelector(".hr-retry-button").addEventListener("click", () => loadRequests());

    state.replaceChildren(node);
  }

  /* Вкладки списка */

  function renderScopes() {
    scopesEl.hidden = scopes.length < 2;

    scopesEl.replaceChildren(...scopes.map(id => {
      const button = document.createElement("button");
      const active = id === scope;

      button.type = "button";
      button.className = `hr-tab${active ? " is-active" : ""}`;
      button.dataset.scope = id;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(active));
      button.textContent = SCOPE_LABELS[id];

      return button;
    }));
  }

  function setScope(id) {
    scope = id;
    renderScopes();
  }

  /* Список */

  function createItem(request) {
    const node = itemTemplate.content.cloneNode(true);

    node.querySelector(".hr-request-item").dataset.id = String(request.id);
    node.querySelector(".hr-request-icon").innerHTML =
      `<svg viewBox="0 0 24 24" aria-hidden="true">${getIcon(request.type)}</svg>`;
    node.querySelector(".hr-request-title").textContent = request.type_label || val(request.type);
    setStatus(node.querySelector(".hr-status"), request);

    const summary = node.querySelector(".hr-request-summary");
    summary.textContent = summarize(request);
    summary.hidden = !summary.textContent;

    const meta = [];

    if (scope !== "mine" && request.requester?.full_name) {
      meta.push(request.requester.full_name);
    }

    meta.push(formatRelativeTime(request.created_at));

    const metaEl = node.querySelector(".hr-request-meta");
    metaEl.textContent = meta.join(" · ");
    metaEl.title = formatDateTime(request.created_at);

    return node;
  }

  function render() {
    list.replaceChildren(...items.map(createItem));

    if (items.length) {
      state.replaceChildren();
    } else {
      showEmpty();
    }
  }

  async function loadRequests({ silent = false } = {}) {
    const token = ++loadToken;
    const params = new URLSearchParams({ scope });

    if (statusSelect.value) params.set("status", statusSelect.value);
    if (typeSelect.value) params.set("type", typeSelect.value);

    if (!silent) {
      hideMessage();
      list.replaceChildren();
      showLoading();
    }

    try {
      const data = await apiFetch(`/requests?${params}`);

      if (token !== loadToken || !root.isConnected) return;

      items = Array.isArray(data) ? data : [];
      render();
    } catch (error) {
      if (token !== loadToken || !root.isConnected) return;

      console.error("Ошибка загрузки заявок:", error);

      if (silent) {
        showMessage(error.message || "Не удалось обновить список заявок.");
      } else {
        showLoadError(error.message || "Проверьте соединение с сервером.");
      }
    }
  }

  /* Создание заявки */

  function showFormMessage(text) {
    formMessage.textContent = text;
    formMessage.hidden = false;
  }

  function setCreateType(type) {
    createType = type;

    typeTabs.forEach(tab => {
      const active = tab.dataset.type === type;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    });

    groups.forEach(group => {
      const active = group.dataset.group === type;

      group.hidden = !active;
      group.querySelectorAll("input, textarea").forEach(field => {
        field.disabled = !active;
      });
    });

    formMessage.hidden = true;
  }

  function openCreateDialog() {
    form.reset();
    setCreateType("vacation");

    root.querySelector("#vacation-hint").textContent =
      user.vacation_days_left !== undefined && user.vacation_days_left !== null
        ? `Остаток дней отпуска: ${user.vacation_days_left}`
        : "";

    root.querySelector("#advance-hint").textContent =
      user.advance_limit !== undefined && user.advance_limit !== null
        ? `Лимит аванса: ${formatMoney(user.advance_limit)}`
        : "";

    createDialog.showModal();
  }

  function buildPayload() {
    const data = new FormData(form);

    if (createType === "vacation") {
      const start = String(data.get("start_date") || "");
      const end = String(data.get("end_date") || "");

      if (end < start) {
        throw new Error("Дата окончания не может быть раньше даты начала.");
      }

      const comment = String(data.get("comment") || "").trim();

      return {
        path: "/requests/vacation",
        body: { start_date: start, end_date: end, ...(comment ? { comment } : {}) }
      };
    }

    const amount = Number(data.get("amount"));

    if (!Number.isFinite(amount) || amount <= 0) {
      throw new Error("Укажите сумму аванса больше нуля.");
    }

    return {
      path: "/requests/advance",
      body: { amount, reason: String(data.get("reason") || "").trim() }
    };
  }

  async function submitForm(event) {
    event.preventDefault();
    formMessage.hidden = true;

    let payload;

    try {
      payload = buildPayload();
    } catch (error) {
      showFormMessage(error.message);
      return;
    }

    submitButton.disabled = true;
    submitButton.textContent = "Отправляем...";

    try {
      await apiFetch(payload.path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload.body)
      });

      createDialog.close();

      statusSelect.value = "";
      typeSelect.value = "";
      setScope("mine");

      loadRequests();
      showMessage("Заявка отправлена на рассмотрение.", "success");
    } catch (error) {
      console.error("Ошибка создания заявки:", error);
      showFormMessage(error.message || "Не удалось создать заявку.");
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = "Отправить заявку";
    }
  }

  /* Карточка заявки */

  function showDetailsMessage(text) {
    detailsMessage.textContent = text;
    detailsMessage.hidden = false;
  }

  function actorName(request, actorId) {
    if (!actorId) return "";
    if (actorId === request.requester?.id) return request.requester.full_name;
    if (actorId === request.decided_by?.id) return request.decided_by.full_name;
    if (user.id && actorId === user.id) return user.full_name;

    return "";
  }

  function renderHistory(request) {
    const history = Array.isArray(request.history) ? request.history : [];

    detailsHistoryHeading.hidden = !history.length;

    detailsHistory.replaceChildren(...history.map(entry => {
      const item = document.createElement("li");
      const title = document.createElement("span");
      const meta = document.createElement("span");

      item.className = "hr-history-item";
      title.className = "hr-history-title";
      meta.className = "hr-history-meta";

      title.textContent = ACTION_LABELS[entry.action] || val(entry.action);
      meta.textContent = [actorName(request, entry.actor_id), formatDateTime(entry.at)]
        .filter(Boolean)
        .join(" · ");

      item.append(title, meta);

      if (entry.comment) {
        const comment = document.createElement("span");

        comment.className = "hr-history-comment";
        comment.textContent = entry.comment;

        item.append(comment);
      }

      return item;
    }));
  }

  function renderActions(request) {
    const pending = request.status === "pending";
    const own = isOwn(request);
    const canDecide = pending && !own && scopes.length > 1;

    actionButtons.cancel.hidden = !(pending && own);
    actionButtons.approve.hidden = !canDecide;
    actionButtons.reject.hidden = !canDecide;
    decisionBox.hidden = !canDecide;

    Object.values(actionButtons).forEach(button => {
      button.disabled = detailsBusy;
    });
  }

  function renderDetails(request) {
    const sameRequest = current?.id === request.id;

    current = request;

    detailsTitle.textContent = request.type_label || val(request.type);
    setStatus(detailsStatus, request);

    detailsMeta.replaceChildren(
      createInfoCard("Заявитель", val(request.requester?.full_name)),
      createInfoCard("Создана", formatDateTime(request.created_at)),
      createInfoCard("Обновлена", formatDateTime(request.updated_at)),
      createInfoCard("Решение принял", val(request.decided_by?.full_name))
    );

    const entries = Object.entries(request.details || {});

    detailsFieldsHeading.hidden = !entries.length;
    detailsFields.replaceChildren(...entries.map(([key, value]) =>
      createInfoCard(DETAIL_LABELS[key] || key, formatDetailValue(key, value))
    ));

    renderHistory(request);
    renderActions(request);

    if (!sameRequest) {
      decisionComment.value = "";
      detailsMessage.hidden = true;
    }
  }

  async function openDetails(id) {
    const request = items.find(entry => String(entry.id) === id);

    if (!request) return;

    const token = ++detailsToken;

    detailsBusy = false;
    current = null;
    renderDetails(request);
    detailsDialog.showModal();

    try {
      const fresh = await apiFetch(`/requests/${encodeURIComponent(id)}`);

      if (token !== detailsToken || !detailsDialog.open) return;

      renderDetails(fresh);
    } catch (error) {
      console.error("Ошибка загрузки заявки:", error);
    }
  }

  async function runAction(kind) {
    if (!current || detailsBusy) return;

    const id = String(current.id);
    const comment = decisionComment.value.trim();
    const options = { method: "POST" };

    detailsMessage.hidden = true;

    if (kind === "cancel" && !window.confirm("Отменить заявку?")) return;

    if (kind === "reject" && !comment) {
      showDetailsMessage("Укажите причину отклонения в комментарии.");
      decisionComment.focus();
      return;
    }

    if (kind === "approve" || kind === "reject") {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(comment ? { comment } : {});
    }

    detailsBusy = true;
    renderActions(current);

    try {
      const updated = await apiFetch(`/requests/${encodeURIComponent(id)}/${kind}`, options);

      decisionComment.value = "";
      detailsBusy = false;

      if (detailsDialog.open) renderDetails(updated);

      loadRequests({ silent: true });
    } catch (error) {
      console.error("Ошибка действия над заявкой:", error);

      detailsBusy = false;

      if (current) renderActions(current);

      showDetailsMessage(error.message || "Не удалось выполнить действие.");
    }
  }

  /* События */

  scopesEl.addEventListener("click", event => {
    const tab = event.target.closest("[data-scope]");

    if (!tab || tab.dataset.scope === scope) return;

    setScope(tab.dataset.scope);
    loadRequests();
  });

  statusSelect.addEventListener("change", () => loadRequests());
  typeSelect.addEventListener("change", () => loadRequests());

  list.addEventListener("click", event => {
    const item = event.target.closest(".hr-request-item");

    if (item) openDetails(item.dataset.id);
  });

  createButton.addEventListener("click", openCreateDialog);

  typeTabs.forEach(tab => {
    tab.addEventListener("click", () => setCreateType(tab.dataset.type));
  });

  form.addEventListener("submit", submitForm);

  Object.entries(actionButtons).forEach(([kind, button]) => {
    button.addEventListener("click", () => runAction(kind));
  });

  [createDialog, detailsDialog].forEach(dialog => {
    dialog.addEventListener("click", event => {
      if (event.target === dialog || event.target.closest("[data-close]")) {
        dialog.close();
      }
    });
  });

  detailsDialog.addEventListener("close", () => {
    detailsToken++;
    current = null;
  });

  renderScopes();
  loadRequests();
}