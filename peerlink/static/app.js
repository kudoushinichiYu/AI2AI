let owner = "";
let isAdmin = false;
let catalogRows = [];
let deviceRows = [];
let ownProjects = [];
let requestRows = [];
let peerRows = [];

const el = id => document.getElementById(id);
const viewCopy = {
  overview: ["总览", "先连接电脑，再绑定项目，最后开始协作。"],
  devices: ["连接电脑", "为这台电脑生成独立配对码，并在本机终端完成连接。"],
  projects: ["项目目录", "先选云端项目，再在本机生成路径绑定命令。"],
  collaboration: ["提问与请求", "向同事的项目提问，或审查发给你的协作请求。"],
  security: ["账号安全", "管理当前账号的密码与登录会话。"],
  admin: ["管理员工作台", "处理成员审批与团队项目目录治理。"]
};
const statusLabels = {
  PENDING: ["等待审批", "wait"],
  ACTIVE: ["可用", "good"],
  RETIRED: ["已退役", ""],
  DISABLED: ["已停用", "bad"],
  COMPLETED: ["已完成", "good"],
  WAITING_APPROVAL: ["待你批准", "wait"],
  WAITING_OUTPUT_APPROVAL: ["待本地审核", "wait"],
  RUNNING: ["执行中", ""],
  FAILED: ["失败", "bad"],
  REJECTED: ["已拒绝", "bad"],
  CANCELLED: ["已取消", ""]
};

function shellQuote(value) {
  return `'${String(value).replace(/'/g, "'\\''")}'`;
}

function setMessage(target, message, kind = "error") {
  const node = el(target);
  node.textContent = message || "";
  node.className = `message${kind === "success" ? " success" : kind === "info" ? " info" : ""}`;
}

async function api(path, method = "GET", body) {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  let data;
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map(item => item.msg).join("；")
      : data.detail;
    const error = new Error(detail || `请求失败（HTTP ${response.status}）`);
    error.status = response.status;
    throw error;
  }
  return data;
}

async function safe(fn, target = "workspace-message") {
  try {
    setMessage(target, "", "info");
    await fn();
  } catch (error) {
    setMessage(target, error.message || "操作失败，请重试。", "error");
  }
}

function showAuthTab(tab) {
  const loginActive = tab === "login";
  el("login-form").hidden = !loginActive;
  el("register-form").hidden = loginActive;
  el("auth-tab-login").classList.toggle("active", loginActive);
  el("auth-tab-register").classList.toggle("active", !loginActive);
  el("auth-tab-login").setAttribute("aria-selected", String(loginActive));
  el("auth-tab-register").setAttribute("aria-selected", String(!loginActive));
  setMessage("auth-message", "", "info");
}

function openView(name) {
  if (!viewCopy[name] || (name === "admin" && !isAdmin)) name = "overview";
  document.querySelectorAll("[data-view-panel]").forEach(panel => {
    panel.hidden = panel.dataset.viewPanel !== name;
  });
  document.querySelectorAll("[data-view]").forEach(button => {
    button.classList.toggle("active", button.dataset.view === name);
    button.setAttribute("aria-current", button.dataset.view === name ? "page" : "false");
  });
  el("page-title").textContent = viewCopy[name][0];
  el("page-subtitle").textContent = viewCopy[name][1];
  setMessage("workspace-message", "", "info");
}

function makeTag(text, tone = "") {
  const tag = document.createElement("span");
  tag.className = `state-tag ${tone}`.trim();
  tag.textContent = text;
  return tag;
}

function translatedStatus(status, isAdminRole = false) {
  if (status === "ACTIVE" && isAdminRole) return ["管理员", "good"];
  return statusLabels[status] || [status || "未知状态", ""];
}

function emptyState(title, detail) {
  const box = document.createElement("div");
  box.className = "empty-state";
  const heading = document.createElement("strong");
  heading.textContent = title;
  const description = document.createElement("span");
  description.textContent = detail;
  box.append(heading, description);
  return box;
}

function updateOverview() {
  const activeProjects = catalogRows.filter(row => row.status === "ACTIVE");
  const pending = requestRows.filter(row =>
    (row.receiver === owner && row.status === "WAITING_APPROVAL") ||
    (row.sender === owner && !["COMPLETED", "FAILED", "CANCELLED", "REJECTED"].includes(row.status))
  );
  el("stat-devices").textContent = String(deviceRows.length);
  el("stat-projects").textContent = String(activeProjects.length);
  el("stat-pending").textContent = String(pending.length);
}

