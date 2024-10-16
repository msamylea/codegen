import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guess'
    LLM_PROVIDER = os.environ.get('LLM_PROVIDER', 'ollama')
    LLM_MODEL = os.environ.get('LLM_MODEL', 'llama3.1:8b-instruct-q8_0')
    DEFAULT_PATH = os.environ.get('DEFAULT_PATH', './code')
    SYSTEM_MESSAGE_TEMPLATE = os.environ.get('SYSTEM_MESSAGE_TEMPLATE', 'prompt_template.txt')
    TEMPERATURE = float(os.environ.get('TEMPERATURE', '0.1'))