import os
import shutil
import subprocess

ADB_KEY_NAME = "bambu_adbkey"


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
