const topicInput = document.querySelector("#topicInput");
const topicCount = document.querySelector("#topicCount");
const startButton = document.querySelector("#startButton");
const pauseButton = document.querySelector("#pauseButton");
const pauseButtonLabel = document.querySelector("#pauseButtonLabel");
const stopButton = document.querySelector("#stopButton");
const formMessage = document.querySelector("#formMessage");
const speakerHint = document.querySelector("#speakerHint");
const roundNumber = document.querySelector("#roundNumber");
const connectionStatus = document.querySelector("#connectionStatus");
const speakerStatus = document.querySelector(".speaker-status");
const affirmativeCard = document.querySelector("#affirmativeCard");
const negativeCard = document.querySelector("#negativeCard");
const affirmativeState = document.querySelector("#affirmativeState");
const affirmativeSpeech = document.querySelector("#affirmativeSpeech p");
const negativeState = document.querySelector("#negativeState");
const negativeSpeech = document.querySelector("#negativeSpeech p");
const affirmativeModel = document.querySelector("#affirmativeModel");
const negativeModel = document.querySelector("#negativeModel");
const affirmativeModelDot = document.querySelector("#affirmativeModelDot");
const negativeModelDot = document.querySelector("#negativeModelDot");
const affirmativeApiLabel = document.querySelector("#affirmativeApiLabel");
const negativeApiLabel = document.querySelector("#negativeApiLabel");
const apiSettingsButton = document.querySelector("#apiSettingsButton");
const apiKeyModal = document.querySelector("#apiKeyModal");
const apiKeyModalClose = document.querySelector("#apiKeyModalClose");
const apiKeyCancel = document.querySelector("#apiKeyCancel");
const apiKeyForm = document.querySelector("#apiKeyForm");
const apiKeySave = document.querySelector("#apiKeySave");
const apiKeyMessage = document.querySelector("#apiKeyMessage");
const kimiApiKey = document.querySelector("#kimiApiKey");
const deepseekApiKey = document.querySelector("#deepseekApiKey");
const kimiKeyStatus = document.querySelector("#kimiKeyStatus");
const deepseekKeyStatus = document.querySelector("#deepseekKeyStatus");

let isRunning = false;
let isPaused = false;
let activeDebateId = null;
let pollTimer = null;
let providerConfiguration = null;
let hasOfferedInitialConfiguration = false;

const modelNames = {
  kimi: "Kimi",
  deepseek: "DeepSeek",
};

function setConnectionText(text) {
  connectionStatus.lastChild.textContent = ` ${text}`;
}

function renderApiKeyStatuses() {
  const statuses = [
    [kimiKeyStatus, providerConfiguration?.kimi?.ready],
    [deepseekKeyStatus, providerConfiguration?.deepseek?.ready],
  ];
  statuses.forEach(([element, ready]) => {
    element.textContent = ready ? "已配置" : "未配置";
    element.classList.toggle("is-ready", Boolean(ready));
  });
}

function openApiKeyModal(message = "") {
  renderApiKeyStatuses();
  apiKeyMessage.textContent = message;
  apiKeyModal.hidden = false;
  document.body.classList.add("modal-open");
  const firstMissingInput = providerConfiguration?.kimi?.ready
    ? deepseekApiKey
    : kimiApiKey;
  window.setTimeout(() => firstMissingInput.focus(), 0);
}

function closeApiKeyModal() {
  apiKeyForm.reset();
  kimiApiKey.type = "password";
  deepseekApiKey.type = "password";
  document.querySelectorAll("[data-secret-toggle]").forEach((button) => {
    button.textContent = "显示";
  });
  apiKeyMessage.textContent = "";
  apiKeyModal.hidden = true;
  document.body.classList.remove("modal-open");
  apiSettingsButton.focus();
}

function selectedProvidersAreReady() {
  const selectedProviders = new Set([
    affirmativeModel.value,
    negativeModel.value,
  ]);
  const missing = [...selectedProviders].filter(
    (provider) => !providerConfiguration?.[provider]?.ready,
  );
  if (!missing.length) return true;

  const names = missing.map((provider) => modelNames[provider]).join("、");
  const message = `请先配置 ${names} API Key。`;
  formMessage.textContent = message;
  setConnectionText("等待配置 API 密钥");
  openApiKeyModal(message);
  return false;
}