async function loadDevices() {
  deviceRows = await api("/api/devices");
  const list = el("devices");
  if (!deviceRows.length) {
    list.replaceChildren(emptyState("还没有连接电脑", "先生成配对码，再在本机运行连接命令。"));
  } else {
    list.replaceChildren(...deviceRows.map(row => {
      const card = document.createElement("article");
      card.className = "item-card";
      const main = document.createElement("div");
      main.className = "item-main";
      const title = document.createElement("div");
      title.className = "item-title";
      title.append(document.createTextNode(row.name), makeTag("已绑定", "good"));
      const detail = document.createElement("p");
      detail.textContent = `设备编号：${row.id}`;
      main.append(title, detail);
      const actions = document.createElement("div");
      actions.className = "item-actions";
      const revoke = document.createElement("button");
      revoke.type = "button";
      revoke.className = "danger";
      revoke.textContent = "撤销设备";
      revoke.onclick = () => safe(async () => {
        if (!confirm(`撤销“${row.name}”？这台电脑将立即无法访问 Peerlink。`)) return;
        await api(`/api/devices/${encodeURIComponent(row.id)}`, "DELETE");
        await loadDevices();
        updateOverview();
        setMessage("workspace-message", "设备已撤销。", "success");
      });
      actions.append(revoke);
      card.append(main, actions);
      return card;
    }));
  }
  updateOverview();
}

function populateBindingProjects() {
  const picker = el("binding-project");
  const previous = picker.value;
  const rows = catalogRows.filter(row => row.status === "ACTIVE");
  picker.replaceChildren(new Option(rows.length ? "选择云端项目" : "暂无可绑定项目", ""));
  rows.forEach(row => {
    const mapped = ownProjects.some(project => project.id === row.id);
    picker.add(new Option(`${row.id}${mapped ? " · 已绑定到本账号" : ""}`, row.id));
  });
  if (rows.some(row => row.id === previous)) picker.value = previous;
}

async function loadCatalog() {
  catalogRows = await api("/api/catalog/projects");
  const list = el("catalog-projects");
  if (!catalogRows.length) {
    list.replaceChildren(emptyState("云端目录还是空的", "管理员可以创建第一个项目；成员可以提交项目申请。"));
  } else {
    list.replaceChildren(...catalogRows.map(row => {
      const card = document.createElement("article");
      card.className = "item-card";
      const main = document.createElement("div");
      main.className = "item-main";
      const title = document.createElement("div");
      title.className = "item-title";
      const state = translatedStatus(row.status);
      title.append(document.createTextNode(row.id), makeTag(state[0], state[1]));
      const description = document.createElement("p");
      description.textContent = row.description || "未填写项目说明";
      main.append(title, description);
      const actions = document.createElement("div");
      actions.className = "item-actions";
      const alreadyBound = ownProjects.some(project => project.id === row.id);
      if (row.status === "ACTIVE") {
        const bind = document.createElement("button");
        bind.type = "button";
        bind.className = alreadyBound ? "secondary" : "primary";
        bind.textContent = alreadyBound ? "再次绑定本机目录" : "绑定本机目录";
        bind.onclick = () => {
          openView("projects");
          el("binding-project").value = row.id;
          el("binding-path").focus();
          el("binding-command-wrap").hidden = true;
        };
        actions.append(bind);
      }
      if (isAdmin) {
        const decision = row.status === "PENDING"
          ? [["approve", "批准项目", "secondary"], ["reject", "拒绝", "danger"]]
          : row.status === "ACTIVE"
            ? [["retire", "退役项目", "danger"]]
            : row.status === "RETIRED"
              ? [["activate", "重新启用", "secondary"]]
              : [];
        decision.forEach(([action, label, buttonClass]) => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = buttonClass;
          button.textContent = label;
          button.onclick = () => safe(async () => {
            await api(`/api/admin/catalog/projects/${encodeURIComponent(row.id)}/decision`, "POST", { action });
            await loadCatalog();
            setMessage("workspace-message", `项目“${row.id}”已更新。`, "success");
          });
          actions.append(button);
        });
      }
      card.append(main, actions);
      return card;
    }));
  }
  populateBindingProjects();
  el("catalog-mode-note").textContent = isAdmin
    ? "管理员创建的项目会立即加入云端目录；可在上方审批、退役或重新启用项目。"
    : "成员提交后由管理员审批。审批通过后，才能绑定本机路径。";
  updateOverview();
}

