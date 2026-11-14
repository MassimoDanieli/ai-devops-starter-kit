from types import SimpleNamespace

import pytest

from aikit.client import (
    AIClient,
    AIConfig,
    AIConfigError,
    AIResponseError,
    check_required,
    extract_json,
    strict_object,
)

SCHEMA = strict_object({"name": {"type": "string"}, "n": {"type": "integer"}})


def test_config_defaults_to_anthropic_with_default_model():
    cfg = AIConfig.from_env({})
    assert cfg.provider == "anthropic"
    assert cfg.model


@pytest.mark.parametrize("provider", ["openai", "local"])
def test_openai_and_local_require_explicit_model(provider):
    with pytest.raises(AIConfigError, match="AI_MODEL"):
        AIConfig.from_env({"AI_PROVIDER": provider, "AI_BASE_URL": "http://x/v1"})


def test_local_requires_base_url():
    with pytest.raises(AIConfigError, match="AI_BASE_URL"):
        AIConfig.from_env({"AI_PROVIDER": "local", "AI_MODEL": "bonsai"})


def test_unknown_provider_rejected():
    with pytest.raises(AIConfigError):
        AIConfig.from_env({"AI_PROVIDER": "gpt"})


@pytest.mark.parametrize(
    "text",
    [
        '{"name": "a", "n": 1}',
        'Sure! Here it is:\n```json\n{"name": "a", "n": 1}\n```',
        'Result: {"name": "a", "n": 1} hope this helps',
    ],
)
def test_extract_json_tolerates_wrappers(text):
    assert extract_json(text) == {"name": "a", "n": 1}


def test_extract_json_raises_on_garbage():
    with pytest.raises(AIResponseError):
        extract_json("no json here")


def test_check_required_catches_missing_and_wrong_types():
    with pytest.raises(AIResponseError, match="missing key 'n'"):
        check_required({"name": "a"}, SCHEMA)
    with pytest.raises(AIResponseError, match="expected integer"):
        check_required({"name": "a", "n": "1"}, SCHEMA)
    with pytest.raises(AIResponseError, match="not in"):
        check_required("x", {"type": "string", "enum": ["a"]})


def test_fake_provider_parses_string_answers():
    client = AIClient(AIConfig(provider="fake"), fake_responder=lambda s, u, sc: '```json\n{"name":"x","n":2}\n```')
    assert client.complete("sys", "user", SCHEMA) == {"name": "x", "n": 2}


def test_anthropic_path_forces_tool_and_reads_tool_input():
    calls = {}

    def create(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input={"name": "y", "n": 3})])

    client = AIClient(AIConfig(provider="anthropic", model="m"))
    client._sdk = SimpleNamespace(messages=SimpleNamespace(create=create))
    assert client.complete("sys", "user", SCHEMA, schema_name="thing") == {"name": "y", "n": 3}
    assert calls["tool_choice"] == {"type": "tool", "name": "thing"}
    assert calls["tools"][0]["input_schema"] is SCHEMA
    assert calls["system"] == "sys"


def test_openai_compatible_path_sends_json_schema():
    calls = {}

    def create(**kwargs):
        calls.update(kwargs)
        msg = SimpleNamespace(content='{"name": "z", "n": 4}')
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    client = AIClient(AIConfig(provider="local", model="bonsai", base_url="http://nero:8080/v1"))
    client._sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    assert client.complete("sys", "user", SCHEMA) == {"name": "z", "n": 4}
    assert calls["response_format"]["json_schema"]["schema"] is SCHEMA
    assert calls["max_tokens"] == 8000
    assert calls["messages"][0] == {"role": "system", "content": "sys"}


def test_plain_text_completion():
    client = AIClient(AIConfig(provider="fake"), fake_responder=lambda s, u, sc: "hello")
    assert client.complete("s", "u") == "hello"
