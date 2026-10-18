import { API_BASE_URL } from "./utils.js";

const appContent = document.getElementById("app-content");

async function loadPage(page) {
  const response = await fetch(page);

  if (!response.ok) {
    throw new Error(`Не удалось загрузить ${page}: HTTP ${response.status}`);
  }

  const html = await response.text();
  appContent.innerHTML = html;

  if (page === "main.html") {
    const { initMain } = await import("./main.js");
    await initMain();
  }

  if (page === "login.html") {
    const { initLogin } = await import("./login.js");
    await initLogin();
  }
}

async function initializeApp() {
  const accessToken = sessionStorage.getItem("access_token");

  if (!accessToken) {
    await loadPage("login.html");
    return;
  }

  try {
    const response = await fetch(`${API_BASE_URL}/auth/me`, {
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

      await loadPage("login.html");
      return;
    }

    if (!response.ok) {
      throw new Error(`Ошибка проверки токена: HTTP ${response.status}`);
    }

    const user = await response.json();

    sessionStorage.setItem("user", JSON.stringify(user));

    await loadPage("main.html");

    window.dispatchEvent(
      new CustomEvent("app:ready", {
        detail: { user }
      })
    );
  } catch (error) {
    console.error("Ошибка инициализации приложения:", error);

    appContent.innerHTML = `
      <div class="error-content">
        <h1>Не удалось подключиться</h1>
        <p class="subtitle">
          Проверьте соединение с сервером и попробуйте снова.
        </p>
        <button class="retry-button" id="retry-button">
          Повторить
        </button>
      </div>
    `;

    document.getElementById("retry-button").addEventListener("click", () => {
      initializeApp();
    });
  }
}

window.showMainPage = initializeApp;
initializeApp();
