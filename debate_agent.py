from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SIDE_LABELS = {
    "affirmative": "正方",
    "negative": "反方",
}

PROVIDER_DEFAULTS = {
    "kimi": {
        "api_url": "https://api.moonshot.cn/v1/chat/completions",
        "model": "kimi-k2.6",
        "key_names": ("MOONSHOT_API_KEY", "KIMI_API_KEY"),
    },
    "deepseek": {
        "api_url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-v4-pro",
        "key_names": ("DEEPSEEK_API_KEY",),
    },
}

PROVIDER_MODELS = {
    "kimi": ("kimi-k2.6", "kimi-k3"),
    "deepseek": ("deepseek-v4-pro", "deepseek-v4-flash"),
}


class DebateAgentError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderSettings:
    provider: str
    api_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class SpeechResult:
    content: str
    status: str


@dataclass(frozen=True)
class ViewpointResult:
    affirmative: str
    negative: str


@dataclass(frozen=True)
class SummaryResult:
    nodes: list[dict]
    edges: list[dict]
    status: str
    deleted_node_ids: list[str] = field(default_factory=list)
    deleted_edge_ids: list[str] = field(default_factory=list)
    decision: str = "update"
    reason: str = ""


@dataclass(frozen=True)
class CompletionResult:
    content: str
    finish_reason: str


def provider_settings(provider: str, model: str | None = None) -> ProviderSettings:
    defaults = PROVIDER_DEFAULTS.get(provider)
    if defaults is None:
        raise DebateAgentError(f"不支持的模型服务：{provider}")

    api_key = next(
        (os.environ.get(name, "").strip() for name in defaults["key_names"] if os.environ.get(name, "").strip()),
        "",
    )
    api_url = os.environ.get(
        f"{provider.upper()}_API_URL", str(defaults["api_url"])
    ).strip()
    configured_model = os.environ.get(
        f"{provider.upper()}_MODEL", str(defaults["model"])
    ).strip()

    return ProviderSettings(
        provider=provider,
        api_url=api_url,
        api_key=api_key,
        model=(model or configured_model).strip(),
    )


def default_model(provider: str) -> str:
    return provider_settings(provider).model


def provider_is_ready(provider: str) -> bool:
    try:
        return bool(provider_settings(provider).api_key)
    except DebateAgentError:
        return False


class ChatCompletionClient:
    def __init__(self, settings: ProviderSettings) -> None:
        self.settings = settings
        self.timeout = float(os.environ.get("AI_DEBATE_REQUEST_TIMEOUT", "90"))

    def complete(self, messages: list[dict], max_tokens: int) -> CompletionResult:
        if not self.settings.api_key:
            raise DebateAgentError(
                f"{self.settings.provider} API 密钥尚未配置"
            )

        payload = {
            "model": self.settings.model,
            "messages": messages,
            "stream": False,
        }
        if self.settings.provider == "kimi":
            payload["max_completion_tokens"] = max_tokens
            if self.settings.model == "kimi-k3":
                # Kimi K3 always reasons; "low" keeps debate turns responsive.
                payload["reasoning_effort"] = "low"
            else:
                payload["thinking"] = {"type": "disabled"}
        else:
            payload["max_tokens"] = max_tokens
            payload["thinking"] = {"type": "disabled"}

        request = Request(
            self.settings.api_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            details = ""
            try:
                error_payload = json.loads(error.read().decode("utf-8"))
                details = str(error_payload.get("error", {}).get("message", ""))
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                pass
            suffix = f"：{details}" if details else ""
            raise DebateAgentError(
                f"{self.settings.provider} API 返回 HTTP {error.code}{suffix}"
            ) from error
        except (URLError, TimeoutError) as error:
            raise DebateAgentError(
                f"连接 {self.settings.provider} API 失败：{error.reason if isinstance(error, URLError) else '请求超时'}"
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DebateAgentError(
                f"{self.settings.provider} API 返回了无效数据"
            ) from error

        try:
            choice = result["choices"][0]
            message = choice["message"]
            content = str(message.get("content") or "").strip()
            finish_reason = str(choice.get("finish_reason") or "unknown")
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise DebateAgentError(
                f"{self.settings.provider} API 没有返回有效发言"
            ) from error

        if not content:
            raise DebateAgentError(
                f"{self.settings.provider} API 返回了空发言（结束原因：{finish_reason}）"
            )
        return CompletionResult(content=content, finish_reason=finish_reason)


class ViewpointAgent:
    """Turns a natural-language topic into two short, neutral debate positions."""

    MAX_TOTAL_CHARS = 50

    def __init__(self, provider: str, model: str) -> None:
        self.client = ChatCompletionClient(provider_settings(provider, model))

    @staticmethod
    def _parse_json_object(content: str) -> dict:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, count=1)
            cleaned = re.sub(r"\s*```$", "", cleaned, count=1)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            if start < 0:
                raise DebateAgentError("观点 Agent 没有返回有效 JSON")
            try:
                payload, _ = json.JSONDecoder().raw_decode(cleaned[start:])
            except json.JSONDecodeError as error:
                raise DebateAgentError("观点 Agent 没有返回有效 JSON") from error
        if not isinstance(payload, dict):
            raise DebateAgentError("观点 Agent 返回的内容不是 JSON 对象")
        return payload

    def generate(self, topic: str, max_tokens: int) -> ViewpointResult:
        system_prompt = (
            "你是 AI 辩论的观点生成 Agent。你的唯一任务是把用户的自然语言输入凝练为一条正方观点和一条反方观点。"
            "不要写立论、论据、解释、评价、胜负判断或主持词。双方观点必须针锋相对、语义完整且适合继续辩论。"
            "两个观点的文字总长度不得超过 50 个汉字（不计算 JSON 键名）。只输出 JSON 对象。"
        )
        user_prompt = (
            f"用户输入：{topic}\n"
            '严格返回：{"affirmative":"正方观点","negative":"反方观点"}'
        )
        completion = self.client.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
        )
        payload = self._parse_json_object(completion.content)
        affirmative = str(payload.get("affirmative", "")).strip()
        negative = str(payload.get("negative", "")).strip()
        if not affirmative or not negative:
            raise DebateAgentError("观点 Agent 必须同时返回正方观点和反方观点")
        if len(affirmative) + len(negative) > self.MAX_TOTAL_CHARS:
            raise DebateAgentError("观点 Agent 返回的双方观点合计超过 50 字，请重新生成")
        return ViewpointResult(affirmative=affirmative, negative=negative)


