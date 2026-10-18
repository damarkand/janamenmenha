import { DASH, apiFetch, formatDate, formatDateTime, val } from "../utils.js";

const STATUS_LABELS = {
  not_started: "Не начат",
  in_progress: "В процессе",
  completed: "Завершён",
  failed: "Не сдан"
};

const TAB_LABELS = {
  my: "Мои курсы",
  catalog: "Каталог",
  team: "Команда"
};

const EMPTY_TEXTS = {
  my: {
    title: "Назначенных курсов пока нет",
    description: "Запишитесь на курс в каталоге, или курс назначит руководитель."
  },
  catalog: {
    title: "Каталог пуст",
    description: "Курсы появятся здесь, когда их добавят."
  },
  team: {
    title: "Назначений нет",
    description: "Назначьте курс сотруднику, и его прогресс появится здесь."
  }
};

const enc = encodeURIComponent;

function canManage(user) {
  const role = `${user?.role ?? ""} ${user?.role_label ?? ""}`.toLowerCase();

  return /\bhr\b|hr-|кадр|manager|head|lead|руковод|начальник/.test(role);
}

function clampProgress(value) {
  return Math.min(100, Math.max(0, Math.round(Number(value) || 0)));
}

function courseSummary(course) {
  return [
    course.category,
    course.duration_min ? `${course.duration_min} мин` : "",
    course.passing_score ? `проходной балл: ${course.passing_score}%` : ""
  ].filter(Boolean).join(" · ");
}

