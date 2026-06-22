@echo off
:: 若使用需要 API Key 的 Provider，请先设置环境变量：
:: set GENSOKYOAI_API_KEY=your-api-key
python -m GensokyoAI.cli.main --character "characters\zh_cn\KirisameMarisa.yaml" --new-session
