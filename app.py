import streamlit as st
from snowflake.snowpark import Session
from pathlib import Path
from io import BytesIO
from PIL import Image
import math
import base64
from streamlit.components.v1 import html as st_html
import pandas as pd


# ─────────── Configurações de página ───────────
st.set_page_config(
    page_title="Visualizador de Fichas Técnicas",
    page_icon="logo_fgv.png",
    layout="wide"
)


@st.cache_resource(show_spinner=False)
def get_session() -> Session:
    return Session.builder.configs(st.secrets["snowflake"]).create()


session = get_session()


@st.cache_data(show_spinner=False)
def list_images() -> list[str]:
    rows = session.sql("LIST @ST_IMGS").collect()
    return [r["name"].split("/", 1)[1] for r in rows]


# 1) Ajuste em load_image_bytes: capturar erro “file does not exist” e retornar None
@st.cache_data(show_spinner=False)
def load_image_bytes(filename: str) -> bytes | None:
    """
    Tenta buscar os bytes do arquivo no stage @ST_IMGS/{filename}.
    Se o arquivo não existir ou ocorrer outro erro, retorna None.
    """
    try:
        chunks = session.file.get_stream(f"@ST_IMGS/{filename}")
        return b"".join(chunks)
    except Exception:
        # Aqui podemos logar ou simplesmente retornar None
        return None


@st.dialog("Ficha Técnica", width="large")
def show_image_dialog(image_bytes: bytes, filename: str):
    st.subheader(Path(filename).stem)

    # 1) Carrega e recorta a imagem se ultrapassar a altura máxima
    img = Image.open(BytesIO(image_bytes))
    height_desejada = 3600
    largura_original, altura_original = img.size
    if altura_original > height_desejada:
        caixa = (0, 0, largura_original, height_desejada)
        img = img.crop(caixa)

    # 2) Converte a imagem recortada para base64
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    b64 = base64.b64encode(buffer.getvalue()).decode()

    # 3) HTML + CSS + JS para zoom dinâmico
    html_code = f'''
    <style>
      html, body {{
        margin: 0;
        padding: 0;
        width: 100%;
        height: 100%;
      }}
      .container-all {{
        display: flex;
        flex-direction: column;
        height: 100%;
      }}
      .controls {{
        display: flex;
        justify-content: center;
        gap: 1rem;
        margin: 0.5rem 0;
      }}
      .controls button {{
        padding: 0.4rem 1rem;
        font-size: 1rem;
        border: 1px solid #ccc;
        background: #f9f9f9;
        border-radius: 4px;
        cursor: pointer;
      }}
      .controls button:active {{
        background: #e0e0e0;
      }}
      .img-wrapper {{
        flex: 1;
        position: relative;
        overflow: auto;
        background: #f5f5f5;
      }}
      .zoomable {{
        display: block;
        width: 100%;
        height: auto;
        transition: width 0.2s ease, height 0.2s ease;
        cursor: grab;
      }}
      .zoomable:active {{
        cursor: grabbing;
      }}
    </style>

    <div class="container-all">
      <div class="controls">
        <button id="btnZoomIn">Zoom In</button>
        <button id="btnZoomOut">Zoom Out</button>
      </div>
      <div class="img-wrapper" id="wrapper">
        <img
          id="imgZoom"
          src="data:image/png;base64,{b64}"
          class="zoomable"
          alt="{filename}"
        />
      </div>
    </div>

    <script>
      const wrapper = document.getElementById("wrapper");
      const img = document.getElementById("imgZoom");
      const btnIn = document.getElementById("btnZoomIn");
      const btnOut = document.getElementById("btnZoomOut");

      let scale = 1;
      const maxScale = 10;
      const minScale = 1;
      const step = 0.5;

      function updateImageSize() {{
        img.style.width = (100 * scale) + '%';
      }}

      btnIn.addEventListener("click", () => {{
        if (scale + step <= maxScale) {{
          scale = parseFloat((scale + step).toFixed(2));
          updateImageSize();
        }}
      }});

      btnOut.addEventListener("click", () => {{
        if (scale - step >= minScale) {{
          scale = parseFloat((scale - step).toFixed(2));
          updateImageSize();
        }}
      }});

      img.addEventListener("dblclick", () => {{
        scale = 1;
        updateImageSize();
      }});

      let isDragging = false;
      let startX, startY, scrollLeft, scrollTop;

      wrapper.addEventListener("mousedown", (e) => {{
        if (scale === 1) return;
        isDragging = true;
        wrapper.classList.add("dragging");
        startX = e.pageX - wrapper.offsetLeft;
        startY = e.pageY - wrapper.offsetTop;
        scrollLeft = wrapper.scrollLeft;
        scrollTop = wrapper.scrollTop;
      }});

      wrapper.addEventListener("mouseup", () => {{
        isDragging = false;
        wrapper.classList.remove("dragging");
      }});

      wrapper.addEventListener("mouseleave", () => {{
        isDragging = false;
        wrapper.classList.remove("dragging");
      }});

      wrapper.addEventListener("mousemove", (e) => {{
        if (!isDragging) return;
        e.preventDefault();
        const x = e.pageX - wrapper.offsetLeft;
        const y = e.pageY - wrapper.offsetTop;
        const walkX = (startX - x);
        const walkY = (startY - y);
        wrapper.scrollLeft = scrollLeft + walkX;
        wrapper.scrollTop = scrollTop + walkY;
      }});
    </script>
    '''

    st_html(html_code, height=1500)


