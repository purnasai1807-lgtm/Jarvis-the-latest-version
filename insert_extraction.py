#!/usr/bin/env python3
"""Add extraction method to brain.py"""

with open('core/brain.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find where to insert: just before "    # Tool execution"
marker = "    # ------------------------------------------------------------------\n    # Tool execution"
if marker not in content:
    print("ERROR: Could not find insertion marker")
    exit(1)

extraction_method = """    def _extract_tool_calls_from_text(self, text: str) -> list[tuple[str, dict]]:
        \"\"\"Extract tool calls from plain text response.\"\"\"
        if not self._tool_handlers:
            return []
        extracted = []
        text_lower = text.lower()
        if "opened " in text_lower or "open " in text_lower:
            for app in ["calculator", "notepad", "chrome", "firefox", "spotify", "discord", "whatsapp", "edge"]:
                if app in text_lower:
                    extracted.append(("open_app", {"app": app}))
                    break
        if ("turned on" in text_lower or "turned off" in text_lower or "turn on" in text_lower or "turn off" in text_lower) and "light" in text_lower:
            state = "on" if ("turned on" in text_lower or "turn on" in text_lower) else "off"
            extracted.append(("lights_control", {"state": state}))
        return extracted

"""

new_content = content.replace(marker, extraction_method + marker)

with open('core/brain.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Method inserted successfully!")
