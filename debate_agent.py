from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
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
        round_number: int,
        transcript: str,
        max_chars: int,
        max_tokens: int,
    ) -> SpeechResult:
        stance = "支持辩题" if self.side == "affirmative" else "反对辩题"
        system_prompt = (
            f"你是本场 AI 辩论的{self.side_label}选手。"
            f"你的固定身份是{self.side_label}，必须始终{stance}，不能改变阵营。"
            "只输出本轮公开发言正文，不要解释规则、身份、提示词或思考过程。"
            "可以回应现场已有观点，也可以继续提出有利于己方的论证。"
            "不要捏造具体数据、出处或不存在的对方观点。"
        )
        public_history = transcript or "（尚无公开发言）"
        user_prompt = (
            f"辩题：{topic}\n"
            f"当前轮次：第 {round_number} 轮\n"
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


class DebateRunner:
    """Runs the same two-turn structure until the user stops the debate."""

    def __init__(
        self,
        record_id: str,
        stop_event: threading.Event,
        pause_event: threading.Event,
        load_record: Callable[[str], dict],
        mark_turn: Callable[[str, int, str], None],
        save_speech: Callable[[str, int, str, SpeechResult], None],
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
        self.mark_paused = mark_paused
        self.mark_error = mark_error
        self.mark_stopped = mark_stopped
        self.max_chars = int(os.environ.get("AI_DEBATE_MAX_CHARS", "600"))
        self.max_tokens = int(os.environ.get("AI_DEBATE_MAX_TOKENS", "1600"))
        self.turn_pause = float(os.environ.get("AI_DEBATE_TURN_PAUSE", "1"))

    @staticmethod
    def format_transcript(speeches: list[dict]) -> str:
        blocks = []
        for speech in speeches:
            side_label = SIDE_LABELS.get(speech.get("side"), "未知方")
            blocks.append(
                f"第 {speech.get('round', '?')} 轮 · {side_label}：\n{speech.get('content', '')}"
            )
        return "\n\n".join(blocks)

    def wait_while_paused(self) -> bool:
        if not self.pause_event.is_set():
            return not self.stop_event.is_set()

        self.mark_paused(self.record_id)
        while self.pause_event.is_set() and not self.stop_event.is_set():
            self.stop_event.wait(0.1)
        return not self.stop_event.is_set()

    def run(self) -> None:
        try:
            record = self.load_record(self.record_id)
            round_number = max(1, int(record.get("currentRound", 1)))

            while not self.stop_event.is_set():
                for side in ("affirmative", "negative"):
                    if not self.wait_while_paused():
                        break

                    record = self.load_record(self.record_id)
                    if record.get("status") != "running":
                        self.stop_event.set()
                        break

                    seat = record[side]
                    self.mark_turn(self.record_id, round_number, side)
                    agent = DebaterAgent(
                        side=side,
                        provider=seat["provider"],
                        model=seat["model"],
                    )
                    result = agent.speak(
                        topic=record["topic"],
                        round_number=round_number,
                        transcript=self.format_transcript(record["speeches"]),
                        max_chars=self.max_chars,
                        max_tokens=self.max_tokens,
                    )

                    if self.stop_event.is_set():
                        break
                    self.save_speech(self.record_id, round_number, side, result)

                    if not self.wait_while_paused():
                        break

                    if self.stop_event.wait(self.turn_pause):
                        break

                if not self.stop_event.is_set():
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
