import { DASH, val, initials, formatDate, formatMoney, fillFields } from "../utils.js";

export function init(root, user) {
  user = user || {};

  const courses = Array.isArray(user.assigned_courses) ? user.assigned_courses : [];

  fillFields(root, {
    initials: initials(user.full_name),
    full_name: val(user.full_name),
    position_line: [user.position, user.department].filter(Boolean).join(" · ") || DASH,
    role_label: val(user.role_label || user.role),

    email: val(user.email),
    company: val(user.company),
    department: val(user.department),
    position: val(user.position),
    manager: val(user.manager?.full_name),
    hire_date: formatDate(user.hire_date),
    data_source: val(user.data_source),
    access_level:
      user.read_only === true ? "Только чтение" :
      user.read_only === false ? "Доступ с изменением" : DASH,

    vacation_days_left: val(user.vacation_days_left),
    advance_limit: formatMoney(user.advance_limit),
    courses_count: `${courses.length} курсов`
  });

  renderCourses(root, courses);
}

function renderCourses(root, courses) {
  const list = root.querySelector("#profile-courses");
  const itemTemplate = root.querySelector("#course-template");
  const emptyTemplate = root.querySelector("#courses-empty-template");

  if (!list || !itemTemplate || !emptyTemplate) return;

  if (!courses.length) {
    list.append(emptyTemplate.content.cloneNode(true));
    return;
  }

  const fragment = document.createDocumentFragment();

  courses.forEach(course => {
    const isObject = course && typeof course === "object";
    const title = isObject ? course.title || course.name || "Курс" : course;
    const description = isObject ? course.description || course.status || "" : "";

    const node = itemTemplate.content.cloneNode(true);
    node.querySelector(".hr-course-title").textContent = val(title);

    if (description) {
      const descEl = node.querySelector(".hr-course-description");
      descEl.textContent = description;
      descEl.hidden = false;
    }

    fragment.append(node);
  });

  list.append(fragment);
}