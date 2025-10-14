import os
from lxml import etree
import xml.etree.ElementTree as ET
import re
from datetime import datetime

def parse_screen(long_clickable_only: bool = True):
    os.system("adb shell uiautomator dump /sdcard/view.xml")
    os.system("adb pull /sdcard/view.xml >/dev/null")
    # For debugging, to see the raw XML:
    # os.system("adb shell cat /sdcard/view.xml")

    if long_clickable_only:
        return extract_long_clickable_descriptions("view.xml")
    else:
        return extract_innermost_content_desc("view.xml")
    
    
def extract_innermost_content_desc(xml_path):
    """
    Parse a uiautomator XML dump and extract content-desc values
    from innermost nodes with non-empty descriptions.
    @returns dict of {content-desc: bounds}
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    results = {}

    def recurse(node):
        children = list(node)
        if not children:
            desc = node.attrib.get("content-desc", "").strip()
            bounds = node.attrib.get("bounds", "")
            if desc:
                results[desc] = bounds
        else:
            for child in children:
                recurse(child)

    recurse(root)
    return results


def extract_long_clickable_descriptions(xml_path):
    """
    Extract content-desc values from nodes with long-clickable="true",
    cleaning out zero-width and direction-control Unicode characters.
    @returns dict of {content-desc: bounds}
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    results = []
    results = {}

    # Regex to strip zero-width spaces, left-to-right markers, etc.
    zwc = re.compile(r'[\u200b-\u200f\u202a-\u202e]')

    for node in root.iter():
        if node.attrib.get("long-clickable") == "true":
            desc = node.attrib.get("content-desc", "").strip()
            bounds = node.attrib.get("bounds", "")
            if desc:
                clean_desc = zwc.sub('', desc)
                split_desc = tuple(clean_desc.split("\n"))
                results[split_desc] = bounds

    return results


def parse_job_date(s: str) -> datetime:
    """Extract and parse a datetime from strings like 'Plate 1 (10/10/2025 23:41)'."""
    match = re.search(r'\((\d{2}/\d{2}/\d{4}) (\d{2}:\d{2})\)', s)
    if not match:
        raise ValueError(f"Could not find date/time in: {s}")
    date_str = f"{match.group(1)} {match.group(2)}"
    return datetime.strptime(date_str, "%m/%d/%Y %H:%M")