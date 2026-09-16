import sqlite3
import pandas as pd
import streamlit as st
import zipfile
import json
from pathlib import Path
from datetime import date

# ==========================================
# CONFIGURAÇÕES E INJEÇÃO VISUAL (TEMA CM)
# ==========================================
st.set_page_config(page_title="Canteiro CM | ERP", page_icon="🏗️", layout="wide")

# CSS Customizado para espelhar a identidade visual do vídeo
st.markdown("""
    <style>
    /* Força o fundo escuro e tipografia do Canteiro CM */
    .stApp {
        background-color: #0B0A33;
        color: #EDEEF6;
    }
    /* Estilização da Sidebar */
    [data-testid="stSidebar"] {
        background-color: #04032A;
        border-right: 1px solid #1D1C48;
    }
    /* Botões Primários no tom Laranja CM */
    .stButton > button[data-baseweb="button"] {
        background-color: #FE641C;
        color: white;
        border: none;
        border-radius: 6px;
        font-weight: 600;
    }
    .stButton > button[data-baseweb="button"]:hover {
        background-color: #E84E0C;
    }
    /* Estilização dos Containers/Cartões Kanban */
    [data-testid="stVerticalBlock"] > [style*="flex-direction: column"] > [data-testid="stVerticalBlock"] {
        background-color: #12113C;
        border: 1px solid #28275A;
        border-radius: 8px;
        padding: 15px;
    }
    /* Ajuste de abas */
    .stTabs [data-baseweb="tab-list"] {
        background-color: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        color: #8E92AE;
    }
    .stTabs [aria-selected="true"] {
        color: #FE641C !important;
        border-bottom-color: #FE641C !important;
    }
    </style>
""", unsafe_allow_html=True)

DB_PATH = Path(__file__).resolve().parent / "cm_erp_v2.db"

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    tabelas = {
        "cargos": ["id", "nome", "abrev", "salario_base", "extras", "ordem"],
        "equipe": ["id", "nome", "funcao", "salario_base", "extras", "custo_mensal", "ativo"],
        "obras": ["id", "codigo", "nome", "cliente", "status", "regime", "fee_mensal", "orcamento"],
        "oportunidades": ["id", "nome", "cliente", "tipo", "estagio", "valor_estimado", "probabilidade"],
        "tarefas": ["id", "titulo", "responsavel", "prioridade", "status", "prazo", "descricao"],
        "custos": ["id", "obra_id", "data", "etapa", "fornecedor", "nf", "reembolso_cm", "valor", "descricao"],
        "locacoes": ["id", "equipamento", "obra_destino", "data_retirada", "data_devolucao", "custo_diario", "status", "valor_total"],
        "patrimonio": ["id", "equipamento", "origem", "status", "valor_compra", "diaria_padrao"]
    }
    
    for tabela, colunas in tabelas.items():
        try:
            df_existente = pd.read_sql(f"SELECT * FROM {tabela} LIMIT 1", conn)
            colunas_existentes = df_existente.columns.tolist()
            for col in colunas:
                if col not in colunas_existentes:
                    conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {col} TEXT")
        except:
            df_vazio = pd.DataFrame(columns=colunas)
            df_vazio.to_sql(tabela, conn, if_exists="replace", index=False)
            
    tabelas_historico = ["historico_alocacoes", "historico_medicoes", "historico_resultados", "historico_creditos", "historico_config"]
    for th in tabelas_historico:
        conn.execute(f"CREATE TABLE IF NOT EXISTS {th} (id TEXT PRIMARY KEY, dados_json TEXT)")
        
    conn.commit()
    conn.close()

# ==========================================
# PLANILHAS E FORMATAÇÃO R$
# ==========================================
def render_planilha_dinamica(tabela, titulo, subtitulo, colunas_moeda=None):
    st.header(titulo)
    st.write(subtitulo)
    
    conn = get_connection()
    try:
        df = pd.read_sql(f"SELECT * FROM {tabela}", conn)
    except:
        st.error(f"Erro ao carregar a tabela {tabela}.")
        return
    
    config = {}
    if colunas_moeda:
        for col in colunas_moeda:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
                config[col] = st.column_config.NumberColumn(
                    f"{col.replace('_', ' ').title()}", 
                    format="R$ %.2f",
                    step=0.01
                )
    
    df_editado = st.data_editor(df, num_rows="dynamic", use_container_width=True, column_config=config, key=f"editor_{tabela}")
    
    if st.button(f"💾 Salvar alterações em {titulo}", type="primary"):
        df_editado.to_sql(tabela, conn, if_exists="replace", index=False)
        st.success("Tabela atualizada com sucesso!")
        st.rerun()
    conn.close()

