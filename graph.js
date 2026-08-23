const graphTitle = document.querySelector("#graphTitle");
const snapshotDescription = document.querySelector("#snapshotDescription");
const nodeStat = document.querySelector("#nodeStat");
const edgeStat = document.querySelector("#edgeStat");
const summaryModel = document.querySelector("#summaryModel");
const debateStatus = document.querySelector("#debateStatus");
const snapshotTime = document.querySelector("#snapshotTime");
const workspace = document.querySelector("#workspace");
const graphSurface = document.querySelector("#graphSurface");
const edgeLayer = document.querySelector("#edgeLayer");
const roundsLayer = document.querySelector("#roundsLayer");
const detailContent = document.querySelector("#detailContent");
const statePanel = document.querySelector("#statePanel");
const stateTitle = document.querySelector("#stateTitle");
const stateMessage = document.querySelector("#stateMessage");

const relationLabels = {
  supports: "支持",
  rebuts: "反驳",
  responds_to: "回应",
  extends: "延伸",
};

const sideLabels = {
  affirmative: "正方",
  negative: "反方",
};

const kindLabels = {
  viewpoint: "观点",
  core_argument: "核心论点",
  support_evidence: "支持论据",
  rebuttal_evidence: "反驳论据",
  // 兼容旧版已保存的交锋图。
  claim: "主张",
  evidence: "论据",
};

const statusLabels = {
  running: "进行中",
  paused: "已暂停",
  stopped: "已停止",
  error: "运行出错",
};

const modelLabels = {
  "kimi-k2.6": "Kimi K2.6",
  "kimi-k3": "Kimi K3",
  "deepseek-v4-pro": "DeepSeek V4 Pro",
  "deepseek-v4-flash": "DeepSeek V4 Flash",
};

let debate = null;
let graph = { nodes: [], edges: [], updatedThroughRound: 0 };
let nodeById = new Map();
let selectedNodeId = null;
let selectedEdgeId = null;
let redrawFrame = null;

function textElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text;
  return element;
}

function setState(type, title, message) {
  statePanel.hidden = false;
  statePanel.className = `state-panel${type ? ` is-${type}` : ""}`;
  stateTitle.textContent = title;
  stateMessage.textContent = message;
  workspace.hidden = true;
}

function formatDate(value) {
  if (!value) return "—";
  if (typeof value === "string" && !value.includes("T")) return value;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function modelName(seat) {
  if (!seat) return "—";
  return modelLabels[seat.model] || seat.name || seat.model || "—";
}

function sortNodes(nodes) {
  const kindOrder = {
    viewpoint: 0,
    core_argument: 1,
    support_evidence: 2,
    rebuttal_evidence: 3,
    argument: 1,
    claim: 1,
    support: 2,
    evidence: 2,
    rebuttal: 3,
  };
  return [...nodes].sort((a, b) => {
    const kindDifference = (kindOrder[a.kind] ?? 2) - (kindOrder[b.kind] ?? 2);
    if (kindDifference) return kindDifference;
    return String(a.id).localeCompare(String(b.id));
  });
}

function createNode(node) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = [
    "argument-node",
    `argument-node--${node.side}`,
    `argument-node--${node.kind}`,
  ].join(" ");
  button.dataset.nodeId = node.id;
  button.setAttribute(
    "aria-label",
    `${sideLabels[node.side] || "未知方"}${kindLabels[node.kind] || "观点"}：${node.text}`,
  );

  const meta = document.createElement("div");
  meta.className = "argument-node__meta";
  meta.append(
    textElement("span", "argument-node__kind", kindLabels[node.kind] || "观点"),
    textElement("span", "", `#${String(node.id).slice(-4).toUpperCase()}`),
  );
  button.append(meta, textElement("p", "argument-node__text", node.text || "未命名观点"));
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    selectNode(node.id);
  });
  return button;
}

function supportsTarget(node, targetId) {
  return graph.edges.some(
    (edge) => edge.type === "supports" && edge.from === node.id && edge.to === targetId,
  );
}

