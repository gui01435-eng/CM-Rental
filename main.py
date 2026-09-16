import sqlite3
import pandas as pd
import streamlit as st
from datetime import date
from pathlib import Path

# ==========================================
# CONFIGURAÇÕES E BANCO DE DADOS
# ==========================================
st.set_page_config(page_title="Canteiro CM | ERP Completo", page_icon="🏗️", layout="wide")

DB_PATH = Path(__file__).resolve().parent / "canteiro_cm.db"

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    # Criar tabelas básicas para o data_editor gerenciar dinamicamente
    tabelas = {
        "equipe": ["id", "nome", "funcao", "salario_base", "extras", "custo_mensal", "ativo"],
        "obras": ["id", "codigo", "nome", "cliente", "status", "regime", "fee_mensal", "orcamento"],
        "oportunidades": ["id", "nome", "cliente", "tipo", "estagio", "valor_estimado", "probabilidade"],
        "tarefas": ["id", "titulo", "responsavel", "prioridade", "status", "prazo", "descricao"],
        "custos": ["id", "obra_id", "data", "etapa", "fornecedor", "nf", "reembolso_cm", "valor", "descricao"],
        "locacoes": ["id", "equipamento", "obra_destino", "data_retirada", "data_devolucao", "custo_diario", "status"],
        "patrimonio": ["id", "equipamento", "origem", "status", "valor_compra", "diaria_padrao"]
    }
    
    for tabela, colunas in tabelas.items():
        try:
            pd.read_sql(f"SELECT * FROM {tabela} LIMIT 1", conn)
        except:
            # Se a tabela não existir, cria um DataFrame vazio e salva no SQL
            df_vazio = pd.DataFrame(columns=colunas)
            df_vazio.to_sql(tabela, conn, if_exists="replace", index=False)
    conn.close()

# ==========================================
# FUNÇÕES DE INTERFACE (CRUD DINÂMICO)
# ==========================================
def render_planilha_dinamica(tabela, titulo, subtitulo):
    st.header(titulo)
    st.write(subtitulo)
    st.info("💡 Dica: Dê um duplo clique na célula para editar. Use a linha vazia no final para adicionar novos registros. Selecione a linha e aperte 'Delete' para apagar.")
    
    conn = get_connection()
    df = pd.read_sql(f"SELECT * FROM {tabela}", conn)
    
    # Editor de dados interativo (Substitui os formulários complexos do JS)
    df_editado = st.data_editor(df, num_rows="dynamic", use_container_width=True, key=f"editor_{tabela}")
    
    if st.button(f"💾 Salvar alterações em {titulo}", type="primary"):
        df_editado.to_sql(tabela, conn, if_exists="replace", index=False)
        st.success("Banco de dados atualizado com sucesso!")
        st.rerun()
    conn.close()

