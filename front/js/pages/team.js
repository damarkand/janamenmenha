import { apiFetch, formatDate, formatMoney } from "../utils.js";

const enc = encodeURIComponent;

function card(label, value, hint = "", warning = false) {
  const div = document.createElement("div");
  div.className = `ws-card${warning ? " is-warning" : ""}`;
  div.innerHTML = `<span class="ws-card-label"></span><span class="ws-card-value"></span><span class="ws-card-hint"></span>`;
  div.querySelector(".ws-card-label").textContent = label;
  div.querySelector(".ws-card-value").textContent = value;
  div.querySelector(".ws-card-hint").textContent = hint;
  return div;
}

function requestSummary(r) {
  const d = r.details || {};
  if (d.start_date) return `${formatDate(d.start_date)} — ${formatDate(d.end_date)}, ${d.days} дн.`;
  if (d.amount !== undefined) return `${formatMoney(d.amount)} ₸`;
  return d.comment || "";
}

export async function init(root, user) {
  const q = s => root.querySelector(s);
  const state = q("#team-state");
  const body = q("#team-body");
  const message = q("#team-message");

  function showMessage(text, type = "error") {
    message.className = type === "success" ? "hr-success-message" : "hr-error-message";
    message.textContent = text;
    message.hidden = false;
  }

  async function loadRequests() {
    const list = q("#team-requests");
    try {
      const items = await apiFetch("/requests?scope=team&status=pending");
      if (!items.length) {
        list.innerHTML = '<div class="ws-empty">Новых заявок нет</div>';
        return;
      }
      list.replaceChildren(...items.map(r => {
        const row = document.createElement("div");
        row.className = "ws-list-item";
        row.dataset.id = r.id;
        const text = document.createElement("span");
        text.innerHTML = "<strong></strong><br><span class=\"ws-muted\"></span>";
        text.querySelector("strong").textContent = `${r.requester.full_name} · ${r.type_label}`;
        text.querySelector(".ws-muted").textContent = requestSummary(r);
        const actions = document.createElement("span");
        actions.className = "ws-task-actions";
        actions.innerHTML = `<button type="button" class="ws-mini-button" data-approve>Одобрить</button>
          <button type="button" class="ws-mini-button" data-reject>Отклонить</button>`;
        row.append(text, actions);
        return row;
      }));
    } catch (error) {
      list.innerHTML = '<div class="ws-empty"></div>';
      list.firstChild.textContent = error.message;
    }
  }

  async function load() {
    let data;
    try {
      data = await apiFetch("/dashboard/team");
    } catch (error) {
      state.innerHTML = '<div class="hr-empty-state"><h2 class="hr-empty-title">Нет доступа к данным команды</h2><p class="hr-empty-description"></p></div>';
      state.querySelector(".hr-empty-description").textContent = error.message;
      return;
    }
    if (!root.isConnected) return;

    const t = data.totals;
    q("#team-cards").replaceChildren(
      card("Сотрудников", t.members, user.role === "hr" ? "вся компания" : "в подчинении"),
      card("Открытых задач", t.open_tasks, t.overdue_tasks ? `просрочено: ${t.overdue_tasks}` : "без просрочек", t.overdue_tasks > 0),
      card("Часы команды", `${t.hours_week} / ${t.planned_week}`, "за неделю, отмечено / план"),
      card("На согласовании", t.pending_requests, "заявок ждут решения", t.pending_requests > 0)
    );

    q("#team-rows").replaceChildren(...data.members.map(m => {
      const tr = document.createElement("tr");
      const pct = m.planned_week ? Math.min(100, Math.round((m.hours_week / m.planned_week) * 100)) : 0;
      tr.innerHTML = `
        <td><span class="ws-person"><strong></strong><small></small></span></td>
        <td><span data-tasks></span></td>
        <td class="ws-hours-cell"><span data-hours></span><span class="ws-bar-track" style="display:block;margin-top:6px"><span class="ws-bar-fill"></span></span></td>
        <td data-courses></td>
        <td data-vacation></td>
        <td><span class="ws-task-actions">
          <button type="button" class="ws-mini-button" data-tasks-of="${m.user.id}">Задачи</button>
          <button type="button" class="ws-mini-button" data-schedule-of="${m.user.id}">График</button>
        </span></td>`;
      tr.querySelector("strong").textContent = m.user.full_name;
      tr.querySelector("small").textContent = m.position;
      const tasks = tr.querySelector("[data-tasks]");
      tasks.textContent = `${m.open_tasks} открыто`;
      if (m.overdue_tasks) {
        const tag = document.createElement("span");
        tag.className = "ws-tag is-danger";
        tag.style.marginLeft = "6px";
        tag.textContent = `${m.overdue_tasks} просроч.`;
        tasks.after(tag);
      }
      tr.querySelector("[data-hours]").textContent = `${m.hours_week} / ${m.planned_week} ч`;
      tr.querySelector(".ws-bar-fill").style.width = `${pct}%`;
      tr.querySelector("[data-courses]").textContent = `${m.courses_done} / ${m.courses_total}`;
      tr.querySelector("[data-vacation]").textContent = `${m.vacation_days_left} дн.`;
      return tr;
    }));

    await loadRequests();
    state.hidden = true;
    body.hidden = false;
  }

  async function decide(row, approve) {
    const id = row.dataset.id;
    let comment = null;
    if (!approve) {
      comment = window.prompt("Причина отклонения:");
      if (!comment || !comment.trim()) return;
    }
    row.querySelectorAll("button").forEach(b => (b.disabled = true));
    try {
      await apiFetch(`/requests/${enc(id)}/${approve ? "approve" : "reject"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comment })
      });
      showMessage(approve ? "Заявка одобрена." : "Заявка отклонена.", "success");
      await load();
    } catch (error) {
      row.querySelectorAll("button").forEach(b => (b.disabled = false));
      showMessage(error.message);
    }
  }

  body.addEventListener("click", event => {
    const row = event.target.closest("#team-requests .ws-list-item");
    if (row && event.target.closest("[data-approve]")) return decide(row, true);
    if (row && event.target.closest("[data-reject]")) return decide(row, false);

    const tasksOf = event.target.closest("[data-tasks-of]");
    if (tasksOf) {
      sessionStorage.setItem("tasks_scope", "team");
      sessionStorage.setItem("tasks_member", tasksOf.dataset.tasksOf);
      document.querySelector('#hr-navigation [data-page="tasks"]')?.click();
    }
    const scheduleOf = event.target.closest("[data-schedule-of]");
    if (scheduleOf) {
      sessionStorage.setItem("schedule_member", scheduleOf.dataset.scheduleOf);
      document.querySelector('#hr-navigation [data-page="schedule"]')?.click();
    }
  });

  await load();
}
