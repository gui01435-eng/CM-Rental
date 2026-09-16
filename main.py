import sqlite3
import pandas as pd
import streamlit as st
import zipfile
import json
from pathlib import Path

# ==========================================
# CONFIGURAÇÕES E BANCO DE DADOS
# ==========================================
st.set_page_config(page_title="CM Rental | ERP Completo", page_icon="🏗️", layout="wide")

# Mudamos o nome do banco de dados para criar um cofre novo e limpo, sem os bloqueios do banco anterior.
DB_PATH = Path(__file__).resolve().parent / "cm_erp_v2.db"

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    # Tabelas ativas para o Data Editor
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
            # Verifica se a tabela existe
            df_existente = pd.read_sql(f"SELECT * FROM {tabela} LIMIT 1", conn)
            colunas_existentes = df_existente.columns.tolist()
            
            # Se faltar alguma coluna, adiciona automaticamente
            for col in colunas:
                if col not in colunas_existentes:
                    conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {col} TEXT")
        except:
            # Cria a tabela do zero flexível para aceitar textos e números
            df_vazio = pd.DataFrame(columns=colunas)
            df_vazio.to_sql(tabela, conn, if_exists="replace", index=False)
            
    # Tabelas de Histórico para dados complexos (Backup JSON do sistema do irmão)
    tabelas_historico = ["historico_alocacoes", "historico_medicoes", "historico_resultados", "historico_creditos", "historico_config"]
    for th in tabelas_historico:
        conn.execute(f"CREATE TABLE IF NOT EXISTS {th} (id TEXT PRIMARY KEY, dados_json TEXT)")
        
    conn.commit()
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
    
    df_editado = st.data_editor(df, num_rows="dynamic", use_container_width=True, key=f"editor_{tabela}")
    
    if st.button(f"💾 Salvar alterações em {titulo}", type="primary"):
        df_editado.to_sql(tabela, conn, if_exists="replace", index=False)
        st.success("Banco de dados atualizado com sucesso!")
        st.rerun()
    conn.close()

