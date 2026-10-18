import { API_BASE_URL, DASH, apiFetch, formatDateTime, formatRelativeTime, val } from "../utils.js";
import { createTyper, irbiSvg } from "../irbi.js";

const STATUS_LABELS = {
  open: "Ожидает ответа",
  answered: "Есть ответ"
};

const MODE_LABELS = {
  qwen: "ответ нейросети по базе знаний",
  extractive: "цитата из базы знаний",
  profile: "ваши данные",
  chat: ""
};

const CONFIDENCE_LABELS = {
  high: "высокая",
  medium: "средняя",
  low: "низкая"
};

const SUGGESTIONS = [
  "Как прошёл твой день?",
  "Я устал, дай совет",
  "Как перенести отпуск?",
  "Какие у меня задачи?",
  "Когда выплачивается аванс?"
];

const FILE_ICON =
  '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h8"/>';

const enc = encodeURIComponent;

let chatLog = [];
let chatOwner = null;

function isHr(user) {
  const role = `${user?.role ?? ""} ${user?.role_label ?? ""}`.toLowerCase();

  return /\bhr\b|hr-|кадр/.test(role);
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

function setStatus(element, item) {
  element.className = `hr-status is-${item.status}`;
  element.textContent = STATUS_LABELS[item.status] || val(item.status);
}

export function init(root, user) {
  user = user || {};

  const owner = user.id || user.email || user.full_name || null;

  if (owner !== chatOwner) {
    chatLog = [];
    chatOwner = owner;
  }

  /* Элементы */

  const q = selector => root.querySelector(selector);

  const tabsEl = q("#assistant-tabs");
  const statusSelect = q("#assistant-status");
  const message = q("#assistant-message");

  const chatPanel = q("#assistant-chat-panel");
  const messagesEl = q("#chat-messages");
  const welcome = q("#chat-welcome");
  const suggestionsEl = q("#chat-suggestions");
  const chatForm = q("#chat-form");
  const chatInput = q("#chat-input");
  const chatSend = q("#chat-send");

  const escPanel = q("#assistant-escalations-panel");
  const escState = q("#escalations-state");
  const escList = q("#escalations-list");

  const messageTemplate = q("#chat-message-template");
  const typingTemplate = q("#chat-typing-template");
  const itemTemplate = q("#escalation-template");
  const loadingTemplate = q("#escalations-loading-template");
  const emptyTemplate = q("#escalations-empty-template");
  const errorTemplate = q("#escalations-error-template");

  const dialog = q("#escalation-dialog");
  const dialogTitle = q("#escalation-title");
  const dialogStatus = q("#escalation-status");
  const dialogQuestion = q("#escalation-question");
  const dialogContextBlock = q("#escalation-context-block");
  const dialogContext = q("#escalation-context");
  const dialogAnswer = q("#escalation-answer");
  const dialogMeta = q("#escalation-meta");
  const dialogMessage = q("#escalation-message");
  const replyBox = q("#escalation-reply");
  const replyInput = q("#escalation-reply-input");
  const answerButton = dialog?.querySelector('[data-action="answer"]');

  if (
    !tabsEl || !statusSelect || !message || !chatPanel || !messagesEl || !welcome || !suggestionsEl ||
    !chatForm || !chatInput || !chatSend || !escPanel || !escState || !escList ||
    !messageTemplate || !typingTemplate || !itemTemplate || !dialog || !answerButton
  ) {
    return;
  }

  /* Состояние */

  const hr = isHr(user);
  const tabs = ["chat", "escalations"];
  const tabLabels = {
    chat: "Чат",
    escalations: hr ? "Все обращения" : "Мои обращения"
  };

  let tab = "chat";
  let chatBusy = false;
  let items = [];
  let current = null;
  let loadToken = 0;
  let busy = false;

  /* Сообщения */

  function showMessage(text, type = "error") {
    message.className = type === "success" ? "hr-success-message" : "hr-error-message";
    message.textContent = text;
    message.hidden = false;
  }

  function hideMessage() {
    message.hidden = true;
  }

  /* Вкладки */

  function renderTabs() {
    tabsEl.replaceChildren(...tabs.map(id => {
      const button = document.createElement("button");
      const active = id === tab;

      button.type = "button";
      button.className = `hr-tab${active ? " is-active" : ""}`;
      button.dataset.tab = id;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(active));
      button.textContent = tabLabels[id];

      return button;
    }));

    chatPanel.hidden = tab !== "chat";
    escPanel.hidden = tab !== "escalations";
    statusSelect.hidden = tab !== "escalations";
  }

  function setTab(id) {
    tab = id;
    hideMessage();
    renderTabs();

    if (tab === "escalations") {
      loadEscalations();
    } else {
      scrollChat();
    }
  }

  /* Чат */

  function scrollChat() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function resizeInput() {
    chatInput.style.height = "auto";
    chatInput.style.height = `${Math.min(chatInput.scrollHeight, 140)}px`;
  }

  function setChatBusy(value) {
    chatBusy = value;
    chatSend.disabled = value;
    chatInput.disabled = value;
  }

  function renderEscalateBox(box, entry) {
    box.replaceChildren();

    if (entry.escalate.done) {
      const note = document.createElement("span");

      note.className = "hr-chat-note";
      note.textContent = `Вопрос передан HR. Ответ появится во вкладке «${tabLabels.escalations}».`;

      box.append(note);
      return;
    }

    const button = document.createElement("button");

    button.type = "button";
    button.className = "hr-secondary-button";
    button.textContent = "Передать вопрос HR";
    button.addEventListener("click", () => escalate(entry, box, button));

    box.append(button);
  }

  function buildMessage(entry) {
    const node = messageTemplate.content.firstElementChild.cloneNode(true);

    node.classList.add(entry.role === "user" ? "is-user" : "is-assistant");
    node.classList.toggle("is-error", Boolean(entry.error));
    node.querySelector(".hr-chat-text").textContent = entry.text;

    if (entry.role !== "assistant") {
      node.querySelector(".irbi-avatar")?.remove();
      return node;
    }

    const avatar = node.querySelector(".irbi-avatar");
    if (avatar) {
      avatar.innerHTML = irbiSvg(entry.state || "idle");
      avatar.hidden = false;
    }

    if (entry.confidence && entry.mode !== "chat" && entry.confidence !== "none") {
      const key = String(entry.confidence).toLowerCase();
      const meta = node.querySelector(".hr-chat-meta");
      const parts = [`Уверенность: ${CONFIDENCE_LABELS[key] || entry.confidence}`];

      if (MODE_LABELS[entry.mode]) parts.push(MODE_LABELS[entry.mode]);
      meta.textContent = parts.join(" · ");
      meta.hidden = false;
    }

    if (entry.sources?.length) {
      const sourcesEl = node.querySelector(".hr-chat-sources");
      const sourcesList = node.querySelector(".hr-chat-sources-list");

      sourcesList.replaceChildren(...entry.sources.map(source => {
        const item = document.createElement("li");
        const text = document.createElement("span");

        item.className = "hr-chat-source";
        item.insertAdjacentHTML("afterbegin", `<svg viewBox="0 0 24 24" aria-hidden="true">${FILE_ICON}</svg>`);

        text.textContent = [source.document, source.section].filter(Boolean).join(" · ") || DASH;
        if (source.file) item.title = source.file;

        item.append(text);

        return item;
      }));

      sourcesEl.hidden = false;
    }

    if (entry.escalate) {
      const box = node.querySelector(".hr-chat-actions");

      renderEscalateBox(box, entry);
      box.hidden = false;
    }

    return node;
  }

  function appendEntry(entry) {
    welcome.hidden = true;
    messagesEl.append(buildMessage(entry));
    scrollChat();
  }

  function history() {
    return chatLog.filter(e => e.role === "user").slice(-5, -1).map(e => e.text).slice(-4);
  }

  async function* streamEvents(question) {
    const token = sessionStorage.getItem("access_token");
    const response = await fetch(`${API_BASE_URL}/assistant/ask/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ question, history: history() })
    });

    if (!response.ok || !response.body) {
      const data = await response.json().catch(() => null);
      throw new Error(data?.message || `Сервер вернул ошибку HTTP ${response.status}.`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let index;
      while ((index = buffer.indexOf("\n\n")) >= 0) {
        const raw = buffer.slice(0, index).trim();
        buffer = buffer.slice(index + 2);
        if (raw.startsWith("data:")) yield JSON.parse(raw.slice(5).trim());
      }
    }
  }

  async function ask(text) {
    const question = String(text || "").trim();

    if (!question || chatBusy) return;

    hideMessage();
    chatInput.value = "";
    resizeInput();

    const userEntry = { role: "user", text: question };

    chatLog.push(userEntry);
    appendEntry(userEntry);

    const typing = typingTemplate.content.firstElementChild.cloneNode(true);

    typing.querySelector(".irbi-avatar")?.insertAdjacentHTML("afterbegin", irbiSvg("thinking"));
    messagesEl.append(typing);
    scrollChat();
    setChatBusy(true);

    const entry = { role: "assistant", text: "", confidence: "", sources: [], escalate: null, mode: "" };
    let node = null;
    let typer = null;

    try {
      for await (const event of streamEvents(question)) {
        if (event.type === "meta") {
          Object.assign(entry, {
            confidence: event.confidence || "",
            sources: Array.isArray(event.sources) ? event.sources : [],
            mode: event.mode || "",
            escalate: event.can_escalate !== false && (event.can_escalate || event.found === false)
              ? { question, found: Boolean(event.found), done: false }
              : null
          });
        } else if (event.type === "token") {
          if (!node) {
            typing.remove();
            node = buildMessage({ role: "assistant", text: "", state: "typing" });
            const textEl = node.querySelector(".hr-chat-text");
            textEl.classList.add("hr-chat-cursor");
            typer = createTyper(textEl, { onTick: scrollChat });
            messagesEl.append(node);
          }
          entry.text += event.text;
          typer.push(event.text);
        }
      }
      if (typer) await typer.idle();
      if (!entry.text) entry.text = "Не удалось получить ответ.";
    } catch (error) {
      console.error("Ошибка вопроса ассистенту:", error);
      Object.assign(entry, {
        text: entry.text || error.message || "Не удалось получить ответ. Попробуйте ещё раз.",
        error: !entry.text
      });
    }

    typing.remove();
    const finalNode = buildMessage(entry);
    if (node) node.replaceWith(finalNode);
    else messagesEl.append(finalNode);
    chatLog.push(entry);
    scrollChat();

    setChatBusy(false);
    chatInput.focus();
  }

  async function loadAiStatus() {
    const chip = root.querySelector("#ai-status");
    if (!chip) return;
    try {
      const st = await apiFetch("/assistant/status");
      if (st.mode === "qwen") {
        chip.className = `ws-ai-status ${st.loaded ? "is-on" : "is-loading"}`;
        chip.textContent = st.loaded ? "Ирби на связи · Qwen2.5-3B" : "Ирби просыпается: модель загружается...";
        if (!st.loaded && root.isConnected) setTimeout(loadAiStatus, 4000);
      } else {
        chip.className = "ws-ai-status";
        chip.textContent = st.model_file ? "Ирби без нейросети — ответы цитатами из базы" : "Модель не скачана — Ирби отвечает цитатами из базы";
      }
    } catch {
      chip.hidden = true;
    }
  }

  async function escalate(entry, box, button) {
    button.disabled = true;
    button.textContent = "Передаём...";
    hideMessage();

    try {
      await apiFetch("/assistant/escalate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: entry.escalate.question,
          context: entry.escalate.found
            ? "Ответ ассистента не помог"
            : "Ассистент не нашёл ответ"
        })
      });

      entry.escalate.done = true;
      renderEscalateBox(box, entry);
    } catch (error) {
      console.error("Ошибка передачи вопроса HR:", error);

      button.disabled = false;
      button.textContent = "Передать вопрос HR";
      showMessage(error.message || "Не удалось передать вопрос HR.");
    }
  }

  function showLoading() {
    escState.replaceChildren(loadingTemplate.content.cloneNode(true));
  }

  function showEmpty() {
    const node = emptyTemplate.content.cloneNode(true);
    const texts = statusSelect.value
      ? { title: "Ничего не найдено", description: "Попробуйте изменить фильтр." }
      : hr
        ? { title: "Обращений нет", description: "Когда сотрудники передадут вопросы, они появятся здесь." }
        : { title: "Обращений пока нет", description: "Если ассистент не нашёл ответ, передайте вопрос HR, и он появится здесь." };

    node.querySelector(".hr-empty-title").textContent = texts.title;
    node.querySelector(".hr-empty-description").textContent = texts.description;

    escState.replaceChildren(node);
  }

  function showLoadError(text) {
    const node = errorTemplate.content.cloneNode(true);

    node.querySelector(".hr-empty-description").textContent = text;
    node.querySelector(".hr-retry-button").addEventListener("click", () => loadEscalations());

    escState.replaceChildren(node);
  }

  function createItem(item) {
    const node = itemTemplate.content.cloneNode(true);

    node.querySelector(".hr-request-item").dataset.id = String(item.id);
    node.querySelector(".hr-request-title").textContent = item.question || DASH;
    setStatus(node.querySelector(".hr-status"), item);

    const summary = node.querySelector(".hr-request-summary");

    summary.textContent = item.answer || "";
    summary.hidden = !item.answer;

    const meta = [];

    if (hr && item.user?.full_name) meta.push(item.user.full_name);
    meta.push(formatRelativeTime(item.created_at));

    const metaEl = node.querySelector(".hr-request-meta");

    metaEl.textContent = meta.join(" · ");
    metaEl.title = formatDateTime(item.created_at);

    return node;
  }

  function renderList() {
    escList.replaceChildren(...items.map(createItem));

    if (items.length) {
      escState.replaceChildren();
    } else {
      showEmpty();
    }
  }

  async function loadEscalations({ silent = false } = {}) {
    const token = ++loadToken;
    const params = new URLSearchParams();

    if (statusSelect.value) params.set("status", statusSelect.value);

    const query = params.toString();

    if (!silent) {
      hideMessage();
      escList.replaceChildren();
      showLoading();
    }

    try {
      const data = await apiFetch(`/assistant/escalations${query ? `?${query}` : ""}`);

      if (token !== loadToken || !root.isConnected) return;

      items = (Array.isArray(data) ? data : []).sort(
        (a, b) => new Date(b.created_at) - new Date(a.created_at)
      );

      renderList();
    } catch (error) {
      if (token !== loadToken || !root.isConnected) return;

      console.error("Ошибка загрузки обращений:", error);

      if (silent) {
        showMessage(error.message || "Не удалось обновить список обращений.");
      } else {
        showLoadError(error.message || "Проверьте соединение с сервером.");
      }
    }
  }

  function showDialogMessage(text) {
    dialogMessage.textContent = text;
    dialogMessage.hidden = false;
  }

  function renderDialog() {
    const item = current;
    const canReply = hr && item.status === "open";

    dialogTitle.textContent = "Обращение";
    setStatus(dialogStatus, item);

    dialogQuestion.textContent = item.question || DASH;

    dialogContextBlock.hidden = !item.context;
    dialogContext.textContent = item.context || "";

    dialogAnswer.textContent = item.answer || "HR пока не ответил на это обращение.";

    const cards = [];

    if (hr) cards.push(["Сотрудник", val(item.user?.full_name)]);

    cards.push(["Создано", formatDateTime(item.created_at)]);

    if (item.answered_by?.full_name) cards.push(["Ответил", item.answered_by.full_name]);
    if (item.answered_at) cards.push(["Дата ответа", formatDateTime(item.answered_at)]);

    dialogMeta.replaceChildren(...cards.map(([label, value]) => createInfoCard(label, value)));

    replyBox.hidden = !canReply;
    answerButton.hidden = !canReply;
    answerButton.disabled = busy;
  }

  function openDetails(id) {
    const item = items.find(entry => String(entry.id) === id);

    if (!item) return;

    current = item;
    busy = false;
    replyInput.value = "";
    dialogMessage.hidden = true;

    renderDialog();
    dialog.showModal();
  }

  async function submitAnswer() {
    if (!current || busy) return;

    const answer = replyInput.value.trim();

    dialogMessage.hidden = true;

    if (!answer) {
      showDialogMessage("Введите текст ответа.");
      replyInput.focus();
      return;
    }

    busy = true;
    renderDialog();

    try {
      const updated = await apiFetch(`/assistant/escalations/${enc(current.id)}/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer })
      });

      const index = items.findIndex(entry => entry.id === updated.id);

      if (index >= 0) items[index] = updated;

      current = updated;
      replyInput.value = "";
      busy = false;

      if (dialog.open) renderDialog();

      loadEscalations({ silent: true });
    } catch (error) {
      console.error("Ошибка отправки ответа:", error);

      busy = false;

      if (current) renderDialog();

      showDialogMessage(error.message || "Не удалось отправить ответ.");
    }
  }

  /* События */

  tabsEl.addEventListener("click", event => {
    const button = event.target.closest("[data-tab]");

    if (!button || button.dataset.tab === tab) return;

    setTab(button.dataset.tab);
  });

  statusSelect.addEventListener("change", () => loadEscalations());

  suggestionsEl.replaceChildren(...SUGGESTIONS.map(text => {
    const chip = document.createElement("button");

    chip.type = "button";
    chip.className = "hr-chip";
    chip.textContent = text;
    chip.addEventListener("click", () => ask(text));

    return chip;
  }));

  chatForm.addEventListener("submit", event => {
    event.preventDefault();
    ask(chatInput.value);
  });

  chatInput.addEventListener("input", resizeInput);

  chatInput.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      chatForm.requestSubmit();
    }
  });

  escList.addEventListener("click", event => {
    const item = event.target.closest(".hr-request-item");

    if (item) openDetails(item.dataset.id);
  });

  answerButton.addEventListener("click", submitAnswer);

  dialog.addEventListener("click", event => {
    if (event.target === dialog || event.target.closest("[data-close]")) {
      dialog.close();
    }
  });

  dialog.addEventListener("close", () => {
    current = null;
  });

  /* Старт */

  const welcomeIrbi = root.querySelector("#chat-welcome-irbi");
  if (welcomeIrbi) welcomeIrbi.innerHTML = irbiSvg("idle");

  chatLog.forEach(entry => messagesEl.append(buildMessage(entry)));
  welcome.hidden = chatLog.length > 0;

  renderTabs();
  scrollChat();
  chatInput.focus();
  loadAiStatus();
}