@st.cache_data(show_spinner=False)
def fetch_business_with_images() -> pd.DataFrame:
    """
    Busca todas as colunas da VIEW que faz JOIN entre MINHA_TABELA e IMAGENS_STAGE.
    A VIEW deve trazer CATEGORIA, ELEMENTAR, MD5_HASH, NOME_ARQUIVO etc.
    """
    query = """
        SELECT *
        FROM VW_TB_IMAGENS
    """
    snow_df = session.sql(query)
    pdf = snow_df.to_pandas()
    return pdf


# ─────────── Corpo principal do app ───────────
st.title("📋 Visualizador de Fichas Técnicas")

st.logo('logo_ibre.png')
# 1) Carrega o DataFrame da VIEW (já contendo as colunas Categoria, Elementar e Nome_Arquivo)
df = fetch_business_with_images()
df["NOME_ARQUIVO"] = (
    df["NOME_ARQUIVO"]
      .astype(str)  # garante que seja string
      .str.replace(r"^st_imgs/", "", regex=True)
)
# 2) Sidebar: filtros para coluna "categoria" e coluna "elementar"
st.sidebar.header("Filtros:")

valores_categoria = sorted(df["CATEGORIA"].dropna().unique().tolist())
filtro_categoria = st.sidebar.multiselect(
    "Categoria",
    options=valores_categoria,
    default=[]
)

valores_elementar = sorted(df["ELEMENTAR"].dropna().unique().tolist())
filtro_elementar = st.sidebar.multiselect(
    "Elementar",
    options=valores_elementar,
    default=[]
)

valores_familia = sorted(df["FAMILIA"].dropna().unique().tolist())
filtro_familia = st.sidebar.multiselect(
    "Família",
    options=valores_familia,
    default=[]
)

# 3) Filtra o DataFrame de negócio
df_filtrado = df.copy()

if filtro_categoria:
    df_filtrado = df_filtrado[df_filtrado["CATEGORIA"].isin(filtro_categoria)]
if filtro_elementar:
    df_filtrado = df_filtrado[df_filtrado["ELEMENTAR"].isin(filtro_elementar)]
if filtro_familia:
    df_filtrado = df_filtrado[df_filtrado["FAMILIA"].isin(filtro_familia)]


# 4) Se quiser um filtro de substring no nome do arquivo, pode manter assim:
query = st.sidebar.text_input("🔎 Buscar por nome de arquivo")
if query:
    df_filtrado = df_filtrado[df_filtrado["NOME_ARQUIVO"].str.contains(query, case=False, na=False)]

# 5) Extrai lista de arquivos após filtro
lista_arquivos_filtrados = df_filtrado["NOME_ARQUIVO"].dropna().unique().tolist()

# 6) Paginação sobre a lista de arquivos filtrados
itens_por_pagina = 25
total_imagens = len(lista_arquivos_filtrados)
total_paginas = math.ceil(total_imagens / itens_por_pagina) if total_imagens > 0 else 1

if "pagina_atual" not in st.session_state:
    st.session_state.pagina_atual = 1

def ir_para_anterior():
    if st.session_state.pagina_atual > 1:
        st.session_state.pagina_atual -= 1

def ir_para_proxima():
    if st.session_state.pagina_atual < total_paginas:
        st.session_state.pagina_atual += 1



pagina = st.session_state.pagina_atual
start = (pagina - 1) * itens_por_pagina
end = start + itens_por_pagina
imagens_pagina = lista_arquivos_filtrados[start:end]


col1, col2, col3 = st.columns([1, 6, 1])
with col1:
    st.button("←", on_click=ir_para_anterior, disabled=(pagina == 1))
with col2:
    
    primeiro_item = start + 1 if total_imagens > 0 else 0
    ultimo_item = min(end, total_imagens)
    texto = (
        f"<div style='text-align:center; align-itens:center; justify-content:center'>"
        f"<b>Página {pagina} de {total_paginas}</b>  |  "
        f"{primeiro_item}–{ultimo_item} de {total_imagens}"
        f"</div>"
    )
    st.markdown(texto, unsafe_allow_html=True)
with col3:
    st.button("→", on_click=ir_para_proxima, disabled=(pagina == total_paginas))

st.write("---")

# 7) Grade de imagens (3 colunas)
if total_imagens == 0:
    st.info("Nenhuma imagem encontrada para o filtro selecionado.")
else:
    n_cols = 3
    cols = st.columns(n_cols)
    for idx, img_name in enumerate(imagens_pagina):
        col = cols[idx % n_cols]
        with col:
            img_bytes = load_image_bytes(img_name)

            if img_bytes is None:
                # Caso o arquivo NÃO exista, exibimos uma mensagem
                st.warning(f"Arquivo `{img_name}` não encontrado em @ST_IMGS.")
            else:
                # Caso exista, mostramos o botão para abrir o diálogo com zoom
                if st.button(f"🔍 {Path(img_name).stem}", key=f"btn_{img_name}"):
                    show_image_dialog(img_bytes, img_name)