function createTreeBranch(side, coreNode, supports) {
  const branch = document.createElement("section");
  branch.className = "tree-branch";
  branch.append(createNode(coreNode));
  if (supports.length) {
    const leaves = document.createElement("div");
    leaves.className = "tree-leaves";
    supports.forEach((node) => leaves.append(createNode(node)));
    branch.append(leaves);
  }
  return branch;
}

function createSideTree(side) {
  const tree = document.createElement("section");
  tree.className = `side-tree side-tree--${side}`;
  const ownNodes = graph.nodes.filter((node) => node.side === side);
  const viewpoint = ownNodes.find((node) => node.kind === "viewpoint");
  const coreNodes = sortNodes(ownNodes.filter((node) => node.kind === "core_argument"));
  const supports = sortNodes(ownNodes.filter((node) => node.kind === "support_evidence"));
  const rebuttals = sortNodes(ownNodes.filter((node) => node.kind === "rebuttal_evidence"));

  tree.append(textElement("div", "tree-label", `${sideLabels[side]}交锋树`));
  if (viewpoint) {
    const root = document.createElement("div");
    root.className = "tree-root";
    root.append(createNode(viewpoint));
    tree.append(root);
  }

  const branches = document.createElement("div");
  branches.className = "tree-branches";
  coreNodes.forEach((coreNode) => {
    branches.append(
      createTreeBranch(
        side,
        coreNode,
        supports.filter((node) => supportsTarget(node, coreNode.id)),
      ),
    );
  });
  const rootSupports = viewpoint
    ? supports.filter((node) => supportsTarget(node, viewpoint.id))
    : [];
  if (rootSupports.length) {
    const directBranch = document.createElement("section");
    directBranch.className = "tree-branch tree-branch--direct";
    directBranch.append(textElement("div", "tree-branch__label", "直接支撑"));
    const leaves = document.createElement("div");
    leaves.className = "tree-leaves";
    rootSupports.forEach((node) => leaves.append(createNode(node)));
    directBranch.append(leaves);
    branches.append(directBranch);
  }
  tree.append(branches);

  if (rebuttals.length) {
    const rebuttalSection = document.createElement("section");
    rebuttalSection.className = "tree-rebuttals";
    rebuttalSection.append(textElement("div", "tree-branch__label", "反驳对方"));
    const leaves = document.createElement("div");
    leaves.className = "tree-leaves";
    rebuttals.forEach((node) => leaves.append(createNode(node)));
    rebuttalSection.append(leaves);
    tree.append(rebuttalSection);
  }
  return tree;
}

function updateHeader() {
  const nodes = graph.nodes;
  const edges = graph.edges;
  graphTitle.textContent = debate.topic || "未命名辩题";
  document.title = `${debate.topic || "交锋图"} · AI 辩论场`;
  snapshotDescription.textContent = "总结 Agent 已客观整理当前交锋树；本页不会自动刷新。";
  nodeStat.textContent = String(nodes.length).padStart(2, "0");
  edgeStat.textContent = String(edges.length).padStart(2, "0");
  summaryModel.textContent = modelName(debate.summarizer);
  debateStatus.textContent = statusLabels[debate.status] || debate.status || "未知";
  snapshotTime.textContent = formatDate(debate.updatedAt);
}

function renderGraph() {
  updateHeader();
  nodeById = new Map(graph.nodes.map((node) => [node.id, node]));

  if (!graph.nodes.length) {
    setState(
      "empty",
      "还没有可绘制的交锋数据",
      "总结 Agent 会在正方与反方都完成一轮发言后保存节点和连线。请稍后从辩论页重新打开交锋图。",
    );
    return;
  }

  roundsLayer.replaceChildren();
  roundsLayer.append(createSideTree("affirmative"), createSideTree("negative"));

  statePanel.hidden = true;
  workspace.hidden = false;
  selectedNodeId = null;
  selectedEdgeId = null;
  renderPlaceholder();
  scheduleDraw();
}

function svgElement(tag, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attributes).forEach(([name, value]) => element.setAttribute(name, value));
  return element;
}

