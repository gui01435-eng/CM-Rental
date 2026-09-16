import sqlite3
import pandas as pd
import streamlit as st
from datetime import date
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "canteiro_cm.db"

STATUS_OBRA = ["Prospecção", "Proposta", "Em execução", "Paralisada", "Concluída"]
ETAPAS_CUSTO = ["Alimentação", "Concreto", "EPI", "Estrutura", "Fôrmas", "Hidráulica", "Elétrica", "Locação", "Mão de Obra"]

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS obras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT NOT NULL,
                nome TEXT NOT NULL,
                cliente TEXT,
                status TEXT NOT NULL,
                regime TEXT,
                percent_admin REAL,
                fee_mensal REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS custos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                obra_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                etapa TEXT,
                fornecedor TEXT,
                nf BOOLEAN,
                reembolso_cm BOOLEAN,
                descricao TEXT,
                valor REAL NOT NULL,
                FOREIGN KEY(obra_id) REFERENCES obras(id)
            )
        """)
        conn.commit()

def render_obras():
    st.header("Pipeline de Obras")
    st.write("Gerencie as obras e contratos no funil.")
    
    with st.form("form_obra", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            codigo = st.text_input("Código / Centro de Custo", placeholder="Ex: RIMAR01")
            nome = st.text_input("Nome da Obra")
            cliente = st.text_input("Cliente")
        with c2:
            status = st.selectbox("Etapa do Funil", STATUS_OBRA)
            regime = st.selectbox("Regime", ["Por administração", "Empreitada global", "Outro contrato"])
            fee = st.number_input("Fee Mensal (R$)", min_value=0.0, step=100.0)
        
        if st.form_submit_button("Salvar Obra", type="primary"):
            if codigo and nome:
                with get_connection() as conn:
                    conn.execute("INSERT INTO obras (codigo, nome, cliente, status, regime, fee_mensal) VALUES (?, ?, ?, ?, ?, ?)",
                                 (codigo, nome, cliente, status, regime, fee))
                    conn.commit()
                st.success(f"Obra {codigo} cadastrada!")
                st.rerun()
            else:
                st.error("Preencha o código e o nome.")

    st.divider()
    with get_connection() as conn:
        df = pd.read_sql("SELECT * FROM obras", conn)
        if not df.empty:
            st.dataframe(df, hide_index=True, use_container_width=True)
        else:
            st.info("Nenhuma obra cadastrada.")

def render_custos():
    st.header("Custos de Material e Serviços")
    
    with get_connection() as conn:
        obras = pd.read_sql("SELECT id, codigo, nome FROM obras WHERE status IN ('Em execução', 'Paralisada')", conn)
    
    if obras.empty:
        st.warning("Cadastre uma obra 'Em execução' ou 'Paralisada' para lançar custos.")
        return

    obra_dict = {f"{row['codigo']} - {row['nome']}": row['id'] for _, row in obras.iterrows()}
    
    with st.form("form_custo", clear_on_submit=True):
        obra_selecionada = st.selectbox("Obra / Centro de Custo", list(obra_dict.keys()))
        c1, c2 = st.columns(2)
        with c1:
            dt_custo = st.date_input("Data", date.today())
            etapa = st.selectbox("Etapa", ETAPAS_CUSTO)
            fornecedor = st.text_input("Fornecedor")
            valor = st.number_input("Valor (R$)", min_value=0.0, step=10.0)
        with c2:
            descricao = st.text_area("Descrição")
            nf = st.checkbox("Com nota fiscal")
            reemb = st.checkbox("Pago pela CM (Reembolso)")
            
        if st.form_submit_button("Lançar Custo", type="primary"):
            if valor > 0:
                with get_connection() as conn:
                    conn.execute("""
                        INSERT INTO custos (obra_id, data, etapa, fornecedor, nf, reembolso_cm, descricao, valor)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (obra_dict[obra_selecionada], dt_custo.isoformat(), etapa, fornecedor, nf, reemb, descricao, valor))
                    conn.commit()
                st.success("Custo lançado com sucesso!")
                st.rerun()
            else:
                st.error("Informe um valor válido.")

    st.divider()
    with get_connection() as conn:
        df = pd.read_sql("SELECT c.data, o.codigo as obra, c.etapa, c.fornecedor, c.valor, c.nf, c.reembolso_cm FROM custos c JOIN obras o ON c.obra_id = o.id ORDER BY c.id DESC", conn)
        if not df.empty:
            df["valor"] = df["valor"].apply(lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            df["nf"] = df["nf"].map({1: "Sim", 0: "Não"})
            df["reembolso_cm"] = df["reembolso_cm"].map({1: "Sim", 0: "Não"})
            st.dataframe(df, hide_index=True, use_container_width=True)

def main():
    st.set_page_config(page_title="Canteiro CM | Core", layout="wide")
    init_db()
    
    st.sidebar.title("Canteiro CM")
    menu = st.sidebar.radio("Navegação", ["Obras", "Custos"])
    
    if menu == "Obras":
        render_obras()
    else:
        render_custos()

if __name__ == "__main__":
    main()
