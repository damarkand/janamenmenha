import { apiFetch, formatDate } from "../utils.js";

const DEFAULT_CATEGORIES = ["Общее", "Отчётность", "Встречи", "Документы", "Клиенты", "Разработка", "Тестирование", "Обучение"];
const NEXT = { todo: ["in_progress", "В работу"], in_progress: ["done", "Готово"], done: ["todo", "Вернуть"] };
const enc = encodeURIComponent;

function isManager(user) {
  return user?.role === "manager" || user?.role === "hr";
}

export async function init(root, user) {
  const q = s => root.querySelector(s);
  const tabsEl = q("#task-tabs");
  const memberSelect = q("#task-member");
  const categorySelect = q("#task-category");
  const message = q("#task-message");
  const state = q("#task-state");
  const board = q("#task-board");

  const dialog = q("#task-dialog");
  const form = q("#task-form");
  const dialogTitle = q("#task-dialog-title");
  const dialogMessage = q("#task-dialog-message");
  const assigneeField = q("#task-assignee-field");
  const assigneeSelect = q("#task-assignee");
  const deleteButton = q("#task-delete");
  const saveButton = q("#task-save");
  const info = q("#task-info");

  const manager = isManager(user);
  let scope = sessionStorage.getItem("tasks_scope") === "team" && manager ? "team" : "mine";
  let team = [];
  let tasks = [];
  let editing = null;
  let loadToken = 0;

  const presetMember = sessionStorage.getItem("tasks_member");
  sessionStorage.removeItem("tasks_scope");
  sessionStorage.removeItem("tasks_member");

  function showMessage(text, type = "error") {
    message.className = type === "success" ? "hr-success-message" : "hr-error-message";
    message.textContent = text;
    message.hidden = false;
  }

  function renderTabs() {
    const tabs = manager ? [["mine", "Мои"], ["team", "Команда"]] : [["mine", "Мои"]];
    tabsEl.replaceChildren(...tabs.map(([id, label]) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = `hr-tab${id === scope ? " is-active" : ""}`;
      b.dataset.tab = id;
      b.textContent = label;
      return b;
    }));
    memberSelect.hidden = scope !== "team";
  }

  function renderCategories() {
    const set = new Set([...DEFAULT_CATEGORIES, ...tasks.map(t => t.category)]);
    const current = categorySelect.value;
    categorySelect.replaceChildren(new Option("Все категории", ""), ...[...set].map(c => new Option(c, c)));
    categorySelect.value = set.has(current) ? current : "";
    q("#task-categories").replaceChildren(...[...set].map(c => new Option(c)));
  }

  function taskCard(t) {
    const card = document.createElement("article");
    card.className = `ws-task${t.status === "done" ? " is-done" : ""}`;
    card.dataset.id = t.id;

    const title = document.createElement("div");
    title.className = "ws-task-title";
    title.textContent = t.title;

    const meta = document.createElement("div");
    meta.className = "ws-task-meta";
    meta.innerHTML = `<span class="ws-priority is-${t.priority}" title="Приоритет: ${t.priority_label}"></span>`;
    const cat = document.createElement("span");
    cat.className = "ws-tag";
    cat.textContent = t.category;
    meta.append(cat);
    if (t.due_date) {
      const due = document.createElement("span");
      due.className = t.overdue ? "ws-tag is-danger" : "";
      due.textContent = t.overdue ? `просрочена · ${formatDate(t.due_date)}` : `до ${formatDate(t.due_date)}`;
      meta.append(due);
    }
    if (scope === "team" || t.assignee?.id !== user.id) {
      const who = document.createElement("span");
      who.textContent = t.assignee?.full_name || "";
      meta.append(who);
    }

    const actions = document.createElement("div");
    actions.className = "ws-task-actions";
    const [next, label] = NEXT[t.status];
    const move = document.createElement("button");
    move.type = "button";
    move.className = "ws-mini-button";
    move.dataset.move = next;
    move.textContent = label;
    actions.append(move);

    card.append(title, meta, actions);
    return card;
  }

  function render() {
    const category = categorySelect.value;
    const visible = tasks.filter(t => !category || t.category === category);
    board.querySelectorAll(".ws-column").forEach(col => {
      const items = visible.filter(t => t.status === col.dataset.status);
      col.querySelector("[data-count]").textContent = items.length;
      const bodyEl = col.querySelector(".ws-column-body");
      bodyEl.replaceChildren(...items.map(taskCard));
      if (!items.length) bodyEl.innerHTML = '<div class="ws-empty">Пусто</div>';
    });
    state.replaceChildren();
    board.hidden = false;
  }

  async function loadTeam() {
    if (!manager || team.length) return;
    try {
      team = await apiFetch("/users");
    } catch {
      team = [];
    }
    memberSelect.replaceChildren(new Option("Вся команда", ""), ...team.map(m => new Option(m.full_name, m.id)));
    if (presetMember) memberSelect.value = presetMember;
  }

  async function load() {
    const token = ++loadToken;
    state.innerHTML = '<div class="hr-page-loading"><span class="hr-spinner"></span><span>Загружаем задачи...</span></div>';
    const params = new URLSearchParams({ scope });
    if (scope === "team" && memberSelect.value) params.set("user_id", memberSelect.value);
    try {
      const data = await apiFetch(`/tasks?${params}`);
      if (token !== loadToken || !root.isConnected) return;
      tasks = data;
      renderCategories();
      render();
    } catch (error) {
      if (token !== loadToken) return;
      board.hidden = true;
      state.innerHTML = '<div class="hr-empty-state"><h2 class="hr-empty-title">Не удалось загрузить задачи</h2><p class="hr-empty-description"></p></div>';
      state.querySelector(".hr-empty-description").textContent = error.message;
    }
  }

  function openDialog(task = null) {
    editing = task;
    form.reset();
    dialogMessage.hidden = true;
    dialogTitle.textContent = task ? "Задача" : "Новая задача";
    q("#task-title").value = task?.title || "";
    q("#task-description").value = task?.description || "";
    q("#task-category-input").value = task?.category || (categorySelect.value || "Общее");
    q("#task-priority").value = task?.priority || "medium";
    q("#task-due").value = task?.due_date || "";
    deleteButton.hidden = !task;

    const canAssign = !task && manager;
    assigneeField.hidden = !canAssign;
    if (canAssign) {
      assigneeSelect.replaceChildren(new Option("Себе", ""), ...team.map(m => new Option(m.full_name, m.id)));
      assigneeSelect.value = scope === "team" ? memberSelect.value || "" : "";
    }

    if (task) {
      const parts = [`Исполнитель: ${task.assignee?.full_name || "—"}`];
      if (task.created_by && task.created_by.id !== task.assignee?.id) parts.push(`поставил(а): ${task.created_by.full_name}`);
      parts.push(`статус: ${task.status_label}`);
      info.textContent = parts.join(" · ");
      info.hidden = false;
    } else {
      info.hidden = true;
    }
    dialog.showModal();
    q("#task-title").focus();
  }

  async function changeStatus(id, status, button) {
    button.disabled = true;
    try {
      const updated = await apiFetch(`/tasks/${enc(id)}/status`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status })
      });
      tasks = tasks.map(t => (t.id === id ? updated : t));
      render();
    } catch (error) {
      button.disabled = false;
      showMessage(error.message);
    }
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    const payload = {
      title: q("#task-title").value.trim(),
      description: q("#task-description").value.trim(),
      category: q("#task-category-input").value.trim() || "Общее",
      priority: q("#task-priority").value,
      due_date: q("#task-due").value || null
    };
    if (!payload.title) {
      dialogMessage.textContent = "Укажите название задачи.";
      dialogMessage.hidden = false;
      return;
    }
    saveButton.disabled = true;
    try {
      if (editing) {
        await apiFetch(`/tasks/${enc(editing.id)}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
        });
      } else {
        if (!assigneeField.hidden && assigneeSelect.value) payload.user_id = assigneeSelect.value;
        await apiFetch("/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      }
      dialog.close();
      await load();
    } catch (error) {
      dialogMessage.textContent = error.message;
      dialogMessage.hidden = false;
    } finally {
      saveButton.disabled = false;
    }
  });

  deleteButton.addEventListener("click", async () => {
    if (!editing) return;
    deleteButton.disabled = true;
    try {
      await apiFetch(`/tasks/${enc(editing.id)}`, { method: "DELETE" });
      dialog.close();
      await load();
    } catch (error) {
      dialogMessage.textContent = error.message;
      dialogMessage.hidden = false;
    } finally {
      deleteButton.disabled = false;
    }
  });

  dialog.addEventListener("click", event => {
    if (event.target === dialog || event.target.closest("[data-close]")) dialog.close();
  });

  board.addEventListener("click", event => {
    const move = event.target.closest("[data-move]");
    const card = event.target.closest(".ws-task");
    if (!card) return;
    if (move) {
      changeStatus(card.dataset.id, move.dataset.move, move);
      return;
    }
    openDialog(tasks.find(t => t.id === card.dataset.id));
  });

  tabsEl.addEventListener("click", async event => {
    const b = event.target.closest("[data-tab]");
    if (!b || b.dataset.tab === scope) return;
    scope = b.dataset.tab;
    renderTabs();
    await loadTeam();
    load();
  });

  memberSelect.addEventListener("change", load);
  categorySelect.addEventListener("change", render);
  q("#task-new").addEventListener("click", async () => {
    await loadTeam();
    openDialog();
  });

  renderTabs();
  if (scope === "team") await loadTeam();
  await load();
}
