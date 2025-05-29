import streamlit as st
from snowflake.snowpark import Session
from pathlib import Path
from io import BytesIO

@st.cache_resource
def get_session() -> Session:
    return Session.builder.configs(st.secrets["snowflake"]).create()

session = get_session()

st.title("Visualizador de Fichas Técnicas")

@st.cache_data(show_spinner=False)
def list_images() -> list[str]:
    rows = session.sql("LIST @ST_IMGS").collect()
    return [r["name"].split("/", 1)[1] for r in rows]

@st.cache_data(show_spinner=False)
def load_image_bytes(filename: str) -> bytes:
    chunks = session.file.get_stream(f"@ST_IMGS/{filename}")
    return b"".join(chunks)

@st.dialog("Ficha Técnica", width="medium")
def show_image_dialog(image_bytes: bytes, filename: str):
    st.subheader(Path(filename).stem)
    st.image(image_bytes, use_container_width=True)

images = list_images()

if not images:
    st.info("Nenhuma imagem encontrada no stage.")
else:
    for img_name in images:
        # extrai só o nome, sem extensão
        display_name = Path(img_name).stem
        if st.button(f"🔍 {display_name}", key=f"btn_{img_name}"):
            img_bytes = load_image_bytes(img_name)
            show_image_dialog(img_bytes, img_name)