function setStatus(element, assignment) {
  element.hidden = false;
  element.className = `hr-status is-${assignment.status}`;
  element.textContent = assignment.status_label || STATUS_LABELS[assignment.status] || val(assignment.status);
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

function todayString() {
  const now = new Date();
  const pad = n => String(n).padStart(2, "0");

  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function init(root, user) {
  user = user || {};

  /* Элементы */

  const q = selector => root.querySelector(selector);

  const tabsEl = q("#learning-tabs");
  const categorySelect = q("#learning-category");
  const userSelect = q("#learning-user");
  const assignButton = q("#learning-assign");
  const message = q("#learning-message");
  const state = q("#learning-state");
  const list = q("#learning-list");

  const itemTemplate = q("#learning-item-template");
  const loadingTemplate = q("#learning-loading-template");
  const emptyTemplate = q("#learning-empty-template");
  const errorTemplate = q("#learning-error-template");

  const detailsDialog = q("#learning-details-dialog");
  const detailsTitle = q("#learning-details-title");
  const detailsStatus = q("#learning-details-status");
  const description = q("#learning-description");
  const materialLink = q("#learning-material");
  const infoGrid = q("#learning-info");
  const progressSection = q("#learning-progress-section");
  const progressBar = q("#learning-progress-bar");
  const progressValue = q("#learning-progress-value");
  const progressRange = q("#learning-progress-range");
  const testSection = q("#learning-test-section");
  const testForm = q("#learning-test-form");
  const resultBox = q("#learning-result");
  const detailsMessage = q("#learning-details-message");

  const actions = {};
  detailsDialog?.querySelectorAll(".hr-dialog-footer [data-action]").forEach(button => {
    actions[button.dataset.action] = button;
  });

  const assignDialog = q("#learning-assign-dialog");
  const assignForm = q("#learning-assign-form");
  const assignMessage = q("#assign-message");
  const assignSubmit = q("#assign-submit");
  const assignUsers = q("#assign-users");
  const assignCourse = q("#assign-course");
  const assignDue = q("#assign-due");

  if (
    !tabsEl || !categorySelect || !userSelect || !assignButton || !message || !state || !list ||
    !itemTemplate || !detailsDialog || !assignDialog || !assignForm
  ) {
    return;
  }

  /* Состояние */

  const tabs = canManage(user) ? ["my", "catalog", "team"] : ["my", "catalog"];

  let tab = "my";
  let myItems = [];
  let catalogItems = [];
  let teamItems = [];
  let loadToken = 0;
  let busy = false;

  let dlg = null;

  const findAssignment = courseId =>
    myItems.find(item => item.course?.id === courseId) || null;

  const isDone = assignment => assignment?.status === "completed";

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

  function showEmpty(filtered) {
    const node = emptyTemplate.content.cloneNode(true);
    const texts = filtered
      ? { title: "Ничего не найдено", description: "Попробуйте изменить фильтр." }
      : EMPTY_TEXTS[tab];

    node.querySelector(".hr-empty-title").textContent = texts.title;
    node.querySelector(".hr-empty-description").textContent = texts.description;

    state.replaceChildren(node);
  }

  function showLoadError(text) {
    const node = errorTemplate.content.cloneNode(true);

    node.querySelector(".hr-empty-description").textContent = text;
    node.querySelector(".hr-retry-button").addEventListener("click", () => loadTab());

    state.replaceChildren(node);
  }

  /* Вкладки и фильтры */

  function renderTabs() {
    tabsEl.hidden = tabs.length < 2;

    tabsEl.replaceChildren(...tabs.map(id => {
      const button = document.createElement("button");
      const active = id === tab;

      button.type = "button";
      button.className = `hr-tab${active ? " is-active" : ""}`;
      button.dataset.tab = id;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(active));
      button.textContent = TAB_LABELS[id];

      return button;
    }));

    categorySelect.hidden = tab !== "catalog";
    userSelect.hidden = tab !== "team";
    assignButton.hidden = tab !== "team";
  }

  function fillSelect(select, firstLabel, entries) {
    const previous = select.value;

    select.replaceChildren(new Option(firstLabel, ""));
    entries.forEach(([value, label]) => select.append(new Option(label, value)));

    select.value = entries.some(([value]) => value === previous) ? previous : "";
  }

  function updateCategories() {
    const categories = [...new Set(catalogItems.map(course => course.category).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b, "ru"));

    fillSelect(categorySelect, "Все категории", categories.map(name => [name, name]));
  }

  function getTeamUsers() {
    const users = new Map();

    teamItems.forEach(item => {
      if (item.user?.id) users.set(item.user.id, item.user.full_name || item.user.id);
    });

    return [...users.entries()].sort((a, b) => a[1].localeCompare(b[1], "ru"));
  }

  function updateUsers() {
    const users = getTeamUsers();

    fillSelect(userSelect, "Все сотрудники", users);

    assignUsers.replaceChildren(...users.map(([id, name]) => {
      const option = document.createElement("option");

      option.value = id;
      option.label = name;

      return option;
    }));
  }

  /* Список */

  function createProgress(node, value) {
    const percent = clampProgress(value);

    node.querySelector(".hr-progress-bar").style.width = `${percent}%`;
    node.querySelector(".hr-progress-value").textContent = `${percent}%`;
  }

  function createAssignmentItem(assignment) {
    const node = itemTemplate.content.cloneNode(true);
    const course = assignment.course || {};

    node.querySelector(".hr-learning-item").dataset.id = String(assignment.id);
    node.querySelector(".hr-request-title").textContent = course.title || DASH;
    setStatus(node.querySelector(".hr-status"), assignment);

    const summary = node.querySelector(".hr-request-summary");
    summary.textContent = courseSummary(course);
    summary.hidden = !summary.textContent;

    createProgress(node, assignment.progress);

    const meta = [];

    if (tab === "team" && assignment.user?.full_name) meta.push(assignment.user.full_name);
    if (course.mandatory) meta.push("Обязательный");
    if (assignment.due_date) meta.push(`Срок: ${formatDate(assignment.due_date)}`);
    if (assignment.attempts > 0) meta.push(`Лучший результат: ${assignment.best_score ?? 0}%`);

    const metaEl = node.querySelector(".hr-request-meta");
    metaEl.textContent = meta.join(" · ");
    metaEl.hidden = !meta.length;

    return node;
  }

  function createCourseItem(course) {
    const node = itemTemplate.content.cloneNode(true);
    const assignment = findAssignment(course.id);
    const statusEl = node.querySelector(".hr-status");

    node.querySelector(".hr-learning-item").dataset.id = String(course.id);
    node.querySelector(".hr-request-title").textContent = course.title || DASH;

    if (assignment) {
      setStatus(statusEl, assignment);
    } else if (course.mandatory) {
      statusEl.className = "hr-status is-pending";
      statusEl.textContent = "Обязательный";
    } else {
      statusEl.hidden = true;
    }

    const summary = node.querySelector(".hr-request-summary");
    summary.textContent = course.description || courseSummary(course);
    summary.hidden = !summary.textContent;

    node.querySelector(".hr-progress").hidden = true;

    const meta = courseSummary(course);
    const metaEl = node.querySelector(".hr-request-meta");
    metaEl.textContent = course.description ? meta : "";
    metaEl.hidden = !metaEl.textContent;

    node.querySelector('[data-action="enroll"]').hidden = Boolean(assignment);

    return node;
  }

  function getVisibleItems() {
    if (tab === "catalog") {
      return categorySelect.value
        ? catalogItems.filter(course => course.category === categorySelect.value)
        : catalogItems;
    }

    if (tab === "team") {
      return userSelect.value
        ? teamItems.filter(item => item.user?.id === userSelect.value)
        : teamItems;
    }

    return myItems;
  }

  function render() {
    const visible = getVisibleItems();

    list.replaceChildren(...visible.map(tab === "catalog" ? createCourseItem : createAssignmentItem));

    if (visible.length) {
      state.replaceChildren();
    } else {
      showEmpty(tab !== "my" && Boolean(categorySelect.value || userSelect.value));
    }
  }

  async function loadTab({ silent = false } = {}) {
    const token = ++loadToken;

    if (!silent) {
      hideMessage();
      list.replaceChildren();
      showLoading();
    }

    try {
      let result;

      if (tab === "catalog") {
        const [courses, mine] = await Promise.all([
          apiFetch("/academy/courses"),
          apiFetch("/academy/my")
        ]);

        result = { courses, mine };
      } else if (tab === "team") {
        result = { team: await apiFetch("/academy/team-progress") };
      } else {
        result = { mine: await apiFetch("/academy/my") };
      }

      if (token !== loadToken || !root.isConnected) return;

      if (result.courses) catalogItems = Array.isArray(result.courses) ? result.courses : [];
      if (result.mine) myItems = Array.isArray(result.mine) ? result.mine : [];
      if (result.team) teamItems = Array.isArray(result.team) ? result.team : [];

      if (tab === "catalog") updateCategories();
      if (tab === "team") updateUsers();

      render();
    } catch (error) {
      if (token !== loadToken || !root.isConnected) return;

      console.error("Ошибка загрузки обучения:", error);

      if (silent) {
        showMessage(error.message || "Не удалось обновить данные.");
      } else {
        showLoadError(error.message || "Проверьте соединение с сервером.");
      }
    }
  }

  function setTab(id) {
    tab = id;
    renderTabs();
    loadTab();
  }

  function applyAssignment(assignment) {
    const index = myItems.findIndex(item =>
      item.id === assignment.id || item.course?.id === assignment.course?.id
    );

    if (index >= 0) {
      myItems[index] = assignment;
    } else {
      myItems.unshift(assignment);
    }

    if (dlg && dlg.course.id === assignment.course?.id) {
      dlg.assignment = assignment;
    }

    render();
  }

  /* Карточка курса */

  function showDetailsMessage(text) {
    detailsMessage.textContent = text;
    detailsMessage.hidden = false;
  }

  function renderInfo() {
    const { course, assignment, readonly } = dlg;
    const cards = [
      ["Категория", val(course.category)],
      ["Длительность", course.duration_min ? `${course.duration_min} мин` : DASH],
      ["Проходной балл", course.passing_score ? `${course.passing_score}%` : DASH],
      ["Вопросов в тесте", val(course.questions_count)],
      ["Обязательный", course.mandatory ? "Да" : "Нет"]
    ];

    if (assignment) {
      if (readonly) cards.unshift(["Сотрудник", val(assignment.user?.full_name)]);
      if (assignment.assigned_by?.full_name) cards.push(["Назначил", assignment.assigned_by.full_name]);
      if (assignment.assigned_at) cards.push(["Назначен", formatDateTime(assignment.assigned_at)]);
      if (assignment.due_date) cards.push(["Срок", formatDate(assignment.due_date)]);
      if (assignment.attempts > 0) {
        cards.push(["Лучший результат", `${assignment.best_score ?? 0}%`]);
        cards.push(["Попыток", String(assignment.attempts)]);
      }
      if (assignment.completed_at && isDone(assignment)) {
        cards.push(["Завершён", formatDateTime(assignment.completed_at)]);
      }
    }

    infoGrid.replaceChildren(...cards.map(([label, value]) => createInfoCard(label, value)));
  }

  function renderTest() {
    const questions = dlg.questions || [];

    testForm.replaceChildren(...questions.map((question, index) => {
      const fieldset = document.createElement("fieldset");
      const legend = document.createElement("legend");

      fieldset.className = "hr-question";
      legend.className = "hr-question-text";
      legend.textContent = `${index + 1}. ${question.text}`;

      fieldset.append(legend);

      (question.options || []).forEach((option, optionIndex) => {
        const label = document.createElement("label");
        const input = document.createElement("input");
        const text = document.createElement("span");

        label.className = "hr-option";
        input.type = "radio";
        input.name = `question-${index}`;
        input.value = String(optionIndex);
        text.textContent = option;

        label.append(input, text);
        fieldset.append(label);
      });

      return fieldset;
    }));
  }

  function renderDialog() {
    const { course, assignment, readonly, testMode, result } = dlg;
    const started = Boolean(assignment) && assignment.status !== "not_started";
    const canWork = !readonly && started && !isDone(assignment);

    detailsTitle.textContent = course.title || "Курс";

    if (assignment) {
      setStatus(detailsStatus, assignment);
    } else {
      detailsStatus.hidden = true;
    }

    description.textContent = course.description || "";
    description.hidden = !course.description;

    const link = String(course.material_link || "");
    const safeLink = /^https?:\/\//i.test(link);

    materialLink.hidden = !safeLink;
    if (safeLink) materialLink.href = link;

    renderInfo();

    // Прогресс
    progressSection.hidden = !assignment || testMode;

    if (assignment) {
      const percent = clampProgress(assignment.progress);

      progressBar.style.width = `${percent}%`;
      progressValue.textContent = `${percent}%`;
      progressRange.value = String(percent);
      progressRange.hidden = !canWork;
    }

    // Тест
    testSection.hidden = !testMode;

    // Результат последней попытки
    resultBox.hidden = !result;

    if (result) {
      resultBox.className = result.passed ? "hr-success-message" : "hr-error-message";
      resultBox.textContent = result.text;
    }

    // Кнопки
    actions.enroll.hidden = Boolean(assignment) || readonly;
    actions.start.hidden = !(assignment && !readonly && assignment.status === "not_started");
    actions.save.hidden = !(canWork && !testMode);
    actions.test.hidden = !(canWork && !testMode && course.questions_count > 0);
    actions.submit.hidden = !testMode;

    Object.values(actions).forEach(button => {
      button.disabled = busy;
    });
  }

  function openDialog(course, assignment, readonly) {
    dlg = { course, assignment, readonly, questions: null, testMode: false, result: null };

    detailsMessage.hidden = true;
    testForm.replaceChildren();
    renderDialog();
    detailsDialog.showModal();
  }

  function openFromList(id) {
    if (tab === "catalog") {
      const course = catalogItems.find(item => String(item.id) === id);

      if (course) openDialog(course, findAssignment(course.id), false);

      return;
    }

    const source = tab === "team" ? teamItems : myItems;
    const assignment = source.find(item => String(item.id) === id);

    if (assignment) openDialog(assignment.course || {}, assignment, tab === "team");
  }

  async function guarded(task) {
    if (busy) return;

    busy = true;
    detailsMessage.hidden = true;
    if (dlg) renderDialog();

    try {
      await task();
    } catch (error) {
      console.error("Ошибка действия:", error);
      showDetailsMessage(error.message || "Не удалось выполнить действие.");
    } finally {
      busy = false;
      if (dlg && detailsDialog.open) renderDialog();
    }
  }

  async function enrollCourse(courseId) {
    const assignment = await apiFetch(`/academy/courses/${enc(courseId)}/enroll`, { method: "POST" });

    applyAssignment(assignment);

    return assignment;
  }

  const dialogTasks = {
    enroll: () => enrollCourse(dlg.course.id),

    async start() {
      const assignment = await apiFetch(`/academy/my/${enc(dlg.course.id)}/start`, { method: "POST" });

      applyAssignment(assignment);
    },

    async save() {
      const assignment = await apiFetch(`/academy/my/${enc(dlg.course.id)}/progress`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ progress: clampProgress(progressRange.value) })
      });

      applyAssignment(assignment);
    },

    async test() {
      const course = await apiFetch(`/academy/courses/${enc(dlg.course.id)}`);

      dlg.questions = Array.isArray(course.questions) ? course.questions : [];

      if (!dlg.questions.length) {
        throw new Error("В этом курсе нет вопросов теста.");
      }

      dlg.testMode = true;
      dlg.result = null;
      renderTest();
    },

    async submit() {
      const answers = dlg.questions.map((_, index) => {
        const checked = testForm.querySelector(`input[name="question-${index}"]:checked`);

        return checked ? Number(checked.value) : null;
      });

      if (answers.some(answer => answer === null)) {
        throw new Error("Ответьте на все вопросы теста.");
      }

      const result = await apiFetch(`/academy/my/${enc(dlg.course.id)}/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers })
      });

      dlg.testMode = false;
      dlg.questions = null;
      testForm.replaceChildren();

      dlg.result = {
        passed: Boolean(result.passed),
        text: `${result.passed ? "Тест сдан" : "Тест не сдан"}. ` +
          `Результат: ${result.score}%, правильных ответов: ${result.correct} из ${result.total}. ` +
          `Проходной балл: ${result.passing_score}%.`
      };

      const mine = await apiFetch("/academy/my");

      myItems = Array.isArray(mine) ? mine : myItems;
      dlg.assignment = findAssignment(dlg.course.id) || dlg.assignment;

      render();
    }
  };

  /* Назначение курса */

  function showAssignMessage(text) {
    assignMessage.textContent = text;
    assignMessage.hidden = false;
  }

  async function openAssignDialog() {
    assignForm.reset();
    assignMessage.hidden = true;
    assignDue.min = todayString();

    assignDialog.showModal();

    if (!catalogItems.length) {
      try {
        const courses = await apiFetch("/academy/courses");

        catalogItems = Array.isArray(courses) ? courses : [];
      } catch (error) {
        showAssignMessage(error.message || "Не удалось загрузить список курсов.");
      }
    }

    assignCourse.replaceChildren(
      new Option("Выберите курс", ""),
      ...catalogItems.map(course => new Option(course.title, course.id))
    );
  }

  async function submitAssign(event) {
    event.preventDefault();
    assignMessage.hidden = true;

    const data = new FormData(assignForm);
    const body = {
      user_id: String(data.get("user_id") || "").trim(),
      course_id: String(data.get("course_id") || "")
    };

    const dueDate = String(data.get("due_date") || "");

    if (dueDate) body.due_date = dueDate;

    if (!body.user_id || !body.course_id) {
      showAssignMessage("Укажите сотрудника и выберите курс.");
      return;
    }

    assignSubmit.disabled = true;
    assignSubmit.textContent = "Назначаем...";

    try {
      await apiFetch("/academy/assignments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });

      assignDialog.close();

      await loadTab({ silent: true });
      showMessage("Курс назначен сотруднику.", "success");
    } catch (error) {
      console.error("Ошибка назначения курса:", error);
      showAssignMessage(error.message || "Не удалось назначить курс.");
    } finally {
      assignSubmit.disabled = false;
      assignSubmit.textContent = "Назначить";
    }
  }

  /* События */

  tabsEl.addEventListener("click", event => {
    const button = event.target.closest("[data-tab]");

    if (!button || button.dataset.tab === tab) return;

    setTab(button.dataset.tab);
  });

  categorySelect.addEventListener("change", render);
  userSelect.addEventListener("change", render);

  list.addEventListener("click", async event => {
    const button = event.target.closest("[data-action]");
    const item = event.target.closest(".hr-learning-item");

    if (!button || !item) return;

    const id = item.dataset.id;

    if (button.dataset.action === "open") {
      openFromList(id);
      return;
    }

    if (button.dataset.action === "enroll") {
      button.disabled = true;
      hideMessage();

      try {
        await enrollCourse(id);
        showMessage("Вы записаны на курс. Он появился в разделе «Мои курсы».", "success");
      } catch (error) {
        console.error("Ошибка записи на курс:", error);
        showMessage(error.message || "Не удалось записаться на курс.");
        button.disabled = false;
      }
    }
  });

  Object.entries(actions).forEach(([kind, button]) => {
    button.addEventListener("click", () => guarded(dialogTasks[kind]));
  });

  progressRange.addEventListener("input", () => {
    const percent = clampProgress(progressRange.value);

    progressBar.style.width = `${percent}%`;
    progressValue.textContent = `${percent}%`;
  });

  assignButton.addEventListener("click", openAssignDialog);
  assignForm.addEventListener("submit", submitAssign);

  [detailsDialog, assignDialog].forEach(dialog => {
    dialog.addEventListener("click", event => {
      if (event.target === dialog || event.target.closest("[data-close]")) {
        dialog.close();
      }
    });
  });

  detailsDialog.addEventListener("close", () => {
    dlg = null;
    testForm.replaceChildren();
  });

  renderTabs();
  loadTab();
}