# ==========================================
# VISUALIZADORES KANBAN
# ==========================================
def render_kanban_obras():
    st.subheader("🗺️ Funil de Obras")
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM obras", conn)
    conn.close()
    
    if df.empty:
        st.warning("Nenhuma obra encontrada.")
        return

    status_list = ["Prospecção", "Proposta", "Em execução", "Paralisada", "Concluída"]
    cols = st.columns(len(status_list))
    
    for i, status in enumerate(status_list):
        with cols[i]:
            # Cabeçalho da coluna
            st.markdown(f"<div style='text-align: center; color: #8E92AE; font-weight: 600; padding-bottom: 10px;'>{status.upper()}</div>", unsafe_allow_html=True)
            itens = df[df['status'].str.lower() == status.lower()] if 'status' in df.columns else pd.DataFrame()
            
            for _, item in itens.iterrows():
                with st.container(border=True):
                    st.markdown(f"**🏗️ {item.get('codigo', 'OBRA')}**")
                    st.caption(f"{item.get('nome', '')}")
                    orcamento = float(item.get('orcamento', 0))
                    if orcamento > 0:
                        st.markdown(f"<span style='color: #5CBB8B; font-weight: bold;'>R$ {orcamento:,.2f}</span>", unsafe_allow_html=True)

def render_kanban_cm_rental():
    st.subheader("🚜 Equipamentos Locados por Obra")
    conn = get_connection()
    df_locacoes = pd.read_sql("SELECT * FROM locacoes WHERE status != 'Devolvida'", conn)
    conn.close()
    
    if df_locacoes.empty:
        st.info("Nenhuma locação ativa no momento.")
        return

    obras_destino = df_locacoes['obra_destino'].dropna().unique()
    if len(obras_destino) == 0:
        return
        
    cols = st.columns(min(len(obras_destino), 4))
    
    for i, obra in enumerate(obras_destino):
        col_index = i % 4
        with cols[col_index]:
            st.markdown(f"<div style='background-color: #1A1948; padding: 5px; border-radius: 5px; text-align: center;'><b>📍 {obra.upper()}</b></div>", unsafe_allow_html=True)
            st.write("")
            equipamentos = df_locacoes[df_locacoes['obra_destino'] == obra]
            
            for _, eq in equipamentos.iterrows():
                with st.container(border=True):
                    st.markdown(f"**⚙️ {eq['equipamento']}**")
                    st.caption(f"De: {eq.get('data_retirada', 'N/A')} Até: {eq.get('data_devolucao', 'N/A')}")
                    custo = float(eq.get('custo_diario', 0))
                    st.markdown(f"<span style='color: #FF8A4D;'>Diária: R$ {custo:,.2f}</span>", unsafe_allow_html=True)

