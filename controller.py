import os
import re
import subprocess
import time
from lxml import etree

def go_to_printing_history():
    os.system("adb shell input keyevent KEYCODE_BACK")
    tap_by_desc("Me")
    tap_by_desc("Printing History")


def go_to_device_page(machine):
    tap_by_desc("Back")
    tap_by_desc("Devices")
    tap_by_desc("brand_logo")
    tap_by_desc(machine)
    time.sleep(1)


def tap_by_desc(desc):
    node = find_by_desc(desc)
    if node:
        tap_by_bounds(node)


def find_by_desc(desc):
    """
    Return the bounds of the first node matching the content description, or False if not found.
    """
    os.system("adb shell uiautomator dump /sdcard/view.xml")
    os.system("adb pull /sdcard/view.xml >/dev/null")
    tree = etree.parse("view.xml")
    node = tree.xpath(f"//node[@content-desc='{desc}']")
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
