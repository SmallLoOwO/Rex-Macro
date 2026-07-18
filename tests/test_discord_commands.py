from miningbot.discord_commands import parse_command


def test_parse_command_accepts_plain_and_bang_prefix():
    assert parse_command("status").name == "status"
    assert parse_command("!STATUS").name == "status"


def test_parse_command_preserves_arguments():
    command = parse_command("keep hall rosarium")

    assert command.name == "keep"
    assert command.args == ("hall", "rosarium")


def test_parse_command_accepts_chinese_reentry():
    assert parse_command("回礦").name == "回礦"


def test_parse_command_rejects_empty_or_normal_chat():
    assert parse_command("") is None
    assert parse_command("   ") is None
    assert parse_command("hello miners") is None


def test_parse_command_accepts_calibration():
    assert parse_command("校準").name == "校準"
    command = parse_command("calib mining")
    assert command.name == "calib"
    assert command.args == ("mining",)