async function saveApiKeys(event) {
  event.preventDefault();
  const keys = {};
  const kimiValue = kimiApiKey.value.trim();
  const deepseekValue = deepseekApiKey.value.trim();
  if (kimiValue) keys.kimi = kimiValue;
  if (deepseekValue) keys.deepseek = deepseekValue;

  if (!Object.keys(keys).length) {
    apiKeyMessage.textContent = "请至少输入一个 API Key。";
    return;
  }

  apiKeySave.disabled = true;
  apiKeySave.textContent = "正在保存…";
  apiKeyMessage.textContent = "";
  try {
    const response = await fetch("/api/config/keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keys }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "无法保存 API 密钥");
    providerConfiguration = payload.providers;
    renderApiKeyStatuses();
    setConnectionText("系统就绪");
    formMessage.textContent = "API 密钥已保存到本机。";
    closeApiKeyModal();
  } catch (error) {
    apiKeyMessage.textContent = error.message;
  } finally {
    apiKeySave.disabled = false;
    apiKeySave.textContent = "保存到本机";
  }
}

function setPauseMode(mode) {
  pauseButton.dataset.mode = mode;
  pauseButtonLabel.textContent = mode === "resume" ? "继续辩论" : "暂停辩论";
}

function updateSeatLabels() {
  const affirmativeName = modelNames[affirmativeModel.value];
  const negativeName = modelNames[negativeModel.value];

  affirmativeApiLabel.textContent = `${affirmativeName} API`;
  negativeApiLabel.textContent = `${negativeName} API`;
  affirmativeModelDot.className = `model-dot model-dot--${affirmativeModel.value}`;
  negativeModelDot.className = `model-dot model-dot--${negativeModel.value}`;
}

function updateCharacterCount() {
  topicCount.textContent = topicInput.value.length;
  formMessage.textContent = "";
}

function setRunningControls(running) {
  isRunning = running;
  topicInput.disabled = running;
  affirmativeModel.disabled = running;
  negativeModel.disabled = running;
  startButton.disabled = running;
  pauseButton.disabled = !running;
  stopButton.disabled = !running;
  speakerStatus.classList.toggle("is-running", running);
  if (!running) {
    isPaused = false;
    setPauseMode("pause");
  }
}

function clearActiveSpeaker() {
  affirmativeCard.classList.remove("is-active");
  negativeCard.classList.remove("is-active");
  affirmativeState.classList.remove("is-speaking");
  negativeState.classList.remove("is-speaking");
}

async function createDebateRecord(topic) {
  const response = await fetch("/api/debates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      topic,
      affirmative: { provider: affirmativeModel.value },
      negative: { provider: negativeModel.value },
    }),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || "无法创建辩论记录");
  }

  return response.json();
}

