let token = "";
let owner = "";
const element = id => document.getElementById(id);
async function api(path, method = "GET", body) {
  const response = await fetch(path, {method, headers: {Authorization: `Bearer ${token}`, "Content-Type": "application/json"}, body: body ? JSON.stringify(body) : undefined});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || response.statusText);
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
element("connect").onclick = () => safe(async () => {
  token = element("token").value.trim();
  owner = (await api("/api/me")).owner;
  element("token").value = "";
  element("identity").textContent = `当前用户：${owner}`;
  element("peer").replaceChildren(...(await api("/api/peers")).map(name => new Option(name, name)));
  element("login").hidden = true; element("workspace").hidden = false;
  await projects(); await refresh();
});
element("peer").onchange = () => safe(projects);
element("refresh").onclick = () => safe(refresh);
element("logout").onclick = () => { token = ""; owner = ""; location.reload(); };
element("ask").onclick = () => safe(async () => {
  await api("/api/requests", "POST", {receiver: element("peer").value, project: element("project").value, question: element("question").value});
  element("question").value = ""; await refresh();
});
setInterval(() => { if (owner) safe(refresh); }, 5000);
