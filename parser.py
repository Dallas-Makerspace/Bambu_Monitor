import os
from lxml import etree
import xml.etree.ElementTree as ET
import re
from datetime import datetime

ZERO_WIDTH_CHARS = re.compile(r'[\u200b-\u200f\u202a-\u202e\ufeff]')


def normalize_ui_text(value: str) -> str:
    """
    Normalize UI text from Bambu Handy so selectors survive zero-width chars and
    multiline labels introduced by app updates.
    """
    if not value:
        return ""

    cleaned = ZERO_WIDTH_CHARS.sub("", value.replace("\r", ""))
    lines = [re.sub(r"\s+", " ", line).strip() for line in cleaned.split("\n")]
    return "\n".join(line for line in lines if line)


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
    Parse a uiautomator XML dump and extract normalized content-desc/text values
    from nodes that expose user-visible text.
    @returns dict of {normalized_label: bounds}
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    results = {}

    def recurse(node):
        children = list(node)
        bounds = node.attrib.get("bounds", "")

        # Prefer content-desc, but also capture text nodes because newer app
        # versions moved some labels there.
        for raw_value in (node.attrib.get("content-desc", ""), node.attrib.get("text", "")):
            value = normalize_ui_text(raw_value)
            if value:
                results[value] = bounds

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
    results = {}

    for node in root.iter():
        if node.attrib.get("long-clickable") == "true":
            desc = normalize_ui_text(node.attrib.get("content-desc", ""))
            if not desc:
                desc = normalize_ui_text(node.attrib.get("text", ""))
            bounds = node.attrib.get("bounds", "")
            if desc:
                split_desc = tuple(desc.split("\n"))
                results[split_desc] = bounds

    return results


def parse_job_date(s: str) -> datetime:
    """Extract and parse a datetime from strings like 'Plate 1 (10/10/2025 23:41)'."""
    match = re.search(r'\((\d{2}/\d{2}/\d{4}) (\d{2}:\d{2})\)', s)
    if not match:
        raise ValueError(f"Could not find date/time in: {s}")
    date_str = f"{match.group(1)} {match.group(2)}"
    return datetime.strptime(date_str, "%m/%d/%Y %H:%M")