async function loadOwnProjects() {
  ownProjects = await api(`/api/projects?owner=${encodeURIComponent(owner)}`);
  populateBindingProjects();
  updateOverview();
}

async function loadPeers() {
  peerRows = await api("/api/peers");
  const picker = el("peer");
  picker.replaceChildren(...peerRows.map(name => new Option(name, name)));
  if (!peerRows.length) {
    picker.replaceChildren(new Option("暂无可提问的成员", ""));
  }
  await loadPeerProjects();
}

async function loadPeerProjects() {
  const picker = el("project");
  if (!el("peer").value) {
    picker.replaceChildren(new Option("先选择项目负责人", ""));
    return;
  }
  const projects = await api(`/api/projects?owner=${encodeURIComponent(el("peer").value)}`);
  picker.replaceChildren(...projects.map(project => new Option(`${project.id} · ${project.runtime}`, project.id)));
  if (!projects.length) picker.replaceChildren(new Option("该成员还没有开放项目", ""));
}

async function loadRequests() {
  requestRows = await api("/api/requests");
  const list = el("requests");
  if (!requestRows.length) {
    list.replaceChildren(emptyState("还没有协作请求", "你发起的问题和发给你的请求都会显示在这里。"));
  } else {
    list.replaceChildren(...requestRows.map(row => {
      const card = document.createElement("article");
      card.className = "request-card";
      const head = document.createElement("div");
      head.className = "request-head";
      const route = document.createElement("div");
      route.className = "request-route";
      route.textContent = `${row.sender} → ${row.receiver} · ${row.project}`;
      const state = translatedStatus(row.status);
      head.append(route, makeTag(state[0], state[1]));
      const id = document.createElement("div");
      id.className = "request-id";
      id.textContent = `请求编号：${row.id}`;
      const question = document.createElement("pre");
      question.textContent = row.question;
      card.append(head, id, question);
      if (row.response || row.error) {
        const answer = document.createElement("pre");
        answer.className = "answer";
        answer.textContent = row.response || `执行失败：${row.error}`;
        card.append(answer);
      }
      const actions = document.createElement("div");
      actions.className = "request-actions";
      if (row.receiver === owner && row.status === "WAITING_APPROVAL") {
        [["approve", "批准本地执行", "primary"], ["reject", "拒绝请求", "danger"]].forEach(([action, label, buttonClass]) => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = buttonClass;
          button.textContent = label;
          button.onclick = () => safe(async () => {
            await api(`/api/requests/${encodeURIComponent(row.id)}/decision`, "POST", { action });
            await loadRequests();
          });
          actions.append(button);
        });
      }
      if (row.sender === owner && !["COMPLETED", "FAILED", "CANCELLED", "REJECTED"].includes(row.status)) {
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "ghost";
        cancel.textContent = "取消请求";
        cancel.onclick = () => safe(async () => {
          if (!confirm("确定取消这个请求吗？")) return;
          await api(`/api/requests/${encodeURIComponent(row.id)}/decision`, "POST", { action: "cancel" });
          await loadRequests();
        });
        actions.append(cancel);
      }
      if (actions.childElementCount) card.append(actions);
      return card;
    }));
  }
  updateOverview();
}

