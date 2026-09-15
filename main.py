from __future__ import annotations
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "locacoes.db"
LOGO_PATH = APP_DIR / "IMG_0207.png"
ATTACHED_LOGO_PATH = APP_DIR / "attached_assets" / "IMG_0207_1789499383772.png"

# Lista de obras ativas
OBRAS = ["CASA RIMAR", "CASA IM", "REFORMA GV", "HBR"]

# Origens/Fornecedores pré-definidos
FORNECEDORES_PADRAO = [
    "Equipamento CM (Próprio)",
    "HL Locações",
    "Loc Express",
    "Escan",
    "Outro (especificar)"
]


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS locacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipamento TEXT NOT NULL,
                fornecedor TEXT NOT NULL,
                obra TEXT NOT NULL,
                data_retirada TEXT NOT NULL,
                data_devolucao TEXT NOT NULL,
                custo_diario REAL NOT NULL CHECK (custo_diario >= 0),
                status TEXT NOT NULL DEFAULT 'Ativa',
                data_baixa TEXT,
                tipo_origem TEXT DEFAULT 'Terceiros'
            )
            """
        )
        # Garante migração caso a coluna tipo_origem não exista ainda
        cursor = connection.execute("PRAGMA table_info(locacoes)")
        colunas = [col[1] for col in cursor.fetchall()]
        if "tipo_origem" not in colunas:
            connection.execute("ALTER TABLE locacoes ADD COLUMN tipo_origem TEXT DEFAULT 'Terceiros'")
        connection.commit()


def load_rentals() -> pd.DataFrame:
    with get_connection() as connection:
        df = pd.read_sql_query(
            "SELECT * FROM locacoes ORDER BY date(data_devolucao), id DESC",
            connection,
        )
        if "tipo_origem" not in df.columns:
            df["tipo_origem"] = "Terceiros"
        return df


def create_rental(
    equipamento: str,
    fornecedor: str,
    tipo_origem: str,
    obra: str,
    data_retirada: date,
    data_devolucao: date,
    custo_diario: float,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO locacoes
                (equipamento, fornecedor, tipo_origem, obra, data_retirada, data_devolucao, custo_diario)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                equipamento.strip(),
                fornecedor.strip(),
                tipo_origem,
                obra.strip(),
                data_retirada.isoformat(),
                data_devolucao.isoformat(),
                custo_diario,
            ),
        )
        connection.commit()


def close_rental(rental_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE locacoes
            SET status = 'Devolvida', data_baixa = ?
            WHERE id = ? AND status = 'Ativa'
            """,
            (date.today().isoformat(), rental_id),
        )
        connection.commit()


def as_date(value: object) -> date:
    return pd.to_datetime(value).date()


def rental_days(row: pd.Series, reference_day: date | None = None) -> int:
    start = as_date(row["data_retirada"])
    today = reference_day or date.today()
    if row["status"] == "Devolvida" and pd.notna(row["data_baixa"]):
        end = as_date(row["data_baixa"])
    else:
        end = min(as_date(row["data_devolucao"]), today)
    return max(1, (end - start).days + 1)


def total_cost(row: pd.Series) -> float:
    return rental_days(row) * float(row["custo_diario"])


