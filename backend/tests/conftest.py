import os

# Тесты детерминированные: без LLM и на фикстуре. Переменные ставим до импорта приложения.
os.environ["MOCK_RAG"] = "1"
os.environ["LLM_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["openai_api_key"] = ""
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