async function updateDebateRecord(status) {
  if (!activeDebateId) return null;

  const response = await fetch(`/api/debates/${encodeURIComponent(activeDebateId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || "无法更新辩论记录");
  }
  return response.json();
}

function latestSpeech(speeches, side) {
  return [...speeches].reverse().find((speech) => speech.side === side);
}

function renderRunningDebate(debate) {
  isPaused = false;
  const currentSide = debate.currentSpeaker;
  const currentSeat = currentSide ? debate[currentSide] : null;
  const sideName = currentSide === "affirmative" ? "正方" : "反方";
  const affirmativeLatest = latestSpeech(debate.speeches, "affirmative");
  const negativeLatest = latestSpeech(debate.speeches, "negative");

  roundNumber.textContent = String(debate.currentRound).padStart(2, "0");
  if (affirmativeLatest) affirmativeSpeech.textContent = affirmativeLatest.content;
  if (negativeLatest) negativeSpeech.textContent = negativeLatest.content;

  clearActiveSpeaker();
  setPauseMode("pause");
  pauseButton.disabled = Boolean(debate.pauseRequested);
  affirmativeState.textContent = affirmativeLatest ? "已发言" : "等待中";
  negativeState.textContent = negativeLatest ? "已发言" : "等待中";

  if (currentSide && currentSeat) {
    const card = currentSide === "affirmative" ? affirmativeCard : negativeCard;
    const state = currentSide === "affirmative" ? affirmativeState : negativeState;
    card.classList.add("is-active");
    state.classList.add("is-speaking");
    state.textContent = "生成中";
    speakerHint.textContent = debate.pauseRequested
      ? `${sideName}完成本次发言后暂停`
      : `第 ${debate.currentRound} 轮 · ${sideName} ${modelNames[currentSeat.provider]} 正在发言`;
  } else {
    speakerHint.textContent = debate.pauseRequested
      ? "正在进入暂停状态"
      : `第 ${debate.currentRound} 轮即将开始`;
  }
}

function renderPausedDebate(debate) {
  setRunningControls(true);
  isPaused = true;
  speakerStatus.classList.remove("is-running");
  clearActiveSpeaker();
  setPauseMode("resume");
  pauseButton.disabled = false;
  roundNumber.textContent = String(debate.currentRound).padStart(2, "0");

  const affirmativeLatest = latestSpeech(debate.speeches, "affirmative");
  const negativeLatest = latestSpeech(debate.speeches, "negative");
  if (affirmativeLatest) affirmativeSpeech.textContent = affirmativeLatest.content;
  if (negativeLatest) negativeSpeech.textContent = negativeLatest.content;
  affirmativeState.textContent = "已暂停";
  negativeState.textContent = "已暂停";
  speakerHint.textContent = "已暂停，继续后才会调用下一位辩手";
  setConnectionText("辩论已暂停");
}

function finishDebate(debate) {
  setRunningControls(false);
  clearActiveSpeaker();
  stopPolling();
  affirmativeState.textContent = "已停止";
  negativeState.textContent = "已停止";

  if (debate.status === "error") {
    speakerHint.textContent = "辩论因模型调用错误而停止";
    setConnectionText("运行出错");
    formMessage.textContent = debate.error || "模型调用失败";
  } else {
    speakerHint.textContent = "辩论已停止，可修改辩题后重新开始";
    setConnectionText("系统就绪");
  }
  activeDebateId = null;
}

function renderDebate(debate) {
  if (debate.status === "running") {
    renderRunningDebate(debate);
    return;
  }
  if (debate.status === "paused") {
    renderPausedDebate(debate);
    return;
  }
  finishDebate(debate);
}

async function pollDebate() {
  if (!activeDebateId) return;
  try {
    const response = await fetch(`/api/debates/${encodeURIComponent(activeDebateId)}`);
    if (!response.ok) throw new Error("无法读取辩论进度");
    const payload = await response.json();
    renderDebate(payload.debate);
  } catch (error) {
    formMessage.textContent = error.message;
  }
}

function startPolling() {
  stopPolling();
  pollDebate();
  pollTimer = window.setInterval(pollDebate, 750);
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function startDebate() {
  const topic = topicInput.value.trim();

  if (!topic) {
    formMessage.textContent = "请先输入本场辩题。";
    topicInput.focus();
    return;
  }

  if (!providerConfiguration) {
    await checkConfiguration({ openWhenEmpty: false });
  }
  if (!selectedProvidersAreReady()) return;

  setRunningControls(true);
  pauseButton.disabled = true;
  stopButton.disabled = true;
  startButton.querySelector("span").textContent = "正在创建";
  speakerHint.textContent = "正在创建辩论记录…";
  setConnectionText("正在连接模型");
  formMessage.textContent = "";

  try {
    const payload = await createDebateRecord(topic);
    activeDebateId = payload.debate.id;
  } catch (error) {
    setRunningControls(false);
    startButton.querySelector("span").textContent = "开始辩论";
    speakerHint.textContent = "辩论创建失败";
    setConnectionText("等待配置");
    formMessage.textContent = error.message;
    if (error.message.includes("API 密钥")) openApiKeyModal(error.message);
    return;
  }

  stopButton.disabled = false;
  pauseButton.disabled = false;
  startButton.querySelector("span").textContent = "开始辩论";
  setConnectionText("辩论进行中");
  roundNumber.textContent = "01";
  affirmativeSpeech.textContent = "正方正在读取辩题，准备本轮发言。";
  negativeSpeech.textContent = "反方等待正方完成本轮发言。";
  startPolling();
}

async function togglePause() {
  if (!isRunning || !activeDebateId) return;

  pauseButton.disabled = true;
  pauseButtonLabel.textContent = isPaused ? "正在继续" : "等待暂停";
  try {
    const payload = await updateDebateRecord(isPaused ? "running" : "paused");
    renderDebate(payload.debate);
  } catch (error) {
    formMessage.textContent = `${error.message}，请重试。`;
    pauseButton.disabled = false;
    setPauseMode(isPaused ? "resume" : "pause");
  }
}

async function stopDebate() {
  if (!isRunning || !activeDebateId) return;

  stopButton.disabled = true;
  speakerHint.textContent = "正在停止辩论…";
  try {
    const payload = await updateDebateRecord("stopped");
    renderDebate(payload.debate);
  } catch (error) {
    formMessage.textContent = `${error.message}，请重试。`;
    stopButton.disabled = false;
  }
}

async function checkConfiguration({ openWhenEmpty = true } = {}) {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error();
    const payload = await response.json();
    providerConfiguration = payload.providers;
    const ready = Object.values(payload.providers).some((provider) => provider.ready);
    setConnectionText(ready ? "系统就绪" : "等待配置 API 密钥");
    if (openWhenEmpty && !ready && !hasOfferedInitialConfiguration) {
      hasOfferedInitialConfiguration = true;
      openApiKeyModal("首次使用，请先填写至少一个 API Key。");
    }
    return payload.providers;
  } catch {
    setConnectionText("本地服务未连接");
    return null;
  }
}

topicInput.addEventListener("input", updateCharacterCount);
affirmativeModel.addEventListener("change", updateSeatLabels);
negativeModel.addEventListener("change", updateSeatLabels);
topicInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !isRunning) startDebate();
});
startButton.addEventListener("click", startDebate);
pauseButton.addEventListener("click", togglePause);
stopButton.addEventListener("click", stopDebate);
apiSettingsButton.addEventListener("click", () => openApiKeyModal());
apiKeyModalClose.addEventListener("click", closeApiKeyModal);
apiKeyCancel.addEventListener("click", closeApiKeyModal);
apiKeyForm.addEventListener("submit", saveApiKeys);
apiKeyModal.addEventListener("click", (event) => {
  if (event.target === apiKeyModal) closeApiKeyModal();
});
document.querySelectorAll("[data-secret-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = document.querySelector(`#${button.dataset.secretToggle}`);
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    button.textContent = show ? "隐藏" : "显示";
    input.focus();
  });
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !apiKeyModal.hidden) closeApiKeyModal();
});
window.addEventListener("beforeunload", () => {
  if (!activeDebateId) return;
  fetch(`/api/debates/${encodeURIComponent(activeDebateId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: "stopped" }),
    keepalive: true,
  });
});

updateSeatLabels();
checkConfiguration();
