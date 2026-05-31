OFERTIX BACKEND COMPLETE MERGED ZIP

Base:
- backend(3).zip

Merged:
- phrase 2(2).zip / Claude Phase 2 backend locale + AI synchronization

Applied files:
- core/locale_context.py
- core/middleware/locale_middleware.py
- core/middleware/__init__.py
- core/api_errors.py
- schemas/scan_schema.py
- routes/scan.py
- routes/ai_deal_brain.py
- routes/ai_search.py
- services/llm_transport.py
- services/locale_prompt_engine.py
- services/unified_ai_service.py
- services/ai_engine_service.py
- services/ai_service.py
- services/ai_brain_service.py
- main.py

Important fix made during merge:
Claude's middleware files are placed under core/middleware/, not middleware/,
because the new main.py imports:
    from core.middleware import LocaleMiddleware

What Phase 2 provides:
- Backend reads X-App-Locale / Accept-Language / ?lang
- Backend sets Content-Language / X-Resolved-Locale
- AI prompts become locale-aware
- /api/scan/product route is added
- Unified AI service and LLM transport are added

Recommended commands after extracting:
cd backend
python -m py_compile core/locale_context.py core/middleware/locale_middleware.py services/llm_transport.py services/locale_prompt_engine.py services/unified_ai_service.py services/ai_engine_service.py services/ai_service.py services/ai_brain_service.py core/api_errors.py schemas/scan_schema.py routes/scan.py routes/ai_deal_brain.py routes/ai_search.py main.py
uvicorn main:app --reload

Then deploy this backend folder to Render.
