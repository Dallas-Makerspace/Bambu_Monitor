import os
import re
import subprocess
import time
from lxml import etree
import parser as pr

def go_to_printing_history():
    os.system("adb shell input keyevent KEYCODE_BACK")
    tap_by_desc("Me")
    tap_by_desc("Printing History")

def get_devices():
    go_to_device_page("Savage")    
    tap_by_desc("brand_logo")
    return list(pr.parse_screen(False).keys())[:-1]

def go_to_device_page(machine):
    tap_by_desc("Devices")
    if not find_by_desc("brand_logo"):
        os.system("adb shell input keyevent KEYCODE_BACK")
        tap_by_desc("Devices")

    tap_by_desc("brand_logo")
    list_screen = pr.parse_screen(False)
    tap_by_desc(machine)
    machine_screen = pr.parse_screen(False)
    if machine_screen.keys() == list_screen.keys():
        os.system("adb shell input keyevent KEYCODE_BACK")
    time.sleep(1)


def tap_by_desc(desc):
    node = find_by_desc(desc)
    if node:
        tap_by_bounds(node)
    else:
        return False


def find_by_desc(desc):
    """
    Return the bounds of the first node whose content-desc or text contains `desc`.
    """
    os.system("adb shell uiautomator dump /sdcard/view.xml")
    os.system("adb pull /sdcard/view.xml >/dev/null")
    tree = etree.parse("view.xml")

    xpath = f"//node[contains(normalize-space(@content-desc), '{desc}')] | //node[contains(normalize-space(@text), '{desc}')]"
    node = tree.xpath(xpath)

    if not node:
        print(f"Element '{desc}' not found")
        return False
    else:
        return node[0].get("bounds")


def tap_by_bounds(bounds):
    """
    Tap the screen at the center of the given bounds string.
    """
    x, y = get_bounds_center(bounds)
    time.sleep(1)
    subprocess.run(["adb", "shell", "input", "tap", str(x), str(y)])
    print(f"Tapped at {x},{y}")


def scroll_up(screen):
    swipe_by_bounds(list(screen.values())[1], list(screen.values())[len(screen) - 2])

def scroll_down(screen):
    swipe_by_bounds(list(screen.values())[len(screen) - 2], list(screen.values())[1])


def swipe_by_bounds(bounds1, bounds2):
    """
    Swipe from the center of bounds1 to the center of bounds2.
    """
    x1, y1 = get_bounds_center(bounds1)
    x2, y2 = get_bounds_center(bounds2)
    time.sleep(1)
    subprocess.run(["adb", "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2)])
    print(f"Swiped from {x1},{y1} to {x2},{y2}")


def get_bounds_center(bounds_str):
    """
    Returns tuple[int, int]: (x, y) coordinates representing the center of the bounds.
    """
    nums = list(map(int, re.findall(r'\d+', bounds_str)))
    x = (nums[0] + nums[2]) // 2
    y = (nums[1] + nums[3]) // 2
    return x, y
