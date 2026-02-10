const statusPill = document.getElementById("status-pill");
const nextEpisodeEl = document.getElementById("next-episode");
const dataRootEl = document.getElementById("data-root");
const sessionPathEl = document.getElementById("session-path");
const currentEpisodeEl = document.getElementById("current-episode");
const collectorStateEl = document.getElementById("collector-state");
const episodeMsgEl = document.getElementById("episode-msg");
const episodeListEl = document.getElementById("episode-list");
const randomMsgEl = document.getElementById("random-msg");
const selectedEpisodeEl = document.getElementById("selected-episode");
const replayMsgEl = document.getElementById("replay-msg");
const logOutputEl = document.getElementById("log-output");
const stackStateEl = document.getElementById("stack-state");
const stackListEl = document.getElementById("stack-list");
const topicMsgEl = document.getElementById("topic-msg");
const stackLogOutputEl = document.getElementById("stack-log-output");
const cleanupStatusEl = document.getElementById("cleanup-status");
const masterStatusEl = document.getElementById("master-status");
const sudoStatusEl = document.getElementById("sudo-status");
const sudoMsgEl = document.getElementById("sudo-msg");

const interfaceSelect = document.getElementById("interface-id");
const userSelect = document.getElementById("user-id");
const taskSelect = document.getElementById("task-id");
const userNameInput = document.getElementById("user-name");
const taskNameInput = document.getElementById("task-name");
const taskDescInput = document.getElementById("task-desc");
const taskSuccessInput = document.getElementById("task-success");
const taskDetailsEl = document.getElementById("task-details");
const sudoInput = document.getElementById("sudo-password");

const startSessionBtn = document.getElementById("start-session");
const startEpisodeBtn = document.getElementById("start-episode");
const stopEpisodeBtn = document.getElementById("stop-episode");
const refreshEpisodesBtn = document.getElementById("refresh-episodes");
const pickRandomBtn = document.getElementById("pick-random");
const prepareReplayBtn = document.getElementById("prepare-replay");
const startStackBtn = document.getElementById("start-stack");
const stopStackBtn = document.getElementById("stop-stack");
const checkTopicsBtn = document.getElementById("check-topics");
const stackCardEl = document.getElementById("stack-card");
const stackLogCardEl = document.getElementById("stack-log-card");
const copyLiveLogBtn = document.getElementById("copy-live-log");
const copyStackLogBtn = document.getElementById("copy-stack-log");
const setSudoBtn = document.getElementById("set-sudo");
const clearSudoBtn = document.getElementById("clear-sudo");
const addUserBtn = document.getElementById("add-user");
const addTaskBtn = document.getElementById("add-task");
const importTasksBtn = document.getElementById("import-tasks-btn");
const importUsersBtn = document.getElementById("import-users-btn");
const importTasksArea = document.getElementById("import-tasks");
const importUsersArea = document.getElementById("import-users");
const importTasksFile = document.getElementById("import-tasks-file");
const importUsersFile = document.getElementById("import-users-file");
const importTasksCsvBtn = document.getElementById("import-tasks-csv-btn");
const importUsersCsvBtn = document.getElementById("import-users-csv-btn");
const registryMsgEl = document.getElementById("registry-msg");

let lastStatus = null;
let lastTasks = [];

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    const error = data && data.error ? data.error : "request_failed";
    throw new Error(error);
  }
  return data;
}

function populateSelect(selectEl, items, placeholder) {
  selectEl.innerHTML = "";
  if (placeholder) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = placeholder;
    selectEl.appendChild(opt);
  }
  items.forEach((item) => {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.name || item.id;
    selectEl.appendChild(opt);
  });
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
      continue;
    }
    if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      row.push(field);
      field = "";
    } else if (ch === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else if (ch !== "\r") {
      field += ch;
    }
  }
  row.push(field);
  if (row.length > 1 || row[0] !== "") {
    rows.push(row);
  }
  return rows.filter((cells) => cells.some((cell) => cell.trim() !== ""));
}

