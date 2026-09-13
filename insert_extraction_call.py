#!/usr/bin/env python3
"""Add tool extraction call to _stream_ollama"""

with open('core/brain.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the exact location - after "yield remaining" and before "if not tool_calls:"
marker = """            remaining = think_filter.flush()
            if remaining:
                text_buf += remaining
                yield remaining

            if not tool_calls:"""

if marker not in content:
    print("ERROR: Could not find insertion marker")
    exit(1)

extraction_call = """            remaining = think_filter.flush()
            if remaining:
                text_buf += remaining
                yield remaining

            # Try to extract tool calls from text (Ollama doesn't reliably call tools)
            extracted_tools = self._extract_tool_calls_from_text(text_buf)
            if extracted_tools:
                logger.info(f"Ollama: extracted {len(extracted_tools)} tool call(s) from text")
                for tool_name, args in extracted_tools:
                    if tool_name in self._tool_handlers:
                        handler = self._tool_handlers[tool_name]
                        result = self._run_tool(tool_name, handler, args)
                        logger.info(f"Extracted tool '{tool_name}' result: {str(result)[:120]}")

            if not tool_calls:"""

new_content = content.replace(marker, extraction_call)

if new_content == content:
    print("ERROR: Replacement did not occur")
    exit(1)

with open('core/brain.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Extraction call added successfully!")