# ==========================================
# MENUS E NAVEGAÇÃO DO ERP
# ==========================================
def main():
    init_db()
    
    st.sidebar.image("https://via.placeholder.com/150x50.png?text=CM+Engenharia", use_container_width=True)
    st.sidebar.markdown("### Canteiro CM")
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
            "🤝 Pipeline de Negócios (CRM)",
            "✅ Pendências da Equipe"
        ]
    )
    
    st.sidebar.divider()
    st.sidebar.caption("Operação CM Engenharia")

    # 1. EQUIPE
    if menu == "👥 Equipe":
        render_planilha_dinamica(
            "equipe", 
            "Equipe & Cargos", 
            "Cadastro de funções e funcionários. O custo mensal alimenta os rateios de medição."
        )

    # 2. CALENDÁRIO DE ALOCAÇÃO
    elif menu == "📅 Calendário de Alocação":
        st.header("Calendário de Alocação")
        st.write("Um dia útil por linha, um funcionário por coluna. Distribua a equipe entre as obras.")
        st.warning("⚠️ Como o calendário exige cruzamento diário de dados, a interface completa será ativada na próxima atualização com os componentes de grade. No momento, o rateio pode ser feito via Medição.")
        conn = get_connection()
        df_eq = pd.read_sql("SELECT nome, funcao FROM equipe WHERE ativo = 'True'", conn)
        df_ob = pd.read_sql("SELECT codigo, nome FROM obras WHERE status = 'Em execução'", conn)
        st.write("**Funcionários Ativos:**", len(df_eq))
        st.write("**Obras em Execução:**", len(df_ob))
        conn.close()

    # 3. PIPELINE DE OBRAS
    elif menu == "🏗️ Pipeline de Obras":
        render_planilha_dinamica(
            "obras", 
            "Pipeline de Obras", 
            "Arraste a visão geral das obras. Altere o status de 'Prospecção' até 'Concluída'."
        )

    # 4. CM RENTAL
    elif menu == "🚜 CM Rental (Equipamentos)":
        st.header("CM Rental | Gestão Integrada")
        tab1, tab2 = st.tabs(["Estoque / Patrimônio", "Despacho / Locações Ativas"])
        
        with tab1:
            render_planilha_dinamica(
                "patrimonio", 
                "Patrimônio e Frota", 
                "Gerencie os equipamentos, valores de compra e locação."
            )
        with tab2:
            render_planilha_dinamica(
                "locacoes", 
                "Equipamentos em Obra", 
                "Registre a saída de máquinas para obras internas ou clientes externos."
            )

    # 5. CUSTOS DE MATERIAL
    elif menu == "💸 Custos de Material":
        render_planilha_dinamica(
            "custos", 
            "Custos de Material e Serviços", 
            "Lançamentos no centro de custo da obra. Marque 'Reembolso CM' se necessário."
        )

    # 6. BOLETIM DE MEDIÇÃO
    elif menu == "📊 Boletim de Medição":
        st.header("Boletim de Medição")
        st.write("Consolida materiais, mão de obra, equipamentos e fee.")
        
        conn = get_connection()
        obras = pd.read_sql("SELECT id, codigo, nome, fee_mensal FROM obras WHERE status = 'Em execução'", conn)
        
        if obras.empty:
            st.info("Nenhuma obra em execução cadastrada para medição.")
        else:
            obra_sel = st.selectbox("Selecione a Obra", obras['codigo'] + " - " + obras['nome'])
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Fee Mensal", f"R$ {obras.iloc[0]['fee_mensal'] or 0}")
            c2.metric("Administração Aplicada", "12%")
            c3.metric("Status da Medição", "Em Aberto")
            
            st.divider()
            st.subheader("Resumo de Custos Acumulados")
            custos = pd.read_sql("SELECT SUM(valor) as total FROM custos", conn)
            st.write(f"**Materiais e Serviços:** R$ {custos['total'].iloc[0] or 0}")
            
        conn.close()

    # 7. RESULTADOS DA CM
    elif menu == "📈 Resultados da CM":
        st.header("Resultados e DRE")
        st.write("Painel de faturamento, lucro da administradora e rendimento da CM Rental.")
        st.image("https://cdn-icons-png.flaticon.com/512/1006/1006657.png", width=100)
        st.info("Os painéis analíticos com os gráficos de barras e linha serão renderizados à medida que as tabelas de Custos e Medição receberem dados das obras.")

    # 8. PIPELINE DE NEGÓCIOS
    elif menu == "🤝 Pipeline de Negócios (CRM)":
        render_planilha_dinamica(
            "oportunidades", 
            "Funil de Oportunidades", 
            "Casas, licitações e incorporações antes de virarem obra."
        )

    # 9. PENDÊNCIAS DA EQUIPE
    elif menu == "✅ Pendências da Equipe":
        render_planilha_dinamica(
            "tarefas", 
            "Tarefas e Meu Quadro", 
            "O que a equipe está devendo. Filtre por pessoa para tratar um a um."
        )

if __name__ == "__main__":
    main()
