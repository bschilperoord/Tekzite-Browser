from engine import net


def test_linux_headless_launch_uses_positional_page_target():
    args = net._chromium_launch_target_args("about:blank", platform_name="posix")

    assert args == ["about:blank"]
    assert not any(arg.startswith("--app=") for arg in args)


def test_windows_launch_keeps_app_mode():
    args = net._chromium_launch_target_args("about:blank", platform_name="nt")

    assert args == ["--app=about:blank"]