# ==========================================
# IMPORTADOR TOTAL DE DADOS (ZIP)
# ==========================================
def render_importador():
    st.header("📥 Importação Profunda do Sistema Antigo")
    st.write("Faça o upload do arquivo **canteiro-cm-export-v23.zip** para migrar todo o histórico para o banco de dados novo.")
    
    uploaded_file = st.file_uploader("Selecione o arquivo .zip", type=["zip"])
    
    if uploaded_file is not None:
        if st.button("🚀 Iniciar Importação Total", type="primary"):
            conn = get_connection()
            cursor = conn.cursor()
            
            contagem = {
                "cargos": 0, "equipe": 0, "obras": 0, "patrimonio": 0, "oportunidades": 0, 
                "tarefas": 0, "custos": 0, "locacoes": 0, "historicos_salvos": 0
            }
            
            with st.spinner('Analisando e planilhando arquivos... Isso pode levar alguns segundos.'):
                try:
                    with zipfile.ZipFile(uploaded_file, 'r') as zip_ref:
                        for info in zip_ref.infolist():
                            if not info.filename.endswith('.json'):
                                continue
                                
                            caminho = info.filename.replace('\\', '/')
                            
                            try:
                                conteudo = zip_ref.read(info.filename).decode('utf-8')
                                dados = json.loads(conteudo)
                            except:
                                continue
                            
                            # 1. Cargos
                            if "colecoes/cargos/" in caminho:
                                if type(dados) == dict:
                                    cursor.execute("INSERT INTO cargos (id, nome, abrev, salario_base, extras, ordem) VALUES (?, ?, ?, ?, ?, ?)",
                                                   (dados.get("id"), dados.get("nome"), dados.get("abrev"), dados.get("salarioBase", 0), dados.get("extras", 0), dados.get("ordem", 99)))
                                    contagem["cargos"] += 1
                            
                            # 2. Funcionários (Equipe)
                            elif "colecoes/funcionarios/" in caminho:
                                if type(dados) == dict:
                                    cursor.execute("INSERT INTO equipe (id, nome, funcao, salario_base, extras, ativo) VALUES (?, ?, ?, ?, ?, ?)",
                                                   (dados.get("id"), dados.get("nome"), dados.get("cargoId"), dados.get("salarioBase", 0), dados.get("extras", 0), str(dados.get("ativo", True))))
                                    contagem["equipe"] += 1
                            
                            # 3. Obras
                            elif "colecoes/obras/" in caminho:
                                if type(dados) == dict:
                                    cursor.execute("INSERT INTO obras (id, codigo, nome, cliente, status, regime, fee_mensal, orcamento) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                                   (dados.get("id"), dados.get("codigo"), dados.get("nome"), dados.get("cliente"), dados.get("status"), dados.get("regime"), dados.get("feeMensal", 0), dados.get("orcamentoPrevisto", 0)))
                                    contagem["obras"] += 1
                            
                            # 4. Equipamentos (Patrimônio)
                            elif "colecoes/equipamentos/" in caminho:
                                if type(dados) == dict:
                                    proprio = "Equipamento CM (Próprio)" if dados.get("proprio", True) else dados.get("fornecedor", "Terceiro")
                                    cursor.execute("INSERT INTO patrimonio (id, equipamento, origem, status, valor_compra, diaria_padrao) VALUES (?, ?, ?, ?, ?, ?)",
                                                   (dados.get("id"), dados.get("nome"), proprio, dados.get("situacao", "Operacional"), dados.get("valorCompra", 0), dados.get("custoDiario", 0)))
                                    contagem["patrimonio"] += 1
                            
                            # 5. Oportunidades
                            elif "colecoes/oportunidades/" in caminho:
                                if type(dados) == dict:
                                    cursor.execute("INSERT INTO oportunidades (id, nome, cliente, tipo, estagio, valor_estimado, probabilidade) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                                   (dados.get("id"), dados.get("nome"), dados.get("cliente"), dados.get("tipo"), dados.get("estagio"), dados.get("valor", 0), dados.get("probabilidade", 0)))
                                    contagem["oportunidades"] += 1

                            # 6. Tarefas
                            elif "colecoes/tarefas/" in caminho:
                                if type(dados) == dict:
                                    cursor.execute("INSERT INTO tarefas (id, titulo, responsavel, prioridade, status, prazo, descricao) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                                   (dados.get("id"), dados.get("titulo"), dados.get("responsavel"), dados.get("prioridade"), dados.get("estado"), dados.get("prazo"), dados.get("descricao")))
                                    contagem["tarefas"] += 1
                            
                            # 7. Custos (Achatamento de listas)
                            elif "colecoes/custos/" in caminho:
                                if type(dados) == dict and "itens" in dados:
                                    obra_id = caminho.split("/")[-1].split("__")[0] if "__" in caminho else "Desconhecida"
                                    for item in dados["itens"]:
                                        cursor.execute("INSERT INTO custos (id, obra_id, data, etapa, fornecedor, nf, reembolso_cm, valor, descricao) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                                       (item.get("id"), obra_id, item.get("data"), item.get("etapa"), item.get("fornecedor"), str(item.get("nf", False)), str(item.get("reembCM", False)), item.get("valor", 0), item.get("descricao")))
                                        contagem["custos"] += 1

                            # 8. Locações (Achatamento de listas)
                            elif "colecoes/locacoes/" in caminho:
                                if type(dados) == dict and "itens" in dados:
                                    for item in dados["itens"]:
                                        cursor.execute("INSERT INTO locacoes (id, equipamento, obra_destino, data_retirada, data_devolucao, custo_diario, status, valor_total) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                                       (item.get("id"), item.get("nome"), item.get("obraId"), item.get("dataIni"), item.get("dataFim"), item.get("valorUnit", 0), "Ativa", item.get("valorUnit", 0) * item.get("qtd", 1)))
                                        contagem["locacoes"] += 1
                            
                            # 9. Backup de Arquivos Complexos
                            else:
                                pasta_mae = caminho.split("/")[-2] if len(caminho.split("/")) > 1 else ""
                                doc_id = caminho.split("/")[-1].replace(".json", "")
                                
                                tabela_hist = f"historico_{pasta_mae}"
                                if tabela_hist in ["historico_alocacoes", "historico_medicoes", "historico_resultados", "historico_creditos", "historico_config"]:
                                    cursor.execute(f"INSERT OR REPLACE INTO {tabela_hist} (id, dados_json) VALUES (?, ?)", (doc_id, json.dumps(dados)))
                                    contagem["historicos_salvos"] += 1

                    conn.commit()
                    st.success("🎉 Importação total concluída com sucesso! Todo o histórico financeiro e cadastros foram recuperados para o novo banco de dados.")
                    
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.write(f"- **Obras:** {contagem['obras']}")
                        st.write(f"- **Funcionários:** {contagem['equipe']}")
                        st.write(f"- **Cargos:** {contagem['cargos']}")
                    with c2:
                        st.write(f"- **Patrimônio / Estoque:** {contagem['patrimonio']}")
                        st.write(f"- **Locações Extraídas:** {contagem['locacoes']}")
                        st.write(f"- **Custos Extraídos:** {contagem['custos']}")
                    with c3:
                        st.write(f"- **Tarefas:** {contagem['tarefas']}")
                        st.write(f"- **Oportunidades:** {contagem['oportunidades']}")
                        st.write(f"- **Backups Complexos Salvos:** {contagem['historicos_salvos']}")
                    
                except Exception as e:
                    st.error(f"Erro ao processar o arquivo ZIP: {e}")
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
            "👔 Cargos e Níveis",
            "📅 Calendário de Alocação",
            "🏗️ Pipeline de Obras",
            "🚜 CM Rental (Equipamentos)",
            "💸 Custos de Material",
            "📊 Boletim de Medição",
            "📈 Resultados da CM",
            "🤝 Pipeline de Negócios (CRM)",
            "✅ Pendências da Equipe",
            "📥 Importar Sistema Antigo"
        ]
    )
    
    st.sidebar.divider()
    st.sidebar.caption("👤 **Guilherme Macedo de Araújo Matias da Costa**")
    st.sidebar.caption("Operação CM Engenharia")

    if menu == "👥 Equipe":
        render_planilha_dinamica("equipe", "Equipe", "Gerenciamento de funcionários e salários.")
    elif menu == "👔 Cargos e Níveis":
        render_planilha_dinamica("cargos", "Cargos", "Tabela base de cargos, salários e níveis.")
    elif menu == "📅 Calendário de Alocação":
        st.header("Calendário de Alocação")
        st.warning("⚠️ O calendário está em processo de conversão para o novo formato de visualização de grade. Os dados foram salvos no `historico_alocacoes`.")
    elif menu == "🏗️ Pipeline de Obras":
        render_planilha_dinamica("obras", "Pipeline de Obras", "Visão geral das obras.")
    elif menu == "🚜 CM Rental (Equipamentos)":
        st.header("CM Rental | Gestão Integrada")
        tab1, tab2 = st.tabs(["Estoque / Patrimônio", "Despacho / Locações Ativas"])
        with tab1:
            render_planilha_dinamica("patrimonio", "Patrimônio e Frota", "Gerencie os equipamentos e frotas.")
        with tab2:
            render_planilha_dinamica("locacoes", "Histórico de Locações", "Máquinas despachadas extraídas do seu histórico.")
    elif menu == "💸 Custos de Material":
        render_planilha_dinamica("custos", "Custos de Material e Serviços", "Lançamentos extraídos do seu histórico antigo.")
    elif menu == "📊 Boletim de Medição":
        st.header("Boletim de Medição")
        st.info("Os dados das medições antigas foram salvos com segurança no banco de dados (`historico_medicoes`). O painel visual será reativado em breve.")
    elif menu == "📈 Resultados da CM":
        st.header("Resultados e DRE")
        st.info("Os resultados passados foram extraídos para o `historico_resultados`. O painel analítico será ativado na próxima etapa.")
    elif menu == "🤝 Pipeline de Negócios (CRM)":
        render_planilha_dinamica("oportunidades", "Funil de Oportunidades", "Oportunidades de obras e orçamentos.")
    elif menu == "✅ Pendências da Equipe":
        render_planilha_dinamica("tarefas", "Tarefas e Meu Quadro", "O que a equipe está devendo.")
    elif menu == "📥 Importar Sistema Antigo":
        render_importador()

if __name__ == "__main__":
    main()
