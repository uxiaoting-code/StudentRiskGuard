"""Shared authentication input rules and user-facing validation messages."""

from __future__ import annotations

import re

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 32
USERNAME_PATTERN_TEXT = r"^[A-Za-z0-9_]+$"
USERNAME_PATTERN = re.compile(USERNAME_PATTERN_TEXT)
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

USERNAME_RULE_MESSAGE = (
    "用户名需为 3～32 位，只能使用英文字母、数字和下划线，"
    "例如 test_student_1109。"
)
PASSWORD_RULE_MESSAGE = "密码长度需为 8～128 位。"
REGISTRATION_RULES = (
    "注册规则：\n"
    "- 用户名 3～32 位，只能使用英文字母、数字和下划线\n"
    "- 密码 8～128 位\n"
    "- 两次输入的密码必须一致\n"
    "- 用户名不区分大小写，已经被使用后需要换一个"
)
LOGIN_NOTE = (
    "请使用注册时的用户名和密码登录。用户名不区分大小写。"
    "当前暂不支持邮箱找回密码。"
)


def _validate_username(username: str) -> str | None:
    if not username:
        return "请先输入用户名。"
    if len(username) < USERNAME_MIN_LENGTH:
        return f"用户名至少需要 {USERNAME_MIN_LENGTH} 个字符。"
    if len(username) > USERNAME_MAX_LENGTH:
        return f"用户名最多只能有 {USERNAME_MAX_LENGTH} 个字符。"
    if USERNAME_PATTERN.fullmatch(username) is None:
        return USERNAME_RULE_MESSAGE
    return None


def _validate_password(password: str) -> str | None:
    if not password:
        return "请先输入密码。"
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"密码至少需要 {PASSWORD_MIN_LENGTH} 个字符。"
    if len(password) > PASSWORD_MAX_LENGTH:
        return f"密码最多只能有 {PASSWORD_MAX_LENGTH} 个字符。"
    return None


def validate_registration_form(
    username: str,
    password: str,
    confirm_password: str,
) -> str | None:
    """Return a friendly error for invalid registration input, otherwise None."""
    username_error = _validate_username(username.strip())
    if username_error:
        return username_error
    password_error = _validate_password(password)
    if password_error:
        return password_error
    if not confirm_password:
        return "请再次输入密码。"
    if password != confirm_password:
        return "两次输入的密码不一致，请重新确认。"
    return None


def validate_login_form(username: str, password: str) -> str | None:
    """Return a friendly error for invalid login input, otherwise None."""
    username_error = _validate_username(username.strip())
    if username_error:
        return username_error
    return _validate_password(password)
