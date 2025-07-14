import streamlit as st
from snowflake.snowpark import Session
from snowflake.snowpark.functions import col
import pandas as pd
import math

# imports adicionais para zoom/pan e abas
from pathlib import Path
from io import BytesIO
from PIL import Image
import base64
from streamlit.components.v1 import html as st_html


# ─────────── Configurações de página ───────────
st.set_page_config(
    page_title="Visualizador de Fichas Técnicas",
    page_icon="logo_fgv.png",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("📋 Visualizador de Fichas Técnicas")

st.logo('logo_ibre.png')
# ─────────── CSS para desabilitar o “X” e o clique fora ───────────
st.markdown(
    """
    <style>
      div[aria-label="dialog"] > button[aria-label="Close"] {display: none !important;}
      [data-testid="stAppViewContainer"] > div:first-child:has(div[aria-label="dialog"]) {
        pointer-events: none;
      }
      div[aria-label="dialog"] {pointer-events: auto;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ─────────── Sessão Snowflake ───────────
@st.cache_resource(show_spinner=False)
def get_session() -> Session:
    return Session.builder.configs(st.secrets["snowflake"]).create()

session = get_session()

# ─────────── Fetchers ───────────
@st.cache_data
def fetch_insumos_meta() -> pd.DataFrame:
    sql = """
      SELECT *
      FROM TB_INSUMOS
      ORDER BY COD_INTERNO
    """
    return session.sql(sql).to_pandas()

@st.cache_data
def fetch_insumo_img(cod_interno: str) -> bytes:
    df = (
        session
          .table("TB_INSUMOS")
          .select(col("IMG"))
          .where(col("COD_INTERNO") == cod_interno)
          .to_pandas()
    )
    return bytes(df.iloc[0, 0])

@st.cache_data
def fetch_coletor_map() -> pd.DataFrame:
    # Puxa todos os pares COLETOR–ELEMENTAR
    sql = """
      SELECT *
      FROM TB_VISUALIZADOR_COLETORES
      ORDER BY COLETOR, ELEMENTAR
    """
    return session.sql(sql).to_pandas()

# ─────────── Helpers de estado ───────────
def clear_selection():
    for k in ("selected", "selected_nome", "selected_elementar"):
        st.session_state.pop(k, None)

# ─────────── Diálogo ───────────
@st.dialog("Visualizador de Imagem de Insumo", width="large")
def show_insumo_dialog(cod_interno: str, nome: str, elementar: str, projeto: str):
    st.subheader(f"{cod_interno} – {nome}")
    st.write(f"**Elementar:** {elementar}")
    st.write(f"**Projeto:** {projeto}")
    # carrega PIL.Image a partir dos bytes
    img = Image.open(BytesIO(fetch_insumo_img(cod_interno)))
    largura, altura = img.size

    # divide em duas partes, se for muito alta
    threshold = 2200
    img1 = img.crop((0, 0, largura, min(altura, threshold)))
    img2 = img.crop((0, threshold, largura, altura)) if altura > threshold else None

    # helper para converter em base64
    def to_b64(im: Image.Image) -> str:
        buf = BytesIO()
        im.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    b64_1 = to_b64(img1)
    b64_2 = to_b64(img2) if img2 else None

    # HTML + JS para zoom in/out & pan
    html_template = '''
    <style>
      .img-wrapper {{ overflow:auto; cursor:grab; background:#f5f5f5; height:85vh; }}
      .img-wrapper:active {{ cursor:grabbing; }}
      .zoomable {{ width:100%; height:auto; transition:width .2s ease; user-select:none; }}
      .controls {{ text-align:center; margin-bottom:8px; }}
      .controls button {{ margin:0 4px; padding:4px 12px; }}
    </style>
    <div class="controls">
      <button id="in_{suf}">+</button>
      <button id="out_{suf}">−</button>
    </div>
    <div class="img-wrapper" id="wrap_{suf}">
      <img id="img_{suf}" src="data:image/png;base64,{b64}" class="zoomable"/>
    </div>
    <script>
      const img_{suf}=document.getElementById("img_{suf}");
      const wrap_{suf}=document.getElementById("wrap_{suf}");
      let scale_{suf}=1;
      document.getElementById("in_{suf}").onclick=() => {{
        scale_{suf}=Math.min(scale_{suf}+0.5,10);
        img_{suf}.style.width=(100*scale_{suf})+'%';
      }};
      document.getElementById("out_{suf}").onclick=() => {{
        scale_{suf}=Math.max(scale_{suf}-0.5,1);
        img_{suf}.style.width=(100*scale_{suf})+'%';
      }};
      img_{suf}.ondblclick=() => {{ scale_{suf}=1; img_{suf}.style.width='100%'; }};
      let isDown_{suf}=false, startX_{suf}, startY_{suf}, scrollL_{suf}, scrollT_{suf};
      wrap_{suf}.addEventListener('mousedown', e => {{
        if (scale_{suf}===1) return;
        isDown_{suf}=true;
        startX_{suf}=e.pageX-wrap_{suf}.offsetLeft;
        startY_{suf}=e.pageY-wrap_{suf}.offsetTop;
        scrollL_{suf}=wrap_{suf}.scrollLeft;
        scrollT_{suf}=wrap_{suf}.scrollTop;
      }});
      wrap_{suf}.addEventListener('mouseup', () => isDown_{suf}=false);
      wrap_{suf}.addEventListener('mouseleave', () => isDown_{suf}=false);
      wrap_{suf}.addEventListener('mousemove', e => {{
        if (!isDown_{suf}) return;
        e.preventDefault();
        const x=e.pageX-wrap_{suf}.offsetLeft;
        const y=e.pageY-wrap_{suf}.offsetTop;
        wrap_{suf}.scrollLeft=scrollL_{suf}-(x-startX_{suf});
        wrap_{suf}.scrollTop=scrollT_{suf}-(y-startY_{suf});
      }});
    </script>
    '''

    # cria abas dinamicamente
    if img2:
        tabs = st.tabs(["Ficha", "Componentes"])
        with tabs[0]:
            st_html(html_template.format(suf="a", b64=b64_1), height=900)
        with tabs[1]:
            st_html(html_template.format(suf="b", b64=b64_2), height=900)
    else:
        tabs = st.tabs(["Ficha"])
        with tabs[0]:
            st_html(html_template.format(suf="single", b64=b64_1), height=900)

    # botão para fechar
    if st.button("Fechar"):
        clear_selection()
        st.rerun()


# ─────────── Carrega dados ───────────
df_meta       = fetch_insumos_meta()
df_coletor_map = fetch_coletor_map()

# ─────────── Sidebar: busca + filtros ───────────
search = st.sidebar.text_input(
    "🔍 Buscar insumo ou código",
    key="search",
    on_change=clear_selection
)

elementares_base = sorted(
    df_meta["ELEMENTAR"]
        .dropna()
        .unique()
        .tolist()
)

coletors_raw = df_coletor_map["COLETOR"].dropna().unique().tolist()
coletors_raw.sort()  # ou: coletors_raw = sorted(coletors_raw)
coletors = ["Todos"] + coletors_raw

selected_coletor = st.sidebar.selectbox(
    "🔽 Selecione Coletor",
    coletors,
    key="coletor",
    on_change=clear_selection
)

# Dropdown de Elementares dependente do Coletor
if selected_coletor == "Todos":
    # todos os elementares que existem em TB_INSUMOS
    elementar_opts = elementares_base
else:
    # elementares que o coletor tem *e* que existem em TB_INSUMOS
    elementar_opts = sorted(
        set(
            df_coletor_map[df_coletor_map["COLETOR"] == selected_coletor]["ELEMENTAR"]
        ) & set(elementares_base)
    )
elementares = ["Todos"] + elementar_opts
selected_elementar = st.sidebar.selectbox(
    "🔽 Filtrar por Elementar",
    elementares,
    key="elementar",
    on_change=clear_selection
)

job_opts = ["Todos"] + sorted(
    df_meta["JOB"]
        .dropna()
        .unique()
        .tolist()
)
selected_job = st.sidebar.selectbox(
    "🔽 Filtrar por Job",
    job_opts,
    key="job",
    on_change=clear_selection
)

project_opts = ["Todos"] + sorted(
    df_meta["PROJETO"]
        .dropna()
        .unique()
        .tolist()
)

selected_project = st.sidebar.selectbox(
    "🔽 Filtrar por Projeto",
    project_opts,
    key="project",
    on_change=clear_selection
)

# ─────────── Aplica filtro de JOB ───────────
if selected_job != "Todos":
    df_meta = df_meta[df_meta["JOB"] == selected_job]

if selected_project != "Todos":
    df_meta = df_meta[df_meta["PROJETO"] == selected_project]
# Aplica filtros à tabela de insumos
if search:
    mask_cod  = df_meta["COD_INTERNO"].astype(str).str.contains(search, case=False, na=False)
    mask_nome = df_meta["INSUMO"].str.contains(search, case=False, na=False)
    df_meta   = df_meta[mask_cod | mask_nome]

# Se escolher um Coletor, mantemos só os insumos cujos ELEMENTAR estejam naquele coletor
if selected_coletor != "Todos":
    df_meta = df_meta[df_meta["ELEMENTAR"].isin(elementar_opts)]

# Se escolher um Elementar específico, filtramos ainda mais
if selected_elementar != "Todos":
    df_meta = df_meta[df_meta["ELEMENTAR"] == selected_elementar]

# ─────────── Paginação ───────────
total_items = len(df_meta)
per_page    = 20
total_pag   = max(1, math.ceil(total_items / per_page))

if "page" not in st.session_state:
    st.session_state.page = 1
if st.session_state.page > total_pag:
    st.session_state.page = total_pag

def prev_page():
    st.session_state.page -= 1
    clear_selection()

def next_page():
    st.session_state.page += 1
    clear_selection()

col_prev, col_info, col_next = st.columns([1,6,1])

with col_prev:
    st.button(
        "← Anterior",
        on_click=prev_page,
        disabled=st.session_state.page <= 1
    )

with col_info:
    start = (st.session_state.page - 1) * per_page + 1
    end   = min(start + per_page - 1, total_items)
    st.markdown(
        f"<center><b>Página {st.session_state.page} / {total_pag}</b><br>"
        f"<i>itens {start}–{end} de {total_items}</i></center>",
        unsafe_allow_html=True
    )

with col_next:
    st.button(
        "Próximo →",
        on_click=next_page,
        disabled=st.session_state.page >= total_pag
    )
st.write("---")
start_idx = (st.session_state.page - 1) * per_page
page_df   = df_meta.iloc[start_idx : start_idx + per_page]

# ─────────── Botões em 3 colunas ───────────
cols = st.columns(3)
for i, (_, row) in enumerate(page_df.iterrows()):
    cod   = str(row["COD_INTERNO"])
    nome  = str(row["INSUMO"])
    label = nome if len(nome) <= 20 else nome[:20] + "…"
    button_col = cols[i % 3]
    if button_col.button(f"{cod} – {label}", key=f"btn_{cod}", help=nome):
        st.session_state.selected           = cod
        st.session_state.selected_nome      = nome
        st.session_state.selected_elementar = row["ELEMENTAR"]
        st.session_state.selected_projeto   = row["PROJETO"]
        

# ─────────── Abre diálogo se selecionado ───────────
if "selected" in st.session_state:
    show_insumo_dialog(
        st.session_state.selected,
        st.session_state.selected_nome,
        st.session_state.selected_elementar,
        st.session_state.selected_projeto
    )
