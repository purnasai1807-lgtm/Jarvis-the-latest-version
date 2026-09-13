import os


def main() -> None:
    os.chdir(r'C:\Users\HP\Desktop\myjarvis-master')

    from core.config import load_config
    from core.brain import Brain
    from tools import register_all

    config = load_config()
    brain = Brain(config)
    register_all(brain, config)

    print('START_VOICE_TEST')
    text = 'open calculator'
    print('PROMPT:', text)
    for chunk in brain.think_stream(text, 'en', source='voice'):
        print('CHUNK:', repr(chunk))
    print('END_VOICE_TEST')


if __name__ == '__main__':
    main()
