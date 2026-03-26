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
const replayTimelineEl = document.getElementById("replay-timeline");
const replayTimeLabelEl = document.getElementById("replay-time-label");
const replaySpeedEl = document.getElementById("replay-speed");
const replayCamLabelEls = [0, 1, 2].map((idx) => document.getElementById(`replay-cam-label-${idx}`));
const replayCamImageEls = [0, 1, 2].map((idx) => document.getElementById(`replay-cam-img-${idx}`));
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
const dataarmLockedJointsFieldEl = document.getElementById("dataarm-locked-joints-field");
const dataarmLockedJointsInput = document.getElementById("dataarm-locked-joints");
const sudoInput = document.getElementById("sudo-password");

const startSessionBtn = document.getElementById("start-session");
const stopSessionBtn = document.getElementById("stop-session");
const startEpisodeBtn = document.getElementById("start-episode");
const stopEpisodeBtn = document.getElementById("stop-episode");
const refreshEpisodesBtn = document.getElementById("refresh-episodes");
const pickRandomBtn = document.getElementById("pick-random");
const prepareReplayBtn = document.getElementById("prepare-replay");
const loadReplayPreviewBtn = document.getElementById("load-replay-preview");
const replayPlayToggleBtn = document.getElementById("replay-play-toggle");
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
let replayPreview = null;
let replayCursor = 0;
let replayTimer = null;
let replayPlaying = false;
let replayLastRenderUrls = ["", "", ""];
let replayAutoLoadedKey = "";
let replayAutoLoading = false;

function stopReplayLoop() {
  replayPlaying = false;
  if (replayTimer) {
    clearTimeout(replayTimer);
    replayTimer = null;
  }
  if (replayPlayToggleBtn) {
    replayPlayToggleBtn.textContent = "Play";
  }
}

function resetReplayViews() {
  stopReplayLoop();
  replayPreview = null;
  replayCursor = 0;
  replayLastRenderUrls = ["", "", ""];
  replayAutoLoadedKey = "";
  replayAutoLoading = false;
  if (replayTimelineEl) {
    replayTimelineEl.min = "0";
    replayTimelineEl.max = "0";
    replayTimelineEl.value = "0";
    replayTimelineEl.disabled = true;
  }
  if (replayTimeLabelEl) {
    replayTimeLabelEl.textContent = "0.00s / 0.00s";
  }
  replayCamLabelEls.forEach((el) => {
    if (el) el.textContent = "-";
  });
  replayCamImageEls.forEach((el) => {
    if (el) {
      el.removeAttribute("src");
      el.style.opacity = "0.25";
    }
  });
}

function maybeAutoLoadReplayPreview(status) {
  if (!status || !status.session) return;
  const selectedEpisode = status.selected_episode;
  if (selectedEpisode === null || selectedEpisode === undefined) return;
  const datasetDir = status.session.dataset_dir || "";
  const autoKey = `${datasetDir}::${selectedEpisode}`;
  if (replayAutoLoading || replayAutoLoadedKey === autoKey) return;

  replayAutoLoading = true;
  replayAutoLoadedKey = autoKey;
  loadReplayPreview(selectedEpisode)
    .catch((err) => {
      replayMsgEl.textContent = `Replay preview error: ${err.message}`;
    })
    .finally(() => {
      replayAutoLoading = false;
    });
}

function currentReplaySpeed() {
  if (!replaySpeedEl) return 1.0;
  const value = Number.parseFloat(replaySpeedEl.value);
  if (!Number.isFinite(value) || value <= 0) return 1.0;
  return value;
}

function formatReplayTime(ms) {
  if (!Number.isFinite(ms)) return "0.00s";
  return `${(ms / 1000).toFixed(2)}s`;
}

function resolveReplayFrameUrl(cameraName, timelineIndex) {
  if (!replayPreview || !cameraName) return "";
  const mapping = replayPreview.timeline_to_frame || {};
  const cameraMap = mapping[cameraName] || [];
  const frameIdx = cameraMap[timelineIndex];
  if (frameIdx === undefined || frameIdx === null) return "";
  return `/api/replay/frame?episode=${encodeURIComponent(replayPreview.episode)}&camera=${encodeURIComponent(
    cameraName,
  )}&frame_idx=${encodeURIComponent(frameIdx)}`;
}