function csvToTasks(text) {
  const rows = parseCsv(text);
  if (!rows.length) return [];
  const headers = rows.shift().map((h) => h.trim().toLowerCase().replace(/^\ufeff/, ""));
  const nameIdx = headers.indexOf("name") >= 0 ? headers.indexOf("name") : headers.indexOf("task_name");
  const descIdx = headers.indexOf("description") >= 0 ? headers.indexOf("description") : headers.indexOf("task_description");
  let successIdx = headers.indexOf("success_criteria");
  if (successIdx < 0) successIdx = headers.indexOf("success");
  if (successIdx < 0) successIdx = headers.indexOf("criteria");
  if (nameIdx < 0) {
    throw new Error("CSV missing name column");
  }
  return rows
    .map((row) => {
      const name = (row[nameIdx] || "").trim();
      if (!name) return null;
      return {
        name,
        description: descIdx >= 0 ? (row[descIdx] || "").trim() : "",
        success_criteria: successIdx >= 0 ? (row[successIdx] || "").trim() : "",
      };
    })
    .filter(Boolean);
}

function csvToUsers(text) {
  const rows = parseCsv(text);
  if (!rows.length) return [];
  const headers = rows.shift().map((h) => h.trim().toLowerCase().replace(/^\ufeff/, ""));
  let nameIdx = headers.indexOf("name");
  if (nameIdx < 0) nameIdx = headers.indexOf("user");
  if (nameIdx < 0) nameIdx = headers.indexOf("user_name");
  const idIdx = headers.indexOf("id") >= 0 ? headers.indexOf("id") : headers.indexOf("uid");
  if (nameIdx < 0) {
    throw new Error("CSV missing name column");
  }
  return rows
    .map((row) => {
      const name = (row[nameIdx] || "").trim();
      if (!name) return null;
      const item = { name };
      if (idIdx >= 0 && row[idIdx]) {
        item.id = row[idIdx].trim();
      }
      return item;
    })
    .filter(Boolean);
}

async function importCsvFile(file, converter, endpoint, successMsg) {
  if (!file) {
    registryMsgEl.textContent = "Choose a CSV file first.";
    return;
  }
  const text = await file.text();
  const items = converter(text);
  await apiRequest(endpoint, {
    method: "POST",
    body: JSON.stringify({ items, mode: "merge" }),
  });
  await loadRegistry();
  registryMsgEl.textContent = successMsg;
}

async function loadRegistry() {
  try {
    const [interfaces, users, tasks] = await Promise.all([
      apiRequest("/api/interfaces"),
      apiRequest("/api/users"),
      apiRequest("/api/tasks"),
    ]);
    populateSelect(interfaceSelect, interfaces.interfaces || [], "Select interface");
    populateSelect(userSelect, users.users || [], "Select user");
    lastTasks = tasks.tasks || [];
    populateSelect(taskSelect, lastTasks, "Select task");
    if (!interfaceSelect.value && (interfaces.interfaces || []).length) {
      interfaceSelect.value = interfaces.interfaces[0].id;
    }
  } catch (err) {
    registryMsgEl.textContent = `Registry load error: ${err.message}`;
  }
}

function setStatusText(text, mode) {
  statusPill.textContent = text;
  statusPill.style.background =
    mode === "running" ? "rgba(72, 182, 156, 0.2)" : "rgba(240, 168, 75, 0.2)";
  statusPill.style.color = mode === "running" ? "#bdf2e5" : "#f9d39b";
}