def format_currency(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_date(value: object) -> str:
    return as_date(value).strftime("%d/%m/%Y")


def deadline_label(row: pd.Series) -> str:
    days = (as_date(row["data_devolucao"]) - date.today()).days
    if days < 0:
        return f"Atrasado {abs(days)} dia(s)"
    if days == 0:
        return "Vence hoje"
    return f"{days} dia(s) restante(s)"


def logo_path() -> Path | None:
    if LOGO_PATH.exists():
        return LOGO_PATH
    if ATTACHED_LOGO_PATH.exists():
        return ATTACHED_LOGO_PATH
    return None


def render_sidebar() -> str:
    img = logo_path()
    if img:
        st.sidebar.image(str(img), use_container_width=True)
    st.sidebar.markdown("### CM Rental")
    st.sidebar.caption("Controle de locação de equipamentos")
    st.sidebar.divider()
    menu = st.sidebar.radio(
        "Menu principal",
        ["Nova Locação", "Equipamentos Alugados", "Dashboard"],
    )
    st.sidebar.divider()
    rentals = load_rentals()
    active_count = int((rentals["status"] == "Ativa").sum()) if not rentals.empty else 0
    st.sidebar.metric("Locações ativas", active_count)
    
    st.sidebar.divider()
    st.sidebar.markdown("👤 **Guilherme Macedo de Araújo Matias da Costa**")
    st.sidebar.caption("Operação CM Rental")
    
    return menu


def render_new_rental() -> None:
    st.title("Nova Locação")
    st.write("Registre a movimentação de um equipamento (próprio ou terceiro).")

    with st.form("new_rental_form", clear_on_submit=True):
        col_one, col_two = st.columns(2)
        with col_one:
            equipamento = st.text_input(
                "Equipamento",
                placeholder="Ex.: Betoneira 400L, Martelete 15kg",
            )
            
            origem_sel = st.selectbox(
                "Origem do Equipamento / Fornecedor",
                FORNECEDORES_PADRAO,
                help="Selecione se é equipamento CM (próprio) ou locação de parceiro."
            )
            
            fornecedor_custom = ""
            if origem_sel == "Outro (especificar)":
                fornecedor_custom = st.text_input("Digite o nome do fornecedor:")
            
            obra = st.selectbox(
                "Obra de destino",
                OBRAS
            )
            
            custo_diario = st.number_input(
                "Custo diário (R$)",
                min_value=0.0,
                step=5.0,
                format="%.2f",
                help="Para equipamentos próprios, você pode lançar o custo interno/depreciação ou R$ 0,00."
            )
            
        with col_two:
            data_retirada = st.date_input(
                "Data de retirada / início",
                value=date.today(),
                format="DD/MM/YYYY",
            )
            data_devolucao = st.date_input(
                "Previsão de devolução",
                value=date.today() + timedelta(days=7),
                format="DD/MM/YYYY",
            )
            st.info(
                "📌 **Classificação:**\n"
                "- **Equipamento CM:** Equipamento Próprio.\n"
                "- **HL Locações, Loc Express, Escan:** Locação Terceirizada."
            )

        submitted = st.form_submit_button(
            "Registrar locação",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        # Define fornecedor final e tipo
        if origem_sel == "Outro (especificar)":
            fornecedor_final = fornecedor_custom.strip() if fornecedor_custom.strip() else "Outro"
            tipo_origem = "Terceiros"
        elif origem_sel == "Equipamento CM (Próprio)":
            fornecedor_final = "CM (Próprio)"
            tipo_origem = "Próprio (CM)"
        else:
            fornecedor_final = origem_sel
            tipo_origem = "Terceiros"

        if not equipamento.strip():
            st.error("Informe o nome do equipamento.")
        elif data_devolucao < data_retirada:
            st.error("A data de devolução deve ser igual ou posterior à retirada.")
        else:
            create_rental(
                equipamento=equipamento,
                fornecedor=fornecedor_final,
                tipo_origem=tipo_origem,
                obra=obra,
                data_retirada=data_retirada,
                data_devolucao=data_devolucao,
                custo_diario=custo_diario,
            )
            st.success(f"Equipamento '{equipamento}' ({tipo_origem}) registrado com sucesso!")
            st.rerun()


def render_active_rentals() -> None:
    st.title("Equipamentos em Uso / Alugados")
    st.write("Acompanhe prazos de devolução, origem e locações ativas por obra.")

    rentals = load_rentals()
    active = rentals[rentals["status"] == "Ativa"].copy()
    if active.empty:
        st.info("Não há equipamentos ativos no momento.")
        return

    overdue_count = sum(
        as_date(row["data_devolucao"]) < date.today()
        for _, row in active.iterrows()
    )
    
    metric_one, metric_two, metric_three, metric_four = st.columns(4)
    metric_one.metric("Total em Uso", len(active))
    metric_two.metric("Próprios (CM)", int((active["tipo_origem"] == "Próprio (CM)").sum()))
    metric_three.metric("Terceirizados", int((active["tipo_origem"] == "Terceiros").sum()))
    metric_four.metric("Em atraso", overdue_count)

    table = active[
        [
            "id",
            "equipamento",
            "tipo_origem",
            "fornecedor",
            "obra",
            "data_retirada",
            "data_devolucao",
            "custo_diario",
        ]
    ].copy()
    table.columns = [
        "ID",
        "Equipamento",
        "Origem",
        "Fornecedor",
        "Obra",
        "Retirada",
        "Devolução",
        "Custo diário",
    ]
    table["Retirada"] = table["Retirada"].map(format_date)
    table["Devolução"] = table["Devolução"].map(format_date)
    table["Custo diário"] = table["Custo diário"].map(format_currency)
    table["Prazo"] = active.apply(deadline_label, axis=1).values
    st.dataframe(table, hide_index=True, use_container_width=True)

    st.subheader("Dar baixa em devolução")
    rental_options = {
        f'#{row["id"]} · {row["equipamento"]} ({row["fornecedor"]}) · {row["obra"]}': int(row["id"])
        for _, row in active.iterrows()
    }
    selected_label = st.selectbox(
        "Selecione o equipamento devolvido / desmobilizado",
        list(rental_options.keys()),
    )
    if st.button("Dar Baixa", type="primary"):
        close_rental(rental_options[selected_label])
        st.success("Equipamento desmobilizado/devolvido com sucesso!")
        st.rerun()


def render_dashboard() -> None:
    st.title("Dashboard de Custos e Frentes")
    st.write("Análise de custos de locação por obra e por fornecedor.")

    rentals = load_rentals()
    if rentals.empty:
        st.info("Cadastre a primeira locação para habilitar os relatórios do dashboard.")
        return

    rentals["dias_cobrados"] = rentals.apply(rental_days, axis=1)
    rentals["custo_total"] = rentals.apply(total_cost, axis=1)
    active = rentals[rentals["status"] == "Ativa"]

    total_cost_value = float(rentals["custo_total"].sum())
    daily_cost_active = float(active["custo_diario"].sum()) if not active.empty else 0.0

    col1, col2 = st.columns(2)
    col1.metric("Custo Total Acumulado", format_currency(total_cost_value))
    col2.metric("Custo Diário Ativo (Dia)", format_currency(daily_cost_active))

    st.divider()
    col_g1, col_g2 = st.columns(2)

    with col_g1:
        st.subheader("Custo Total por Obra")
        by_work = (
            rentals.groupby("obra")["custo_total"]
            .sum()
            .sort_values(ascending=False)
            .to_frame("Custo Total")
        )
        st.bar_chart(by_work, color="#F35A24")

    with col_g2:
        st.subheader("Custo por Fornecedor / Origem")
        by_supplier = (
            rentals.groupby("fornecedor")["custo_total"]
            .sum()
            .sort_values(ascending=False)
            .to_frame("Custo Total")
        )
        st.bar_chart(by_supplier, color="#1F77B4")

    st.subheader("Detalhamento Geral")
    resumo_df = rentals.groupby(["obra", "fornecedor", "tipo_origem"])["custo_total"].sum().reset_index()
    resumo_df.columns = ["Obra", "Fornecedor", "Tipo", "Custo Total"]
    resumo_df["Custo Total"] = resumo_df["Custo Total"].map(format_currency)
    st.dataframe(resumo_df, hide_index=True, use_container_width=True)


def main() -> None:
    st.set_page_config(
        page_title="CM Rental | Controle de locações",
        page_icon="🏗️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_db()
    menu = render_sidebar()

    if menu == "Nova Locação":
        render_new_rental()
    elif menu == "Equipamentos Alugados":
        render_active_rentals()
    else:
        render_dashboard()


if __name__ == "__main__":
    main()