# ==========================================
# MÓDULOS DE NEGÓCIO ATIVADOS
# ==========================================
def modulo_calendario():
    st.header("📅 Calendário de Alocação")
    st.write("Grade de alocação de equipe por obra. Edite as células para direcionar a equipe.")
    
    conn = get_connection()
    df_equipe = pd.read_sql("SELECT id, nome, funcao FROM equipe WHERE ativo = 'True' OR ativo = '1'", conn)
    df_obras = pd.read_sql("SELECT codigo FROM obras WHERE status = 'Em execução'", conn)
    conn.close()
    
    if df_equipe.empty or df_obras.empty:
        st.info("É necessário ter equipe ativa e obras em execução.")
        return

    # Gerando Grade Dinâmica de Alocação (Seg a Sex fictício para controle)
    opcoes_obras = ["Escritório / Base", "Falta", "Férias"] + df_obras['codigo'].tolist()
    
    df_alocacao = pd.DataFrame({
        "Funcionário": df_equipe['nome'],
        "Função": df_equipe['funcao'],
        "Segunda": ["Escritório / Base"] * len(df_equipe),
        "Terça": ["Escritório / Base"] * len(df_equipe),
        "Quarta": ["Escritório / Base"] * len(df_equipe),
        "Quinta": ["Escritório / Base"] * len(df_equipe),
        "Sexta": ["Escritório / Base"] * len(df_equipe),
    })

    st.data_editor(
        df_alocacao,
        column_config={
            "Segunda": st.column_config.SelectboxColumn("Segunda", options=opcoes_obras),
            "Terça": st.column_config.SelectboxColumn("Terça", options=opcoes_obras),
            "Quarta": st.column_config.SelectboxColumn("Quarta", options=opcoes_obras),
            "Quinta": st.column_config.SelectboxColumn("Quinta", options=opcoes_obras),
            "Sexta": st.column_config.SelectboxColumn("Sexta", options=opcoes_obras),
        },
        hide_index=True,
        use_container_width=True
    )

