const topicInput = document.querySelector("#topicInput");
const topicCount = document.querySelector("#topicCount");
const startButton = document.querySelector("#startButton");
const graphButton = document.querySelector("#graphButton");
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
const affirmativeConfirmedViewpoint = document.querySelector("#affirmativeConfirmedViewpoint");
const negativeConfirmedViewpoint = document.querySelector("#negativeConfirmedViewpoint");
const affirmativeModel = document.querySelector("#affirmativeModel");
const negativeModel = document.querySelector("#negativeModel");
const viewpointModel = document.querySelector("#viewpointModel");
const summaryModel = document.querySelector("#summaryModel");
const viewpointConfig = document.querySelector("#viewpointConfig");
const viewpointState = document.querySelector("#viewpointState");
const summaryConfig = document.querySelector("#summaryConfig");
const summaryState = document.querySelector("#summaryState");
const viewpointReview = document.querySelector("#viewpointReview");
const affirmativeViewpoint = document.querySelector("#affirmativeViewpoint");
const negativeViewpoint = document.querySelector("#negativeViewpoint");
const viewpointTotalCount = document.querySelector("#viewpointTotalCount");
const viewpointReviewMessage = document.querySelector("#viewpointReviewMessage");
const cancelViewpointsButton = document.querySelector("#cancelViewpointsButton");
const regenerateViewpointsButton = document.querySelector("#regenerateViewpointsButton");
const confirmViewpointsButton = document.querySelector("#confirmViewpointsButton");
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
let latestDebateId = null;
let pendingTopic = null;
let isReviewingViewpoints = false;
let isGeneratingViewpoints = false;
let pollTimer = null;
let providerConfiguration = null;
let hasOfferedInitialConfiguration = false;

const providerNames = {
  kimi: "Kimi",
  deepseek: "DeepSeek",
};

const modelNames = new Map(
  [...affirmativeModel.options].map((option) => [
    option.value,
    option.textContent.trim(),
  ]),
);
const modelPickerControls = new Map();

function selectedModel(select) {
  const option = select.selectedOptions[0];
  return {
    provider: option.dataset.provider,
    model: option.value,
    name: option.textContent.trim(),
  };
}

function displayModelName(seat) {
  return modelNames.get(seat.model) || providerNames[seat.provider] || seat.model;
}

function closeModelPickers(exceptPicker = null) {
  modelPickerControls.forEach((control) => {
    if (control.picker !== exceptPicker) control.close();
  });
}

