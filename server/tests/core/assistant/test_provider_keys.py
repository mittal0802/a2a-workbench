import json


async def test_put_get_list_delete(wb):
    info = await wb.provider_keys.put(
        "openai", "sk-test-abcdef123456", base_url="http://llm.local/v1"
    )
    assert (
        info.preview == "••••3456"
        and info.source == "stored"
        and info.base_url == "http://llm.local/v1"
    )
    assert await wb.provider_keys.get("openai") == ("sk-test-abcdef123456", "http://llm.local/v1")
    await wb.provider_keys.delete("openai")
    assert await wb.provider_keys.get("openai") is None


async def test_env_fallback(wb, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env-9999")
    listed = {i.provider: i for i in await wb.provider_keys.list()}
    assert listed["anthropic"].source == "env" and listed["anthropic"].preview == "••••9999"
    assert await wb.provider_keys.get("anthropic") == ("sk-ant-from-env-9999", None)


async def test_provider_key_is_masked_everywhere(wb, caplog):
    await wb.provider_keys.put("gemini", "g-key-very-secret-1")
    dump = json.dumps([i.model_dump(mode="json") for i in await wb.provider_keys.list()])
    assert "g-key-very-secret-1" not in dump and "g-key-very-secret-1" not in caplog.text