function renderReplayFrame(index) {
  if (!replayPreview) return;
  const frameCount = replayPreview.frame_count || 0;
  if (frameCount <= 0) return;
  const clamped = Math.max(0, Math.min(frameCount - 1, index));
  replayCursor = clamped;

  const timeline = replayPreview.timeline_ms || [];
  const t0 = timeline.length ? timeline[0] : 0;
  const now = timeline.length ? timeline[clamped] : 0;
  const tend = timeline.length ? timeline[timeline.length - 1] : 0;
  if (replayTimelineEl) {
    replayTimelineEl.value = String(clamped);
  }
  if (replayTimeLabelEl) {
    replayTimeLabelEl.textContent = `${formatReplayTime(now - t0)} / ${formatReplayTime(tend - t0)}`;
  }

  const cameras = replayPreview.camera_names || [];
  for (let i = 0; i < 3; i += 1) {
    const cameraName = cameras[i] || "";
    const labelEl = replayCamLabelEls[i];
    const imgEl = replayCamImageEls[i];
    if (!labelEl || !imgEl) continue;
    if (!cameraName) {
      labelEl.textContent = "-";
      imgEl.removeAttribute("src");
      imgEl.style.opacity = "0.2";
      replayLastRenderUrls[i] = "";
      continue;
    }
    labelEl.textContent = cameraName;
    const url = resolveReplayFrameUrl(cameraName, clamped);
    if (url && replayLastRenderUrls[i] !== url) {
      imgEl.src = `${url}&_t=${Date.now()}`;
      replayLastRenderUrls[i] = url;
    }
    imgEl.style.opacity = "1.0";
  }
}

function scheduleReplayStep() {
  if (!replayPlaying || !replayPreview) return;
  const frameCount = replayPreview.frame_count || 0;
  if (frameCount <= 1) {
    stopReplayLoop();
    return;
  }
  if (replayCursor >= frameCount - 1) {
    stopReplayLoop();
    return;
  }

  const timeline = replayPreview.timeline_ms || [];
  const nowTs = timeline[replayCursor] || 0;
  const nextTs = timeline[replayCursor + 1] || nowTs;
  const rawDtMs = Math.max(10, nextTs - nowTs);
  const dtMs = Math.max(10, rawDtMs / currentReplaySpeed());

  replayTimer = setTimeout(() => {
    replayTimer = null;
    renderReplayFrame(replayCursor + 1);
    scheduleReplayStep();
  }, dtMs);
}

async function loadReplayPreview(episodeOverride = null) {
  const body = {};
  if (episodeOverride !== null && episodeOverride !== undefined) {
    body.episode = Number(episodeOverride);
  }
  const data = await apiRequest("/api/replay/preview", {
    method: "POST",
    body: JSON.stringify(body),
  });
  replayPreview = data.preview || null;
  if (!replayPreview || !replayPreview.frame_count) {
    resetReplayViews();
    replayMsgEl.textContent = "Replay preview empty.";
    return;
  }

  const maxFrame = Math.max(0, (replayPreview.frame_count || 1) - 1);
  if (replayTimelineEl) {
    replayTimelineEl.disabled = false;
    replayTimelineEl.min = "0";
    replayTimelineEl.max = String(maxFrame);
    replayTimelineEl.value = "0";
  }
  stopReplayLoop();
  renderReplayFrame(0);
  replayMsgEl.textContent = `Replay preview loaded: ${replayPreview.frame_count} frames, cams=${(
    replayPreview.camera_names || []
  ).join(", ")}.`;
}

function currentInterfaceId() {
  return (interfaceSelect?.value || "").trim();
}

function isDataArmInterfaceSelected() {
  return currentInterfaceId() === "dataarm";
}

function getLockedJointsValue() {
  if (!dataarmLockedJointsInput) return "";
  return String(dataarmLockedJointsInput.value || "").trim();
}

function getCollectorParamsFromUI() {
  const params = {};
  const lockedJoints = getLockedJointsValue();
  if (lockedJoints) {
    params.locked_joints = lockedJoints;
  }
  return params;
}

async function syncDataArmCollectorParamsFromUI() {
  if (!isDataArmInterfaceSelected()) return;
  if (!lastStatus || !lastStatus.session) return;

  const sessionParams =
    lastStatus.session && typeof lastStatus.session.collector_params === "object"
      ? { ...lastStatus.session.collector_params }
      : {};
  const uiLocked = getLockedJointsValue();
  const currentLocked =
    typeof sessionParams.locked_joints === "string" ? sessionParams.locked_joints : "";
  if (currentLocked === uiLocked) return;

  if (uiLocked) {
    sessionParams.locked_joints = uiLocked;
  } else {
    delete sessionParams.locked_joints;
  }

  const data = await apiRequest("/api/dataarm/params", {
    method: "POST",
    body: JSON.stringify({ collector_params: sessionParams }),
  });
  if (lastStatus && lastStatus.session) {
    lastStatus.session.collector_params = data.collector_params || {};
  }
}

