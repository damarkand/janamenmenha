import { API_BASE_URL } from "./utils.js";


export async function initLogin() {
  const form = document.getElementById("login-form");
  const passwordInput = document.getElementById("password");
  const passwordToggle = document.getElementById("password-toggle");
  const submitButton = document.getElementById("submit-button");
  const message = document.getElementById("form-message");

  if (!form || !passwordInput || !passwordToggle || !submitButton || !message) {
    throw new Error("Не удалось найти элементы формы авторизации.");
  }

  passwordToggle.addEventListener("click", () => {
    const isPassword = passwordInput.type === "password";

    passwordInput.type = isPassword ? "text" : "password";
    passwordToggle.setAttribute("aria-pressed", String(isPassword));
    passwordToggle.setAttribute(
      "aria-label",
      isPassword ? "Скрыть пароль" : "Показать пароль"
    );
  });

  form.addEventListener("submit", async event => {
    event.preventDefault();

    message.hidden = true;
    message.className = "message";

    const email = document.getElementById("email").value.trim();
    const password = passwordInput.value;

    submitButton.disabled = true;
    submitButton.querySelector("span").textContent = "Выполняется вход...";

    try {
      const response = await fetch(`${API_BASE_URL}/auth/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ email, password })
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(
          data.message || "Не удалось войти. Проверьте почту и пароль."
        );
      }

      if (!data.access_token) {
        throw new Error("Сервер не вернул токен авторизации.");
      }

      sessionStorage.setItem("access_token", data.access_token);

      if (data.refresh_token) {
        sessionStorage.setItem("refresh_token", data.refresh_token);
      }

      message.textContent = "Вход выполнен. Загружаем профиль...";
      message.className = "message success";
      message.hidden = false;

      await window.showMainPage();
    } catch (error) {
      message.textContent =
        error instanceof TypeError
          ? "Не удалось подключиться к серверу. Проверьте соединение."
          : error.message;

      message.className = "message error";
      message.hidden = false;
    } finally {
      submitButton.disabled = false;

      const buttonText = submitButton.querySelector("span");

      if (buttonText) {
        buttonText.textContent = "Войти в систему";
      }
    }
  });
}
