import sqlite3
import pandas as pd
import streamlit as st
import zipfile
import json
from pathlib import Path

# ==========================================
# CONFIGURAÇÕES E INJEÇÃO VISUAL (TEMA CM)
# ==========================================
st.set_page_config(page_title="Canteiro CM | ERP", page_icon="🏗️", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0B0A33; color: #EDEEF6; }
    [data-testid="stSidebar"] { background-color: #04032A; border-right: 1px solid #1D1C48; }
    .stButton > button[data-baseweb="button"] { background-color: #FE641C; color: white; border: none; border-radius: 6px; font-weight: 600; }
    .stButton > button[data-baseweb="button"]:hover { background-color: #E84E0C; }
    [data-testid="stVerticalBlock"] > [style*="flex-direction: column"] > [data-testid="stVerticalBlock"] { background-color: #12113C; border: 1px solid #28275A; border-radius: 8px; padding: 15px; }
    .stTabs [data-baseweb="tab-list"] { background-color: transparent; }
    .stTabs [data-baseweb="tab"] { color: #8E92AE; }
    .stTabs [aria-selected="true"] { color: #FE641C !important; border-bottom-color: #FE641C !important; }
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
            
    conn.commit()
    conn.close()

# ==========================================
# PLANILHAS DINÂMICAS COM DROPDOWNS
# ==========================================
def render_planilha_dinamica(tabela, titulo, instrucoes, colunas_moeda=None, colunas_opcoes=None, colunas_check=None):
    st.header(titulo)
    st.info(f"**Como usar:**\n{instrucoes}")
    
    conn = get_connection()
    try:
        df = pd.read_sql(f"SELECT * FROM {tabela}", conn)
    except:
        st.error(f"Erro ao carregar a tabela {tabela}.")
        return
    
    config = {}
    
    # 1. Configurar Colunas de Moeda (R$)
    if colunas_moeda:
        for col in colunas_moeda:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
                config[col] = st.column_config.NumberColumn(
                    f"{col.replace('_', ' ').title()}", 
                    format="R$ %.2f",
                    step=0.01
                )
                
    # 2. Configurar Menus Suspensos (Selectbox)
    if colunas_opcoes:
        for col, opcoes in colunas_opcoes.items():
            if col in df.columns:
                config[col] = st.column_config.SelectboxColumn(
                    f"{col.replace('_', ' ').title()}", 
                    options=opcoes,
                    required=True
                )
                
    # 3. Configurar Caixas de Seleção (Checkboxes para Sim/Não)
    if colunas_check:
        for col in colunas_check:
            if col in df.columns:
                # Converte strings legadas ('True', '1', etc) para booleano real
                df[col] = df[col].astype(str).str.lower().map({'true': True, '1': True, 'yes': True}).fillna(False)
                config[col] = st.column_config.CheckboxColumn(f"{col.replace('_', ' ').title()}")
    
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
    st.subheader("🗺️ Quadro Visual de Obras")
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
            st.markdown(f"<div style='text-align: center; color: #8E92AE; font-weight: 600; padding-bottom: 10px;'>{status.upper()}</div>", unsafe_allow_html=True)
            # Compatibilidade com status em letras minúsculas (legado)
            itens = df[df['status'].astype(str).str.lower() == status.lower()] if 'status' in df.columns else pd.DataFrame()
            
            for _, item in itens.iterrows():
                with st.container(border=True):
                    st.markdown(f"**🏗️ {item.get('codigo', 'OBRA')}**")
                    st.caption(f"{item.get('nome', '')}")

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
            st.markdown(f"<div style='background-color: #1A1948; padding: 5px; border-radius: 5px; text-align: center;'><b>📍 {str(obra).upper()}</b></div>", unsafe_allow_html=True)
            st.write("")
            equipamentos = df_locacoes[df_locacoes['obra_destino'] == obra]
            
            for _, eq in equipamentos.iterrows():
                with st.container(border=True):
                    st.markdown(f"**⚙️ {eq['equipamento']}**")
                    custo = float(eq.get('custo_diario', 0))
                    st.markdown(f"<span style='color: #FF8A4D;'>Diária: R$ {custo:,.2f}</span>", unsafe_allow_html=True)

def render_kanban_tarefas():
    st.subheader("✅ Acompanhamento de Pendências")
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM tarefas", conn)
    conn.close()
    
    if df.empty:
        return

    status_list = ["Pendente", "Em andamento", "Aguardando retorno", "Concluída"]
    cols = st.columns(len(status_list))
    
    for i, status in enumerate(status_list):
        with cols[i]:
            st.markdown(f"<div style='text-align: center; color: #8E92AE; font-weight: 600; padding-bottom: 10px;'>{status.upper()}</div>", unsafe_allow_html=True)
            itens = df[df['status'].astype(str).str.lower().str.contains(status.lower().split()[0])] if 'status' in df.columns else pd.DataFrame()
            
            for _, item in itens.iterrows():
                with st.container(border=True):
                    prio = item.get('prioridade', '').lower()
                    cor_prio = "red" if prio == "alta" else "orange" if prio == "media" else "gray"
                    st.markdown(f"<span style='color: {cor_prio}; font-size: 10px;'>● {prio.upper()}</span>", unsafe_allow_html=True)
                    st.markdown(f"**{item.get('titulo', 'Tarefa')}**")
                    st.caption(f"Resp: {item.get('responsavel', 'Não definido')}")

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
            render_planilha_dinamica("equipe", "Equipe", "Adicione os funcionários na última linha. Marque a caixa 'Ativo' para quem está trabalhando.", colunas_moeda=["salario_base", "extras", "custo_mensal"], colunas_check=["ativo"])
        with tab2:
            render_planilha_dinamica("cargos", "Tabela de Cargos", "Defina o piso salarial para cada cargo da empresa.", colunas_moeda=["salario_base", "extras"])

    elif menu == "📅 Calendário de Alocação":
        st.header("📅 Calendário de Alocação")
        st.warning("⚠️ Módulo em desenvolvimento. O cruzamento visual de dias e obras será ativado na próxima atualização.")

    elif menu == "🏗️ Pipeline de Obras":
        tab1, tab2 = st.tabs(["Kanban Visual", "Tabela de Gestão"])
        with tab1:
            render_kanban_obras()
        with tab2:
            render_planilha_dinamica(
                "obras", 
                "Gerenciamento de Obras", 
                "1. Adicione a obra na última linha.\n2. Escolha o Regime e Status nos menus suspensos para que elas apareçam no Kanban.", 
                colunas_moeda=["fee_mensal", "orcamento"],
                colunas_opcoes={
                    "status": ["Prospecção", "Proposta", "Em execução", "Paralisada", "Concluída"],
                    "regime": ["Administração", "Empreitada", "Outro"]
                }
            )

    elif menu == "🚜 CM Rental (Equipamentos)":
        tab1, tab2, tab3 = st.tabs(["Obras (Kanban)", "Despachos / Locações", "Estoque (Patrimônio)"])
        with tab1:
            render_kanban_cm_rental()
        with tab2:
            render_planilha_dinamica(
                "locacoes", 
                "Controle de Locações", 
                "Para enviar uma máquina para a obra, digite o nome dela, selecione a obra e coloque o Status como 'Ativa'. Quando voltar, mude para 'Devolvida'.", 
                colunas_moeda=["custo_diario", "valor_total"],
                colunas_opcoes={"status": ["Ativa", "Devolvida"]}
            )
        with tab3:
            render_planilha_dinamica(
                "patrimonio", 
                "Patrimônio e Frota", 
                "Cadastre novas máquinas aqui. Selecione 'CM Rental' na origem se for sua, ou 'Terceirizado' se for alugada de outra empresa.", 
                colunas_moeda=["valor_compra", "diaria_padrao"],
                colunas_opcoes={
                    "origem": ["CM Rental (Próprio)", "Terceirizado (LocExpress, etc)"],
                    "status": ["Operacional", "Em Manutenção", "Quebrado", "Baixado"]
                }
            )

    elif menu == "💸 Custos de Material":
        st.header("Lançamento de Custos e NFs")
        st.info("**Automação de NFs:** No futuro, integraremos uma Inteligência Artificial para ler os PDFs. Por enquanto, solte o arquivo abaixo para guardar o anexo, e preencha os dados manualmente na tabela.")
        
        with st.container(border=True):
            nf_files = st.file_uploader("📥 Arraste as Notas Fiscais aqui (PDF/JPG) para arquivamento", accept_multiple_files=True)
            if nf_files:
                st.success("Arquivos retidos em memória!")
                
        st.divider()
        conn = get_connection()
        obras_df = pd.read_sql("SELECT codigo FROM obras", conn)
        conn.close()
        lista_obras = obras_df['codigo'].tolist() if not obras_df.empty else ["Sem Obra"]

        render_planilha_dinamica(
            "custos", 
            "Tabela de Despesas", 
            "Lance o valor da nota, selecione a Obra onde foi gasto, a Etapa e marque as caixas se possui NF e se é reembolso.", 
            colunas_moeda=["valor"],
            colunas_check=["nf", "reembolso_cm"],
            colunas_opcoes={
                "obra_id": lista_obras,
                "etapa": ["Alimentação", "Concreto", "EPI", "Estrutura", "Fôrmas", "Hidráulica", "Elétrica", "Locação", "Mão de Obra", "Transporte", "Outros"]
            }
        )

    elif menu == "📊 Boletim de Medição":
        st.header("📊 Boletim de Medição")
        st.info("Aguardando o fechamento das rotinas de Custo. Painel será ativado em breve.")

    elif menu == "📈 Resultados da CM":
        st.header("📈 Resultados da CM")
        st.info("Painel de DRE em desenvolvimento.")

    elif menu == "🤝 Pipeline de Negócios":
        render_planilha_dinamica(
            "oportunidades", 
            "CRM e Orçamentos", 
            "Acompanhe suas propostas comerciais mudando o Estágio.", 
            colunas_moeda=["valor_estimado"],
            colunas_opcoes={
                "estagio": ["Prospecção", "Estudo/Orçamento", "Proposta Enviada", "Em Negociação", "Contrato Fechado", "Ganha", "Perdida"],
                "tipo": ["Residencial", "Licitação", "Incorporação", "Reforma", "Outro"]
            }
        )

    elif menu == "✅ Pendências da Equipe":
        render_kanban_tarefas()
        st.divider()
        render_planilha_dinamica(
            "tarefas", 
            "Gestão de Tarefas", 
            "Atribua uma prioridade, escreva quem é o responsável e atualize o Status para mover o cartão no Kanban acima.",
            colunas_opcoes={
                "prioridade": ["Alta", "Media", "Baixa"],
                "status": ["Pendente", "Em andamento", "Aguardando retorno", "Concluída"]
            }
        )

if __name__ == "__main__":
    main()
