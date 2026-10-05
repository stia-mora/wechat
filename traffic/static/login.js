'use strict';
const form = document.querySelector('#login-form');
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = form.querySelector('button');
  const message = document.querySelector('#message');
  const password = document.querySelector('#password');
  button.disabled = true;
  button.textContent = '正在登录…';
  message.textContent = '';
  password.removeAttribute('aria-invalid');
  try {
    const response = await fetch('/traffic/login', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({username: form.username.value, password: form.password.value})});
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(response.status === 429 ? '登录尝试过于频繁，请一分钟后重试。' : result.detail || '登录失败，请检查用户名与密码。');
    }
    message.textContent = '登录成功';
    location.replace('/traffic');
  } catch (error) {
    message.textContent = error.message === 'Failed to fetch' ? '网络连接失败，请稍后重试。' : error.message;
    password.setAttribute('aria-invalid', 'true');
    button.disabled = false;
    button.textContent = '登录后台';
  }
});
