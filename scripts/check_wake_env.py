import importlib.util
import sys

mods = ['sounddevice', 'openwakeword', 'numpy']
print('PYTHON', sys.executable)
for name in mods:
    spec = importlib.util.find_spec(name)
    print(name, 'OK' if spec is not None else 'MISSING')
    if spec is not None:
        try:
            module = __import__(name)
            print('IMPORT_OK', name, getattr(module, '__version__', 'no-version'))
        except Exception as exc:
            print('IMPORT_ERROR', name, type(exc).__name__, exc)