function setupModelPicker(select) {
  const picker = select.closest(".model-picker");
  select.classList.add("model-picker__native");
  select.hidden = true;
  select.tabIndex = -1;
  select.setAttribute("aria-hidden", "true");

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "model-picker__trigger";
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", "false");

  const triggerLabel = document.createElement("span");
  triggerLabel.className = "model-picker__trigger-label";
  const chevron = document.createElement("span");
  chevron.className = "model-picker__chevron";
  chevron.setAttribute("aria-hidden", "true");
  chevron.textContent = "▼";
  trigger.append(triggerLabel, chevron);

  const menu = document.createElement("div");
  menu.id = `${select.id}Menu`;
  menu.className = "model-picker__menu";
  menu.setAttribute("role", "listbox");
  menu.setAttribute("aria-label", select.getAttribute("aria-label"));
  menu.hidden = true;
  trigger.setAttribute("aria-controls", menu.id);

  const optionButtons = [];
  [...select.children].forEach((group) => {
    const options = group.matches("optgroup")
      ? [...group.querySelectorAll("option")]
      : group.matches("option")
        ? [group]
        : [];
    if (!options.length) return;

    if (group.matches("optgroup")) {
      const groupLabel = document.createElement("div");
      groupLabel.className = "model-picker__group-label";
      groupLabel.textContent = group.label;
      menu.append(groupLabel);
    }

    options.forEach((option) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "model-picker__option";
      button.dataset.value = option.value;
      button.setAttribute("role", "option");
      button.tabIndex = -1;

      const providerDot = document.createElement("span");
      providerDot.className =
        `model-picker__provider-dot model-picker__provider-dot--${option.dataset.provider}`;
      providerDot.setAttribute("aria-hidden", "true");

      const label = document.createElement("span");
      label.className = "model-picker__option-label";
      label.textContent = option.textContent.trim();

      const check = document.createElement("span");
      check.className = "model-picker__check";
      check.setAttribute("aria-hidden", "true");
      check.textContent = "✓";

      button.append(providerDot, label, check);
      menu.append(button);
      optionButtons.push(button);
    });
  });

  function selectedButtonIndex() {
    return optionButtons.findIndex((button) => button.dataset.value === select.value);
  }

  function sync() {
    const option = select.selectedOptions[0];
    triggerLabel.textContent = option.textContent.trim();
    trigger.setAttribute(
      "aria-label",
      `${select.getAttribute("aria-label")}，当前 ${option.textContent.trim()}`,
    );
    optionButtons.forEach((button) => {
      const selected = button.dataset.value === select.value;
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
  }

  function close() {
    menu.hidden = true;
    picker.classList.remove("is-open");
    trigger.setAttribute("aria-expanded", "false");
  }

  function focusOption(index) {
    const normalizedIndex = (index + optionButtons.length) % optionButtons.length;
    optionButtons[normalizedIndex].focus();
  }

  function open({ focusSelected = false } = {}) {
    if (trigger.disabled) return;
    closeModelPickers(picker);
    menu.hidden = false;
    picker.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
    if (focusSelected) {
      window.setTimeout(() => focusOption(selectedButtonIndex()), 0);
    }
  }

  function choose(button) {
    select.value = button.dataset.value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
    sync();
    close();
    trigger.focus();
  }

  trigger.addEventListener("click", () => {
    if (menu.hidden) open();
    else close();
  });
  trigger.addEventListener("keydown", (event) => {
    if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
    event.preventDefault();
    open({ focusSelected: true });
  });

  optionButtons.forEach((button, index) => {
    button.addEventListener("click", () => choose(button));
    button.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        focusOption(index + (event.key === "ArrowDown" ? 1 : -1));
      } else if (event.key === "Home" || event.key === "End") {
        event.preventDefault();
        focusOption(event.key === "Home" ? 0 : optionButtons.length - 1);
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        choose(button);
      } else if (event.key === "Escape") {
        event.preventDefault();
        close();
        trigger.focus();
      } else if (event.key === "Tab") {
        close();
      }
    });
  });

  select.addEventListener("change", sync);
  picker.append(trigger, menu);

  const control = {
    picker,
    close,
    syncDisabled() {
      trigger.disabled = select.disabled;
      if (trigger.disabled) close();
    },
  };
  modelPickerControls.set(select, control);
  sync();
  control.syncDisabled();
}

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
  closeModelPickers();
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
    selectedModel(affirmativeModel).provider,
    selectedModel(negativeModel).provider,
    selectedModel(viewpointModel).provider,
    selectedModel(summaryModel).provider,
  ]);
  const missing = [...selectedProviders].filter(
    (provider) => !providerConfiguration?.[provider]?.ready,
  );
  if (!missing.length) return true;

  const names = missing.map((provider) => providerNames[provider]).join("、");
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
  const affirmative = selectedModel(affirmativeModel);
  const negative = selectedModel(negativeModel);

  affirmativeApiLabel.textContent = `${affirmative.name} API`;
  negativeApiLabel.textContent = `${negative.name} API`;
  affirmativeModelDot.className = `model-dot model-dot--${affirmative.provider}`;
  negativeModelDot.className = `model-dot model-dot--${negative.provider}`;
}

function updateCharacterCount() {
  topicCount.textContent = topicInput.value.length;
  formMessage.textContent = "";
  if (!isReviewingViewpoints && !isGeneratingViewpoints && !isRunning) {
    viewpointState.textContent = "等待中";
  }
}

function syncSetupControls() {
  const locked = isRunning || isReviewingViewpoints || isGeneratingViewpoints;
  topicInput.disabled = locked;
  [affirmativeModel, negativeModel, viewpointModel, summaryModel].forEach((select) => {
    select.disabled = locked;
    modelPickerControls.get(select)?.syncDisabled();
  });
  startButton.disabled = locked;
}

function setRunningControls(running) {
  isRunning = running;
  syncSetupControls();
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
  viewpointConfig.classList.remove("is-active");
  summaryConfig.classList.remove("is-active");
  affirmativeState.classList.remove("is-speaking");
  negativeState.classList.remove("is-speaking");
  viewpointState.classList.remove("is-speaking");
  summaryState.classList.remove("is-speaking");
}

async function createDebateRecord(topic, viewpoints) {
  const affirmative = selectedModel(affirmativeModel);
  const negative = selectedModel(negativeModel);
  const viewpointAgent = selectedModel(viewpointModel);
  const summarizer = selectedModel(summaryModel);
  const response = await fetch("/api/debates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      topic,
      affirmative: { provider: affirmative.provider, model: affirmative.model },
      negative: { provider: negative.provider, model: negative.model },
      viewpointAgent: { provider: viewpointAgent.provider, model: viewpointAgent.model },
      summarizer: { provider: summarizer.provider, model: summarizer.model },
      viewpoints,
    }),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || "无法创建辩论记录");
  }

  return response.json();
}

