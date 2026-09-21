import pytest

from seed_audio_cli.config import api_key


def test_environment_key_takes_precedence_over_root_dotenv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "BYTEPLUS_API_KEY=file-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BYTEPLUS_API_KEY", "environment-key")

    assert api_key() == "environment-key"


def test_root_dotenv_supplies_key_when_environment_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BYTEPLUS_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "# local development secret\nBYTEPLUS_API_KEY=file-key\n",
        encoding="utf-8",
    )

    assert api_key() == "file-key"


def test_missing_key_error_does_not_include_dotenv_contents(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BYTEPLUS_API_KEY", raising=False)
    secret = "secret-that-must-not-appear"
    (tmp_path / ".env").write_text(
        f"OTHER_VALUE={secret}\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError) as error:
        api_key()

    assert secret not in str(error.value)
