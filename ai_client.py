"""
AI Client — обёртка для работы с OpenAI/DeepSeek/Gemini API.
Единый интерфейс для bot.py.
"""

import requests
import logging

logger = logging.getLogger(__name__)


class AIClient:
    def __init__(self, provider: str = 'openai', api_key: str = '', model: str = 'gpt-4o'):
        self.provider = provider.lower().strip()  # нормализуем регистр
        self.api_key = api_key
        self.model = model

    async def complete(self, system_prompt: str, user_prompt: str, history: list = None) -> str:
        """Единый метод для генерации ответа AI."""
        if not self.api_key:
            return ''

        try:
            if self.provider in ('openai', 'deepseek'):
                return self._call_openai_compatible(system_prompt, user_prompt, history)
            elif self.provider == 'gemini':
                return self._call_gemini(system_prompt, user_prompt)
            else:
                logger.error(f'Unknown AI provider: {self.provider}')
                return ''
        except Exception as e:
            logger.error(f'AI complete error: {e}')
            return ''

    def _call_openai_compatible(self, system_prompt: str, user_prompt: str, history: list = None) -> str:
        """OpenAI / DeepSeek API call с историей диалога."""
        base_url = 'https://api.openai.com/v1' if self.provider == 'openai' else 'https://api.deepseek.com/v1'

        messages = [{'role': 'system', 'content': system_prompt}]

        # Добавляем историю диалога если есть
        if history:
            for msg in history:
                role = 'user' if msg.get('direction') == 'INCOMING' else 'assistant'
                messages.append({'role': role, 'content': msg.get('content', '')})

        # Текущее сообщение
        if user_prompt:
            messages.append({'role': 'user', 'content': user_prompt})

        r = requests.post(
            f'{base_url}/chat/completions',
            headers={'Authorization': f'Bearer {self.api_key}'},
            json={
                'model': self.model,
                'messages': messages,
                'max_tokens': 300,
                'temperature': 0.7,
            },
            timeout=15
        )
        return r.json().get('choices', [{}])[0].get('message', {}).get('content', '')

    def _call_gemini(self, system_prompt: str, user_prompt: str) -> str:
        """Google Gemini API call."""
        prompt = f'{system_prompt}\n\n{user_prompt}'
        r = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}',
            json={'contents': [{'parts': [{'text': prompt}]}]},
            timeout=15
        )
        return r.json().get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