function nodeGeometry(nodeElement, surfaceRect) {
  const rect = nodeElement.getBoundingClientRect();
  return {
    left: rect.left - surfaceRect.left,
    right: rect.right - surfaceRect.left,
    top: rect.top - surfaceRect.top,
    bottom: rect.bottom - surfaceRect.top,
    centerX: rect.left - surfaceRect.left + rect.width / 2,
    centerY: rect.top - surfaceRect.top + rect.height / 2,
  };
}

function edgePath(source, target, index) {
  const horizontalDistance = target.centerX - source.centerX;
  if (Math.abs(horizontalDistance) > 150) {
    const leftToRight = horizontalDistance > 0;
    const sx = leftToRight ? source.right : source.left;
    const tx = leftToRight ? target.left : target.right;
    const sy = source.centerY;
    const ty = target.centerY;
    const midpoint = (sx + tx) / 2 + ((index % 5) - 2) * 8;
    return {
      d: `M ${sx} ${sy} C ${midpoint} ${sy}, ${midpoint} ${ty}, ${tx} ${ty}`,
      labelX: midpoint,
      labelY: (sy + ty) / 2 - 5,
    };
  }

  const downward = target.centerY >= source.centerY;
  const sx = source.centerX;
  const tx = target.centerX;
  const sy = downward ? source.bottom : source.top;
  const ty = downward ? target.top : target.bottom;
  const onLeft = source.centerX < graphSurface.clientWidth / 2;
  const unclampedRouteX = onLeft
    ? Math.min(source.left, target.left) - 25 - (index % 4) * 7
    : Math.max(source.right, target.right) + 25 + (index % 4) * 7;
  const routeX = Math.max(22, Math.min(graphSurface.clientWidth - 22, unclampedRouteX));
  return {
    d: `M ${sx} ${sy} C ${routeX} ${sy}, ${routeX} ${ty}, ${tx} ${ty}`,
    labelX: routeX,
    labelY: (sy + ty) / 2 - 5,
  };
}

function drawEdges() {
  redrawFrame = null;
  if (workspace.hidden) return;

  const definitions = edgeLayer.querySelector("defs");
  edgeLayer.replaceChildren(definitions);
  const width = graphSurface.scrollWidth;
  const height = graphSurface.scrollHeight;
  edgeLayer.setAttribute("width", width);
  edgeLayer.setAttribute("height", height);
  edgeLayer.setAttribute("viewBox", `0 0 ${width} ${height}`);

  const surfaceRect = graphSurface.getBoundingClientRect();
  graph.edges.forEach((edge, index) => {
    const sourceElement = roundsLayer.querySelector(`[data-node-id="${CSS.escape(edge.from)}"]`);
    const targetElement = roundsLayer.querySelector(`[data-node-id="${CSS.escape(edge.to)}"]`);
    if (!sourceElement || !targetElement) return;

    const geometry = edgePath(
      nodeGeometry(sourceElement, surfaceRect),
      nodeGeometry(targetElement, surfaceRect),
      index,
    );
    const normalizedType = relationLabels[edge.type] ? edge.type : "responds_to";
    const group = svgElement("g", {
      class: `graph-edge graph-edge--${normalizedType.replaceAll("_", "-")}`,
      "data-edge-id": edge.id,
      role: "button",
      tabindex: "0",
      "aria-label": `${relationLabels[normalizedType]}关系`,
    });
    const title = svgElement("title");
    title.textContent = `${relationLabels[normalizedType]}：${nodeById.get(edge.from)?.text || edge.from} → ${nodeById.get(edge.to)?.text || edge.to}`;
    const hit = svgElement("path", { class: "graph-edge__hit", d: geometry.d });
    const path = svgElement("path", { class: "graph-edge__path", d: geometry.d });
    const label = svgElement("text", {
      class: "graph-edge__label",
      x: geometry.labelX,
      y: geometry.labelY,
    });
    label.textContent = relationLabels[normalizedType];
    group.append(title, hit, path, label);
    group.addEventListener("click", (event) => {
      event.stopPropagation();
      selectEdge(edge.id);
    });
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectEdge(edge.id);
      }
    });
    edgeLayer.append(group);
  });
  applySelectionStyles();
}

