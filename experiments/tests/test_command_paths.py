from mrexp.mutants import split_command


def test_windows_commands_preserve_backslashes_and_quoted_spaces():
    assert split_command(r'C:\Python\python.exe "C:\work folder\sut.py" --port 8001', windows=True) == [
        r"C:\Python\python.exe",
        r"C:\work folder\sut.py",
        "--port",
        "8001",
    ]


def test_posix_commands_keep_quoted_spaces():
    assert split_command("'/opt/work folder/python' -m uvicorn", windows=False) == [
        "/opt/work folder/python",
        "-m",
        "uvicorn",
    ]
