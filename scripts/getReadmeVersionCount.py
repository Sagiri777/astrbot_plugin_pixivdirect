from pathlib import Path

text = Path("README.md").read_text(encoding="utf-8")
print(text.count("### v"))
