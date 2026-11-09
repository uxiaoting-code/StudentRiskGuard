from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def _registration_app() -> AppTest:
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=20).run()
    app.radio[0].set_value("注册").run()
    return app


def _text_input(app: AppTest, label: str):
    return next(item for item in app.text_input if item.label == label)


def _submit_registration(app: AppTest) -> None:
    next(button for button in app.button if button.label == "注册").click().run()


def test_registration_rules_are_visible() -> None:
    app = _registration_app()

    assert not app.exception
    assert any("注册规则" in caption.value for caption in app.caption)
    assert any("英文字母、数字和下划线" in caption.value for caption in app.caption)


def test_registration_form_shows_friendly_validation_errors() -> None:
    app = _registration_app()

    _text_input(app, "用户名").set_value("ab")
    _text_input(app, "密码").set_value("password")
    _text_input(app, "确认密码").set_value("password")
    _submit_registration(app)

    assert not app.exception
    assert app.error[0].value == "用户名至少需要 3 个字符。"

    _text_input(app, "用户名").set_value("student_1109")
    _text_input(app, "密码").set_value("1234567")
    _text_input(app, "确认密码").set_value("1234567")
    _submit_registration(app)

    assert app.error[0].value == "密码至少需要 8 个字符。"

    _text_input(app, "密码").set_value("password")
    _text_input(app, "确认密码").set_value("different")
    _submit_registration(app)

    assert app.error[0].value == "两次输入的密码不一致，请重新确认。"
