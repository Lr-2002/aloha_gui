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

const userInput = document.getElementById("user-id");
const taskInput = document.getElementById("task-name");

const startSessionBtn = document.getElementById("start-session");
const startEpisodeBtn = document.getElementById("start-episode");
const stopEpisodeBtn = document.getElementById("stop-episode");
const refreshEpisodesBtn = document.getElementById("refresh-episodes");
const pickRandomBtn = document.getElementById("pick-random");
const prepareReplayBtn = document.getElementById("prepare-replay");
const startStackBtn = document.getElementById("start-stack");
const stopStackBtn = document.getElementById("stop-stack");
const checkTopicsBtn = document.getElementById("check-topics");
const copyLiveLogBtn = document.getElementById("copy-live-log");
const copyStackLogBtn = document.getElementById("copy-stack-log");

let lastStatus = null;

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
    if (missing.length) {
      topicMsgEl.textContent = `Missing required: ${missing.join(", ")}`;
    } else if (missingOptional.length) {
      topicMsgEl.textContent = `Missing optional: ${missingOptional.join(", ")}`;
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
  const user = userInput.value.trim();
  const task = taskInput.value.trim();
  if (!user || !task) {
    episodeMsgEl.textContent = "User ID and Task Name are required.";
    return;
  }
  try {
    await apiRequest("/api/session/start", {
      method: "POST",
      body: JSON.stringify({ user, task }),
    });
    await refreshStatus();
    episodeMsgEl.textContent = "Session started.";
  } catch (err) {
    episodeMsgEl.textContent = `Session error: ${err.message}`;
  }
});

startEpisodeBtn.addEventListener("click", async () => {
  try {
    const data = await apiRequest("/api/episode/start", { method: "POST", body: "{}" });
    episodeMsgEl.textContent = `Episode ${data.episode} started.`;
    await refreshStatus();
  } catch (err) {
    episodeMsgEl.textContent = `Start error: ${err.message}`;
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

refreshStatus();
setInterval(refreshStatus, 2500);