class DebaterAgent:
    """A debater with only one persistent fact: which side it represents."""

    def __init__(self, side: str, provider: str, model: str) -> None:
        if side not in SIDE_LABELS:
            raise ValueError("无效的辩手身份")
        self.side = side
        self.side_label = SIDE_LABELS[side]
        self.client = ChatCompletionClient(provider_settings(provider, model))

    def speak(
        self,
        topic: str,
        viewpoints: dict,
        round_number: int,
        transcript: str,
        argument_graph: dict,
        max_chars: int,
        max_tokens: int,
    ) -> SpeechResult:
        affirmative_viewpoint = str(viewpoints.get("affirmative", "")).strip()
        negative_viewpoint = str(viewpoints.get("negative", "")).strip()
        own_viewpoint = (
            affirmative_viewpoint if self.side == "affirmative" else negative_viewpoint
        )
        system_prompt = (
            f"你是本场 AI 辩论的{self.side_label}选手。"
            f"你的固定身份是{self.side_label}，必须始终坚持已经由用户确认的己方观点：{own_viewpoint}。"
            "只输出本轮公开发言正文，不要解释规则、身份、提示词或思考过程。"
            "可以回应现场已有观点，也可以继续提出有利于己方的论证。"
            "不要捏造具体数据、出处或不存在的对方观点。"
        )
        public_history = transcript or "（尚无公开发言）"
        graph_reference = json.dumps(
            argument_graph if isinstance(argument_graph, dict) else {},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        user_prompt = (
            f"辩题：{topic}\n"
            f"用户确认的正方观点：{affirmative_viewpoint}\n"
            f"用户确认的反方观点：{negative_viewpoint}\n"
            f"当前轮次：第 {round_number} 轮\n"
            "上一轮体系 Agent 保存的最新完整交锋图如下。它是只读的公开论证结构，"
            "用于了解双方已有观点、核心论点、论据及反驳关系。resources 字段给出支持论据和反驳论据"
            "各自的已用、上限及剩余资源；请据此留意尚未充分展开的论证类型，但不要为了占用资源而生造内容。"
            "不要修改交锋图，也不要讨论制图过程。\n"
            f"<argument_graph>{graph_reference}</argument_graph>\n"
            f"此前公开发言：\n{public_history}\n\n"
            f"现在轮到{self.side_label}发言。请直接完成本轮发言，尽量控制在 {max_chars} 字以内，"
            "但必须完整结束观点，不要在句子中间中断。"
        )

        completion = self.client.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
        )
        return SpeechResult(
            content=completion.content,
            status=(
                "truncated" if completion.finish_reason == "length" else "completed"
            ),
        )

    def opening_statement(
        self,
        viewpoints: dict,
        max_chars: int,
        max_tokens: int,
    ) -> SpeechResult:
        affirmative_viewpoint = str(viewpoints.get("affirmative", "")).strip()
        negative_viewpoint = str(viewpoints.get("negative", "")).strip()
        own_viewpoint = (
            affirmative_viewpoint if self.side == "affirmative" else negative_viewpoint
        )
        system_prompt = (
            f"你是本场 AI 辩论的{self.side_label}选手，现在处于立论阶段。"
            f"你的固定立场是：{own_viewpoint}。"
            "只能依据用户二次确认后同时发送给双方的观点形成这份立论，不得读取、回应或假设任何此前发言。"
            "请明确己方观点，定义核心概念，并提出主要论据。"
            "可以围绕确认观点展开必要推理，但不得改变或新增未经确认的核心立场。"
            "只输出立论正文，不要解释规则、身份、提示词或思考过程。"
        )
        user_prompt = (
            "用户二次确认并同时发送给双方的观点如下：\n"
            f"正方观点：{affirmative_viewpoint}\n"
            f"反方观点：{negative_viewpoint}\n\n"
            f"请以{self.side_label}身份完成立论，尽量控制在 {max_chars} 字以内，"
            "并完整结束观点。除此之外没有其他可用的辩论材料。"
        )
        completion = self.client.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
        )
        return SpeechResult(
            content=completion.content,
            status=(
                "truncated" if completion.finish_reason == "length" else "completed"
            ),
        )