function updateDataArmFieldVisibility() {
  if (!dataarmLockedJointsFieldEl) return;
  dataarmLockedJointsFieldEl.style.display = isDataArmInterfaceSelected() ? "" : "none";
}

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
    updateDataArmFieldVisibility();
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
  updateDataArmFieldVisibility();

  if (dataarmLockedJointsInput && document.activeElement !== dataarmLockedJointsInput) {
    const sessionLocked = data?.session?.collector_params?.locked_joints;
    if (typeof sessionLocked === "string") {
      dataarmLockedJointsInput.value = sessionLocked;
    } else if (!data?.session && isDataArmInterfaceSelected()) {
      const defaultLocked = data?.dataarm_defaults?.locked_joints;
      // Before session starts, keep user's local selection instead of repeatedly
      // forcing backend default on every status refresh.
      if (typeof defaultLocked === "string" && !getLockedJointsValue()) {
        dataarmLockedJointsInput.value = defaultLocked;
      }
    }
  }

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
    maybeAutoLoadReplayPreview(data);
  } else {
    selectedEpisodeEl.textContent = "-";
    randomMsgEl.textContent = "No episode selected.";
    if (!data.running) {
      resetReplayViews();
    }
  }

  if (!data.session) {
    resetReplayViews();
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
    const body = { interface_id: interfaceId, user_id: userId, task_id: taskId };
    const collectorParams = getCollectorParamsFromUI();
    if (Object.keys(collectorParams).length) {
      body.collector_params = collectorParams;
    }
    const data = await apiRequest("/api/session/start", {
      method: "POST",
      body: JSON.stringify(body),
    });
    await refreshStatus();
    if (data && data.gc_started) {
      episodeMsgEl.textContent = "Session started. GC is running.";
    } else {
      episodeMsgEl.textContent = "Session started.";
    }
  } catch (err) {
    episodeMsgEl.textContent = `Session error: ${err.message}`;
  }
});

if (stopSessionBtn) {
  stopSessionBtn.addEventListener("click", async () => {
    try {
      const data = await apiRequest("/api/session/stop", { method: "POST", body: "{}" });
      await refreshStatus();
      const had = data && data.had_session ? "session stopped" : "no active session";
      episodeMsgEl.textContent = `Session stop: ${had}.`;
    } catch (err) {
      episodeMsgEl.textContent = `Stop session error: ${err.message}`;
    }
  });
}

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
    const collectorParams = getCollectorParamsFromUI();
    const body = Object.keys(collectorParams).length ? { collector_params: collectorParams } : {};
    const data = await apiRequest("/api/episode/start", {
      method: "POST",
      body: JSON.stringify(body),
    });
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

if (loadReplayPreviewBtn) {
  loadReplayPreviewBtn.addEventListener("click", async () => {
    try {
      const selectedEpisode =
        lastStatus && lastStatus.selected_episode !== null && lastStatus.selected_episode !== undefined
          ? lastStatus.selected_episode
          : null;
      await loadReplayPreview(selectedEpisode);
      await refreshStatus();
    } catch (err) {
      replayMsgEl.textContent = `Replay preview error: ${err.message}`;
    }
  });
}

if (replayPlayToggleBtn) {
  replayPlayToggleBtn.addEventListener("click", () => {
    if (!replayPreview || !(replayPreview.frame_count > 0)) {
      replayMsgEl.textContent = "Load replay preview first.";
      return;
    }
    if (replayPlaying) {
      stopReplayLoop();
      return;
    }
    replayPlaying = true;
    replayPlayToggleBtn.textContent = "Pause";
    scheduleReplayStep();
  });
}

if (replayTimelineEl) {
  replayTimelineEl.addEventListener("input", () => {
    if (!replayPreview) return;
    const idx = Number.parseInt(replayTimelineEl.value, 10);
    if (!Number.isFinite(idx)) return;
    stopReplayLoop();
    renderReplayFrame(idx);
  });
}

if (replaySpeedEl) {
  replaySpeedEl.addEventListener("change", () => {
    if (!replayPlaying) return;
    stopReplayLoop();
    replayPlaying = true;
    if (replayPlayToggleBtn) replayPlayToggleBtn.textContent = "Pause";
    scheduleReplayStep();
  });
}

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
interfaceSelect.addEventListener("change", () => updateDataArmFieldVisibility());
if (dataarmLockedJointsInput) {
  dataarmLockedJointsInput.addEventListener("change", async () => {
    try {
      await syncDataArmCollectorParamsFromUI();
      await refreshStatus();
    } catch (err) {
      episodeMsgEl.textContent = `Lock profile update error: ${err.message}`;
    }
  });
}

resetReplayViews();
loadRegistry().then(refreshStatus);
setInterval(refreshStatus, 2500);
