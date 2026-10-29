"""The OpenAI-compatible Chat Completions adapter, against a recorded stream."""

import json

import httpx
import pytest

from eidolon.llm import ChatMessage, LLMError, Reasoning, Tool, ToolCall
from eidolon.llm.openai_compat import OpenAICompatLLM

RECORDED_STREAM = (
    'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"index":0,'
    '"delta":{"role":"assistant","content":""},"finish_reason":null}]}\n\n'
    'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"index":0,'
    '"delta":{"content":"<ja>えっと"},"finish_reason":null}]}\n\n'
    ": keep-alive\n\n"
    'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"index":0,'
    '"delta":{"content":"</ja><zh>哇</zh>"},"finish_reason":null}]}\n\n'
    'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"index":0,'
    '"delta":{},"finish_reason":"stop"}]}\n\n'
    'data: {"id":"c1","object":"chat.completion.chunk","choices":[],'
    '"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n'
    "data: [DONE]\n\n"
)


async def test_streams_content_deltas_and_sends_a_chat_completions_request():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, text=RECORDED_STREAM, headers={"content-type": "text/event-stream"}
        )

    llm = OpenAICompatLLM(
        "https://llm.example/v1/", "sk-test", "some-model",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    chunks = [c async for c in llm.stream([ChatMessage("user", "你好")])]

    assert chunks == ["<ja>えっと", "</ja><zh>哇</zh>"]
    (request,) = requests
    assert str(request.url) == "https://llm.example/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-test"
    assert json.loads(request.content) == {
        "model": "some-model",
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [{"role": "user", "content": "你好"}],
    }


async def test_error_status_is_raised_with_the_provider_message():
    llm = OpenAICompatLLM(
        "https://llm.example/v1", "sk-bad", "some-model",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(401, json={"error": {"message": "invalid api key"}})
            )
        ),
    )

    with pytest.raises(LLMError, match="401.*invalid api key"):
        [c async for c in llm.stream([ChatMessage("user", "你好")])]


async def test_error_sent_inside_the_stream_is_raised():
    stream = (
        'data: {"choices":[{"delta":{"content":"<ja>ほわ"}}]}\n\n'
        'data: {"error":{"message":"upstream overloaded"}}\n\n'
    )
    llm = OpenAICompatLLM(
        "https://llm.example/v1", "sk-test", "some-model",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text=stream))
        ),
    )

    with pytest.raises(LLMError, match="upstream overloaded"):
        [c async for c in llm.stream([ChatMessage("user", "你好")])]


# A recorded tool call: the name and an id first, then the arguments in fragments.
RECORDED_TOOL_CALL_STREAM = (
    'data: {"id":"c2","object":"chat.completion.chunk","choices":[{"index":0,'
    '"delta":{"role":"assistant","content":null,"tool_calls":[{"index":0,"id":"call_abc",'
    '"type":"function","function":{"name":"recall_story","arguments":""}}]},'
    '"finish_reason":null}]}\n\n'
    'data: {"id":"c2","object":"chat.completion.chunk","choices":[{"index":0,'
    '"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"query\\": \\"写"}}]},'
    '"finish_reason":null}]}\n\n'
    'data: {"id":"c2","object":"chat.completion.chunk","choices":[{"index":0,'
    '"delta":{"tool_calls":[{"index":0,"function":{"arguments":"真集\\"}"}}]},'
    '"finish_reason":null}]}\n\n'
    'data: {"id":"c2","object":"chat.completion.chunk","choices":[{"index":0,'
    '"delta":{},"finish_reason":"tool_calls"}]}\n\n'
    "data: [DONE]\n\n"
)

RECALL = Tool(
    "recall_story",
    "回顾剧情",
    {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
)


async def test_tool_calls_are_assembled_from_their_fragments_and_tools_are_offered():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=RECORDED_TOOL_CALL_STREAM)

    llm = OpenAICompatLLM(
        "https://llm.example/v1", "sk-test", "some-model",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    items = [i async for i in llm.stream([ChatMessage("user", "那次拍写真集")], [RECALL])]

    assert items == [ToolCall("call_abc", "recall_story", {"query": "写真集"})]
    body = json.loads(requests[0].content)
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "recall_story",
                "description": "回顾剧情",
                "parameters": RECALL.parameters,
            },
        }
    ]


