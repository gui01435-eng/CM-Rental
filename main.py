import sqlite3
import pandas as pd
import streamlit as st
import zipfile
import json
from pathlib import Path

# ==========================================
# CONFIGURAÇÕES E BANCO DE DADOS
# ==========================================
st.set_page_config(page_title="CM ERP | Gestão Completa", page_icon="🏗️", layout="wide")

DB_PATH = Path(__file__).resolve().parent / "cm_erp_v2.db"

def get_connection():
    return sqlite3.connect(DB_PATH)

# ==========================================
# MOTOR DE PLANILHAS (COM MOEDA R$)
# ==========================================
def render_planilha_dinamica(tabela, titulo, subtitulo, colunas_moeda=None):
    st.header(titulo)
    st.write(subtitulo)
    st.info("💡 Edite clicando nas células. Adicione novas linhas na base da tabela. Selecione e aperte 'Delete' para excluir.")
    
    conn = get_connection()
    try:
        df = pd.read_sql(f"SELECT * FROM {tabela}", conn)
    except:
        st.error(f"Erro ao carregar a tabela {tabela}. Verifique a importação.")
        return
    
    # Configurar colunas de moeda para aparecer com R$
    config = {}
    if colunas_moeda:
        for col in colunas_moeda:
            if col in df.columns:
                # Converte para numérico caso o importador tenha trazido como texto
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
                config[col] = st.column_config.NumberColumn(f"{col.replace('_', ' ').title()}", format="R$ %.2f")
    
    df_editado = st.data_editor(df, num_rows="dynamic", use_container_width=True, column_config=config, key=f"editor_{tabela}")
    
    if st.button(f"💾 Salvar alterações em {titulo}", type="primary", key=f"btn_{tabela}"):
        df_editado.to_sql(tabela, conn, if_exists="replace", index=False)
        st.success("Banco de dados atualizado com sucesso!")
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
        st.warning("Nenhuma obra cadastrada ainda.")
        return

    status_list = ["Prospecção", "Proposta", "Em execução", "Paralisada", "Concluída"]
    cols = st.columns(len(status_list))
    
    for i, status in enumerate(status_list):
        with cols[i]:
            st.markdown(f"**{status.upper()}**")
            # Usa str.contains ou == ignorando case para evitar erros de importação
            itens = df[df['status'].str.lower() == status.lower()] if 'status' in df.columns else pd.DataFrame()
            
            for _, item in itens.iterrows():
                with st.container(border=True):
                    st.markdown(f"**🏗️ {item.get('codigo', 'SEM COD')}**")
                    st.caption(f"{item.get('nome', '')}")
                    orcamento = float(item.get('orcamento', 0))
                    if orcamento > 0:
                        st.write(f"R$ {orcamento:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

def render_kanban_cm_rental():
    st.subheader("🚜 Equipamentos Locados por Obra (Visão Kanban)")
    conn = get_connection()
    df_locacoes = pd.read_sql("SELECT * FROM locacoes WHERE status != 'Devolvida'", conn)
    conn.close()
    
    if df_locacoes.empty:
        st.info("Nenhuma locação ativa no momento.")
        return

    obras_destino = df_locacoes['obra_destino'].dropna().unique()
    if len(obras_destino) == 0:
        return
        
    cols = st.columns(min(len(obras_destino), 4)) # Máximo de 4 colunas por linha para não esmagar
    
    for i, obra in enumerate(obras_destino):
        col_index = i % 4
        with cols[col_index]:
            st.markdown(f"**📍 OBRA: {obra.upper()}**")
            equipamentos = df_locacoes[df_locacoes['obra_destino'] == obra]
            
            for _, eq in equipamentos.iterrows():
                with st.container(border=True):
                    st.markdown(f"**⚙️ {eq['equipamento']}**")
                    st.caption(f"Retirada: {eq.get('data_retirada', 'N/A')}")
                    custo = float(eq.get('custo_diario', 0))
                    st.write(f"Diária: R$ {custo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

# ==========================================
# MÓDULOS DE NEGÓCIO
# ==========================================
def modulo_boletim():
    st.header("📊 Boletim de Medição Automatizado")
    st.write("Consolida os dados das obras em execução diretamente das tabelas de custos e locações.")
    
    conn = get_connection()
    obras = pd.read_sql("SELECT id, codigo, nome, fee_mensal FROM obras WHERE status = 'Em execução'", conn)
    
    if obras.empty:
        st.warning("Nenhuma obra marcada como 'Em execução' no Pipeline de Obras.")
        conn.close()
        return

    obra_sel_nome = st.selectbox("Selecione a Obra para gerar a medição", obras['codigo'] + " - " + obras['nome'])
    obra_sel_id = obras[obras['codigo'] + " - " + obras['nome'] == obra_sel_nome]['id'].values[0]
    fee_mensal = float(obras[obras['codigo'] + " - " + obras['nome'] == obra_sel_nome]['fee_mensal'].values[0] or 0)
    codigo_obra = obra_sel_nome.split(" - ")[0]

    st.divider()
    
    # Buscar Custos da Obra
    df_custos = pd.read_sql(f"SELECT SUM(valor) as total FROM custos WHERE obra_id = '{obra_sel_id}' OR obra_id = '{codigo_obra}'", conn)
    total_materiais = float(df_custos['total'].iloc[0] or 0)
    
    # Buscar Locações da Obra (CM Rental)
    df_loc = pd.read_sql(f"SELECT SUM(valor_total) as total FROM locacoes WHERE obra_destino = '{obra_sel_id}' OR obra_destino = '{codigo_obra}'", conn)
    total_locacoes = float(df_loc['total'].iloc[0] or 0)

    # DRE Simplificado da Medição
    base_incidencia = total_materiais + total_locacoes + fee_mensal
    taxa_admin = base_incidencia * 0.12 # 12% Padrão da CM
    total_medicao = base_incidencia + taxa_admin

    col1, col2, col3 = st.columns(3)
    col1.metric("Materiais e Serviços", f"R$ {total_materiais:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    col2.metric("Equipamentos CM Rental", f"R$ {total_locacoes:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    col3.metric("Fee Mensal", f"R$ {fee_mensal:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    
    st.markdown("### Resumo de Faturamento")
    st.info(f"**Base de Incidência:** R$ {base_incidencia:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    st.success(f"**Administração (12%):** R$ {taxa_admin:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    st.error(f"**TOTAL DA MEDIÇÃO:** R$ {total_medicao:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    
    conn.close()

def modulo_calendario():
    st.header("📅 Calendário de Alocação (Resumo)")
    st.write("Cruzamento de pessoal ativo vs Obras em andamento.")
    
    conn = get_connection()
    df_equipe = pd.read_sql("SELECT nome, funcao FROM equipe WHERE ativo = 'True' OR ativo = '1'", conn)
    df_obras = pd.read_sql("SELECT codigo, nome FROM obras WHERE status = 'Em execução'", conn)
    conn.close()
    
    if df_equipe.empty or df_obras.empty:
        st.info("É necessário ter equipe ativa e obras em execução para montar a matriz.")
        return

    # Cria uma matriz visual falsa para planejamento
    st.write("### Equipe Disponível para Alocação")
    cols = st.columns(3)
    for i, row in df_equipe.iterrows():
        with cols[i % 3]:
            st.markdown(f"👤 **{row['nome']}**")
            st.caption(f"Cargo: {row['funcao']}")
            st.selectbox(f"Alocar {row['nome'].split()[0]} em:", ["Escritório / Base"] + df_obras['codigo'].tolist(), key=f"aloc_{i}")

# ==========================================
# MENUS E NAVEGAÇÃO DO ERP
# ==========================================
def main():
    st.sidebar.image("https://via.placeholder.com/150x50.png?text=CM+Engenharia", use_container_width=True)
    st.sidebar.markdown("### Canteiro CM")
    st.sidebar.caption("Obras por administração & Gestão de Frotas")
    st.sidebar.divider()
    
    menu = st.sidebar.radio(
        "Módulos do Sistema",
        [
            "👥 Equipe e Cargos",
            "📅 Calendário de Alocação",
            "🏗️ Pipeline de Obras",
            "🚜 CM Rental (Equipamentos)",
            "💸 Custos de Material (com NF)",
            "📊 Boletim de Medição",
            "📈 Resultados da CM",
            "🤝 Pipeline de Negócios (CRM)",
            "✅ Pendências da Equipe"
        ]
    )

    if menu == "👥 Equipe e Cargos":
        render_planilha_dinamica("equipe", "Gestão de Equipe", "Administre funcionários e custos de folha.", colunas_moeda=["salario_base", "extras", "custo_mensal"])
        st.divider()
        render_planilha_dinamica("cargos", "Tabela de Cargos e Níveis", "Piso salarial da empresa.", colunas_moeda=["salario_base", "extras"])

    elif menu == "📅 Calendário de Alocação":
        modulo_calendario()

    elif menu == "🏗️ Pipeline de Obras":
        render_kanban_obras()
        st.divider()
        render_planilha_dinamica("obras", "Gestão de Obras", "Edite os detalhes, status e orçamentos abaixo.", colunas_moeda=["fee_mensal", "orcamento"])

    elif menu == "🚜 CM Rental (Equipamentos)":
        render_kanban_cm_rental()
        st.divider()
        tab1, tab2 = st.tabs(["Locações e Despachos", "Estoque e Patrimônio"])
        with tab1:
            render_planilha_dinamica("locacoes", "Painel de Locações", "Adicione, edite ou exclua locações. Marque o status como 'Devolvida' para retirar da obra.", colunas_moeda=["custo_diario", "valor_total"])
        with tab2:
            render_planilha_dinamica("patrimonio", "Patrimônio e Frota", "Gerencie o valor investido nas máquinas.", colunas_moeda=["valor_compra", "diaria_padrao"])

    elif menu == "💸 Custos de Material (com NF)":
        st.header("Lançamento Rápido de Notas")
        with st.container(border=True):
            # NOVO: Zona de Drag and Drop para Notas Fiscais
            nf_files = st.file_uploader("📥 Arraste e solte as Notas Fiscais / Recibos aqui (PDF, JPG, PNG, XML)", accept_multiple_files=True)
            if nf_files:
                st.success(f"{len(nf_files)} arquivo(s) carregado(s) e pronto(s) para anexo!")
            
        st.divider()
        render_planilha_dinamica("custos", "Histórico de Custos e Despesas", "Edite e faça a conciliação financeira abaixo.", colunas_moeda=["valor"])

    elif menu == "📊 Boletim de Medição":
        modulo_boletim()

    elif menu == "📈 Resultados da CM":
        st.header("Resultados e DRE da Empresa")
        st.write("Visão consolidada de todas as operações.")
        conn = get_connection()
        df_c = pd.read_sql("SELECT SUM(valor) as t FROM custos", conn)
        df_l = pd.read_sql("SELECT SUM(valor_total) as t FROM locacoes", conn)
        conn.close()
        
        c_tot = float(df_c['t'].iloc[0] or 0)
        l_tot = float(df_l['t'].iloc[0] or 0)
        
        st.metric("Total de Custos de Obra Registrados", f"R$ {c_tot:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        st.metric("Total Faturado pela CM Rental", f"R$ {l_tot:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        st.info("Para uma visão analítica profunda de rentabilidade mês a mês, assegure-se de realizar o fechamento dos Boletins de Medição.")

    elif menu == "🤝 Pipeline de Negócios (CRM)":
        st.subheader("🎯 Oportunidades Comerciais")
        # Visual simples antes da tabela
        conn = get_connection()
        df_opp = pd.read_sql("SELECT * FROM oportunidades", conn)
        conn.close()
        if not df_opp.empty and 'estagio' in df_opp.columns:
            st.bar_chart(df_opp['estagio'].value_counts())
        
        st.divider()
        render_planilha_dinamica("oportunidades", "Gestão de Leads", "Acompanhe orçamentos e licitações.", colunas_moeda=["valor_estimado"])

    elif menu == "✅ Pendências da Equipe":
        render_planilha_dinamica("tarefas", "Gestão de Tarefas", "Defina prioridades e cobre responsáveis.")

if __name__ == "__main__":
    main()
