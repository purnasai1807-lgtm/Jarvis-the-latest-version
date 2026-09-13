import os
import time

os.chdir(r'C:\Users\HP\Desktop\myjarvis-master')

from tools import ALL_TOOLS
from tools.system import open_app, open_url, close_app, volume_control

print('REGISTRY_COUNT', len(ALL_TOOLS))
print('FIRST_TEN', [tool['name'] for tool in ALL_TOOLS[:10]])

results = []

try:
    results.append(('open_app', open_app('calculator')))
    time.sleep(1)
except Exception as exc:
    results.append(('open_app', f'ERROR: {exc}'))

try:
    results.append(('open_url', open_url('https://example.com')))
    time.sleep(1)
except Exception as exc:
    results.append(('open_url', f'ERROR: {exc}'))

try:
    results.append(('volume_up', volume_control('up')))
    time.sleep(1)
except Exception as exc:
    results.append(('volume_up', f'ERROR: {exc}'))

try:
    results.append(('close_app', close_app('calculator')))
    time.sleep(1)
except Exception as exc:
    results.append(('close_app', f'ERROR: {exc}'))

for item in results:
    print(item)
