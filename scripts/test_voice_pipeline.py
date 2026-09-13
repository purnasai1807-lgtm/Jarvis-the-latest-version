import io
import os
import wave


def main() -> None:
    os.chdir(r'C:\Users\HP\Desktop\myjarvis-master')

    from core.config import load_config
    from core.stt import SpeechToText
    from core.brain import Brain
    from tools import register_all

    print('START')
    config = load_config()
    print('CONFIG_OK', bool(config))

    stt = SpeechToText(config)
    print('STT_CLASS_OK', type(stt).__name__)

    # Generate a tiny silent WAV payload to exercise the transcription pipeline.
    with io.BytesIO() as buf:
        with wave.open(buf, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b'\x00\x00' * 1600)
        wav_bytes = buf.getvalue()

    text, lang = stt.transcribe(wav_bytes, force_language='en')
    print('TRANSCRIBE_RESULT', repr(text), lang)

    brain = Brain(config)
    print('BRAIN_MODEL', brain._openai_model)
    print('BRAIN_TOOLS', len(brain._tools))

    register_all(brain, config)
    print('REGISTERED_TOOLS', len(brain._tools))
    print('END')


if __name__ == '__main__':
    main()
