from pathlib import Path

from engine import net


def test_linux_gpu_inventory_detects_common_vendors_and_nodes(tmp_path, monkeypatch):
    monkeypatch.setattr(net.sys, "platform", "linux")
    sysfs = tmp_path / "sys-class-drm"
    dev = tmp_path / "dev"
    for card, vendor in (("card0", "0x1002"), ("card1", "0x8086")):
        vendor_file = sysfs / card / "device" / "vendor"
        vendor_file.parent.mkdir(parents=True, exist_ok=True)
        vendor_file.write_text(vendor, encoding="ascii")
    render = dev / "dri" / "renderD128"
    render.parent.mkdir(parents=True, exist_ok=True)
    render.touch()
    (dev / "nvidiactl").touch()

    inv = net._linux_gpu_inventory(str(sysfs), str(dev))
    assert inv["available"] is True
    assert inv["vendors"] == ["AMD", "Intel", "NVIDIA"]
    assert str(render) in inv["render_nodes"]
    assert str(dev / "nvidiactl") in inv["nvidia_device_nodes"]


def test_linux_gpu_policy_enables_vendor_neutral_acceleration(monkeypatch):
    monkeypatch.delenv("TEKZITE_LINUX_GPU", raising=False)
    monkeypatch.delenv("TEKZITE_LINUX_HW_VIDEO", raising=False)
    inv = {
        "available": True,
        "vendors": ["AMD"],
        "render_nodes": ["/dev/dri/renderD128"],
        "nvidia_device_nodes": [],
    }
    policy = net._linux_gpu_launch_policy(attempt=1, inventory=inv, vaapi_ok=False)
    assert policy["hardware_requested"] is True
    assert "--enable-gpu-rasterization" in policy["flags"]
    assert "--enable-zero-copy" in policy["flags"]
    assert "--disable-gpu" not in policy["flags"]
    assert "--ignore-gpu-blocklist" not in policy["flags"]
    assert "--disable-gpu-driver-bug-workaround" not in policy["flags"]


def test_linux_gpu_policy_second_attempt_is_software_fallback(monkeypatch):
    monkeypatch.delenv("TEKZITE_LINUX_GPU", raising=False)
    inv = {
        "available": True,
        "vendors": ["Intel"],
        "render_nodes": ["/dev/dri/renderD128"],
        "nvidia_device_nodes": [],
    }
    policy = net._linux_gpu_launch_policy(attempt=2, inventory=inv, vaapi_ok=True)
    assert policy["hardware_requested"] is False
    assert policy["fallback"] is True
    assert policy["flags"] == ["--disable-gpu"]


def test_linux_gpu_policy_respects_explicit_software_mode(monkeypatch):
    monkeypatch.setenv("TEKZITE_LINUX_GPU", "software")
    inv = {
        "available": True,
        "vendors": ["NVIDIA"],
        "render_nodes": [],
        "nvidia_device_nodes": ["/dev/nvidiactl"],
    }
    policy = net._linux_gpu_launch_policy(attempt=1, inventory=inv, vaapi_ok=True)
    assert policy["hardware_requested"] is False
    assert policy["flags"] == ["--disable-gpu"]


def test_nvidia_vaapi_stays_off_in_auto_but_can_be_explicitly_enabled(monkeypatch):
    inv = {
        "available": True,
        "vendors": ["NVIDIA"],
        "render_nodes": ["/dev/dri/renderD128"],
        "nvidia_device_nodes": ["/dev/nvidiactl"],
    }
    monkeypatch.delenv("TEKZITE_LINUX_GPU", raising=False)
    monkeypatch.delenv("TEKZITE_LINUX_HW_VIDEO", raising=False)
    automatic = net._linux_gpu_launch_policy(attempt=1, inventory=inv, vaapi_ok=True)
    assert automatic["video_decode_requested"] is False
    assert not any("VaapiOnNvidiaGPUs" in flag for flag in automatic["flags"])

    monkeypatch.setenv("TEKZITE_LINUX_HW_VIDEO", "1")
    forced = net._linux_gpu_launch_policy(attempt=1, inventory=inv, vaapi_ok=True)
    assert forced["video_decode_requested"] is True
    assert any("VaapiOnNvidiaGPUs" in flag for flag in forced["flags"])


def test_runtime_gpu_probe_distinguishes_hardware_from_software(monkeypatch):
    class DummyWS:
        def close(self):
            pass

    monkeypatch.setattr(net, "_open_devtools_websocket", lambda *args, **kwargs: DummyWS())
    monkeypatch.setattr(
        net,
        "_cdp_call",
        lambda *args, **kwargs: {
            "gpu": {
                "devices": [{"vendorId": 0x1002, "deviceId": 0x744C, "vendorString": "AMD"}],
                "auxAttributes": {"glRenderer": "AMD Radeon"},
                "featureStatus": {"gpu_compositing": "enabled"},
            }
        },
    )
    info = net._probe_chromium_gpu_info("ws://127.0.0.1:9222/devtools/browser/test")
    assert info["hardware_active"] is True
    assert info["software_renderer"] is False
    assert info["renderer"] == "AMD Radeon"

    monkeypatch.setattr(
        net,
        "_cdp_call",
        lambda *args, **kwargs: {
            "gpu": {
                "devices": [],
                "auxAttributes": {"glRenderer": "ANGLE (Google, Vulkan 1.3 SwiftShader)"},
            }
        },
    )
    info = net._probe_chromium_gpu_info("ws://127.0.0.1:9222/devtools/browser/test")
    assert info["hardware_active"] is False
    assert info["software_renderer"] is True


def test_linux_diagnostics_reports_requested_and_actual_gpu_backend():
    source = Path("browser_features.py").read_text(encoding="utf-8")
    block = source[source.index("def _show_diagnostics"):source.index("def _show_network_connections")]
    assert "Linux GPU vendors:" in block
    assert "Linux Chromium GPU request:" in block
    assert "Linux Chromium GPU active:" in block
    assert "Linux Chromium renderer:" in block
    assert "Linux presentation: CDP software compositor" in block
