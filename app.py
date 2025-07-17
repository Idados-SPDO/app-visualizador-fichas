import streamlit as st
from snowflake.snowpark import Session
from snowflake.snowpark.functions import col
import pandas as pd
import math
from pathlib import Path
from io import BytesIO
from PIL import Image
import base64
from streamlit.components.v1 import html as st_html

st.set_page_config(
    page_title="Visualizador de Fichas Técnicas",
    page_icon="logo_fgv.png",
    layout="wide",
    initial_sidebar_state="expanded"
)
# ─────────── Sessão Snowflake ───────────
@st.cache_resource(show_spinner=False)
def get_session() -> Session:
    return Session.builder.configs(st.secrets["snowflake"]).create()

session = get_session()

# ─────────── Fetchers ───────────
@st.cache_data
def fetch_coletor_map() -> pd.DataFrame:
    sql = """
      SELECT *
      FROM TB_VISUALIZADOR_COLETORES
      ORDER BY COLETOR, ELEMENTAR
    """
    return session.sql(sql).to_pandas()

@st.cache_data(show_spinner=False)
def fetch_meta_page(
    search: str,
    coletor: str,
    elementar: str,
    job: str,
    project: str,
    page: int,
    per_page: int = 20
) -> tuple[pd.DataFrame, int]:
    # Monta cláusula WHERE dinamicamente
    where_clauses = []
    if search:
        where_clauses.append(
            "(COD_INTERNO ILIKE '%{0}%' OR INSUMO ILIKE '%{0}%')".format(search.replace("'", ""))
        )
    if coletor != "Todos":
        where_clauses.append(
            f"ELEMENTAR IN (SELECT ELEMENTAR FROM TB_VISUALIZADOR_COLETORES WHERE COLETOR = '{coletor}')"
        )
    if elementar != "Todos":
        where_clauses.append(f"ELEMENTAR = '{elementar}'")
    if job != "Todos":
        where_clauses.append(f"JOB = '{job}'")
    if project != "Todos":
        where_clauses.append(f"PROJETO = '{project}'")

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    # Conta total de itens
    count_sql = f"SELECT COUNT(*) AS CNT FROM TB_INSUMOS {where_sql}"
    total = session.sql(count_sql).to_pandas().iloc[0, 0]

    # Busca apenas a página atual
    offset = (page - 1) * per_page
    data_sql = f"""
      SELECT COD_INTERNO, INSUMO, ELEMENTAR, JOB, PROJETO
      FROM TB_INSUMOS
      {where_sql}
      ORDER BY COD_INTERNO
      LIMIT {per_page}
      OFFSET {offset}
    """
    df = session.sql(data_sql).to_pandas()
    return df, total

# ─────────── Carrega dados auxiliares ───────────
df_coletor_map = fetch_coletor_map()

for key in ("elementar", "job", "project"):
    if key not in st.session_state:
        st.session_state[key] = "Todos"

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

def clear_selection():
    for k in ("selected", "selected_nome", "selected_elementar"):
        st.session_state.pop(k, None)

# ─────────── Sidebar: busca + filtros ───────────
search            = st.sidebar.text_input("🔍 Buscar insumo ou código", key="search", on_change=lambda: st.session_state.pop("page", None))
selected_coletor  = st.sidebar.selectbox("🔽 Selecione Coletor", ["Todos"] + sorted(df_coletor_map["COLETOR"].dropna().unique()), key="coletor", on_change=lambda: st.session_state.pop("page", None))
elementar_opts = (
    ["Todos"]
    + sorted(
        session
        .table("TB_INSUMOS")
        .select("ELEMENTAR")
        .distinct()
        .to_pandas()["ELEMENTAR"]
        .dropna()
        .tolist()
    )
)
st.sidebar.selectbox(
    "🔽 Filtrar por Elementar",
    elementar_opts,
    key="elementar",
    on_change=lambda: st.session_state.pop("page", None)
)
job_opts = (
    ["Todos"]
    + sorted(
        session
        .table("TB_INSUMOS")
        .select("JOB")
        .distinct()
        .to_pandas()["JOB"]
        .dropna()
        .tolist()
    )
)
st.sidebar.selectbox(
    "🔽 Filtrar por Job",
    job_opts,
    key="job",
    on_change=lambda: st.session_state.pop("page", None)
)
project_opts = (
    ["Todos"]
    + sorted(
        session
        .table("TB_INSUMOS")
        .select("PROJETO")
        .distinct()
        .to_pandas()["PROJETO"]
        .dropna()
        .tolist()
    )
)
st.sidebar.selectbox(
    "🔽 Filtrar por Projeto",
    project_opts,
    key="project",
    on_change=lambda: st.session_state.pop("page", None)
)
# … demais selects (elementar, job, project) …
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
# ─────────── Paginação paginada no banco ───────────
per_page = 20
if "page" not in st.session_state:
    st.session_state.page = 1

page_df, total_items = fetch_meta_page(
    search=search,
    coletor=selected_coletor,
    elementar=st.session_state.elementar,
    job=st.session_state.job,
    project=st.session_state.project,
    page=st.session_state.page,
    per_page=per_page
)

total_pag = max(1, math.ceil(total_items / per_page))

# Navegação de páginas
def prev_page():
    st.session_state.page = max(1, st.session_state.page - 1)
def next_page():
    st.session_state.page = min(total_pag, st.session_state.page + 1)

col1, col2, col3 = st.columns([1,6,1])
with col1:
    st.button("← Anterior", on_click=prev_page, disabled=st.session_state.page <= 1)
with col2:
    start = (st.session_state.page - 1) * per_page + 1
    end   = min(start + per_page - 1, total_items)
    st.markdown(f"<center><b>Página {st.session_state.page} / {total_pag}</b><br><i>itens {start}–{end} de {total_items}</i></center>", unsafe_allow_html=True)
with col3:
    st.button("Próximo →", on_click=next_page, disabled=st.session_state.page >= total_pag)

st.write("---")

# ─────────── Renderiza botões com os 20 itens da página ───────────
cols = st.columns(3)
for i, row in page_df.iterrows():
    cod  = str(row["COD_INTERNO"])
    nome = row["INSUMO"]
    label = nome if len(nome) <= 20 else nome[:20] + "…"
    c = cols[i % 3]
    if c.button(f"{cod} – {label}", key=f"btn_{cod}", help=nome):
        st.session_state.selected = cod
        st.session_state.selected_nome = nome
        st.session_state.selected_elementar = row["ELEMENTAR"]
        st.session_state.selected_projeto = row["PROJETO"]

# ─────────── Abre diálogo se selecionado ───────────
if "selected" in st.session_state:
    show_insumo_dialog(
        st.session_state.selected,
        st.session_state.selected_nome,
        st.session_state.selected_elementar,
        st.session_state.selected_projeto
    )