function updateUI(data) {
  lastStatus = data;
  dataRootEl.textContent = data.data_root || "~/data";
  nextEpisodeEl.textContent = data.next_episode ?? 0;
  const running = data.running;
  setStatusText(running ? "running" : "idle", running ? "running" : "idle");

  if (data.session) {
    sessionPathEl.textContent = `Session path: ${data.session.dataset_dir}`;
    currentEpisodeEl.textContent =
      data.current_episode !== null && data.current_episode !== undefined
        ? data.current_episode
        : "-";
  } else {
    sessionPathEl.textContent = "Session path: -";
    currentEpisodeEl.textContent = "-";
  }

  if (taskSelect && lastTasks.length) {
    const selected = lastTasks.find((t) => t.id === taskSelect.value);
    if (selected) {
      taskDetailsEl.textContent = `${selected.description || "No description"} | ${
        selected.success_criteria || "No success criteria"
      }`;
    } else {
      taskDetailsEl.textContent = "Select a task to see details.";
    }
  }

  collectorStateEl.textContent = data.collect_configured ? "configured" : "not configured";
  if (!data.collect_configured) {
    episodeMsgEl.textContent = "Set collect_script or collect_shell_template in config.json.";
  } else if (running) {
    episodeMsgEl.textContent = `Collecting episode ${data.current_episode}...`;
  } else {
    episodeMsgEl.textContent = "Ready to start the next episode.";
  }

  const episodes = data.episodes || [];
  episodeListEl.textContent = episodes.length ? episodes.join(", ") : "-";

  if (data.selected_episode !== null && data.selected_episode !== undefined) {
    selectedEpisodeEl.textContent = data.selected_episode;
    randomMsgEl.textContent = `Selected episode ${data.selected_episode}.`;
  } else {
    selectedEpisodeEl.textContent = "-";
    randomMsgEl.textContent = "No episode selected.";
  }

  if (data.last_replay) {
    replayMsgEl.textContent = `Prepared replay for episode ${data.last_replay.episode}.`;
  } else {
    replayMsgEl.textContent = "No replay payload.";
  }

  const logLines = data.last_log || [];
  logOutputEl.textContent = logLines.length ? logLines.join("\n") : "No output yet.";

  const stackEnabled = data.stack_enabled !== false;
  if (stackCardEl) {
    stackCardEl.style.display = stackEnabled ? "" : "none";
  }
  if (stackLogCardEl) {
    stackLogCardEl.style.display = stackEnabled ? "" : "none";
  }

  const stackRunning = data.stack_running;
  stackStateEl.textContent = stackRunning ? "running" : "idle";
  const processes = data.stack_processes || {};
  const list = Object.keys(processes).length
    ? Object.entries(processes)
        .map(([name, info]) => {
          if (info.external) {
            return `${name}:ext`;
          }
          return `${name}:${info.running ? "on" : "off"}`;
        })
        .join(" ")
    : "-";
  stackListEl.textContent = list;

  const topicStatus = data.topic_status || {};
  if (topicStatus.last_check) {
    const missing = topicStatus.missing || [];
    const missingOptional = topicStatus.missing_optional || [];
    const missingData = topicStatus.missing_data || [];
    const missingOptionalData = topicStatus.missing_optional_data || [];
    if (missing.length) {
      topicMsgEl.textContent = `Missing required: ${missing.join(", ")}`;
    } else if (missingData.length) {
      topicMsgEl.textContent = `No data on: ${missingData.join(", ")}`;
    } else if (missingOptional.length) {
      topicMsgEl.textContent = `Missing optional: ${missingOptional.join(", ")}`;
    } else if (missingOptionalData.length) {
      topicMsgEl.textContent = `Optional no data: ${missingOptionalData.join(", ")}`;
    } else {
      topicMsgEl.textContent = "All required topics present.";
    }
  } else {
    topicMsgEl.textContent = "No topic check yet.";
  }

  const stackLogLines = data.stack_log || [];
  stackLogOutputEl.textContent = stackLogLines.length
    ? stackLogLines.join("\n")
    : "No output yet.";

  const cleanup = data.camera_cleanup_status || {};
  if (cleanup.last_run) {
    if (cleanup.remaining_nodes && cleanup.remaining_nodes.length) {
      cleanupStatusEl.textContent = `remaining nodes: ${cleanup.remaining_nodes.join(", ")}`;
    } else if (cleanup.remaining_processes && Object.keys(cleanup.remaining_processes).length) {
      cleanupStatusEl.textContent = "remaining procs";
    } else {
      cleanupStatusEl.textContent = "ok";
    }
  } else {
    cleanupStatusEl.textContent = "-";
  }

  const master = data.master_status || {};
  if (master.last_check) {
    const missingData = master.missing_data || [];
    if (missingData.length) {
      masterStatusEl.textContent = `no data: ${missingData.join(", ")}`;
    } else {
      masterStatusEl.textContent = "ok";
    }
  } else {
    masterStatusEl.textContent = "-";
  }

  if (data.sudo_ready) {
    sudoStatusEl.textContent = "set";
    sudoMsgEl.textContent = "Sudo password stored in memory.";
  } else {
    sudoStatusEl.textContent = "not set";
    sudoMsgEl.textContent = "Sudo password not set.";
  }
}

