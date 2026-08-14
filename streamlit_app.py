import streamlit as st

from core.config import settings
from core.ollama_client import OllamaClient, OllamaError


st.set_page_config(page_title="privAI · Streamlit", page_icon="🔒", layout="centered")
client = OllamaClient()

st.title("🔒 privAI")
st.caption("Ollama와 Streamlit으로 만든 완전 로컬 LLM 데모")

try:
    available = [item["name"] for item in client.list_models()]
except OllamaError as exc:
    st.error(str(exc))
    available = [settings.default_model]

model = st.sidebar.selectbox("모델", available, index=0)
system = st.sidebar.text_area("시스템 프롬프트", "간결하고 정확한 한국어로 답하세요.")

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
        placeholder = st.empty()
        answer = ""
        stats = None
        try:
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