async function loadUsers() {
  if (!isAdmin) return;
  const rows = await api("/api/admin/users");
  const list = el("users");
  if (!rows.length) {
    list.replaceChildren(emptyState("暂时没有成员", "新成员注册后会出现在这里等待审批。"));
    return;
  }
  list.replaceChildren(...rows.map(row => {
    const card = document.createElement("article");
    card.className = "item-card";
    const main = document.createElement("div");
    main.className = "item-main";
    const title = document.createElement("div");
    title.className = "item-title";
    const state = translatedStatus(row.status, row.is_admin);
    title.append(document.createTextNode(row.id), makeTag(state[0], state[1]));
    const detail = document.createElement("p");
    detail.textContent = row.is_admin ? "可管理团队成员和云端项目目录。" : "Peerlink 团队成员账号。";
    main.append(title, detail);
    const actions = document.createElement("div");
    actions.className = "item-actions";
    const available = row.status === "PENDING"
      ? [["approve", "批准加入", "primary"], ["reject", "拒绝", "danger"]]
      : row.status === "ACTIVE" && !row.is_admin
        ? [["disable", "停用账号", "danger"]]
        : row.status === "DISABLED"
          ? [["enable", "重新启用", "secondary"]]
          : [];
    available.forEach(([action, label, buttonClass]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = buttonClass;
      button.textContent = label;
      button.onclick = () => safe(async () => {
        await api(`/api/admin/users/${encodeURIComponent(row.id)}/decision`, "POST", { action });
        await loadUsers();
        setMessage("workspace-message", `账号“${row.id}”已更新。`, "success");
      });
      actions.append(button);
    });
    card.append(main, actions);
    return card;
  }));
}

async function refreshData() {
  await Promise.all([loadDevices(), loadCatalog(), loadOwnProjects(), loadPeers(), loadRequests(), loadUsers()]);
}

async function enter() {
  const me = await api("/api/me");
  owner = me.owner;
  isAdmin = Boolean(me.is_admin);
  el("auth-screen").hidden = true;
  el("workspace").hidden = false;
  el("identity").textContent = owner;
  el("side-identity").textContent = owner;
  el("avatar-letter").textContent = (owner[0] || "P").toUpperCase();
  el("role-badge").textContent = isAdmin ? "管理员" : "成员";
  el("side-role").textContent = isAdmin ? "管理员" : "成员";
  el("nav-admin").hidden = !isAdmin;
  openView("overview");
  await refreshData();
}

async function copyText(text, successMessage) {
  try {
    await navigator.clipboard.writeText(text);
    setMessage("workspace-message", successMessage, "success");
  } catch {
    setMessage("workspace-message", "浏览器未允许自动复制，请选中命令后手动复制。", "error");
  }
}

el("auth-tab-login").onclick = () => showAuthTab("login");
el("auth-tab-register").onclick = () => showAuthTab("register");

el("login-form").addEventListener("submit", event => {
  event.preventDefault();
  safe(async () => {
    await api("/api/login", "POST", {
      username: el("login-name").value.trim(),
      password: el("login-password").value
    });
    el("login-password").value = "";
    await enter();
  }, "auth-message");
});

el("register-form").addEventListener("submit", event => {
  event.preventDefault();
  safe(async () => {
    const username = el("register-name");
    const password = el("register-password");
    const confirmPassword = el("register-confirm");
    if (!username.reportValidity() || !password.reportValidity() || !confirmPassword.reportValidity()) return;
    if (password.value !== confirmPassword.value) throw new Error("两次输入的密码不一致，请重新检查。");
    const result = await api("/api/register", "POST", {
      username: username.value.trim(),
      password: password.value
    });
    password.value = "";
    confirmPassword.value = "";
    el("registration-status").hidden = false;
    el("registration-status").textContent = `申请已提交：${result.username}。请等待管理员批准，批准后使用同一账号密码登录。`;
    setMessage("auth-message", "注册申请已送达。", "success");
  }, "auth-message");
});

el("logout").onclick = () => safe(async () => {
  await api("/api/logout", "POST");
  location.reload();
});

el("pair-device").onclick = () => safe(async () => {
  const deviceName = el("device-name").value.trim();
  if (!deviceName) throw new Error("先给这台电脑起个名字。 ");
  const result = await api("/api/pairing-codes", "POST");
  const command = [
    `export PEERLINK_STATE="$HOME/.peerlink-${owner.replace(/[^a-zA-Z0-9._-]/g, "-")}"`,
    `peerlink --state "$PEERLINK_STATE" connect --hub https://peerlink.jd.com --name ${shellQuote(deviceName)} --code ${shellQuote(result.code)}`
  ].join("\n");
  el("pairing-code").hidden = false;
  el("pairing-code").textContent = `配对码：${result.code} · 10 分钟有效 · 一次性使用`;
  el("connect-command").textContent = command;
  el("connect-command-wrap").hidden = false;
  el("pair-device").textContent = "重新生成配对码";
  setMessage("workspace-message", `已为账号 ${owner} 生成独立配对码。请在 10 分钟内于本机终端运行命令。`, "success");
});