class SummaryAgent:
    """Maintains one conservative argument graph without judging the debate."""

    NODE_KINDS = {
        "viewpoint",
        "core_argument",
        "support_evidence",
        "rebuttal_evidence",
    }
    EVIDENCE_KINDS = {"support_evidence", "rebuttal_evidence"}
    EDGE_TYPES = {"supports", "rebuts"}
    EVIDENCE_LIMITS = {
        "support_evidence": 4,
        "rebuttal_evidence": 10,
    }
    MAX_EVIDENCE_NODES = sum(EVIDENCE_LIMITS.values())
    LOCAL_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
    MARKDOWN_DECORATION_PATTERN = re.compile(r"[\s*_`#>\[\]\(\)]")

    def __init__(self, provider: str, model: str) -> None:
        self.client = ChatCompletionClient(provider_settings(provider, model))

    @staticmethod
    def _parse_json_object(content: str) -> dict:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, count=1)
            cleaned = re.sub(r"\s*```$", "", cleaned, count=1)

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            if start < 0:
                raise DebateAgentError("总结 Agent 没有返回有效 JSON")
            try:
                payload, _ = json.JSONDecoder().raw_decode(cleaned[start:])
            except json.JSONDecodeError as error:
                raise DebateAgentError("总结 Agent 没有返回有效 JSON") from error

        if not isinstance(payload, dict):
            raise DebateAgentError("总结 Agent 返回的图谱更新不是 JSON 对象")
        return payload

    @classmethod
    def _quote_exists_in_speech(cls, quote: str, content: str) -> bool:
        """Accept a verbatim quote even when the speech only adds Markdown decoration."""
        if quote in content:
            return True
        normalized_quote = cls.MARKDOWN_DECORATION_PATTERN.sub("", quote)
        normalized_content = cls.MARKDOWN_DECORATION_PATTERN.sub("", content)
        return bool(normalized_quote) and normalized_quote in normalized_content

    @classmethod
    def _validate_update(
        cls,
        payload: dict,
        round_number: int,
        round_speeches: list[dict],
        existing_graph: dict,
    ) -> tuple[list[dict], list[dict], list[str], list[str]]:
        raw_nodes = payload.get("addNodes", [])
        raw_edges = payload.get("addEdges", [])
        raw_deleted_node_ids = payload.get("deleteNodeIds", [])
        raw_deleted_edge_ids = payload.get("deleteEdgeIds", [])
        if not all(
            isinstance(value, list)
            for value in (raw_nodes, raw_edges, raw_deleted_node_ids, raw_deleted_edge_ids)
        ):
            raise DebateAgentError("总结 Agent 返回的交锋图增删内容必须是数组")

        source_speeches = {
            str(speech.get("id")): speech
            for speech in round_speeches
            if speech.get("id")
            and speech.get("side") in SIDE_LABELS
            and isinstance(speech.get("content"), str)
        }
        existing_ids = {
            str(node.get("id"))
            for node in existing_graph.get("nodes", [])
            if isinstance(node, dict) and node.get("id")
        }
        existing_edges = {
            str(edge.get("id")): edge
            for edge in existing_graph.get("edges", [])
            if isinstance(edge, dict) and edge.get("id")
        }
        node_details = {
            str(node.get("id")): node
            for node in existing_graph.get("nodes", [])
            if isinstance(node, dict) and node.get("id")
        }

        requested_deleted_evidence_ids = {
            str(node_id).strip()
            for node_id in raw_deleted_node_ids
            if str(node_id).strip() in node_details
            and node_details[str(node_id).strip()].get("kind") in cls.EVIDENCE_KINDS
        }
        available_evidence_slots = {}
        for evidence_kind, limit in cls.EVIDENCE_LIMITS.items():
            existing_count = sum(
                node.get("kind") == evidence_kind
                for node in node_details.values()
            )
            deleted_count = sum(
                node_details[node_id].get("kind") == evidence_kind
                for node_id in requested_deleted_evidence_ids
            )
            available_evidence_slots[evidence_kind] = limit - (
                existing_count - deleted_count
            )
        allowed_kinds = (
            {"viewpoint", "core_argument"}
            if round_number == 1
            else cls.EVIDENCE_KINDS
        )
        nodes: list[dict] = []
        local_keys: set[str] = set()
        for raw_node in raw_nodes:
            if not isinstance(raw_node, dict):
                continue
            key = str(raw_node.get("key", "")).strip()
            side = str(raw_node.get("side", "")).strip()
            kind = str(raw_node.get("kind", "")).strip()
            text = str(raw_node.get("text", "")).strip()
            source_speech_id = str(raw_node.get("sourceSpeechId", "")).strip()
            source_quote = str(raw_node.get("sourceQuote", "")).strip()
            speech = source_speeches.get(source_speech_id)

            if (
                not cls.LOCAL_KEY_PATTERN.fullmatch(key)
                or key in local_keys
                or key in existing_ids
                or side not in SIDE_LABELS
                or kind not in allowed_kinds
                or not text
                or len(text) > 240
                or not source_quote
                or len(source_quote) > 240
                or speech is None
                or speech.get("side") != side
                or not cls._quote_exists_in_speech(source_quote, speech["content"])
            ):
                continue

            if (
                kind in cls.EVIDENCE_KINDS
                and sum(node["kind"] == kind for node in nodes)
                >= available_evidence_slots[kind]
            ):
                continue

            local_keys.add(key)
            nodes.append(
                {
                    "key": key,
                    "side": side,
                    "kind": kind,
                    "text": text,
                    "sourceSpeechId": source_speech_id,
                    "sourceQuote": source_quote,
                }
            )

        new_node_details = {node["key"]: node for node in nodes}
        valid_refs = existing_ids | local_keys
        edges: list[dict] = []
        seen_edges: set[tuple[str, str, str]] = set()
        for raw_edge in raw_edges:
            if not isinstance(raw_edge, dict):
                continue
            from_ref = str(raw_edge.get("from", "")).strip()
            to_ref = str(raw_edge.get("to", "")).strip()
            edge_type = str(raw_edge.get("type", "")).strip()
            edge_key = (from_ref, to_ref, edge_type)
            if (
                from_ref not in valid_refs
                or to_ref not in valid_refs
                or from_ref == to_ref
                or edge_type not in cls.EDGE_TYPES
                or edge_key in seen_edges
                or (from_ref not in local_keys and to_ref not in local_keys)
            ):
                continue
            seen_edges.add(edge_key)
            edges.append({"from": from_ref, "to": to_ref, "type": edge_type})

        def node_for(ref: str) -> dict:
            return new_node_details.get(ref) or node_details.get(ref, {})

        valid_edges: list[dict] = []
        for edge in edges:
            source = node_for(edge["from"])
            target = node_for(edge["to"])
            source_kind = source.get("kind")
            target_kind = target.get("kind")
            if source_kind == "core_argument" and (
                edge["type"] != "supports"
                or source.get("side") != target.get("side")
                or target_kind != "viewpoint"
            ):
                continue
            if source_kind == "support_evidence" and (
                edge["type"] != "supports"
                or source.get("side") != target.get("side")
                or target_kind not in {"viewpoint", "core_argument"}
            ):
                continue
            if source_kind == "rebuttal_evidence" and (
                edge["type"] != "rebuts" or source.get("side") == target.get("side")
            ):
                continue
            valid_edges.append(edge)
        edges = valid_edges

        # On later rounds, omit malformed, detached evidence rather than
        # failing the whole debate. First-round skeleton requirements remain
        # strict below.
        if round_number != 1:
            while True:
                retained_keys = {node["key"] for node in nodes}
                edges = [
                    edge
                    for edge in edges
                    if edge["from"] not in local_keys
                    or edge["from"] in retained_keys
                ]
                linked_keys = {edge["from"] for edge in edges}
                isolated_keys = {
                    node["key"]
                    for node in nodes
                    if node["kind"] in cls.EVIDENCE_KINDS
                    and node["key"] not in linked_keys
                }
                if not isolated_keys:
                    break
                nodes = [node for node in nodes if node["key"] not in isolated_keys]
                local_keys -= isolated_keys
                new_node_details = {node["key"]: node for node in nodes}
                edges = [
                    edge
                    for edge in edges
                    if edge["from"] not in isolated_keys
                    and edge["to"] not in isolated_keys
                ]

        if round_number == 1:
            viewpoint_counts = {
                side: sum(
                    node["side"] == side and node["kind"] == "viewpoint"
                    for node in nodes
                )
                for side in SIDE_LABELS
            }
            core_counts = {
                side: sum(
                    node["side"] == side and node["kind"] == "core_argument"
                    for node in nodes
                )
                for side in SIDE_LABELS
            }
            if any(count != 1 for count in viewpoint_counts.values()):
                raise DebateAgentError("第一轮必须为正反双方各生成一个观点根节点")
            if any(count < 2 or count > 4 for count in core_counts.values()):
                raise DebateAgentError("第一轮每方必须生成 2 至 4 个核心论点")
            linked_core_keys = {
                edge["from"]
                for edge in edges
                if node_for(edge["from"]).get("kind") == "core_argument"
                and node_for(edge["to"]).get("kind") == "viewpoint"
            }
            if any(
                node["kind"] == "core_argument" and node["key"] not in linked_core_keys
                for node in nodes
            ):
                raise DebateAgentError("每个核心论点必须连向本方观点根节点")

        deleted_node_ids = []
        seen_node_ids: set[str] = set()
        for node_id in raw_deleted_node_ids:
            normalized_id = str(node_id).strip()
            node = node_details.get(normalized_id, {})
            if (
                normalized_id in existing_ids
                and node.get("kind") in cls.EVIDENCE_KINDS
                and normalized_id not in seen_node_ids
            ):
                seen_node_ids.add(normalized_id)
                deleted_node_ids.append(normalized_id)

        deleted_edge_ids = []
        seen_edge_ids: set[str] = set()
        for edge_id in raw_deleted_edge_ids:
            normalized_id = str(edge_id).strip()
            edge = existing_edges.get(normalized_id, {})
            adjacent_kinds = {
                node_details.get(str(edge.get(ref)), {}).get("kind")
                for ref in ("from", "to")
            }
            if (
                normalized_id in existing_edges
                and adjacent_kinds & cls.EVIDENCE_KINDS
                and normalized_id not in seen_edge_ids
            ):
                seen_edge_ids.add(normalized_id)
                deleted_edge_ids.append(normalized_id)

        if round_number == 1 and (deleted_node_ids or deleted_edge_ids):
            raise DebateAgentError("第一轮交锋图不能删除节点或边")

        return nodes, edges, deleted_node_ids, deleted_edge_ids

    def summarize(
        self,
        topic: str,
        round_number: int,
        round_speeches: list[dict],
        existing_graph: dict,
        max_tokens: int,
    ) -> SummaryResult:
        speech_payload = [
            {
                "id": speech.get("id"),
                "side": speech.get("side"),
                "content": speech.get("content", ""),
            }
            for speech in round_speeches
        ]
        graph_payload = {
            "nodes": existing_graph.get("nodes", []),
            "edges": existing_graph.get("edges", []),
        }
        evidence_counts = {
            kind: sum(
                isinstance(node, dict) and node.get("kind") == kind
                for node in graph_payload["nodes"]
            )
            for kind in self.EVIDENCE_KINDS
        }
        system_prompt = (
            "你是 AI 辩论的客观体系 Agent，不是辩手、主持人或裁判。"
            "你维护同一张交锋图：第一轮建立逻辑体系，后续轮次只在已有体系上增删。"
            "交锋图由正反双方各自的一棵树组成：观点是根，核心论点是主枝，论据是叶。"
            "反驳论据是唯一可跨越两方树的连线。"
            "你的目标不是逐句摘要，而是保留对体系有不可替代作用的内容。"
            "禁止判断胜负、评分、评价逻辑正确性、补充外部知识、纠正事实，或推测发言者没有说出的意图。"
            "不确定时省略节点或关系，不要强行连线。只输出一个 JSON 对象，不要输出 Markdown 或解释。"
        )
        user_prompt = (
            f"辩题：{topic}\n"
            f"当前完整轮次：第 {round_number} 轮\n"
            + (
                "这是第一轮：每方必须且只能创建一个 kind 为 viewpoint 的观点根节点，"
                "并创建 2 至 4 个 kind 为 core_argument 的核心论点。每个核心论点必须以 supports 连到本方观点根节点。"
                "本轮不得创建任何论据节点，也不得删除任何节点或边。\n\n"
                if round_number == 1
                else "这是后续轮次：先自主判断本轮对话是否仍能作用于已有观点或核心论点。"
                "只有整轮内容已偏离既有核心论点、完全无法建立逻辑关系时，才选择 decision 为 refuse；"
                "此时不得新增、删除节点或边。"
                "若内容相关但只是重复、没有更优论据，或论据资源已满且没有值得替换的旧论据，选择 decision 为 hold，"
                "保留原图且四个增删数组均为空。资源已满绝不是 refuse 的理由，也不能终止后续辩论。"
                "若选择 update，观点根节点与核心论点均不可新增、修改或删除。"
                "只能新增 kind 为 support_evidence 或 rebuttal_evidence 的论据节点。"
                "正反双方共享两个互不借用的资源池：support_evidence 最多 4 个，rebuttal_evidence 最多 10 个。"
                "某类资源已满时，若本轮出现更强、更关键且不重复的同类论据，可先删除较弱的同类旧论据及其连线，再新增替代论据；"
                "否则选择 hold。"
                "support_evidence 必须以 supports 连向本方 viewpoint 或 core_argument，不能连向其他论据。"
                "rebuttal_evidence 必须以 rebuts 连向对方任意节点。"
                "删除只允许删除已有论据及其连线。\n\n"
            )
            + "重复已有观点且没有新增含义时不要创建重复节点。\n\n"
            f"当前已使用支持论据资源：{evidence_counts['support_evidence']}/4；"
            f"反驳论据资源：{evidence_counts['rebuttal_evidence']}/10。"
            "两类剩余资源应分别保留或使用，不得相互借用。\n\n"
            "本轮发言 JSON：\n"
            f"{json.dumps(speech_payload, ensure_ascii=False)}\n\n"
            "已有交锋图 JSON：\n"
            f"{json.dumps(graph_payload, ensure_ascii=False)}\n\n"
            "严格返回以下结构：\n"
            "{\n"
            '  "decision": "update、hold 或 refuse",\n'
            '  "reason": "简短说明体系判断；hold 或 refuse 时必填",\n'
            '  "addNodes": [{"key":"本轮局部唯一键","side":"affirmative 或 negative",'
            '"kind":"viewpoint、core_argument、support_evidence 或 rebuttal_evidence","text":"忠实、简洁的命题表述",'
            '"sourceSpeechId":"本轮发言 ID","sourceQuote":"该发言中的逐字短引文"}],\n'
            '  "addEdges": [{"from":"新节点 key 或已有节点 id","to":"新节点 key 或已有节点 id",'
            '"type":"supports 或 rebuts"}],\n'
            '  "deleteNodeIds": ["已有节点 id"],\n'
            '  "deleteEdgeIds": ["已有边 id"]\n'
            "}\n"
            "第一轮的 decision 必须是 update。后续若 decision 为 hold 或 refuse，四个增删数组必须全部为空。"
            "关系方向约定：作为支持或反驳内容的节点放在 from，被作用的节点放在 to。"
            "每个新增的核心论点或论据节点都必须至少有一条从该节点出发的关系。"
            "不要输出对已有节点或边的修改；需要修正时删除旧项并新增替代项。"
            "sourceQuote 必须是 sourceSpeechId 对应发言中真实存在的连续原文。"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        for attempt in range(2):
            completion = self.client.complete(messages, max_tokens=max_tokens)
            try:
                payload = self._parse_json_object(completion.content)
                decision = str(payload.get("decision", "")).strip().lower()
                reason = str(payload.get("reason", "")).strip()
                if decision not in {"update", "hold", "refuse"}:
                    raise DebateAgentError("体系 Agent 必须返回 update、hold 或 refuse 决策")
                if round_number == 1 and decision != "update":
                    raise DebateAgentError("第一轮体系 Agent 必须建立初始逻辑体系")
                if decision in {"hold", "refuse"}:
                    if not reason or len(reason) > 240:
                        raise DebateAgentError("体系 Agent 保持或拒绝入图时必须说明原因")
                    if any(
                        payload.get(key) not in ([], None)
                        for key in (
                            "addNodes",
                            "addEdges",
                            "deleteNodeIds",
                            "deleteEdgeIds",
                        )
                    ):
                        raise DebateAgentError("体系 Agent 保持或拒绝入图时不能修改交锋图")
                    nodes, edges, deleted_node_ids, deleted_edge_ids = [], [], [], []
                    break
                nodes, edges, deleted_node_ids, deleted_edge_ids = self._validate_update(
                    payload,
                    round_number=round_number,
                    round_speeches=round_speeches,
                    existing_graph=existing_graph,
                )
                break
            except DebateAgentError as error:
                if attempt:
                    raise
                messages.extend(
                    [
                        {"role": "assistant", "content": completion.content},
                        {
                            "role": "user",
                            "content": (
                                f"上一版交锋图不合格：{error}。请保留客观性并完整重做，"
                                "严格遵守本轮节点数量、节点类型和树状连线规则；"
                                "只输出修正后的 JSON 对象。"
                            ),
                        },
                    ]
                )
        return SummaryResult(
            nodes=nodes,
            edges=edges,
            status=(
                "truncated" if completion.finish_reason == "length" else "completed"
            ),
            deleted_node_ids=deleted_node_ids,
            deleted_edge_ids=deleted_edge_ids,
            decision=decision,
            reason=reason,
        )


class DebateRunner:
    """Runs an opening stage, then repeating debate rounds with summaries."""

    def __init__(
        self,
        record_id: str,
        stop_event: threading.Event,
        pause_event: threading.Event,
        load_record: Callable[[str], dict],
        mark_turn: Callable[[str, int, str, str], None],
        save_speech: Callable[[str, int, str, SpeechResult, str], None],
        save_summary: Callable[[str, int, SummaryResult], None],
        advance_phase: Callable[[str, str, int], None],
        mark_paused: Callable[[str], None],
        mark_error: Callable[[str, str], None],
        mark_stopped: Callable[[str], None],
    ) -> None:
        self.record_id = record_id
        self.stop_event = stop_event
        self.pause_event = pause_event
        self.load_record = load_record
        self.mark_turn = mark_turn
        self.save_speech = save_speech
        self.save_summary = save_summary
        self.advance_phase = advance_phase
        self.mark_paused = mark_paused
        self.mark_error = mark_error
        self.mark_stopped = mark_stopped
        self.max_chars = int(os.environ.get("AI_DEBATE_MAX_CHARS", "600"))
        self.max_tokens = int(os.environ.get("AI_DEBATE_MAX_TOKENS", "1600"))
        self.summary_max_tokens = int(
            os.environ.get("AI_DEBATE_SUMMARY_MAX_TOKENS", "2400")
        )
        self.turn_pause = float(os.environ.get("AI_DEBATE_TURN_PAUSE", "1"))

    @staticmethod
    def format_transcript(speeches: list[dict]) -> str:
        blocks = []
        for speech in speeches:
            side_label = SIDE_LABELS.get(speech.get("side"), "未知方")
            turn_label = (
                "立论阶段"
                if speech.get("phase") == "opening"
                else f"第 {speech.get('round', '?')} 轮"
            )
            blocks.append(
                f"{turn_label} · {side_label}：\n{speech.get('content', '')}"
            )
        return "\n\n".join(blocks)

    def wait_while_paused(self) -> bool:
        if not self.pause_event.is_set():
            return not self.stop_event.is_set()

        self.mark_paused(self.record_id)
        while self.pause_event.is_set() and not self.stop_event.is_set():
            self.stop_event.wait(0.1)
        return not self.stop_event.is_set()

    def summarize_round(self, round_number: int, phase: str) -> bool:
        if self.stop_event.is_set() or not self.wait_while_paused():
            return False

        record = self.load_record(self.record_id)
        if record.get("status") != "running":
            self.stop_event.set()
            return False
        round_speeches = [
            speech
            for speech in record.get("speeches", [])
            if speech.get("round") == round_number
            and speech.get("side") in SIDE_LABELS
        ]
        round_sides = {speech.get("side") for speech in round_speeches}
        if round_sides != set(SIDE_LABELS):
            raise DebateAgentError(
                f"第 {round_number} 轮双方发言不完整，无法生成交锋图"
            )

        summary_seat = record.get("summarizer") or record["negative"]
        self.mark_turn(self.record_id, round_number, "summarizer", phase)
        summary_agent = SummaryAgent(
            provider=summary_seat["provider"],
            model=summary_seat["model"],
        )
        summary_result = summary_agent.summarize(
            topic=record["topic"],
            round_number=round_number,
            round_speeches=round_speeches,
            existing_graph=record.get("argumentGraph", {}),
            max_tokens=self.summary_max_tokens,
        )

        if self.stop_event.is_set():
            return False
        self.save_summary(self.record_id, round_number, summary_result)
        return True

    def run_opening_stage(self) -> bool:
        round_number = 1
        record = self.load_record(self.record_id)
        viewpoints = record.get("viewpoints")
        if (
            not isinstance(viewpoints, dict)
            or not str(viewpoints.get("affirmative", "")).strip()
            or not str(viewpoints.get("negative", "")).strip()
        ):
            raise DebateAgentError("缺少用户确认的正反方观点，无法进入立论阶段")

        existing_sides = {
            speech.get("side")
            for speech in record.get("speeches", [])
            if speech.get("round") == round_number
            and speech.get("phase") == "opening"
        }
        for side in ("affirmative", "negative"):
            if side in existing_sides:
                continue
            if not self.wait_while_paused():
                return False

            record = self.load_record(self.record_id)
            if record.get("status") != "running":
                self.stop_event.set()
                return False
            seat = record[side]
            self.mark_turn(self.record_id, round_number, side, "opening")
            agent = DebaterAgent(
                side=side,
                provider=seat["provider"],
                model=seat["model"],
            )
            result = agent.opening_statement(
                viewpoints=viewpoints,
                max_chars=self.max_chars,
                max_tokens=self.max_tokens,
            )
            if self.stop_event.is_set():
                return False
            self.save_speech(self.record_id, round_number, side, result, "opening")

            if not self.wait_while_paused():
                return False
            if self.stop_event.wait(self.turn_pause):
                return False

        record = self.load_record(self.record_id)
        already_summarized = any(
            summary.get("round") == round_number
            for summary in record.get("roundSummaries", [])
            if isinstance(summary, dict)
        )
        if not already_summarized and not self.summarize_round(round_number, "opening"):
            return False
        self.advance_phase(self.record_id, "debate", 2)
        if not self.wait_while_paused():
            return False
        return not self.stop_event.wait(self.turn_pause)

    def run(self) -> None:
        try:
            record = self.load_record(self.record_id)
            if record.get("phase") == "opening":
                if not self.run_opening_stage():
                    return
                round_number = 2
            else:
                round_number = max(1, int(record.get("currentRound", 1)))

            while not self.stop_event.is_set():
                side_order = (
                    ("affirmative", "negative")
                    if round_number % 2 == 1
                    else ("negative", "affirmative")
                )
                for side in side_order:
                    if not self.wait_while_paused():
                        break

                    record = self.load_record(self.record_id)
                    if record.get("status") != "running":
                        self.stop_event.set()
                        break

                    seat = record[side]
                    self.mark_turn(self.record_id, round_number, side, "debate")
                    agent = DebaterAgent(
                        side=side,
                        provider=seat["provider"],
                        model=seat["model"],
                    )
                    result = agent.speak(
                        topic=record["topic"],
                        viewpoints=record.get("viewpoints", {}),
                        round_number=round_number,
                        transcript=self.format_transcript(record["speeches"]),
                        argument_graph=record.get("argumentGraph", {}),
                        max_chars=self.max_chars,
                        max_tokens=self.max_tokens,
                    )

                    if self.stop_event.is_set():
                        break
                    self.save_speech(
                        self.record_id, round_number, side, result, "debate"
                    )

                    if not self.wait_while_paused():
                        break

                    if self.stop_event.wait(self.turn_pause):
                        break

                if self.stop_event.is_set():
                    break
                if not self.summarize_round(round_number, "debate"):
                    break

                if not self.wait_while_paused():
                    break
                if self.stop_event.wait(self.turn_pause):
                    break
                round_number += 1
        except DebateAgentError as error:
            if not self.stop_event.is_set():
                self.mark_error(self.record_id, str(error))
        except Exception as error:
            if not self.stop_event.is_set():
                self.mark_error(self.record_id, f"辩论流程异常：{error}")
        finally:
            if self.stop_event.is_set():
                self.mark_stopped(self.record_id)