async def test_a_tool_round_trip_is_sent_back_in_chat_completions_form():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=RECORDED_STREAM)

    llm = OpenAICompatLLM(
        "https://llm.example/v1", "sk-test", "some-model",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    call = ToolCall("call_abc", "recall_story", {"query": "写真集"})

    [c async for c in llm.stream(
        [
            ChatMessage("user", "那次拍写真集"),
            ChatMessage("assistant", "", tool_calls=(call,)),
            ChatMessage("tool", "## 剧情……", tool_call_id="call_abc"),
        ],
        [RECALL],
    )]

    assert json.loads(requests[0].content)["messages"] == [
        {"role": "user", "content": "那次拍写真集"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {"name": "recall_story", "arguments": '{"query": "写真集"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_abc", "content": "## 剧情……"},
    ]


async def test_the_opening_system_messages_go_as_one_and_a_later_one_where_it_is():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=RECORDED_STREAM)

    llm = OpenAICompatLLM(
        "https://llm.example/v1", "sk-test", "some-model",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    [c async for c in llm.stream([
        ChatMessage("system", "甲", cache_breakpoint=True),
        ChatMessage("system", "乙"),
        ChatMessage("user", "你好"),
        ChatMessage("assistant", "嗨", cache_breakpoint=True),
        ChatMessage("system", "丙"),
        ChatMessage("user", "在吗"),
    ])]

    # The opening ones joined by a blank line, as every service takes them; a later one as a
    # message of its own, which DeepSeek's own encoder renders as a part of its own.
    assert json.loads(requests[0].content)["messages"] == [
        {"role": "system", "content": "甲\n\n乙"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "嗨"},
        {"role": "system", "content": "丙"},
        {"role": "user", "content": "在吗"},
    ]


async def test_tool_call_arguments_that_are_not_json_are_passed_on_as_malformed():
    stream = (
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_x",'
        '"function":{"name":"recall_story","arguments":"{\\"query\\": "}}]}}]}\n\n'
        "data: [DONE]\n\n"
    )
    llm = OpenAICompatLLM(
        "https://llm.example/v1", "sk-test", "some-model",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text=stream))
        ),
    )

    items = [i async for i in llm.stream([ChatMessage("user", "你好")], [RECALL])]

    assert items == [ToolCall("call_x", "recall_story", None)]


async def test_parallel_calls_are_kept_apart_and_calls_without_an_id_get_one():
    stream = (
        'data: {"choices":[{"delta":{"tool_calls":['
        '{"index":0,"function":{"name":"recall_story","arguments":{"query":"写真集"}}},'
        '{"index":1,"id":"call_b","function":{"name":"recall_story","arguments":"{\\"query\\""}}'
        ']}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"function":{"arguments":": \\"決勝\\"}"}}]}}]}\n\n'
        "data: [DONE]\n\n"
    )
    llm = OpenAICompatLLM(
        "https://llm.example/v1", "sk-test", "some-model",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text=stream))
        ),
    )

    items = [i async for i in llm.stream([ChatMessage("user", "你好")], [RECALL])]

    assert items == [
        ToolCall("call_0", "recall_story", {"query": "写真集"}),
        ToolCall("call_b", "recall_story", {"query": "決勝"}),
    ]


async def test_a_reply_that_is_not_streamed_is_an_error():
    llm = OpenAICompatLLM(
        "https://llm.example/v1", "sk-test", "some-model",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})
            )
        ),
    )

    with pytest.raises(LLMError, match="流式"):
        [c async for c in llm.stream([ChatMessage("user", "你好")])]


# A tool call from a thinking model, written after the shapes DeepSeek and Gemini document:
# its reasoning streams first, then the calls, the first carrying Gemini's thought signature.
THINKING_TOOL_CALL_STREAM = (
    'data: {"choices":[{"delta":{"role":"assistant","reasoning_content":"制作人问的是"}}]}\n\n'
    'data: {"choices":[{"delta":{"reasoning_content":"公园那次。"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"我想想"}}]}\n\n'
    'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_a","type":"function",'
    '"extra_content":{"google":{"thought_signature":"c2lnLWE="}},'
    '"function":{"name":"recall_story","arguments":"{\\"query\\": \\"公园\\"}"}}]}}]}\n\n'
    'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"id":"call_b","type":"function",'
    '"function":{"name":"recall_story","arguments":"{\\"query\\": \\"鸽子\\"}"}}]}}]}\n\n'
    'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
    "data: [DONE]\n\n"
)


async def tool_round(first_stream: str) -> tuple[list, dict]:
    """The items `first_stream` streams, and the request body sent after them: the calls
    they made, with all the model sent alongside them, and their results."""
    replies = iter([first_stream, RECORDED_STREAM])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=next(replies))

    llm = OpenAICompatLLM(
        "https://llm.example/v1", "sk-test", "some-model",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    prompt = [ChatMessage("user", "公园那次呢？")]

    items = [i async for i in llm.stream(prompt, [RECALL])]
    calls = tuple(i for i in items if isinstance(i, ToolCall))
    said = "".join(i for i in items if isinstance(i, str))
    thought = tuple(i for i in items if isinstance(i, Reasoning))
    results = [ChatMessage("tool", "## 剧情……", tool_call_id=c.id) for c in calls]
    [c async for c in llm.stream(
        [*prompt, ChatMessage("assistant", said, calls, reasoning=thought), *results],
        [RECALL], forbid_calls=True,
    )]

    return items, json.loads(requests[-1].content)


async def test_the_reasoning_and_thought_signatures_streamed_go_back_with_the_tool_calls():
    items, body = await tool_round(THINKING_TOOL_CALL_STREAM)

    # The reasoning is never part of what she says.
    assert "".join(i for i in items if isinstance(i, str)) == "我想想"
    assert body["messages"][1] == {
        "role": "assistant",
        "content": "我想想",
        "reasoning_content": "制作人问的是公园那次。",
        "tool_calls": [
            {
                "id": "call_a",
                "type": "function",
                "function": {"name": "recall_story", "arguments": '{"query": "公园"}'},
                "extra_content": {"google": {"thought_signature": "c2lnLWE="}},
            },
            {  # Gemini signs only the first call of a step; nothing is made up for the rest
                "id": "call_b",
                "type": "function",
                "function": {"name": "recall_story", "arguments": '{"query": "鸽子"}'},
            },
        ],
    }

