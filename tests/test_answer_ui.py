import shutil
import subprocess
from pathlib import Path

import pytest
import json


def test_answer_presentation_javascript():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js required for frontend presentation tests')
    script = Path(__file__).with_name('answer_ui.test.cjs')
    result = subprocess.run([node, '--test', str(script)], capture_output=True, text=True,
                            encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('framework', ['fastapi', 'flask'])
@pytest.mark.parametrize('kind', ['missing_role', 'missing_memory'])
def test_real_partial_stream_exposes_ui_required_evidence(framework, kind, monkeypatch):
    from fastapi.testclient import TestClient
    import app as fastapi_module
    import flask_app as flask_module
    from core.knowledge_base import KnowledgeBase
    module = fastapi_module if framework == 'fastapi' else flask_module
    knowledge = KnowledgeBase(module.ROOT / 'wiki')
    knowledge.reindex()
    monkeypatch.setattr(module, 'knowledge', knowledge)
    def forbidden(*args, **kwargs):
        pytest.fail('partial source presentation must not call the model')
    monkeypatch.setattr(module.client, 'chat', forbidden)
    client = TestClient(module.app) if framework == 'fastapi' else module.app.test_client()
    question = ('FastAPI와 Flask의 역할과 Django의 역할도 알려줘.' if kind == 'missing_role' else
                'Flask와 Streamlit의 역할을 적고 각 도구의 최소 RSS 실측값도 덧붙여줘.')
    response = client.post('/rag/chat/stream', json={'prompt': question})
    assert response.status_code == 200
    body = response.text if framework == 'fastapi' else response.get_data(as_text=True)
    events = [json.loads(line) for line in body.splitlines()]
    assert events[0]['sources']
    text = ''.join(e.get('content', '') for e in events)
    check = events[-1]['verification']
    assert text.startswith('검색된 Wiki 원문에서 확인한 항목:\n')
    assert '\n\n확인하지 못한 항목:\n' in text
    assert check['method'] == 'deterministic_requirement_copy'
    assert check['missing_items'] and check['passed'] is None
    assert events[-1]['done'] is True and events[-1]['eval_count'] == 0
