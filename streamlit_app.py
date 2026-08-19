import streamlit as st
from pathlib import Path

from core.config import settings
from core.knowledge_base import KnowledgeBase
from core.ollama_client import OllamaClient, OllamaError
from core.rag_service import rag_response


st.set_page_config(page_title="privAI · Streamlit", page_icon="🔒", layout="centered")

@st.cache_resource
def local_services():
    local_client = OllamaClient()
    local_knowledge = KnowledgeBase(Path(__file__).resolve().parent / "wiki")
    local_knowledge.reindex()
    return local_client, local_knowledge


client, knowledge = local_services()

st.title("🔒 privAI")
st.caption("Ollama와 Streamlit으로 만든 완전 로컬 LLM 데모")

try:
    available = [item["name"] for item in client.list_models()]
except OllamaError as exc:
    st.error(str(exc))
    available = [settings.default_model]

model = st.sidebar.selectbox("모델", available, index=0)
system = st.sidebar.text_area("시스템 프롬프트", "간결하고 정확한 한국어로 답하세요.")
use_wiki = st.sidebar.checkbox("Wiki 근거 사용", value=True)
status = knowledge.status()
st.sidebar.caption(
    f"{status['files_indexed']}개 문서 · {status['chunks_indexed']}개 조각"
)
if st.sidebar.button("Wiki 재색인"):
    status = knowledge.reindex()
    st.sidebar.success(
        f"{status['files_indexed']}개 문서 · {status['chunks_indexed']}개 조각"
    )

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("질문을 입력하세요"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        try:
            if use_wiki:
                with st.spinner("Wiki에서 근거를 찾는 중입니다..."):
                    result = rag_response(
                        prompt, model, system, 3, knowledge, client
                    )
                answer = result["answer"]
                st.markdown(answer)
                if result["sources"]:
                    with st.expander("사용한 Wiki 근거"):
                        for source in result["sources"]:
                            st.caption(f"{source['source']}#{source['heading']}")
                verification = result.get("verification") or {}
                if verification.get("passed") is True:
                    st.success("근거 검증 통과")
                elif verification.get("passed") is False:
                    st.warning("근거를 찾지 못했거나 검증을 통과하지 못했습니다.")
                st.caption(
                    f"{result['elapsed_seconds']}초 · "
                    f"{result['tokens_per_second'] or '-'} token/s"
                )
            else:
                placeholder = st.empty()
                answer = ""
                stats = None
                for chunk in client.stream_chat(prompt, model, system):
                    if chunk["done"]:
                        stats = chunk
                    else:
                        answer += chunk["content"]
                        placeholder.markdown(answer + "▌")
                placeholder.markdown(answer)
                if stats:
                    st.caption(
                        f"{stats['elapsed_seconds']}초 · "
                        f"{stats['tokens_per_second'] or '-'} token/s"
                    )
            st.session_state.messages.append({"role": "assistant", "content": answer})
        except OllamaError as exc:
            st.error(str(exc))
