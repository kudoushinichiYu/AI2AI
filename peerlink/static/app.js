let token = "";
let owner = "";
let isAdmin = false;
const registrationKey = "peerlink-registration";
const sessionTokenKey = "peerlink-user-token";
const element = id => document.getElementById(id);
async function api(path, method = "GET", body) {
  const response = await fetch(path, {method, headers: {Authorization: `Bearer ${token}`, "Content-Type": "application/json"}, body: body ? JSON.stringify(body) : undefined});
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map(item => item.msg || JSON.stringify(item)).join("；")
      : data.detail;
    throw new Error(detail || response.statusText);
  }
  return data;
}
async function safe(action) {
  try { element("message").textContent = ""; await action(); }
  catch (error) { element("message").textContent = error.message; }
}
async function projects() {
  const rows = await api(`/api/projects?owner=${encodeURIComponent(element("peer").value)}`);
  element("project").replaceChildren(...rows.map(row => new Option(`${row.id} · ${row.runtime}`, row.id)));
}
async function refreshUsers() {
  const rows = await api("/api/admin/users");
  element("users").replaceChildren(...rows.map(row => {
    const item = document.createElement("article");
    const heading = document.createElement("strong");
    heading.textContent = row.id;
    const status = document.createElement("p");
    status.className = "tag";
    status.textContent = row.status + (row.is_admin ? " · 管理员" : "");
    item.append(heading, status);
    if (row.status === "PENDING" && row.id !== owner) {
      for (const [action, label] of [["approve", "批准"], ["reject", "拒绝"]]) {
        const button = document.createElement("button");
        button.textContent = label;
        button.onclick = () => safe(async () => { await api(`/api/admin/users/${encodeURIComponent(row.id)}/decision`, "POST", {action}); await Promise.all([refreshUsers(), refresh()]); });
        item.append(button);
      }
    }
    return item;
  }));
}
async function refresh() {
  const rows = await api("/api/requests");
  element("requests").replaceChildren(...rows.map(row => {
    const card = document.createElement("article");
    const heading = document.createElement("strong");
    heading.textContent = `${row.sender} → ${row.receiver} / ${row.project}`;
    const status = document.createElement("p");
    status.className = "tag";
    status.textContent = `${row.status} · ${row.id}`;
    const question = document.createElement("pre"); question.textContent = row.question;
    card.append(heading, status, question);
    if (row.response || row.error) { const answer = document.createElement("pre"); answer.textContent = row.response || row.error; card.append(answer); }
    const actions = [];
    if (row.receiver === owner && row.status === "WAITING_APPROVAL") actions.push(["approve", "批准本地执行"], ["reject", "拒绝"]);
    if (row.sender === owner && !["COMPLETED", "FAILED", "CANCELLED", "REJECTED"].includes(row.status)) actions.push(["cancel", "取消请求"]);
    for (const [action, label] of actions) {
      const button = document.createElement("button"); button.textContent = label;
      button.onclick = () => safe(async () => { await api(`/api/requests/${row.id}/decision`, "POST", {action}); await refresh(); });
      card.append(button);
    }
    return card;
  }));
}
async function connect(loginToken) {
  token = loginToken;
  const me = await api("/api/me");
  owner = me.owner;
  isAdmin = me.is_admin;
  element("admin").hidden = !isAdmin;
  element("token").value = "";
  element("identity").textContent = `当前用户：${owner}${isAdmin ? "（管理员）" : ""}`;
  element("peer").replaceChildren(...(await api("/api/peers")).map(name => new Option(name, name)));
  element("login").hidden = true; element("workspace").hidden = false;
  if (isAdmin) await refreshUsers();
  await projects(); await refresh();
}
element("connect").onclick = () => safe(async () => {
  const loginToken = element("token").value.trim();
  await connect(loginToken);
  sessionStorage.setItem(sessionTokenKey, loginToken);
});
async function checkRegistration() {
  const saved = JSON.parse(localStorage.getItem(registrationKey) || "null");
  if (!saved) return;
  element("registration-status").textContent = `ERP ${saved.username} 的申请正在等待管理员审批。`;
  const result = await api("/api/register/status", "POST", saved);
  if (result.status === "ACTIVE" && result.token) {
    localStorage.removeItem(registrationKey);
    sessionStorage.setItem(sessionTokenKey, result.token);
    element("registration-status").textContent = "审批已通过，正在自动登录。";
    await connect(result.token);
  }
}
element("register-submit").onclick = () => {
  const input = element("register-name");
  if (!input.reportValidity()) return;
  safe(async () => {
    const result = await api("/api/register", "POST", {username: input.value.trim()});
    input.value = "";
    localStorage.setItem(registrationKey, JSON.stringify({username: result.username, receipt: result.receipt}));
    element("registration-status").textContent = `注册请求发送成功：${result.username}，正在等待管理员审批。`;
  });
};
element("peer").onchange = () => safe(projects);
element("refresh").onclick = () => safe(refresh);
element("logout").onclick = () => { token = ""; owner = ""; sessionStorage.removeItem(sessionTokenKey); location.reload(); };
element("ask").onclick = () => safe(async () => {
  await api("/api/requests", "POST", {receiver: element("peer").value, project: element("project").value, question: element("question").value});
  element("question").value = ""; await refresh();
});
setInterval(() => { if (owner) safe(refresh); }, 5000);
setInterval(() => { if (!owner) safe(checkRegistration); }, 5000);
const savedToken = sessionStorage.getItem(sessionTokenKey);
if (savedToken) safe(() => connect(savedToken));
else safe(checkRegistration);