function scheduleDraw() {
  if (redrawFrame !== null) cancelAnimationFrame(redrawFrame);
  redrawFrame = requestAnimationFrame(() => requestAnimationFrame(drawEdges));
}

function relationDescription(edge, currentNodeId) {
  const outgoing = edge.from === currentNodeId;
  const counterpartId = outgoing ? edge.to : edge.from;
  const counterpart = nodeById.get(counterpartId);
  return {
    counterpart,
    direction: outgoing ? "指向" : "来自",
    label: relationLabels[edge.type] || "关联",
  };
}

function addRelationsSection(container, node) {
  const relations = graph.edges.filter((edge) => edge.from === node.id || edge.to === node.id);
  const section = document.createElement("section");
  section.className = "detail-section";
  section.append(textElement("h3", "", `关联关系 · ${relations.length}`));

  if (!relations.length) {
    section.append(textElement("p", "source-quote", "这个节点暂时没有已提取的连线。"));
    container.append(section);
    return;
  }

  const list = document.createElement("ul");
  list.className = "relation-list";
  relations.forEach((edge) => {
    const relation = relationDescription(edge, node.id);
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    const type = textElement(
      "strong",
      `type--${String(edge.type).replaceAll("_", "-")}`,
      `${relation.direction} · ${relation.label}`,
    );
    button.append(type, document.createTextNode(relation.counterpart?.text || "未知观点"));
    if (relation.counterpart) {
      button.addEventListener("click", () => selectNode(relation.counterpart.id));
    }
    item.append(button);
    list.append(item);
  });
  section.append(list);
  container.append(section);
}

function createDetailHeader(side, kind) {
  const header = document.createElement("div");
  header.className = "detail-header";
  const badges = document.createElement("div");
  badges.className = "detail-badges";
  badges.append(
    textElement("span", `detail-badge detail-badge--${side}`, sideLabels[side] || "未知方"),
    textElement("span", "detail-badge", kindLabels[kind] || "观点"),
  );
  const close = textElement("button", "detail-close", "×");
  close.type = "button";
  close.setAttribute("aria-label", "关闭详情");
  close.addEventListener("click", clearSelection);
  header.append(badges, close);
  return header;
}

function renderNodeDetail(node) {
  const fragment = document.createDocumentFragment();
  fragment.append(
    createDetailHeader(node.side, node.kind),
    textElement("h2", "detail-title", node.text || "未命名观点"),
  );

  const sourceSection = document.createElement("section");
  sourceSection.className = "detail-section";
  sourceSection.append(textElement("h3", "", "总结依据 · 原句引用"));
  const quote = document.createElement("blockquote");
  quote.className = "source-quote";
  quote.textContent = node.sourceQuote || "没有保存引用原句。";
  sourceSection.append(quote);

  const speech = (debate.speeches || []).find((item) => item.id === node.sourceSpeechId);
  if (speech?.content) {
    const details = document.createElement("details");
    details.className = "speech-details";
    details.append(
      textElement("summary", "", "展开本轮完整发言"),
      textElement("p", "", speech.content),
    );
    sourceSection.append(details);
  }
  fragment.append(sourceSection);
  addRelationsSection(fragment, node);
  detailContent.className = "";
  detailContent.replaceChildren(fragment);
}

function renderEdgeDetail(edge) {
  const source = nodeById.get(edge.from);
  const target = nodeById.get(edge.to);
  const fragment = document.createDocumentFragment();
  fragment.append(createDetailHeader(source?.side || "affirmative", source?.kind || "viewpoint"));
  fragment.append(textElement("h2", "detail-title", `${relationLabels[edge.type] || "关联"}关系`));

  const section = document.createElement("section");
  section.className = "detail-section";
  section.append(textElement("h3", "", "关系方向"));
  const list = document.createElement("ul");
  list.className = "relation-list";
  [
    ["起点", source],
    ["终点", target],
  ].forEach(([label, node]) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.append(textElement("strong", `type--${String(edge.type).replaceAll("_", "-")}`, label));
    button.append(document.createTextNode(node?.text || "未知观点"));
    if (node) button.addEventListener("click", () => selectNode(node.id));
    item.append(button);
    list.append(item);
  });
  section.append(list);
  fragment.append(section);
  detailContent.className = "";
  detailContent.replaceChildren(fragment);
}

