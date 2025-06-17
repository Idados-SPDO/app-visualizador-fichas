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

# 1) Ajuste em load_image_bytes: capturar erro “file does not exist” e retornar None
@st.cache_data(show_spinner=False,  ttl=3600)
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

    # carrega e mostra tamanho original
    img = Image.open(BytesIO(image_bytes))
    largura, altura = img.size

    # helper para base64
    def to_b64(im: Image.Image) -> str:
        buf = BytesIO()
        im.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    # recorte
    threshold = 2600
    img1 = img.crop((0, 0, largura, min(altura, threshold)))
    img2 = img.crop((0, threshold, largura, altura)) if altura > threshold else None

    b64_1 = to_b64(img1)
    b64_2 = to_b64(img2) if img2 else None

    # template de zoom/drag (IDs parametrizados por {suf})
    html_template = '''
    <style>
      .img-wrapper {{ overflow:auto; cursor:grab; background:#f5f5f5; height:910px; }}
      .img-wrapper:active {{ cursor:grabbing; }}
      .zoomable {{ width:100%; height:auto; transition:width 0.2s ease; user-select:none; }}
      .controls {{ text-align:center; margin-bottom:8px; }}
      .controls button {{ margin:0 4px; padding:4px 12px; }}
    </style>
    <div class="controls">
      <button id="btnIn_{suf}">+</button>
      <button id="btnOut_{suf}">−</button>
    </div>
    <div class="img-wrapper" id="wrap_{suf}">
      <img id="img_{suf}" src="data:image/png;base64,{b64}" class="zoomable"/>
    </div>
    <script>
      const img_{suf}=document.getElementById("img_{suf}");
      const wrap_{suf}=document.getElementById("wrap_{suf}");
      let scale_{suf}=1;
      document.getElementById("btnIn_{suf}").onclick=()=>{{ scale_{suf}=Math.min(scale_{suf}+0.5,10); img_{suf}.style.width=(100*scale_{suf})+'%'; }};
      document.getElementById("btnOut_{suf}").onclick=()=>{{ scale_{suf}=Math.max(scale_{suf}-0.5,1); img_{suf}.style.width=(100*scale_{suf})+'%'; }};
      img_{suf}.ondblclick=()=>{{ scale_{suf}=1; img_{suf}.style.width='100%'; }};
      let isDown_{suf}=false, startX_{suf}, startY_{suf}, scrollL_{suf}, scrollT_{suf};
      wrap_{suf}.addEventListener('mousedown',e=>{{ if(scale_{suf}===1)return; isDown_{suf}=true; startX_{suf}=e.pageX-wrap_{suf}.offsetLeft; startY_{suf}=e.pageY-wrap_{suf}.offsetTop; scrollL_{suf}=wrap_{suf}.scrollLeft; scrollT_{suf}=wrap_{suf}.scrollTop; }});
      wrap_{suf}.addEventListener('mouseup',()=>isDown_{suf}=false);
      wrap_{suf}.addEventListener('mouseleave',()=>isDown_{suf}=false);
      wrap_{suf}.addEventListener('mousemove',e=>{{ if(!isDown_{suf})return; e.preventDefault(); const x=e.pageX-wrap_{suf}.offsetLeft; const y=e.pageY-wrap_{suf}.offsetTop; wrap_{suf}.scrollLeft=scrollL_{suf}-(x-startX_{suf}); wrap_{suf}.scrollTop=scrollT_{suf}-(y-startY_{suf}); }});
    </script>
    '''

    # define abas dinamicamente
    if img2:
        tabs = st.tabs([f"Ficha", f"Componentes"])
        with tabs[0]:
            st_html(html_template.format(suf="tab1", b64=b64_1), height=900)
        with tabs[1]:
            st_html(html_template.format(suf="tab2", b64=b64_2), height=900)
    else:
        tabs = st.tabs(["Ficha"])
        with tabs[0]:
            st_html(html_template.format(suf="single", b64=b64_1), height=900)



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

@st.cache_data(show_spinner=False)
def fetch_colectors() -> pd.DataFrame:
    query = """
        SELECT *
        FROM TB_VISUALIZADOR_COLETORES
    """
    snow_df = session.sql(query)
    pdf = snow_df.to_pandas()
    return pdf

# ─────────── Corpo principal do app ───────────
st.title("📋 Visualizador de Fichas Técnicas")

st.logo('logo_ibre.png')

with st.spinner("Carregando registros da base…"):
    df = fetch_business_with_images()
    df_coletor = fetch_colectors()
    df_coletor["ELEMENTAR"] = df_coletor["ELEMENTAR"].astype(str)

df["NOME_ARQUIVO"] = (
    df["NOME_ARQUIVO"]
      .astype(str)  # garante que seja string
      .str.replace(r"^st_imgs/", "", regex=True)
)
# 2) Sidebar: filtros para coluna "categoria" e coluna "elementar"
st.sidebar.header("Filtros:")
coletores = sorted(df_coletor["COLETOR"].dropna().unique().tolist())

filtro_coletor = st.sidebar.selectbox(
    "Coletor",
    options=["Todos"] + coletores,
    index=0
)


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
if filtro_coletor != "Todos":
    elementares_do_coletor = (
        df_coletor[df_coletor["COLETOR"] == filtro_coletor]
        ["ELEMENTAR"]
        .dropna()
        .unique()
    )
    df_filtrado = df_filtrado[df_filtrado["ELEMENTAR"].isin(elementares_do_coletor)]

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