async function requestViewpoints(topic) {
  const agent = selectedModel(viewpointModel);
  const response = await fetch("/api/viewpoints", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      topic,
      agent: { provider: agent.provider, model: agent.model },
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || "无法生成双方观点");
  return payload;
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

function renderConfirmedViewpoints(viewpoints) {
  const affirmative = String(viewpoints?.affirmative || "").trim();
  const negative = String(viewpoints?.negative || "").trim();
  const hasViewpoints = Boolean(affirmative && negative);
  affirmativeConfirmedViewpoint.hidden = !hasViewpoints;
  negativeConfirmedViewpoint.hidden = !hasViewpoints;
  if (!hasViewpoints) return;
  affirmativeConfirmedViewpoint.querySelector("p").textContent = affirmative;
  negativeConfirmedViewpoint.querySelector("p").textContent = negative;
}

function renderRunningDebate(debate) {
  isPaused = false;
  const isOpening = debate.phase === "opening";
  const currentSide = debate.currentSpeaker;
  const currentSeat = currentSide ? debate[currentSide] : null;
  const sideName = currentSide === "affirmative" ? "正方" : "反方";
  const affirmativeLatest = latestSpeech(debate.speeches, "affirmative");
  const negativeLatest = latestSpeech(debate.speeches, "negative");
  renderConfirmedViewpoints(debate.viewpoints);

  roundNumber.textContent = isOpening
    ? "立论"
    : String(debate.currentRound).padStart(2, "0");
  if (affirmativeLatest) affirmativeSpeech.textContent = affirmativeLatest.content;
  if (negativeLatest) negativeSpeech.textContent = negativeLatest.content;

  clearActiveSpeaker();
  setPauseMode("pause");
  pauseButton.disabled = Boolean(debate.pauseRequested);
  affirmativeState.textContent = affirmativeLatest
    ? isOpening ? "已立论" : "已发言"
    : "等待中";
  negativeState.textContent = negativeLatest
    ? isOpening ? "已立论" : "已发言"
    : "等待中";
  viewpointState.textContent = "已确认";
  const latestSummary = debate.roundSummaries?.at(-1);
  summaryState.textContent = !latestSummary
    ? "等待中"
    : latestSummary.decision === "refuse" ? "已拒绝入图"
    : latestSummary.decision === "hold" ? "已审阅，保持原图"
    : "已更新";

  if (currentSide === "summarizer" && currentSeat) {
    summaryConfig.classList.add("is-active");
    summaryState.classList.add("is-speaking");
    summaryState.textContent = "生成中";
    speakerHint.textContent = debate.pauseRequested
      ? "总结 Agent 完成交锋图更新后暂停"
      : isOpening
        ? `立论阶段 · 总结 Agent ${displayModelName(currentSeat)} 正在整理交锋图`
        : `第 ${debate.currentRound} 轮 · 总结 Agent ${displayModelName(currentSeat)} 正在整理交锋图`;
  } else if (currentSide && currentSeat) {
    const card = currentSide === "affirmative" ? affirmativeCard : negativeCard;
    const state = currentSide === "affirmative" ? affirmativeState : negativeState;
    card.classList.add("is-active");
    state.classList.add("is-speaking");
    state.textContent = "生成中";
    speakerHint.textContent = debate.pauseRequested
      ? `${sideName}完成本次发言后暂停`
      : isOpening
        ? `立论阶段 · ${sideName} ${displayModelName(currentSeat)} 正在生成立论`
        : `第 ${debate.currentRound} 轮 · ${sideName} ${displayModelName(currentSeat)} 正在发言`;
  } else {
    speakerHint.textContent = debate.pauseRequested
      ? "正在进入暂停状态"
      : isOpening ? "立论阶段即将开始" : `第 ${debate.currentRound} 轮即将开始`;
  }
}

function renderPausedDebate(debate) {
  setRunningControls(true);
  isPaused = true;
  speakerStatus.classList.remove("is-running");
  clearActiveSpeaker();
  setPauseMode("resume");
  pauseButton.disabled = false;
  roundNumber.textContent = debate.phase === "opening"
    ? "立论"
    : String(debate.currentRound).padStart(2, "0");

  const affirmativeLatest = latestSpeech(debate.speeches, "affirmative");
  const negativeLatest = latestSpeech(debate.speeches, "negative");
  renderConfirmedViewpoints(debate.viewpoints);
  if (affirmativeLatest) affirmativeSpeech.textContent = affirmativeLatest.content;
  if (negativeLatest) negativeSpeech.textContent = negativeLatest.content;
  affirmativeState.textContent = "已暂停";
  negativeState.textContent = "已暂停";
  viewpointState.textContent = "已确认";
  summaryState.textContent = "已暂停";
  speakerHint.textContent = "已暂停，继续后才会调用下一位 Agent";
  setConnectionText("辩论已暂停");
}

function finishDebate(debate) {
  setRunningControls(false);
  clearActiveSpeaker();
  stopPolling();
  affirmativeState.textContent = "已停止";
  negativeState.textContent = "已停止";
  viewpointState.textContent = debate.viewpoints ? "已确认" : "等待中";
  summaryState.textContent = "已停止";
  renderConfirmedViewpoints(debate.viewpoints);

  if (debate.status === "error") {
    speakerHint.textContent = "辩论因模型调用错误而停止";
    setConnectionText("运行出错");
    formMessage.textContent = debate.error || "模型调用失败";
  } else {
    speakerHint.textContent = "辩论已停止，可修改辩题后重新开始";
    setConnectionText("系统就绪");
  }
  startButton.querySelector("span").textContent = "生成双方观点";
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

function openArgumentGraph() {
  if (!latestDebateId) return;

  const graphUrl = new URL("/graph.html", window.location.origin);
  graphUrl.searchParams.set("debate", latestDebateId);
  graphUrl.searchParams.set("snapshot", Date.now());
  const graphWindow = window.open(graphUrl.toString(), "ai-debate-argument-graph");
  if (!graphWindow) {
    formMessage.textContent = "浏览器阻止了新标签页，请允许本站打开弹窗后重试。";
    return;
  }
  graphWindow.focus();
}

function currentViewpoints() {
  return {
    affirmative: affirmativeViewpoint.value.trim(),
    negative: negativeViewpoint.value.trim(),
  };
}

function updateViewpointCount() {
  const viewpoints = currentViewpoints();
  const total = viewpoints.affirmative.length + viewpoints.negative.length;
  viewpointTotalCount.textContent = total;
  viewpointTotalCount.parentElement.classList.toggle("is-over-limit", total > 50);
  if (viewpointReviewMessage.textContent) viewpointReviewMessage.textContent = "";
  return total;
}

function setViewpointReviewBusy(busy) {
  affirmativeViewpoint.disabled = busy;
  negativeViewpoint.disabled = busy;
  cancelViewpointsButton.disabled = busy;
  regenerateViewpointsButton.disabled = busy;
  confirmViewpointsButton.disabled = busy;
}

function ensureViewpointProviderIsReady() {
  const selected = selectedModel(viewpointModel);
  if (providerConfiguration?.[selected.provider]?.ready) return true;
  const message = `请先配置 ${providerNames[selected.provider]} API Key。`;
  formMessage.textContent = message;
  setConnectionText("等待配置 API 密钥");
  openApiKeyModal(message);
  return false;
}

async function generateViewpoints(topicOverride = null) {
  const topic = (topicOverride || topicInput.value).trim();
  if (!topic) {
    formMessage.textContent = "请先输入本场辩题。";
    topicInput.focus();
    return;
  }

  if (!providerConfiguration) {
    await checkConfiguration({ openWhenEmpty: false });
  }
  if (!ensureViewpointProviderIsReady()) return;

  const wasReviewing = isReviewingViewpoints;
  isReviewingViewpoints = false;
  isGeneratingViewpoints = true;
  syncSetupControls();
  setViewpointReviewBusy(true);
  viewpointConfig.classList.add("is-active");
  viewpointState.classList.add("is-speaking");
  viewpointState.textContent = "生成中";
  speakerStatus.classList.add("is-running");
  startButton.querySelector("span").textContent = "正在生成观点";
  speakerHint.textContent = `立场生成 Agent ${selectedModel(viewpointModel).name} 正在凝练双方观点`;
  setConnectionText("观点 Agent 工作中");
  formMessage.textContent = "";
  viewpointReviewMessage.textContent = "";

  try {
    const payload = await requestViewpoints(topic);
    pendingTopic = payload.topic;
    affirmativeViewpoint.value = payload.viewpoints.affirmative;
    negativeViewpoint.value = payload.viewpoints.negative;
    updateViewpointCount();
    viewpointReview.hidden = false;
    isReviewingViewpoints = true;
    viewpointState.textContent = "待确认";
    speakerHint.textContent = "观点已生成，请二次确认后开始立论";
    setConnectionText("等待观点确认");
    window.setTimeout(() => affirmativeViewpoint.focus(), 0);
  } catch (error) {
    isReviewingViewpoints = wasReviewing;
    viewpointState.textContent = "生成失败";
    speakerHint.textContent = wasReviewing ? "保留上次观点，请修改或重新生成" : "观点生成失败";
    setConnectionText("观点生成失败");
    formMessage.textContent = error.message;
    if (error.message.includes("API 密钥")) openApiKeyModal(error.message);
  } finally {
    isGeneratingViewpoints = false;
    viewpointConfig.classList.remove("is-active");
    viewpointState.classList.remove("is-speaking");
    speakerStatus.classList.remove("is-running");
    startButton.querySelector("span").textContent = "生成双方观点";
    setViewpointReviewBusy(false);
    syncSetupControls();
  }
}

function cancelViewpointReview() {
  isReviewingViewpoints = false;
  pendingTopic = null;
  viewpointReview.hidden = true;
  viewpointReviewMessage.textContent = "";
  viewpointState.textContent = "等待中";
  speakerHint.textContent = "等待输入辩题";
  setConnectionText("系统就绪");
  syncSetupControls();
  topicInput.focus();
}

async function confirmViewpoints() {
  const viewpoints = currentViewpoints();
  const total = updateViewpointCount();
  if (!viewpoints.affirmative || !viewpoints.negative) {
    viewpointReviewMessage.textContent = "正方观点和反方观点都不能为空。";
    return;
  }
  if (total > 50) {
    viewpointReviewMessage.textContent = "双方观点合计不得超过 50 字。";
    return;
  }
  if (!pendingTopic) {
    viewpointReviewMessage.textContent = "观点对应的辩题已失效，请返回重新生成。";
    return;
  }
  if (!selectedProvidersAreReady()) return;

  setViewpointReviewBusy(true);
  setRunningControls(true);
  pauseButton.disabled = true;
  stopButton.disabled = true;
  viewpointState.textContent = "确认中";
  speakerHint.textContent = "正在发送确认观点并创建立论阶段…";
  setConnectionText("正在创建辩论");
  formMessage.textContent = "";

  try {
    const payload = await createDebateRecord(pendingTopic, viewpoints);
    activeDebateId = payload.debate.id;
    latestDebateId = payload.debate.id;
    graphButton.disabled = false;
  } catch (error) {
    setRunningControls(false);
    viewpointState.textContent = "待确认";
    speakerHint.textContent = "辩论创建失败，请检查后重新确认";
    setConnectionText("等待观点确认");
    viewpointReviewMessage.textContent = error.message;
    setViewpointReviewBusy(false);
    if (error.message.includes("API 密钥")) openApiKeyModal(error.message);
    return;
  }

  isReviewingViewpoints = false;
  pendingTopic = null;
  viewpointReview.hidden = true;
  syncSetupControls();
  stopButton.disabled = false;
  pauseButton.disabled = false;
  viewpointState.textContent = "已确认";
  setConnectionText("立论阶段进行中");
  roundNumber.textContent = "立论";
  affirmativeSpeech.textContent = "正方正在读取双方已确认的观点，准备立论。";
  negativeSpeech.textContent = "反方已收到相同观点，等待正方完成立论。";
  renderConfirmedViewpoints(viewpoints);
  summaryState.textContent = "等待中";
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
  if (event.key === "Enter" && !isRunning && !isReviewingViewpoints) {
    generateViewpoints();
  }
});
startButton.addEventListener("click", () => generateViewpoints());
affirmativeViewpoint.addEventListener("input", updateViewpointCount);
negativeViewpoint.addEventListener("input", updateViewpointCount);
cancelViewpointsButton.addEventListener("click", cancelViewpointReview);
regenerateViewpointsButton.addEventListener("click", () => generateViewpoints(pendingTopic));
confirmViewpointsButton.addEventListener("click", confirmViewpoints);
graphButton.addEventListener("click", openArgumentGraph);
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
  if (event.key !== "Escape") return;
  closeModelPickers();
  if (!apiKeyModal.hidden) closeApiKeyModal();
});
document.addEventListener("click", (event) => {
  modelPickerControls.forEach((control) => {
    if (!control.picker.contains(event.target)) control.close();
  });
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

setupModelPicker(affirmativeModel);
setupModelPicker(negativeModel);
setupModelPicker(viewpointModel);
setupModelPicker(summaryModel);
updateSeatLabels();
checkConfiguration();
