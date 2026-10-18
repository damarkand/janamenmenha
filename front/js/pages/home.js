import { apiFetch, formatDate } from "../utils.js";
import { COLORS, barChart, donutChart, lineChart, progressBars } from "../charts.js";

const WEEKDAYS = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

function greeting(name) {
  const hour = new Date().getHours();
  const part = hour < 5 ? "Доброй ночи" : hour < 12 ? "Доброе утро" : hour < 18 ? "Добрый день" : "Добрый вечер";
  const first = String(name || "").split(/\s+/)[0];
  return first ? `${part}, ${first}!` : `${part}!`;
}

function card(label, value, hint = "", warning = false) {
  const div = document.createElement("div");
  div.className = `ws-card${warning ? " is-warning" : ""}`;
  div.innerHTML = `<span class="ws-card-label"></span><span class="ws-card-value"></span><span class="ws-card-hint"></span>`;
  div.querySelector(".ws-card-label").textContent = label;
  div.querySelector(".ws-card-value").textContent = value;
  div.querySelector(".ws-card-hint").textContent = hint;
  return div;
}

function listItem(title, tagText, tagClass = "") {
  const item = document.createElement("div");
  item.className = "ws-list-item";
  const left = document.createElement("span");
  left.textContent = title;
  item.append(left);
  if (tagText) {
    const tag = document.createElement("span");
    tag.className = `ws-tag ${tagClass}`;
    tag.textContent = tagText;
    item.append(tag);
  }
  return item;
}

function daysUntil(iso) {
  const target = new Date(`${iso}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((target - today) / 86400000);
}

export async function init(root, user) {
  const q = s => root.querySelector(s);
  const state = q("#home-state");
  const body = q("#home-body");
  const message = q("#home-message");

  q("#home-greeting").textContent = greeting(user?.full_name);

  function showMessage(text, type = "error") {
    message.className = type === "success" ? "hr-success-message" : "hr-error-message";
    message.textContent = text;
    message.hidden = false;
  }

  let data;
  try {
    data = await apiFetch("/dashboard/me");
  } catch (error) {
    state.innerHTML = `<div class="hr-empty-state"><h2 class="hr-empty-title">Не удалось загрузить сводку</h2>
      <p class="hr-empty-description"></p><button type="button" class="hr-retry-button">Повторить</button></div>`;
    state.querySelector(".hr-empty-description").textContent = error.message;
    state.querySelector(".hr-retry-button").addEventListener("click", () => init(root, user));
    return;
  }
  if (!root.isConnected) return;

  const c = data.cards;
  q("#home-cards").replaceChildren(
    card("Открытые задачи", c.open_tasks, c.overdue_tasks ? `просрочено: ${c.overdue_tasks}` : "без просрочек", c.overdue_tasks > 0),
    card("Часы за неделю", `${c.hours_week} / ${c.planned_week}`, "отмечено / по графику"),
    card("Остаток отпуска", `${c.vacation_days_left} дн.`, c.pending_requests ? `заявок на рассмотрении: ${c.pending_requests}` : "данные 1С:ЗУП"),
    card("Обучение", `${c.courses_done} / ${c.courses_total}`, "курсов завершено")
  );

  const ch = data.charts;
  barChart(q("#chart-hours"), ch.hours_by_day.map(d => {
    const dt = new Date(`${d.date}T00:00:00`);
    return {
      label: formatDate(d.date), short: `${dt.getDate()} ${WEEKDAYS[dt.getDay()]}`, value: d.logged, plan: d.planned,
      color: d.type === "vacation" ? COLORS.blue : undefined
    };
  }), { planKey: "plan", unit: " ч" });

  const s = ch.tasks_by_status;
  donutChart(q("#chart-status"), [
    { label: "К выполнению", value: s.todo || 0, color: COLORS.gray },
    { label: "В работе", value: s.in_progress || 0, color: COLORS.amber },
    { label: "Готово", value: s.done || 0, color: COLORS.accent }
  ], { centerLabel: "задач" });

  lineChart(q("#chart-weeks"), ch.tasks_done_by_week.map(w => {
    const dt = new Date(`${w.week_start}T00:00:00`);
    return { label: `Неделя с ${formatDate(w.week_start)}`, short: `${dt.getDate()}.${String(dt.getMonth() + 1).padStart(2, "0")}`, value: w.count };
  }));

  progressBars(q("#chart-learning"), ch.learning.map(l => ({
    label: l.title, value: l.progress, color: l.status === "completed" ? COLORS.accent : COLORS.blue
  })));

  const maxCat = Math.max(1, ...ch.tasks_by_category.map(x => x.count));
  progressBars(q("#chart-categories"), ch.tasks_by_category.map(x => ({
    label: `${x.category} — ${x.count}`, value: Math.round((x.count / maxCat) * 100), color: COLORS.indigo
  })));
  q("#chart-categories").querySelectorAll(".ws-bar-value").forEach(v => (v.textContent = ""));

  const upcoming = q("#home-upcoming");
  if (!data.upcoming_tasks.length) {
    upcoming.innerHTML = '<div class="ws-empty">Задач со сроком нет</div>';
  } else {
    upcoming.replaceChildren(...data.upcoming_tasks.map(t => {
      const days = daysUntil(t.due_date);
      const text = t.overdue ? "просрочена" : days === 0 ? "сегодня" : days === 1 ? "завтра" : `до ${formatDate(t.due_date)}`;
      return listItem(t.title, text, t.overdue ? "is-danger" : days <= 1 ? "is-amber" : "");
    }));
  }

  const dates = [];
  if (data.next_vacation) {
    dates.push(listItem(`Отпуск ${formatDate(data.next_vacation.start_date)} — ${formatDate(data.next_vacation.end_date)}`,
      `${data.next_vacation.days} дн.`, "is-accent"));
  }
  if (data.next_holiday) {
    const d = daysUntil(data.next_holiday.date);
    dates.push(listItem(`${data.next_holiday.name}, ${formatDate(data.next_holiday.date)}`, d === 0 ? "сегодня" : `через ${d} дн.`));
  }
  q("#home-dates").replaceChildren(...(dates.length ? dates : [listItem("Ближайших событий нет")]));

  state.hidden = true;
  body.hidden = false;

  const dialog = q("#certificate-dialog");
  const form = q("#certificate-form");
  const dialogMessage = q("#certificate-message");
  const submit = q("#certificate-submit");

  q("#home-certificate").addEventListener("click", () => {
    form.reset();
    dialogMessage.hidden = true;
    dialog.showModal();
  });

  dialog.addEventListener("click", event => {
    if (event.target === dialog || event.target.closest("[data-close]")) dialog.close();
  });

  form.addEventListener("submit", async event => {
    event.preventDefault();
    submit.disabled = true;
    dialogMessage.hidden = true;
    try {
      await apiFetch("/requests/certificate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: q("#certificate-kind").value, comment: q("#certificate-comment").value.trim() || null })
      });
      dialog.close();
      showMessage("Запрос отправлен в HR. Статус можно посмотреть во вкладке «Заявки».", "success");
    } catch (error) {
      dialogMessage.textContent = error.message;
      dialogMessage.hidden = false;
    } finally {
      submit.disabled = false;
    }
  });
}
