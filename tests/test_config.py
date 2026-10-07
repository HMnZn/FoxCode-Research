import os
import sys

import pytest

from fox_coding_agent.src import Config


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    for name in ("FOX_MODEL", "FOX_BASE_URL", "FOX_API_KEY", "OPENAI_API_KEY",
                 "FOX_CONTEXT_BUDGET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


def test_dotenv_quotes_comments_expansion_and_windows_encoding(tmp_path):
    (tmp_path / ".env").write_text(
        '# Local settings\nexport FOX_MODEL="test-model" # comment\n'
        'ENDPOINT=https://example.test\nFOX_BASE_URL=${ENDPOINT}/v1\n'
        "FOX_API_KEY='test key # literal'\nFOX_CONTEXT_BUDGET=8192\n",
        encoding="utf-8-sig", newline="\r\n",
    )
    config = Config.from_env()
    assert config.model == "test-model"
    assert config.base_url == "https://example.test/v1"
    assert config.api_key == "test key # literal"
    assert config.context_budget == 8192
    assert "FOX_MODEL" not in os.environ
    assert config.api_key not in repr(config)


def test_precedence_and_none_overrides(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "FOX_MODEL=file-model\nFOX_BASE_URL=https://file.test/v1\n"
        "FOX_API_KEY=file-key\nFOX_CONTEXT_BUDGET=8192\n", encoding="utf-8",
    )
    monkeypatch.setenv("FOX_MODEL", "env-model")
    monkeypatch.setenv("FOX_API_KEY", "env-key")
    monkeypatch.setenv("FOX_CONTEXT_BUDGET", "9000")
    config = Config.from_env(model=None, base_url=None, api_key=None)
    assert config.model == "env-model"
    assert config.base_url == "https://file.test/v1"
    assert config.api_key == "env-key"
    assert config.context_budget == 9000
    config = Config.from_env(model="cli-model", base_url="https://cli.test/v1",
                             api_key="cli-key", context_budget=10000)
    assert (config.model, config.base_url, config.api_key, config.context_budget) == (
        "cli-model", "https://cli.test/v1", "cli-key", 10000,
    )


def test_missing_dotenv_retains_defaults_and_requires_model():
    with pytest.raises(ValueError, match="Set FOX_MODEL"):
        Config.from_env()
    config = Config.from_env(model="test")
    assert config.base_url == "https://api.openai.com/v1"
    assert config.api_key == ""
    assert config.context_budget == 12000


@pytest.mark.parametrize("entry, expected", [("", "fallback-key"),
                                           ("FOX_API_KEY\n", "fallback-key"),
                                           ("FOX_API_KEY=\n", "")])
def test_openai_key_fallback(tmp_path, entry, expected):
    (tmp_path / ".env").write_text(
        "FOX_MODEL=test\nOPENAI_API_KEY=fallback-key\n" + entry, encoding="utf-8",
    )
    assert Config.from_env().api_key == expected


def test_nearest_project_dotenv_and_launch_fallback(monkeypatch, tmp_path):
    launch = tmp_path / "launch"
    project = tmp_path / "project"
    nested = project / "nested"
    launch.mkdir()
    nested.mkdir(parents=True)
    (launch / ".env").write_text("FOX_MODEL=launch\n", encoding="utf-8")
    (project / ".env").write_text("FOX_MODEL=project\n", encoding="utf-8")
    monkeypatch.chdir(launch)
    assert Config.from_env(cwd=nested).model == "project"
    (nested / ".env").write_text("FOX_MODEL=nested\n", encoding="utf-8")
    assert Config.from_env(cwd=nested).model == "nested"
    other = tmp_path / "other"
    other.mkdir()
    assert Config.from_env(cwd=other).model == "launch"
    assert "FOX_MODEL" not in os.environ


def test_explicit_budget_overrides_invalid_dotenv_budget(tmp_path):
    (tmp_path / ".env").write_text(
        "FOX_MODEL=test\nFOX_CONTEXT_BUDGET=invalid\n", encoding="utf-8",
    )
    assert Config.from_env(context_budget=8000).context_budget == 8000
    with pytest.raises(ValueError):
        Config.from_env()


def test_cli_reads_dotenv(monkeypatch, tmp_path):
    from fox_coding_agent.src import cli

    (tmp_path / ".env").write_text("FOX_MODEL=file-model\n", encoding="utf-8")
    configs = []

    async def run(config, prompt, json_events):
        configs.append(config)
        assert prompt == "hello"
        return 0

    monkeypatch.setattr(cli, "run", run)
    monkeypatch.setattr(sys, "argv", ["fox", "hello"])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 0
    assert configs[0].model == "file-model"


@pytest.mark.parametrize("source", ["dotenv", "env", "argument", "unconfigured"])
def test_server_startup_model_sources(monkeypatch, tmp_path, source):
    from fox_serve import __main__ as server

    args = ["fox_serve"]
    if source != "unconfigured":
        (tmp_path / ".env").write_text("FOX_MODEL=dotenv\n", encoding="utf-8")
    if source in ("env", "argument"):
        monkeypatch.setenv("FOX_MODEL", "env")
    if source == "argument":
        args += ["--model", "argument"]
    monkeypatch.setattr(sys, "argv", args)
    configs = []
    monkeypatch.setattr(server, "create_app", lambda config: config)
    monkeypatch.setattr(server.uvicorn, "run", lambda config, **kwargs: configs.append(config))
    server.main()
    assert len(configs) == 1
    if source == "unconfigured":
        assert configs[0] is None
    else:
        assert configs[0].model == source
