import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

ANDROID_IP = "192.168.240.112"
ADB_AUTH_RETRIES = 3
ADB_AUTH_DELAY_S = 2
ADB_WAIT_TIMEOUT_S = 60
ADB_RETRY_SLEEP_S = 5
ADB_CONNECT_RETRIES = 5
ADB_SERVER_SOCKET = "tcp:localhost:5038"
ADB_KEY_NAME = "bambu_adbkey"


def adb_env(adb_home, android_ip=ANDROID_IP, adb_server_socket=ADB_SERVER_SOCKET):
    env = os.environ.copy()
    env["HOME"] = adb_home
    env.setdefault("ANDROID_SDK_HOME", adb_home)
    env["ADB_SERVER_SOCKET"] = adb_server_socket
    env["ANDROID_SERIAL"] = f"{android_ip}:5555"
    return env


def prepare_adb_env(adb_home, android_ip=ANDROID_IP, adb_server_socket=ADB_SERVER_SOCKET):
    env = adb_env(adb_home, android_ip=android_ip, adb_server_socket=adb_server_socket)
    ensure_adb_key(adb_home, env, android_ip=android_ip, adb_server_socket=adb_server_socket)
    return env


def _adb_device_status(env, android_ip=ANDROID_IP):
    result = subprocess.run(
        ["adb", "devices"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        if line.startswith(android_ip):
            parts = line.split()
            if len(parts) >= 2:
                return parts[1]
    return None


def _adb_get_state(env, android_ip=ANDROID_IP):
    result = subprocess.run(
        ["adb", "-s", f"{android_ip}:5555", "get-state"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.stdout else ""


def _wait_for_adb_device(env, timeout_s=ADB_WAIT_TIMEOUT_S, android_ip=ANDROID_IP):
    start = time.time()
    last_status = None
    while time.time() - start < timeout_s:
        status = _adb_get_state(env, android_ip=android_ip) or _adb_device_status(env, android_ip=android_ip)
        if status == "device":
            return True
        if status:
            last_status = status
        if status == "offline":
            subprocess.run(
                ["adb", "disconnect", android_ip],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(["adb", "connect", android_ip], env=env, check=False)
        time.sleep(1)
    if last_status:
        print(f"[Supervisor] ADB device wait timeout (last status={last_status}).")
    else:
        print("[Supervisor] ADB device wait timeout (no device).")
    return False


def ensure_adb_connected(env, android_ip=ANDROID_IP, retries=ADB_CONNECT_RETRIES):
    for _ in range(retries):
        subprocess.run(["adb", "connect", android_ip], env=env, check=False)
        if _wait_for_adb_device(env, android_ip=android_ip):
            return True
        time.sleep(1)
    return False


def _restart_adbd():
    restart_script = "\n".join([
        "setprop ctl.restart adbd",
    ]) + "\n"
    subprocess.run(
        ["sudo", "waydroid", "shell"],
        input=restart_script,
        text=True,
        check=False,
    )


def _waydroid_shell(cmd_args):
    return subprocess.run(
        ["sudo", "waydroid", "shell", "--", *cmd_args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )


def _bounds_center(bounds_str):
    nums = list(map(int, re.findall(r"\d+", bounds_str)))
    if len(nums) < 4:
        return None
    x = (nums[0] + nums[2]) // 2
    y = (nums[1] + nums[3]) // 2
    return x, y


def _find_nodes(root, predicate):
    matches = []
    for node in root.iter():
        if predicate(node):
            matches.append(node)
    return matches


def _screen_size():
    result = _waydroid_shell(["wm", "size"])
    if not result.stdout:
        return None
    m = re.search(r"Physical size:\s*(\d+)x(\d+)", result.stdout)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _tap_at_ratio(x_ratio, y_ratio):
    size = _screen_size()
    if not size:
        return False
    w, h = size
    x = int(w * x_ratio)
    y = int(h * y_ratio)
    _waydroid_shell(["input", "tap", str(x), str(y)])
    return True


def _tap_usb_prompt_fallback():
    # Fallback taps for the USB debugging dialog when UI dump doesn't expose it.
    did_tap = False
    # Try a few likely positions for checkbox and Allow button.
    checkbox_points = [
        (0.23, 0.48),
        (0.24, 0.50),
    ]
    allow_points = [
        (0.81, 0.51),
        (0.81, 0.52),
    ]
    for x_ratio, y_ratio in checkbox_points:
        if _tap_at_ratio(x_ratio, y_ratio):
            did_tap = True
    for x_ratio, y_ratio in allow_points:
        if _tap_at_ratio(x_ratio, y_ratio):
            did_tap = True
    _waydroid_shell(["input", "keyevent", "66"])
    return did_tap


def _maybe_accept_usb_debugging_prompt():
    subprocess.run(
        ["sudo", "waydroid", "shell", "--", "screencap", "-p", "/sdcard/adb_prompt_before.png"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    dump_run = _waydroid_shell(["uiautomator", "dump", "/sdcard/view.xml"])
    if dump_run.stdout:
        print(f"[Supervisor] uiautomator dump: {dump_run.stdout.strip()}")
    dump = _waydroid_shell(["cat", "/sdcard/view.xml"])
    if dump.stdout:
        print(f"[Supervisor] UI dump size: {len(dump.stdout)} bytes")
    if not dump.stdout or "<hierarchy" not in dump.stdout:
        print("[Supervisor] UI dump missing hierarchy; cannot detect USB prompt.")
        if _tap_usb_prompt_fallback():
            subprocess.run(
                ["sudo", "waydroid", "shell", "--", "screencap", "-p", "/sdcard/adb_prompt_after.png"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            print("[Supervisor] Used fallback taps for USB prompt.")
            return True
        return False
    try:
        root = ET.fromstring(dump.stdout)
    except ET.ParseError:
        print("[Supervisor] UI dump parse failed.")
        return False

    def text_or_desc(node):
        text = node.attrib.get("text", "")
        desc = node.attrib.get("content-desc", "")
        return text or desc

    prompt = _find_nodes(
        root,
        lambda n: "usb debugging" in text_or_desc(n).lower(),
    )
    if not prompt:
        print("[Supervisor] USB debugging prompt not found in UI dump.")
        if _tap_usb_prompt_fallback():
            subprocess.run(
                ["sudo", "waydroid", "shell", "--", "screencap", "-p", "/sdcard/adb_prompt_after.png"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            print("[Supervisor] Used fallback taps for USB prompt.")
            return True
        return False

    checkbox = _find_nodes(
        root,
        lambda n: "always allow from this computer" in text_or_desc(n).lower(),
    )
    if checkbox:
        bounds = checkbox[0].attrib.get("bounds")
        center = _bounds_center(bounds or "")
        if center:
            _waydroid_shell(["input", "tap", str(center[0]), str(center[1])])
            print("[Supervisor] Tapped 'Always allow from this computer'.")

    allow_buttons = _find_nodes(
        root,
        lambda n: text_or_desc(n).strip().lower() == "allow",
    )
    if allow_buttons:
        bounds = allow_buttons[0].attrib.get("bounds")
        center = _bounds_center(bounds or "")
        if center:
            _waydroid_shell(["input", "tap", str(center[0]), str(center[1])])
            subprocess.run(
                ["sudo", "waydroid", "shell", "--", "screencap", "-p", "/sdcard/adb_prompt_after.png"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            print("[Supervisor] Tapped 'Allow' button.")
            return True

    print("[Supervisor] 'Allow' button not found in USB prompt.")
    return False


def ensure_adb_authorized(
    adb_home=None,
    android_ip=ANDROID_IP,
    retries=ADB_AUTH_RETRIES,
    delay_s=ADB_AUTH_DELAY_S,
):
    if adb_home is None:
        adb_home = os.path.expanduser("~")
    env = adb_env(adb_home, android_ip=android_ip)
    adb_pub_path = ensure_adb_key(
        adb_home,
        env,
        android_ip=android_ip,
        adb_server_socket=ADB_SERVER_SOCKET,
    )

    for attempt in range(1, retries + 1):
        if not sync_adb_keys(adb_pub_path):
            print(f"[Supervisor] adb_keys sync failed (attempt {attempt}/{retries}).")
        _restart_adbd()
        subprocess.run(["adb", "disconnect", android_ip], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        connect = subprocess.run(
            ["adb", "connect", android_ip],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if connect.stdout:
            print(connect.stdout.strip())
        if connect.stdout and "failed to authenticate" in connect.stdout.lower():
            if _maybe_accept_usb_debugging_prompt():
                print("[Supervisor] Accepted USB debugging prompt.")
                time.sleep(2)
        subprocess.run(["adb", "reconnect", "device"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if _wait_for_adb_device(env, android_ip=android_ip):
            print("[Supervisor] ADB authorized.")
            return True
        status = _adb_device_status(env, android_ip=android_ip)
        if status == "unauthorized":
            if _maybe_accept_usb_debugging_prompt():
                print("[Supervisor] Accepted USB debugging prompt.")
                time.sleep(2)
                continue
        print(f"[Supervisor] ADB not authorized (status={status}), retrying...")
        time.sleep(delay_s)

    print("[Supervisor] ADB authorization failed after retries.")
    return False

def ensure_adb_key(adb_home, env, android_ip=None, adb_server_socket=None, adb_key_name=ADB_KEY_NAME):
    android_dir = os.path.join(adb_home, ".android")
    adb_key_path = os.path.join(android_dir, adb_key_name)
    default_key_path = os.path.join(android_dir, "adbkey")
    adb_pub_path = f"{adb_key_path}.pub"
    default_pub_path = f"{default_key_path}.pub"
    os.makedirs(android_dir, exist_ok=True)
    if not os.path.exists(adb_pub_path):
        subprocess.run(["adb", "keygen", adb_key_path], env=env, check=False)
    # Keep the default key in sync so adb uses the same private key everywhere.
    if not os.path.exists(default_key_path):
        shutil.copyfile(adb_key_path, default_key_path)
    if not os.path.exists(default_pub_path):
        shutil.copyfile(adb_pub_path, default_pub_path)
    env["ADB_VENDOR_KEYS"] = adb_key_path
    os.environ["ADB_VENDOR_KEYS"] = adb_key_path
    if adb_server_socket:
        os.environ["ADB_SERVER_SOCKET"] = adb_server_socket
    if android_ip:
        os.environ["ANDROID_SERIAL"] = f"{android_ip}:5555"
    subprocess.run(["adb", "kill-server"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["adb", "start-server"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return adb_pub_path


def sync_adb_keys(adb_pub_path):
    try:
        with open(adb_pub_path, "r") as f:
            adb_key = f.read().strip()
        adb_setup_script = "\n".join([
            "settings put global adb_enabled 1 || true",
            "settings put global adb_notify 0 || true",
            "setprop persist.adb.notify 0 || true",
            "setprop persist.adb.secure 0 || true",
            "mkdir -p /data/misc/adb",
            "mkdir -p /data/adb",
            f'printf "%s\\n" "{adb_key}" > /data/misc/adb/adb_keys',
            f'printf "%s\\n" "{adb_key}" > /data/adb/adb_keys',
            "chmod 600 /data/misc/adb/adb_keys",
            "chmod 600 /data/adb/adb_keys",
            "chown shell:shell /data/misc/adb/adb_keys",
            "chown shell:shell /data/adb/adb_keys",
            "command -v restorecon >/dev/null 2>&1 && restorecon /data/misc/adb/adb_keys || true",
            "command -v restorecon >/dev/null 2>&1 && restorecon /data/adb/adb_keys || true",
            "command -v chcon >/dev/null 2>&1 && chcon u:object_r:adb_keys_file:s0 /data/misc/adb/adb_keys || true",
            "command -v chcon >/dev/null 2>&1 && chcon u:object_r:adb_keys_file:s0 /data/adb/adb_keys || true",
        ]) + "\n"
        result = subprocess.run(
            ["sudo", "waydroid", "shell"],
            input=adb_setup_script,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[Supervisor] Failed to sync adb_keys: {e}")
        return False
