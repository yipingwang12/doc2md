"""Fix PUA characters in existing markdown output files."""
import pathlib
import re

PUA_RE = re.compile(r"[\uF720-\uF77E]+")


def replace_pua(match):
    return "".join(chr(ord(c) - 0xF700) for c in match.group())


fixed = 0
for f in sorted(pathlib.Path("results").glob("**/*.md")):
    text = f.read_text()
    if PUA_RE.search(text):
        new_text = PUA_RE.sub(replace_pua, text)
        f.write_text(new_text)
        fixed += 1
        old_first = text.splitlines()[0]
        new_first = new_text.splitlines()[0]
        if old_first != new_first:
            print(f"  {f.parent.name}: {new_first}")

print(f"\nFixed {fixed} files")