function renderPlaceholder() {
  detailContent.className = "detail-placeholder";
  const icon = textElement("span", "detail-placeholder__icon", "⌁");
  icon.setAttribute("aria-hidden", "true");
  detailContent.replaceChildren(
    icon,
    textElement("h2", "", "查看论据脉络"),
    textElement("p", "", "选择一个观点节点，查看总结 Agent 引用的原句及其关联论点。"),
  );
}

function applySelectionStyles() {
  const relatedNodes = new Set();
  const relatedEdges = new Set();

  if (selectedNodeId) {
    relatedNodes.add(selectedNodeId);
    graph.edges.forEach((edge) => {
      if (edge.from === selectedNodeId || edge.to === selectedNodeId) {
        relatedEdges.add(edge.id);
        relatedNodes.add(edge.from);
        relatedNodes.add(edge.to);
      }
    });
  } else if (selectedEdgeId) {
    const edge = graph.edges.find((item) => item.id === selectedEdgeId);
    if (edge) {
      relatedEdges.add(edge.id);
      relatedNodes.add(edge.from);
      relatedNodes.add(edge.to);
    }
  }

  roundsLayer.querySelectorAll(".argument-node").forEach((element) => {
    const id = element.dataset.nodeId;
    element.classList.toggle("is-selected", id === selectedNodeId || relatedNodes.has(id) && Boolean(selectedEdgeId));
    element.classList.toggle("is-muted", relatedNodes.size > 0 && !relatedNodes.has(id));
  });
  edgeLayer.querySelectorAll(".graph-edge").forEach((element) => {
    const id = element.dataset.edgeId;
    element.classList.toggle("is-highlighted", relatedEdges.has(id));
    element.classList.toggle("is-muted", relatedEdges.size > 0 && !relatedEdges.has(id));
  });
}

function selectNode(nodeId) {
  const node = nodeById.get(nodeId);
  if (!node) return;
  selectedNodeId = nodeId;
  selectedEdgeId = null;
  applySelectionStyles();
  renderNodeDetail(node);
}

function selectEdge(edgeId) {
  const edge = graph.edges.find((item) => item.id === edgeId);
  if (!edge) return;
  selectedNodeId = null;
  selectedEdgeId = edgeId;
  applySelectionStyles();
  renderEdgeDetail(edge);
}

function clearSelection() {
  selectedNodeId = null;
  selectedEdgeId = null;
  applySelectionStyles();
  renderPlaceholder();
}

async function loadDebate() {
  const debateId = new URLSearchParams(window.location.search).get("debate");
  if (!debateId) {
    graphTitle.textContent = "没有指定辩论记录";
    snapshotDescription.textContent = "请从辩论页的“查看交锋图”按钮进入。";
    setState("error", "缺少辩论编号", "这个地址没有包含 debate 参数，无法判断要读取哪场辩论。 ");
    return;
  }

  try {
    const response = await fetch(`/api/debates/${encodeURIComponent(debateId)}`, {
      cache: "no-store",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.debate) {
      throw new Error(payload.error || "无法读取这场辩论");
    }
    debate = payload.debate;
    const argumentGraph = debate.argumentGraph || {};
    graph = {
      nodes: Array.isArray(argumentGraph.nodes) ? argumentGraph.nodes : [],
      edges: Array.isArray(argumentGraph.edges) ? argumentGraph.edges : [],
      updatedThroughRound: Number(argumentGraph.updatedThroughRound) || 0,
    };
    renderGraph();
  } catch (error) {
    graphTitle.textContent = "交锋图读取失败";
    snapshotDescription.textContent = "请确认本地服务仍在运行，然后从辩论页重新打开。";
    setState("error", "没有取得交锋数据", error.message);
  }
}

graphSurface.addEventListener("click", (event) => {
  if (!event.target.closest(".argument-node") && !event.target.closest(".graph-edge")) {
    clearSelection();
  }
});
window.addEventListener("resize", scheduleDraw);
if (document.fonts?.ready) document.fonts.ready.then(scheduleDraw);

loadDebate();
