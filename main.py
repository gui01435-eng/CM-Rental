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
                data_baixa TEXT
            )
            """
        )
        connection.commit()


def load_rentals() -> pd.DataFrame:
    with get_connection() as connection:
        return pd.read_sql_query(
            "SELECT * FROM locacoes ORDER BY date(data_devolucao), id DESC",
            connection,
        )


def create_rental(
    equipamento: str,
    fornecedor: str,
    obra: str,
    data_retirada: date,
    data_devolucao: date,
    custo_diario: float,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO locacoes
                (equipamento, fornecedor, obra, data_retirada, data_devolucao, custo_diario)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                equipamento.strip(),
                fornecedor.strip(),
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


def logo_path() -> Path:
    if LOGO_PATH.exists():
        return LOGO_PATH
    return ATTACHED_LOGO_PATH


def render_sidebar() -> str:
    st.sidebar.image(str(logo_path()), use_container_width=True)
    st.sidebar.markdown("### CM Rental")
    st.sidebar.caption("Controle de locação de equipamentos")
    st.sidebar.divider()
    menu = st.sidebar.radio(
        "Menu principal",
        ["Nova Locação", "Equipamentos Alugados", "Dashboard"],
    )
    st.sidebar.divider()
    active_count = int((load_rentals()["status"] == "Ativa").sum())
    st.sidebar.metric("Locações ativas", active_count)
    st.sidebar.caption("Dados armazenados localmente em SQLite.")
    
    st.sidebar.divider()
    st.sidebar.markdown("👤 **Guilherme Macedo de Araújo Matias da Costa**")
    st.sidebar.caption("Operação CM Rental")
    
    return menu


def render_new_rental() -> None:
    st.title("Nova Locação")
    st.write("Registre a retirada de um equipamento e acompanhe o custo da operação.")

    with st.form("new_rental_form", clear_on_submit=True):
        col_one, col_two = st.columns(2)
        with col_one:
            equipamento = st.text_input(
                "Equipamento",
                placeholder="Ex.: Betoneira 400L",
            )
            fornecedor = st.text_input(
                "Fornecedor",
                placeholder="Ex.: CM Rental",
            )
            obra = st.selectbox(
                "Obra de destino",
                ["CASA RIMAR", "CASA IM", "REFORMA GV", "HBR"]
            )
            custo_diario = st.number_input(
                "Custo diário (R$)",
                min_value=0.0,
                step=10.0,
                format="%.2f",
            )
        with col_two:
            data_retirada = st.date_input(
                "Data de retirada",
                value=date.today(),
                format="DD/MM/YYYY",
            )
            data_devolucao = st.date_input(
                "Data de devolução",
                value=date.today() + timedelta(days=7),
                format="DD/MM/YYYY",
            )
            st.info(
                "O prazo, o custo acumulado e os atrasos serão calculados automaticamente."
            )

        submitted = st.form_submit_button(
            "Registrar locação",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        if not equipamento.strip() or not fornecedor.strip():
            st.error("Preencha equipamento e fornecedor.")
        elif data_devolucao < data_retirada:
            st.error("A data de devolução deve ser igual ou posterior à retirada.")
        else:
            create_rental(
                equipamento,
                fornecedor,
                obra,
                data_retirada,
                data_devolucao,
                custo_diario,
            )
            st.success("Locação registrada com sucesso.")
            st.rerun()


def render_active_rentals() -> None:
    st.title("Equipamentos Alugados")
    st.write("Acompanhe prazos de devolução, atrasos e locações em andamento.")

    rentals = load_rentals()
    active = rentals[rentals["status"] == "Ativa"].copy()
    if active.empty:
        st.info("Não há equipamentos alugados no momento.")
        return

    overdue_count = sum(
        as_date(row["data_devolucao"]) < date.today()
        for _, row in active.iterrows()
    )
    metric_one, metric_two, metric_three = st.columns(3)
    metric_one.metric("Equipamentos ativos", len(active))
    metric_two.metric("Em atraso", overdue_count)
    metric_three.metric(
        "Custo diário",
        format_currency(float(active["custo_diario"].sum())),
    )

    table = active[
        [
            "id",
            "equipamento",
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

    st.subheader("Dar baixa em uma devolução")
    rental_options = {
        f'{row["equipamento"]} · {row["obra"]} · devolução {format_date(row["data_devolucao"])}': int(
            row["id"]
        )
        for _, row in active.iterrows()
    }
    selected_label = st.selectbox(
        "Selecione a locação devolvida",
        list(rental_options.keys()),
    )
    if st.button("Dar Baixa", type="primary"):
        close_rental(rental_options[selected_label])
        st.success("Equipamento marcado como devolvido.")
        st.rerun()


def render_dashboard() -> None:
    st.title("Dashboard")
    st.write("Visão financeira das locações de equipamentos por obra.")

    rentals = load_rentals()
    if rentals.empty:
        st.info("Registre uma locação para começar a visualizar o dashboard.")
        return

    rentals["dias_cobrados"] = rentals.apply(rental_days, axis=1)
    rentals["custo_total"] = rentals.apply(total_cost, axis=1)
    active = rentals[rentals["status"] == "Ativa"]

    total_cost_value = float(rentals["custo_total"].sum())
    daily_cost = float(active["custo_diario"].sum()) if not active.empty else 0.0
    overdue = (
        int((active["data_devolucao"].map(as_date) < date.today()).sum())
        if not active.empty
        else 0
    )
    metric_one, metric_two, metric_three = st.columns(3)
    metric_one.metric("Custo total", format_currency(total_cost_value))
    metric_two.metric("Custo diário ativo", format_currency(daily_cost))
    metric_three.metric("Locações em atraso", overdue)

    st.subheader("Custo total por obra")
    by_work = (
        rentals.groupby("obra", as_index=True)["custo_total"]
        .sum()
        .sort_values(ascending=False)
        .to_frame("Custo total")
    )
    st.bar_chart(by_work, color="#F35A24")

    chart_table = by_work.reset_index()
    chart_table["Custo total"] = chart_table["Custo total"].map(format_currency)
    st.dataframe(chart_table, hide_index=True, use_container_width=True)
    st.caption(
        "Para locações ativas, o valor considera os dias já utilizados. "
        "Para locações devolvidas, considera o período até a baixa."
    )


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