async function copyText(text) {
  if (!text) {
    return;
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

function flashButton(button, text) {
  const original = button.textContent;
  button.textContent = text;
  setTimeout(() => {
    button.textContent = original;
  }, 900);
}

async function refreshStatus() {
  try {
    const data = await apiRequest("/api/status");
    updateUI(data);
  } catch (err) {
    episodeMsgEl.textContent = `Status error: ${err.message}`;
  }
}

startSessionBtn.addEventListener("click", async () => {
  const interfaceId = interfaceSelect.value;
  const userId = userSelect.value;
  const taskId = taskSelect.value;
  if (!interfaceId || !userId || !taskId) {
    episodeMsgEl.textContent = "Interface, user, and task are required.";
    return;
  }
  try {
    await apiRequest("/api/session/start", {
      method: "POST",
      body: JSON.stringify({ interface_id: interfaceId, user_id: userId, task_id: taskId }),
    });
    await refreshStatus();
    episodeMsgEl.textContent = "Session started.";
  } catch (err) {
    episodeMsgEl.textContent = `Session error: ${err.message}`;
  }
});

addUserBtn.addEventListener("click", async () => {
  const name = userNameInput.value.trim();
  if (!name) {
    registryMsgEl.textContent = "User name is required.";
    return;
  }
  try {
    await apiRequest("/api/users", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    userNameInput.value = "";
    await loadRegistry();
    registryMsgEl.textContent = "User added.";
  } catch (err) {
    registryMsgEl.textContent = `User add error: ${err.message}`;
  }
});

addTaskBtn.addEventListener("click", async () => {
  const name = taskNameInput.value.trim();
  if (!name) {
    registryMsgEl.textContent = "Task name is required.";
    return;
  }
  try {
    await apiRequest("/api/tasks", {
      method: "POST",
      body: JSON.stringify({
        name,
        description: taskDescInput.value.trim(),
        success_criteria: taskSuccessInput.value.trim(),
      }),
    });
    taskNameInput.value = "";
    taskDescInput.value = "";
    taskSuccessInput.value = "";
    await loadRegistry();
    registryMsgEl.textContent = "Task added.";
  } catch (err) {
    registryMsgEl.textContent = `Task add error: ${err.message}`;
  }
});

if (importTasksBtn && importTasksArea) {
  importTasksBtn.addEventListener("click", async () => {
    try {
      const items = JSON.parse(importTasksArea.value || "[]");
      await apiRequest("/api/tasks/import", {
        method: "POST",
        body: JSON.stringify({ items, mode: "merge" }),
      });
      await loadRegistry();
      registryMsgEl.textContent = "Tasks imported.";
    } catch (err) {
      registryMsgEl.textContent = `Task import error: ${err.message}`;
    }
  });
}

if (importUsersBtn && importUsersArea) {
  importUsersBtn.addEventListener("click", async () => {
    try {
      const items = JSON.parse(importUsersArea.value || "[]");
      await apiRequest("/api/users/import", {
        method: "POST",
        body: JSON.stringify({ items, mode: "merge" }),
      });
      await loadRegistry();
      registryMsgEl.textContent = "Users imported.";
    } catch (err) {
      registryMsgEl.textContent = `User import error: ${err.message}`;
    }
  });
}

if (importTasksCsvBtn && importTasksFile) {
  importTasksCsvBtn.addEventListener("click", async () => {
    try {
      await importCsvFile(
        importTasksFile.files[0],
        csvToTasks,
        "/api/tasks/import",
        "Tasks imported from CSV.",
      );
    } catch (err) {
      registryMsgEl.textContent = `Task CSV import error: ${err.message}`;
    }
  });
}

if (importUsersCsvBtn && importUsersFile) {
  importUsersCsvBtn.addEventListener("click", async () => {
    try {
      await importCsvFile(
        importUsersFile.files[0],
        csvToUsers,
        "/api/users/import",
        "Users imported from CSV.",
      );
    } catch (err) {
      registryMsgEl.textContent = `User CSV import error: ${err.message}`;
    }
  });
}

setSudoBtn.addEventListener("click", async () => {
  const password = sudoInput.value;
  if (!password) {
    sudoMsgEl.textContent = "Enter sudo password first.";
    return;
  }
  try {
    await apiRequest("/api/sudo", {
      method: "POST",
      body: JSON.stringify({ password }),
    });
    sudoInput.value = "";
    await refreshStatus();
    sudoMsgEl.textContent = "Sudo password set.";
  } catch (err) {
    sudoMsgEl.textContent = `Sudo error: ${err.message}`;
  }
});

clearSudoBtn.addEventListener("click", async () => {
  try {
    await apiRequest("/api/sudo", {
      method: "POST",
      body: JSON.stringify({ password: "" }),
    });
    await refreshStatus();
    sudoMsgEl.textContent = "Sudo password cleared.";
  } catch (err) {
    sudoMsgEl.textContent = `Sudo error: ${err.message}`;
  }
});

startEpisodeBtn.addEventListener("click", async () => {
  startEpisodeBtn.disabled = true;
  const original = startEpisodeBtn.textContent;
  startEpisodeBtn.textContent = "Starting...";
  try {
    const data = await apiRequest("/api/episode/start", { method: "POST", body: "{}" });
    episodeMsgEl.textContent = `Episode ${data.episode} started.`;
    await refreshStatus();
  } catch (err) {
    episodeMsgEl.textContent = `Start error: ${err.message}`;
  } finally {
    startEpisodeBtn.disabled = false;
    startEpisodeBtn.textContent = original;
  }
});

stopEpisodeBtn.addEventListener("click", async () => {
  try {
    await apiRequest("/api/episode/stop", { method: "POST", body: "{}" });
    episodeMsgEl.textContent = "Stop signal sent.";
    await refreshStatus();
  } catch (err) {
    episodeMsgEl.textContent = `Stop error: ${err.message}`;
  }
});

document.addEventListener("keydown", async (event) => {
  if (event.key !== "Enter" || event.repeat) {
    return;
  }
  const target = event.target;
  const tag = target && target.tagName ? target.tagName.toUpperCase() : "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target?.isContentEditable) {
    return;
  }
  event.preventDefault();
  if (lastStatus && lastStatus.running) {
    if (!stopEpisodeBtn.disabled) {
      stopEpisodeBtn.click();
    }
    return;
  }
  if (lastStatus && !lastStatus.session) {
    episodeMsgEl.textContent = "Start session first.";
    return;
  }
  if (!startEpisodeBtn.disabled) {
    startEpisodeBtn.click();
  }
});

refreshEpisodesBtn.addEventListener("click", async () => {
  try {
    await apiRequest("/api/episodes");
    await refreshStatus();
  } catch (err) {
    episodeMsgEl.textContent = `Refresh error: ${err.message}`;
  }
});

pickRandomBtn.addEventListener("click", async () => {
  try {
    const data = await apiRequest("/api/episode/random", { method: "POST", body: "{}" });
    randomMsgEl.textContent = `Selected episode ${data.episode}.`;
    await refreshStatus();
  } catch (err) {
    randomMsgEl.textContent = `Random error: ${err.message}`;
  }
});

prepareReplayBtn.addEventListener("click", async () => {
  try {
    const data = await apiRequest("/api/replay/prepare", { method: "POST", body: "{}" });
    replayMsgEl.textContent = `Prepared replay for episode ${data.replay.episode}.`;
    await refreshStatus();
  } catch (err) {
    replayMsgEl.textContent = `Replay error: ${err.message}`;
  }
});

startStackBtn.addEventListener("click", async () => {
  try {
    await apiRequest("/api/stack/start", { method: "POST", body: "{}" });
    await refreshStatus();
    topicMsgEl.textContent = "Stack started.";
  } catch (err) {
    topicMsgEl.textContent = `Stack error: ${err.message}`;
  }
});

stopStackBtn.addEventListener("click", async () => {
  try {
    await apiRequest("/api/stack/stop", { method: "POST", body: "{}" });
    await refreshStatus();
    topicMsgEl.textContent = "Stop signal sent.";
  } catch (err) {
    topicMsgEl.textContent = `Stop error: ${err.message}`;
  }
});

checkTopicsBtn.addEventListener("click", async () => {
  try {
    await apiRequest("/api/topics/check", { method: "POST", body: "{}" });
    await refreshStatus();
  } catch (err) {
    topicMsgEl.textContent = `Check error: ${err.message}`;
  }
});

copyLiveLogBtn.addEventListener("click", async () => {
  try {
    await copyText(logOutputEl.textContent);
    flashButton(copyLiveLogBtn, "Copied");
  } catch (err) {
    flashButton(copyLiveLogBtn, "Failed");
  }
});

copyStackLogBtn.addEventListener("click", async () => {
  try {
    await copyText(stackLogOutputEl.textContent);
    flashButton(copyStackLogBtn, "Copied");
  } catch (err) {
    flashButton(copyStackLogBtn, "Failed");
  }
});

taskSelect.addEventListener("change", () => updateUI(lastStatus || {}));

loadRegistry().then(refreshStatus);
setInterval(refreshStatus, 2500);
