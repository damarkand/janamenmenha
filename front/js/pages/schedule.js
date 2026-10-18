import { apiFetch, formatDate } from "../utils.js";

const MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const DAY_NAMES = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"];
const TYPE_LABELS = {
  workday: "Рабочий день", weekend: "Выходной", holiday: "Праздник", vacation: "Отпуск", vacation_pending: "Отпуск на согласовании"
};
const enc = encodeURIComponent;

function monthKey(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function localToday() {
  const d = new Date();
  return `${monthKey(d)}-${String(d.getDate()).padStart(2, "0")}`;
}

function card(label, value, hint = "") {
  const div = document.createElement("div");
  div.className = "ws-card";
  div.innerHTML = `<span class="ws-card-label"></span><span class="ws-card-value"></span><span class="ws-card-hint"></span>`;
  div.querySelector(".ws-card-label").textContent = label;
  div.querySelector(".ws-card-value").textContent = value;
  div.querySelector(".ws-card-hint").textContent = hint;
  return div;
}

export async function init(root, user) {
  const q = s => root.querySelector(s);
  const calendarEl = q("#calendar");
  const memberSelect = q("#schedule-member");
  const message = q("#schedule-message");
  const form = q("#time-form");
  const timeMessage = q("#time-message");

  const manager = user?.role === "manager" || user?.role === "hr";
  let cursor = new Date();
  cursor.setDate(1);
  let data = null;
  let entries = [];
  let myTasks = [];
  let selected = null;
  let loadToken = 0;

  function showMessage(text, type = "error") {
    message.className = type === "success" ? "hr-success-message" : "hr-error-message";
    message.textContent = text;
    message.hidden = false;
  }

  const lastDay = () => String(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0).getDate()).padStart(2, "0");
  const viewingSelf = () => !memberSelect.value || memberSelect.value === user.id;

  async function loadMembers() {
    if (!manager) return;
    try {
      const team = await apiFetch("/users");
      memberSelect.replaceChildren(new Option("Мой график", ""), ...team.map(m => new Option(m.full_name, m.id)));
      memberSelect.hidden = false;
      const preset = sessionStorage.getItem("schedule_member");
      sessionStorage.removeItem("schedule_member");
      if (preset) memberSelect.value = preset;
    } catch {
      memberSelect.hidden = true;
    }
  }

  async function loadMyTasks() {
    try {
      myTasks = (await apiFetch("/tasks?scope=mine")).filter(t => t.status !== "done");
    } catch {
      myTasks = [];
    }
    q("#time-task").replaceChildren(new Option("Без задачи", ""), ...myTasks.map(t => new Option(t.title, t.id)));
  }

  function renderSummary() {
    const s = data.summary;
    const sch = data.schedule;
    q("#schedule-cards").replaceChildren(
      card("Рабочих дней", s.workdays, `${data.hours_per_day} ч в день`),
      card("Отмечено часов", s.logged_hours, `план на сегодня: ${s.planned_to_date} ч`),
      card("План на месяц", `${s.planned_hours} ч`, s.holidays ? `праздников: ${s.holidays}` : "без праздников"),
      card("Отпуск", `${s.vacation_days} дн.`, "в этом месяце")
    );
    const days = sch.work_days.map(d => WEEKDAYS[d]).join(", ");
    q("#schedule-info").textContent = `${days} · ${sch.start_time}–${sch.end_time}, обед ${sch.lunch_minutes} мин · ${sch.work_format_label}`;
  }

  function renderCalendar() {
    const [year, month] = data.month.split("-").map(Number);
    q("#month-title").textContent = `${MONTHS[month - 1]} ${year}`;
    const first = new Date(year, month - 1, 1);
    const offset = (first.getDay() + 6) % 7;

    const cells = WEEKDAYS.map(w => {
      const head = document.createElement("div");
      head.className = "ws-weekday";
      head.textContent = w;
      return head;
    });
    for (let i = 0; i < offset; i++) {
      const blank = document.createElement("div");
      blank.className = "ws-day is-empty";
      cells.push(blank);
    }
    data.days.forEach(d => {
      const cell = document.createElement("button");
      cell.type = "button";
      const future = d.date > localToday();
      cell.className = `ws-day is-${d.type}${d.is_today ? " is-today" : ""}${future ? " is-future" : ""}${selected === d.date ? " is-selected" : ""}`;
      cell.dataset.date = d.date;

      const num = document.createElement("span");
      num.className = "ws-day-number";
      num.textContent = Number(d.date.slice(8));
      cell.append(num);

      const labelText = d.holiday || (d.type === "vacation" ? "Отпуск" : d.type === "vacation_pending" ? "Отпуск?" : "");
      if (labelText) {
        const label = document.createElement("span");
        label.className = "ws-day-label";
        label.textContent = labelText;
        cell.append(label);
      }

      if (d.tasks_due.length) {
        const dots = document.createElement("span");
        dots.className = "ws-day-dots";
        d.tasks_due.slice(0, 4).forEach(t => {
          const dot = document.createElement("span");
          if (t.status === "done") dot.className = "is-done";
          dots.append(dot);
        });
        cell.append(dots);
      }

      if (future && d.planned_hours) {
        const plan = document.createElement("span");
        plan.className = "ws-day-hours";
        plan.textContent = `${d.planned_hours} ч`;
        cell.append(plan);
      } else if (d.logged_hours || d.planned_hours) {
        const hours = document.createElement("span");
        hours.className = "ws-day-hours";
        hours.textContent = d.planned_hours ? `${d.logged_hours} / ${d.planned_hours} ч` : `${d.logged_hours} ч`;
        cell.append(hours);
        if (d.planned_hours) {
          const bar = document.createElement("span");
          bar.className = "ws-day-bar";
          const fill = document.createElement("span");
          fill.style.width = `${Math.min(100, (d.logged_hours / d.planned_hours) * 100)}%`;
          if (d.logged_hours > d.planned_hours) fill.className = "is-over";
          bar.append(fill);
          cell.append(bar);
        }
      }
      cells.push(cell);
    });
    calendarEl.replaceChildren(...cells);
  }

  function renderDay() {
    const day = data.days.find(d => d.date === selected);
    const panelTitle = q("#day-title");
    const typeTag = q("#day-type");
    const tasksEl = q("#day-tasks");
    const entriesEl = q("#day-entries");

    if (!day) {
      panelTitle.textContent = "Выберите день";
      typeTag.textContent = "";
      tasksEl.replaceChildren();
      entriesEl.replaceChildren();
      form.hidden = true;
      return;
    }

    const dt = new Date(`${day.date}T00:00:00`);
    panelTitle.textContent = `${formatDate(day.date)}, ${DAY_NAMES[(dt.getDay() + 6) % 7]}`;
    typeTag.textContent = day.holiday || TYPE_LABELS[day.type];

    tasksEl.replaceChildren(...day.tasks_due.map(t => {
      const item = document.createElement("div");
      item.className = "ws-list-item";
      item.append(Object.assign(document.createElement("span"), { textContent: `Срок: ${t.title}` }));
      const tag = document.createElement("span");
      tag.className = `ws-tag${t.status === "done" ? " is-accent" : ""}`;
      tag.textContent = t.status === "done" ? "готово" : "открыта";
      item.append(tag);
      return item;
    }));

    const dayEntries = entries.filter(e => e.day === day.date);
    q("#day-total").textContent = day.planned_hours ? `${day.logged_hours} из ${day.planned_hours} ч` : `${day.logged_hours} ч`;
    entriesEl.replaceChildren(...(dayEntries.length ? dayEntries.map(e => {
      const item = document.createElement("div");
      item.className = "ws-list-item";
      const task = myTasks.find(t => t.id === e.task_id);
      const text = document.createElement("span");
      text.innerHTML = "<strong></strong> ";
      text.querySelector("strong").textContent = `${e.hours} ч`;
      text.append([e.note, task?.title].filter(Boolean).join(" · ") || "Без комментария");
      item.append(text);
      if (viewingSelf()) {
        const del = document.createElement("button");
        del.type = "button";
        del.className = "ws-mini-button";
        del.dataset.delete = e.id;
        del.textContent = "Удалить";
        item.append(del);
      }
      return item;
    }) : [Object.assign(document.createElement("div"), { className: "ws-empty", textContent: viewingSelf() ? "Пока ничего не отмечено" : "Детали видны только сотруднику" })]));

    const isFuture = day.date > localToday();
    form.hidden = !viewingSelf() || isFuture;
    q("#time-hint").textContent = !viewingSelf() ? "Вы смотрите график сотрудника." : isFuture ? "Часы за будущие дни отметить нельзя." : "";
    if (!form.hidden) {
      const left = Math.max(0, day.planned_hours - day.logged_hours);
      q("#time-hours").value = left > 0 ? left : 1;
    }
  }

  async function load() {
    const token = ++loadToken;
    message.hidden = true;
    const params = new URLSearchParams({ month: monthKey(cursor) });
    if (memberSelect.value) params.set("user_id", memberSelect.value);
    try {
      const [cal, list] = await Promise.all([
        apiFetch(`/schedule/calendar?${params}`),
        viewingSelf() ? apiFetch(`/time?start=${monthKey(cursor)}-01&end=${monthKey(cursor)}-${lastDay()}`) : Promise.resolve([])
      ]);
      if (token !== loadToken || !root.isConnected) return;
      data = cal;
      entries = list;
      if (!data.days.some(d => d.date === selected)) {
        selected = (data.days.find(d => d.is_today) || data.days[0]).date;
      }
      renderSummary();
      renderCalendar();
      renderDay();
    } catch (error) {
      if (token !== loadToken) return;
      showMessage(error.message);
    }
  }

  calendarEl.addEventListener("click", event => {
    const cell = event.target.closest(".ws-day[data-date]");
    if (!cell) return;
    selected = cell.dataset.date;
    renderCalendar();
    renderDay();
  });

  q("#day-entries").addEventListener("click", async event => {
    const button = event.target.closest("[data-delete]");
    if (!button) return;
    button.disabled = true;
    try {
      await apiFetch(`/time/${enc(button.dataset.delete)}`, { method: "DELETE" });
      await load();
    } catch (error) {
      button.disabled = false;
      showMessage(error.message);
    }
  });

  form.addEventListener("submit", async event => {
    event.preventDefault();
    timeMessage.hidden = true;
    const submit = q("#time-submit");
    submit.disabled = true;
    try {
      await apiFetch("/time", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          day: selected, hours: Number(q("#time-hours").value),
          task_id: q("#time-task").value || null, note: q("#time-note").value.trim()
        })
      });
      q("#time-note").value = "";
      await load();
    } catch (error) {
      timeMessage.textContent = error.message;
      timeMessage.hidden = false;
    } finally {
      submit.disabled = false;
    }
  });

  q("#month-prev").addEventListener("click", () => { cursor.setMonth(cursor.getMonth() - 1); load(); });
  q("#month-next").addEventListener("click", () => { cursor.setMonth(cursor.getMonth() + 1); load(); });
  q("#month-today").addEventListener("click", () => {
    cursor = new Date();
    cursor.setDate(1);
    selected = null;
    load();
  });
  memberSelect.addEventListener("change", load);

  await Promise.all([loadMembers(), loadMyTasks()]);
  await load();
}