el("copy-connect").onclick = () => copyText(el("connect-command").textContent, "连接命令已复制。请只在你自己的电脑终端运行。");

el("generate-binding").onclick = () => {
  const projectId = el("binding-project").value;
  const path = el("binding-path").value.trim();
  const runtime = el("binding-runtime").value;
  const project = catalogRows.find(row => row.id === projectId && row.status === "ACTIVE");
  if (!project) {
    setMessage("workspace-message", "先选择一个状态为“可用”的云端项目。", "error");
    return;
  }
  if (!path.startsWith("/") || path === "/" || /[\r\n\0]/.test(path)) {
    setMessage("workspace-message", "请填写项目文件夹的绝对路径；不能使用根目录或多行内容。", "error");
    return;
  }
  const stateName = owner.replace(/[^a-zA-Z0-9._-]/g, "-") || "member";
  const command = [
    `export PEERLINK_STATE="$HOME/.peerlink-${stateName}"`,
    `peerlink --state "$PEERLINK_STATE" project-add ${shellQuote(project.id)} ${shellQuote(path)} --runtime ${shellQuote(runtime)} --description ${shellQuote(project.description || project.id)}`
  ].join("\n");
  el("binding-command").textContent = command;
  el("binding-command-wrap").hidden = false;
  setMessage("workspace-message", "命令已在本页本地生成；路径尚未提交。复制并在本机终端运行后，映射才会写入 Hub。", "success");
};

el("copy-binding").onclick = () => copyText(el("binding-command").textContent, "绑定命令已复制。执行后云端只保存路径映射与运行方式，不上传项目文件。");

el("catalog-submit").onclick = () => safe(async () => {
  const id = el("catalog-id");
  const description = el("catalog-description");
  if (!id.reportValidity() || !id.value.trim() || !description.value.trim()) throw new Error("请填写项目标识和项目说明。");
  const result = await api("/api/catalog/projects", "POST", { id: id.value.trim(), description: description.value.trim() });
  id.value = "";
  description.value = "";
  await loadCatalog();
  const message = result.status === "ACTIVE" ? "项目已加入云端目录，现在可以绑定本机路径。" : "项目申请已提交，等待管理员审批。";
  setMessage("workspace-message", message, "success");
});

el("peer").onchange = () => safe(loadPeerProjects);
el("ask").onclick = () => safe(async () => {
  const receiver = el("peer").value;
  const project = el("project").value;
  const question = el("question").value.trim();
  if (!receiver || !project) throw new Error("先选择有开放项目的成员。");
  if (!question) throw new Error("请先写下你要询问的问题。");
  await api("/api/requests", "POST", { receiver, project, question });
  el("question").value = "";
  await loadRequests();
  setMessage("workspace-message", "请求已发送。对方批准并完成本地审核后，你会在收件箱看到回复。", "success");
});

el("change-password").onclick = () => safe(async () => {
  const current = el("current-password");
  const next = el("new-password");
  const confirmation = el("confirm-new-password");
  if (!current.value || !next.reportValidity() || !confirmation.reportValidity()) throw new Error("请检查当前密码和新密码。 ");
  if (next.value !== confirmation.value) throw new Error("两次输入的新密码不一致。");
  await api("/api/account/password", "POST", { current_password: current.value, new_password: next.value });
  location.reload();
});

el("revoke-sessions").onclick = () => safe(async () => {
  if (!confirm("这会退出所有登录会话，需要重新登录。确定继续吗？")) return;
  await api("/api/sessions/revoke", "POST");
  location.reload();
});

document.querySelectorAll("[data-view]").forEach(button => {
  button.onclick = () => openView(button.dataset.view);
});
document.querySelectorAll("[data-go]").forEach(button => {
  button.onclick = () => openView(button.dataset.go);
});
el("refresh").onclick = () => safe(refreshData);
el("refresh-requests").onclick = () => safe(loadRequests);
el("refresh-users").onclick = () => safe(loadUsers);

enter().catch(error => {
  if (error.status !== 401) setMessage("auth-message", "暂时无法连接 Peerlink 服务，请检查网络后刷新页面。", "error");
});
setInterval(() => {
  if (owner && !el("workspace").hidden) safe(loadRequests);
}, 15000);
