"""Native host boundary tests use synthetic tab structures, never a personal browser."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "companion_bridge", Path(__file__).resolve().parents[3] / "scripts" / "companion_bridge.py"
)
assert spec and spec.loader
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

REQUEST = {
    "action": "inspect",
    "url": "https://jobs.example.test/apply?step=1",
    "nonce": "11111111-1111-4111-8111-111111111111",
}


def test_native_inspection_is_bound_to_exact_tab_and_fixed_reader(mocker):
    calls = mocker.patch.object(
        bridge,
        "cli",
        side_effect=[
            {
                "tabs": [
                    {"tabId": "t1", "url": "https://unrelated.example.test"},
                    {"tabId": "t2", "url": REQUEST["url"]},
                ]
            },
            {},
            {"result": {"engine": "agent-browser", "controls": []}},
        ],
    )
    assert bridge.inspect(REQUEST)["ok"] is True
    assert calls.call_args_list[1].args == ("tab", "t2")
    script = calls.call_args_list[2].args[1]
    assert REQUEST["url"] in script and REQUEST["nonce"] in script
    assert "data-command-center-inspection" in script


@pytest.mark.parametrize(
    "change",
    [
        {"action": "eval"},
        {"url": "file:///private/data"},
        {"nonce": "';alert(1)//"},
        {"script": "arbitrary code"},
    ],
)
def test_native_host_rejects_arbitrary_commands_and_invalid_bindings(mocker, change):
    call = mocker.patch.object(bridge, "cli")
    with pytest.raises(ValueError):
        bridge.inspect(REQUEST | change)
    call.assert_not_called()


def test_native_host_never_reads_other_pages_when_binding_is_missing(mocker):
    call = mocker.patch.object(
        bridge,
        "cli",
        return_value={"tabs": [{"tabId": "t1", "url": "https://unrelated.example.test"}]},
    )
    with pytest.raises(ValueError, match="outside AgentBrowser"):
        bridge.inspect(REQUEST)
    assert call.call_count == 1


def test_cli_does_not_inherit_agentbrowser_daemon_environment_or_native_stdin(
    mocker, monkeypatch, tmp_path
):
    monkeypatch.setenv("AGENT_BROWSER_DAEMON", "1")
    monkeypatch.setattr(bridge, "LOCAL", tmp_path)
    mocker.patch.object(bridge.shutil, "which", return_value="/synthetic/ab")
    run = mocker.patch.object(
        bridge.subprocess,
        "run",
        return_value=subprocess.CompletedProcess([], 0, '{"success":true,"data":{"tabs":[]}}', ""),
    )
    assert bridge.cli("tab", "list") == {"tabs": []}
    assert not any(key.startswith("AGENT_BROWSER_") for key in run.call_args.kwargs["env"])
    assert run.call_args.kwargs["stdin"] == subprocess.DEVNULL
    assert run.call_args.args[0] == ["/synthetic/ab", "clean", "tab", "list", "--json"]