def modulo_boletim():
    st.header("📊 Boletim de Medição")
    st.write("Apuração automática de materiais e equipamentos por obra.")
    
    conn = get_connection()
    obras = pd.read_sql("SELECT id, codigo, nome, fee_mensal FROM obras WHERE status = 'Em execução'", conn)
    
    if obras.empty:
        st.warning("Nenhuma obra em execução.")
        conn.close()
        return

    obra_sel_nome = st.selectbox("Selecione a Obra para gerar a medição", obras['codigo'] + " - " + obras['nome'])
    obra_sel_id = str(obras[obras['codigo'] + " - " + obras['nome'] == obra_sel_nome]['id'].values[0])
    fee_mensal = float(obras[obras['codigo'] + " - " + obras['nome'] == obra_sel_nome]['fee_mensal'].values[0] or 0)
    codigo_obra = obra_sel_nome.split(" - ")[0]

    df_custos = pd.read_sql(f"SELECT SUM(valor) as total FROM custos WHERE obra_id = '{obra_sel_id}' OR obra_id = '{codigo_obra}'", conn)
    total_materiais = float(df_custos['total'].iloc[0] or 0)
    
    df_loc = pd.read_sql(f"SELECT SUM(valor_total) as total FROM locacoes WHERE obra_destino = '{obra_sel_id}' OR obra_destino = '{codigo_obra}'", conn)
    total_locacoes = float(df_loc['total'].iloc[0] or 0)

    base_incidencia = total_materiais + total_locacoes + fee_mensal
    taxa_admin = base_incidencia * 0.12 
    total_medicao = base_incidencia + taxa_admin

    col1, col2, col3 = st.columns(3)
    col1.metric("Materiais e Serviços", f"R$ {total_materiais:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    col2.metric("Equipamentos CM Rental", f"R$ {total_locacoes:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    col3.metric("Fee Mensal", f"R$ {fee_mensal:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    
    st.divider()
    st.markdown(f"### **Total da Medição:** <span style='color: #FE641C;'>R$ {total_medicao:,.2f}</span>", unsafe_allow_html=True)
    st.caption(f"Base (R$ {base_incidencia:,.2f}) + Administração 12% (R$ {taxa_admin:,.2f})")
    
    conn.close()

def modulo_resultados():
    st.header("📈 Resultados da CM (DRE Simplificado)")
    
    conn = get_connection()
    df_c = pd.read_sql("SELECT SUM(valor) as t FROM custos", conn)
    df_l = pd.read_sql("SELECT SUM(valor_total) as t FROM locacoes", conn)
    
    c_tot = float(df_c['t'].iloc[0] or 0)
    l_tot = float(df_l['t'].iloc[0] or 0)
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("<div style='background-color:#12113C; padding: 20px; border-radius: 8px;'>", unsafe_allow_html=True)
        st.subheader("Custos Operacionais")
        st.markdown(f"<h2 style='color:#E2796D;'>R$ {c_tot:,.2f}</h2>", unsafe_allow_html=True)
        st.caption("Total de saídas registradas.")
        st.markdown("</div>", unsafe_allow_html=True)
        
    with col2:
        st.markdown("<div style='background-color:#12113C; padding: 20px; border-radius: 8px;'>", unsafe_allow_html=True)
        st.subheader("Faturamento CM Rental")
        st.markdown(f"<h2 style='color:#5CBB8B;'>R$ {l_tot:,.2f}</h2>", unsafe_allow_html=True)
        st.caption("Receita bruta de locações.")
        st.markdown("</div>", unsafe_allow_html=True)
        
    conn.close()

# ==========================================
# MENUS E NAVEGAÇÃO
# ==========================================
def main():
    init_db()
    
    st.sidebar.markdown(f"<h2 style='color: #FE641C; font-family: sans-serif; font-weight: bold;'>Canteiro CM</h2>", unsafe_allow_html=True)
    st.sidebar.caption("Obras por administração & Gestão de Frotas")
    st.sidebar.divider()
    
    menu = st.sidebar.radio(
        "Módulos do Sistema",
        [
            "👥 Equipe",
            "📅 Calendário de Alocação",
            "🏗️ Pipeline de Obras",
            "🚜 CM Rental (Equipamentos)",
            "💸 Custos de Material",
            "📊 Boletim de Medição",
            "📈 Resultados da CM",
            "🤝 Pipeline de Negócios",
            "✅ Pendências da Equipe"
        ]
    )

    if menu == "👥 Equipe":
        tab1, tab2 = st.tabs(["Funcionários", "Cargos e Níveis"])
        with tab1:
            render_planilha_dinamica("equipe", "Equipe", "", colunas_moeda=["salario_base", "extras", "custo_mensal"])
        with tab2:
            render_planilha_dinamica("cargos", "Tabela de Cargos", "", colunas_moeda=["salario_base", "extras"])

    elif menu == "📅 Calendário de Alocação":
        modulo_calendario()

    elif menu == "🏗️ Pipeline de Obras":
        tab1, tab2 = st.tabs(["Kanban Visual", "Tabela de Gestão"])
        with tab1:
            render_kanban_obras()
        with tab2:
            render_planilha_dinamica("obras", "Gerenciamento de Obras", "Crie, edite ou apague obras.", colunas_moeda=["fee_mensal", "orcamento"])

    elif menu == "🚜 CM Rental (Equipamentos)":
        tab1, tab2, tab3 = st.tabs(["Obras (Kanban)", "Despachos e Locações", "Estoque"])
        with tab1:
            render_kanban_cm_rental()
        with tab2:
            render_planilha_dinamica("locacoes", "Adicionar / Remover Locações", "Use a tabela para gerenciar onde os equipamentos estão.", colunas_moeda=["custo_diario", "valor_total"])
        with tab3:
            render_planilha_dinamica("patrimonio", "Patrimônio", "Cadastre novas máquinas.", colunas_moeda=["valor_compra", "diaria_padrao"])

    elif menu == "💸 Custos de Material":
        st.header("Lançamento de Custos e NFs")
        
        # Área de Drag & Drop para Notas Fiscais
        with st.container(border=True):
            nf_files = st.file_uploader("📥 Arraste e solte as Notas Fiscais / Recibos aqui (PDF, JPG, PNG, XML)", accept_multiple_files=True)
            if nf_files:
                st.success(f"{len(nf_files)} arquivo(s) carregado(s) temporariamente no sistema!")
                
        st.divider()
        render_planilha_dinamica("custos", "Tabela de Custos", "Lance os valores relacionados às notas fiscais enviadas.", colunas_moeda=["valor"])

    elif menu == "📊 Boletim de Medição":
        modulo_boletim()

    elif menu == "📈 Resultados da CM":
        modulo_resultados()

    elif menu == "🤝 Pipeline de Negócios":
        render_planilha_dinamica("oportunidades", "CRM e Orçamentos", "Gerencie suas oportunidades futuras.", colunas_moeda=["valor_estimado"])

    elif menu == "✅ Pendências da Equipe":
        render_planilha_dinamica("tarefas", "Gestão de Tarefas", "Defina prioridades e cobre responsáveis.")

if __name__ == "__main__":
    main()
